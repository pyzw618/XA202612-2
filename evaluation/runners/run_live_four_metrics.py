"""四项指标真机评测统一入口。

针对已部署的 MemoryHub 服务（麒麟 embedding + Milvus）跑端到端评测，产出
一份带环境指纹与数据集哈希的报告。**不 import memoryhub 运行时对象**，只走
HTTP，因此测的是真实部署而不是进程内 mock 配置。

退出码：
    0  四项全部测量完成
    2  环境指纹不满足验收要求
    3  服务不可达
    4  语料就绪判定失败（索引故障，分数无意义）
    5  播种超时

用法::

    .venv/bin/python -m evaluation.runners.run_live_four_metrics \\
        --base-url http://127.0.0.1:8099 \\
        --metrics retrieval,latency,preference,conflict
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.live import LiveClient, LiveClientError          # noqa: E402
from evaluation.live.client import ServiceUnavailable             # noqa: E402
from evaluation.live.datasets import DatasetError, load_dataset   # noqa: E402
from evaluation.live.fingerprint import (                         # noqa: E402
    PRODUCTION_REQUIREMENTS,
    FingerprintMismatch,
    assert_fingerprint,
    check_preconditions,
    check_fingerprint,
)
from evaluation.live.metrics_conflict import evaluate_conflict    # noqa: E402
from evaluation.live.metrics_latency import evaluate_latency      # noqa: E402
from evaluation.live.metrics_preference import evaluate_preference  # noqa: E402
from evaluation.live.metrics_retrieval import evaluate_retrieval   # noqa: E402
from evaluation.live.readiness import ReadinessError, assess_readiness  # noqa: E402
from evaluation.live.report import build_report, write_report      # noqa: E402
from evaluation.live.seeding import EvalUser, seed_corpus          # noqa: E402

DEFAULT_DATASETS = {
    "retrieval": ROOT / "evaluation/datasets/memoryhub_graded_retrieval_v2.1_dev.json",
    "preference": ROOT / "evaluation/datasets/memoryhub_preference_extraction_v2.1.json",
    "conflict": ROOT / "evaluation/datasets/memoryhub_conflict_resolution_v2.1.json",
    "latency": ROOT / "evaluation/datasets/memoryhub_retrieval_latency_v2.1_dev.json",
}

EXIT_OK, EXIT_FINGERPRINT, EXIT_UNREACHABLE, EXIT_READINESS, EXIT_SEED_TIMEOUT = 0, 2, 3, 4, 5


def _parse_requirements(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="四项指标真机评测")
    parser.add_argument("--base-url", default="http://127.0.0.1:8099")
    parser.add_argument("--metrics", default="retrieval,latency,preference,conflict")
    parser.add_argument("--retrieval-dataset", type=Path, default=DEFAULT_DATASETS["retrieval"])
    parser.add_argument("--preference-dataset", type=Path, default=DEFAULT_DATASETS["preference"])
    parser.add_argument("--conflict-dataset", type=Path, default=DEFAULT_DATASETS["conflict"])
    parser.add_argument("--latency-dataset", type=Path, default=DEFAULT_DATASETS["latency"])
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--concurrency", default="1,4,8,16")
    parser.add_argument("--warmup", type=int, default=100)
    parser.add_argument("--canary-sample", type=int, default=20)
    parser.add_argument("--seed-concurrency", type=int, default=8)
    parser.add_argument("--seed-timeout-s", type=float, default=5400.0)
    parser.add_argument("--require-fingerprint", default=",".join(PRODUCTION_REQUIREMENTS))
    parser.add_argument("--allow-dataset-drift", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划与预计耗时")
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    args = parser.parse_args()

    wanted = {item.strip() for item in args.metrics.split(",") if item.strip()}
    datasets: dict[str, dict] = {}
    provenance: dict[str, dict] = {}

    print("== 加载数据集 ==", flush=True)
    for name in ("retrieval", "preference", "conflict", "latency"):
        if name not in wanted and name != "retrieval":
            continue
        path = getattr(args, f"{name}_dataset")
        try:
            data, prov = load_dataset(path, allow_drift=args.allow_dataset_drift)
        except DatasetError as exc:
            print(f"  数据集错误：{exc}", file=sys.stderr)
            return 1
        datasets[name] = data
        provenance[name] = prov
        counts = ", ".join(f"{k}={v}" for k, v in prov["counts"].items())
        print(f"  {name:11s} {path.name}  ({counts})  sha256={prov['sha256'][:12]}…", flush=True)

    if args.dry_run:
        total = len(datasets.get("retrieval", {}).get("memories", []))
        print(f"\n[dry-run] 需播种 {total} 条记忆，按 ~3 条/秒估算约 {total / 3.0 / 60:.1f} 分钟")
        return EXIT_OK

    with LiveClient(args.base_url, timeout_s=180.0) as client:
        if not client.health():
            print(f"服务不可达：{args.base_url}", file=sys.stderr)
            return EXIT_UNREACHABLE

        print("\n== 环境指纹 ==", flush=True)
        try:
            fingerprint = assert_fingerprint(
                client, _parse_requirements(args.require_fingerprint),
                service_config=_safe_config(client),
            )
        except FingerprintMismatch as exc:
            print(f"  指纹不满足：{exc}", file=sys.stderr)
            fp = None
            try:
                from evaluation.live.fingerprint import build_environment_fingerprint, read_system_status

                fp = build_environment_fingerprint(
                    read_system_status(client), base_url=args.base_url
                )
                print("  实际：" + "; ".join(
                    check_fingerprint(fp, _parse_requirements(args.require_fingerprint))
                ), file=sys.stderr)
            except LiveClientError:
                pass
            return EXIT_FINGERPRINT
        emb = fingerprint.get("embedding", {})
        vec = fingerprint.get("vector_engine", {})
        print(f"  runtime={fingerprint.get('runtime_mode')} "
              f"embedding={emb.get('provider')}/{emb.get('dimension')} "
              f"vector={vec.get('provider')}(connected={vec.get('connected')})", flush=True)

        preconditions = check_preconditions(fingerprint)
        for item in preconditions:
            print(f"  ⚠️  {item}", flush=True)

        user = EvalUser.new(prefix="liveeval")
        report_kwargs: dict = {
            "fingerprint": fingerprint,
            "datasets": provenance,
            "preconditions": preconditions,
            "preference": None, "retrieval": None, "latency": None, "conflict": None,
        }
        notes = [
            "本报告全部数据由 HTTP 端到端采集，检索响应均校验 served=vnext。",
            "≤500ms 结论取并发 1 的 cold 阶段客户端端到端耗时（含 embedding 与网络）。",
        ]

        # ---- 检索（含播种 + 就绪判定）
        if "retrieval" in wanted:
            corpus = datasets["retrieval"]["memories"]
            print(f"\n== 播种 {len(corpus)} 条语料到 {user.user_id} ==", flush=True)
            started = time.perf_counter()
            seed = seed_corpus(client, corpus, user, concurrency=args.seed_concurrency)
            print(f"  播种 {seed.succeeded}/{seed.requested}，失败 {len(seed.failures)}，"
                  f"耗时 {seed.elapsed_s:.0f}s（{seed.items_per_second:.2f} 条/秒）", flush=True)
            if seed.elapsed_s > args.seed_timeout_s:
                print("  播种超时", file=sys.stderr)
                return EXIT_SEED_TIMEOUT

            print("== 就绪判定 ==", flush=True)
            try:
                readiness = assess_readiness(
                    client, user, corpus, canary_sample=args.canary_sample
                )
            except ReadinessError as exc:
                print(f"  就绪失败：{exc}", file=sys.stderr)
                return EXIT_READINESS
            report_kwargs["readiness"] = readiness.as_dict()
            print(f"  {readiness.verdict}  canary={readiness.canary_hits}/"
                  f"{readiness.canary_sampled}  零结果={readiness.canary_zero_results}", flush=True)

            print("== 检索评测（scoped / unscoped）==", flush=True)
            report_kwargs["retrieval"] = evaluate_retrieval(
                client, datasets["retrieval"]["queries"], user,
                top_k=args.top_k, scoped=True,
            )
            report_kwargs["retrieval_unscoped"] = evaluate_retrieval(
                client, datasets["retrieval"]["queries"], user,
                top_k=args.top_k, scoped=False,
            )
            r = report_kwargs["retrieval"]
            print(f"  scoped   recall@k={r['recall_at_k']:.4f} mrr={r['mrr']:.4f} "
                  f"no_answer={r['no_answer_precision']} "
                  f"isolation_violations={r['isolation_violation_count']}", flush=True)

        # ---- 延迟
        if "latency" in wanted:
            print("\n== 延迟评测 ==", flush=True)
            levels = tuple(int(x) for x in args.concurrency.split(",") if x.strip())
            report_kwargs["latency"] = evaluate_latency(
                client, datasets["latency"], user,
                concurrency_levels=levels, warmup_count=args.warmup,
                top_k=args.top_k, scoped=True,
            )
            for name, phase in report_kwargs["latency"]["phases"].items():
                print(f"  [{name}] p50={phase['p50_ms']} p95={phase['p95_ms']} "
                      f"p99={phase['p99_ms']} err={phase['errors']}", flush=True)

        # ---- 偏好
        if "preference" in wanted:
            print("\n== 偏好提取评测 ==", flush=True)
            report_kwargs["preference"] = evaluate_preference(
                client, datasets["preference"], user
            )
            p = report_kwargs["preference"]
            print(f"  accuracy={p['accuracy']:.4f}  by_block="
                  f"{ {k: v['accuracy'] for k, v in p['by_block'].items()} }", flush=True)

        # ---- 冲突
        if "conflict" in wanted:
            print("\n== 冲突处理评测 ==", flush=True)
            report_kwargs["conflict"] = evaluate_conflict(
                client, datasets["conflict"], user
            )
            c = report_kwargs["conflict"]
            print(f"  accuracy={c['accuracy']} scored={c['scored_cases']} "
                  f"drive_failures={c['drive_failure_count']}", flush=True)

        report_kwargs["request_summary"] = client.request_summary()
        report_kwargs["notes"] = notes
        report = build_report(**report_kwargs)

    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    json_path = args.output_json or ROOT / f"evaluation/results/live/four_metrics_{stamp}.json"
    md_path = args.output_md or json_path.with_suffix(".md")
    write_report(report, json_path=json_path, md_path=md_path)

    print(f"\n== 结果 ==", flush=True)
    for m in report["metrics"]:
        value = "—" if m["value"] is None else (
            f"{m['value']:.2f}ms" if m["unit"] == "ms" else f"{m['value'] * 100:.2f}%"
        )
        print(f"  {m['name']}: {value}  阈值 {m['threshold']}  [{m['verdict']}]", flush=True)
    print(f"\n报告：{json_path}\n     {md_path}", flush=True)
    return EXIT_OK


def _safe_config(client: LiveClient) -> dict | None:
    try:
        return client.get_system_config()
    except LiveClientError:
        return None


if __name__ == "__main__":
    raise SystemExit(main())
