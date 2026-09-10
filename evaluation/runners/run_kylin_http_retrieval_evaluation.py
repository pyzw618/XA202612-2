"""MemoryHub HTTP 端到端检索评测 (P0-5)

三阶段冷热隔离 + 并发档位 1/4/8/16，通过 HTTP POST /api/memory/search。
"""

from __future__ import annotations

import argparse, json, os, sys, time, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def percentile(data: list[float], p: float) -> float:
    if not data: return 0.0
    s = sorted(data)
    idx = (p / 100.0) * (len(s) - 1)
    if idx.is_integer(): return s[int(idx)]
    lo, hi = int(idx), int(idx) + 1
    return s[lo] * (1 - (idx - lo)) + s[hi] * (idx - lo)


def run_concurrent(url: str, queries: list[dict], concurrency: int,
                   phase: str) -> list[dict]:
    """使用线程池并发发送 HTTP 请求。"""
    results = []

    def _fetch(q):
        t0 = time.perf_counter()
        try:
            resp = httpx.post(
                url, json={
                    "user_id": q.get("user_id", "default"),
                    "query": q.get("query_text", ""),
                    "top_k": 5,
                    "context": q.get("context", {}),
                    "project_id": q.get("project_id", ""),
                    "memory_types": q.get("memory_types", ["knowledge"]),
                },
                timeout=10.0,
            )
            elapsed = (time.perf_counter() - t0) * 1000
            if resp.status_code == 200:
                body = resp.json()
                return {
                    "query_id": q.get("query_id", "?"),
                    "status": 200,
                    "client_e2e_ms": round(elapsed, 2),
                    "server_latency_ms": body.get("latency_ms", 0),
                    "result_count": body.get("total_count", 0),
                    "phase": phase,
                }
            else:
                return {
                    "query_id": q.get("query_id", "?"),
                    "status": resp.status_code,
                    "client_e2e_ms": round(elapsed, 2),
                    "server_latency_ms": 0,
                    "result_count": 0,
                    "error": resp.text[:200],
                    "phase": phase,
                }
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return {
                "query_id": q.get("query_id", "?"),
                "status": -1,
                "client_e2e_ms": round(elapsed, 2),
                "server_latency_ms": 0,
                "error": str(e)[:200],
                "phase": phase,
            }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(_fetch, q): q for q in queries}
        for f in as_completed(futures):
            results.append(f.result())
    return results


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    ok = [r for r in results if r["status"] == 200]
    err = [r for r in results if r["status"] != 200]
    lat = [r["client_e2e_ms"] for r in ok]
    srv_lat = [r["server_latency_ms"] for r in ok]
    return {
        "count": n,
        "success": len(ok),
        "errors": len(err),
        "error_rate": round(len(err) / max(n, 1), 4),
        "p50_ms": round(percentile(lat, 50), 2),
        "p95_ms": round(percentile(lat, 95), 2),
        "p99_ms": round(percentile(lat, 99), 2),
        "max_ms": round(max(lat), 2) if lat else 0,
        "mean_ms": round(sum(lat) / max(len(lat), 1), 2) if lat else 0,
        "server_p50_ms": round(percentile(srv_lat, 50), 2),
        "server_p95_ms": round(percentile(srv_lat, 95), 2),
        "qps": round(len(ok) / max(sum(lat) / 1000, 0.001), 2) if lat else 0,
    }


def main():
    p = argparse.ArgumentParser(description="HTTP 端到端检索评测 (P0-5)")
    p.add_argument("--base-url", default="http://127.0.0.1:8099")
    p.add_argument("--dataset", required=True, help="延迟查询集路径")
    p.add_argument("--phase", default="cold", choices=["cold","vector_hot","result_hot"])
    p.add_argument("--concurrency", default="1,4,8,16")
    p.add_argument("--min-requests", type=int, default=1000)
    p.add_argument("--output-json", default="evaluation/results/http_eval.json")
    p.add_argument("--output-md", default="evaluation/results/http_eval.md")
    args = p.parse_args()

    url = f"{args.base_url.rstrip('/')}/api/memory/search"
    concurrencies = [int(x) for x in args.concurrency.split(",")]

    with open(args.dataset) as f:
        ds = json.load(f)
    queries = ds.get("warmup_queries", [])[:50] + ds.get("formal_queries", [])[:args.min_requests]
    print(f"加载查询: {len(queries)}")

    # 预热
    print("预热中...")
    _ = run_concurrent(url, queries[:50], 1, "warmup")

    report: dict = {
        "environment": {
            "base_url": args.base_url,
            "dataset": args.dataset,
            "phase": args.phase,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "git_commit": _get_commit(),
        },
        "phases": {},
    }

    for cc in concurrencies:
        label = f"{args.phase}_c{cc}"
        print(f"\n[{label}] 运行 {len(queries)} 条查询, 并发={cc}...")
        t0 = time.perf_counter()
        results = run_concurrent(url, queries, cc, label)
        elapsed = (time.perf_counter() - t0)
        agg = aggregate(results)
        agg["wall_clock_s"] = round(elapsed, 2)
        report["phases"][label] = agg
        print(f"  [{label}] P50={agg['p50_ms']}ms P95={agg['p95_ms']}ms P99={agg['p99_ms']}ms "
              f"err={agg['errors']}/{agg['count']} QPS={agg['qps']}")

    os.makedirs(os.path.dirname(args.output_json) or ".", exist_ok=True)
    with open(args.output_json, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Markdown
    md = ["# HTTP 端到端检索评测 (P0-5)\n", f"**Base URL**: {url}",
          f"**查询数**: {len(queries)}\n",
          "## 延迟 (客户端 wall-clock)\n",
          "| 并发 | P50 | P95 | P99 | Max | 均值 | QPS | 错误 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for cc in concurrencies:
        label = f"{args.phase}_c{cc}"
        a = report["phases"][label]
        md.append(f"| {cc} | {a['p50_ms']} | {a['p95_ms']} | {a['p99_ms']} | "
                  f"{a['max_ms']} | {a['mean_ms']} | {a['qps']} | {a['errors']} |")
    md.append(f"\n## 达标检查\n")
    cold_p95 = report["phases"].get("cold_c1", {}).get("p95_ms", 99999)
    cold_p99 = report["phases"].get("cold_c1", {}).get("p99_ms", 99999)
    md.append(f"- cold P95: **{cold_p95}ms** → {'✅' if cold_p95 <= 350 else '❌'} (≤350ms)")
    md.append(f"- cold P99: **{cold_p99}ms** → {'✅' if cold_p99 <= 500 else '❌'} (≤500ms)")
    md.append("")

    with open(args.output_md, "w") as f:
        f.write("\n".join(md))
    print(f"\n报告: {args.output_json}, {args.output_md}")


def _get_commit():
    try:
        return subprocess.run(["git","rev-parse","--short","HEAD"],
                              capture_output=True, text=True).stdout.strip()
    except: return "unknown"

if __name__ == "__main__":
    main()
