from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.ingestion import IngestionPipeline


def iter_json_array(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[dict[str, Any]]:
    """Stream top-level objects from a JSON array without loading the file."""

    decoder = json.JSONDecoder()
    buffer = ""
    position = 0
    with path.open("r", encoding="utf-8") as handle:
        while True:
            chunk = handle.read(chunk_size)
            eof = not chunk
            buffer += chunk
            while True:
                while position < len(buffer) and buffer[position] in " \t\r\n,[":
                    position += 1
                if position < len(buffer) and buffer[position] == "]":
                    return
                if position >= len(buffer):
                    buffer = ""
                    position = 0
                    break
                try:
                    value, end = decoder.raw_decode(buffer, position)
                except json.JSONDecodeError:
                    buffer = buffer[position:]
                    position = 0
                    break
                if not isinstance(value, dict):
                    raise ValueError("LongMemEval top-level entries must be objects")
                yield value
                position = end
            if eof:
                if buffer.strip() not in ("", "]"):
                    raise ValueError("incomplete JSON value at end of file")
                return


def iter_raw_events(row: dict[str, Any]) -> Iterator[tuple[dict[str, Any], str]]:
    question_id = str(row.get("question_id", "unknown"))
    dates = row.get("haystack_dates") or []
    session_ids = row.get("haystack_session_ids") or []
    sessions = row.get("haystack_sessions") or []
    for session_index, session in enumerate(sessions):
        if not isinstance(session, list):
            continue
        session_id = str(session_ids[session_index]) if session_index < len(session_ids) else f"session_{session_index}"
        occurred_at = dates[session_index] if session_index < len(dates) else row.get("question_date", "")
        for message_index, message in enumerate(session):
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "unknown")).lower()
            content = message.get("content", "")
            event_id = f"lme:{question_id}:{session_id}:{message_index}"
            common = {
                "event_id": event_id,
                "user_id": f"longmemeval:{question_id}",
                "session_id": session_id,
                "scene": "long_term_memory",
                "task_type": str(row.get("question_type", "unknown")),
                "occurred_at": occurred_at,
                "text": content,
            }
            if role == "user":
                raw = {
                    **common,
                    "source_type": "user_behavior",
                    "event_type": "user_action",
                    "payload": {
                        "action": "message",
                        "role": role,
                        "has_answer": bool(message.get("has_answer", False)),
                    },
                }
            else:
                raw = {
                    **common,
                    "source_type": "tool_result",
                    "event_type": "tool_result",
                    "payload": {
                        "tool_name": "assistant_response",
                        "status": "success",
                        "role": role,
                        "has_answer": bool(message.get("has_answer", False)),
                    },
                }
            yield raw, role


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def evaluate(
    path: Path,
    limit_events: int = 0,
    progress_every: int = 100_000,
    events_output: Path | None = None,
) -> dict[str, Any]:
    pipeline = IngestionPipeline(reference_time="2026-07-20T00:00:00Z")
    status_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    question_type_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    redaction_counts: Counter[str] = Counter()
    latencies_ms: list[float] = []
    questions = sessions = events = empty_text = timestamp_failures = 0
    quality_sum = 0.0
    started = time.perf_counter()
    output_handle = None
    if events_output is not None:
        events_output.parent.mkdir(parents=True, exist_ok=True)
        output_handle = events_output.open("w", encoding="utf-8", newline="\n")

    try:
        stop = False
        for row in iter_json_array(path):
            questions += 1
            question_type_counts[str(row.get("question_type", "unknown"))] += 1
            sessions += len(row.get("haystack_sessions") or [])
            for raw, role in iter_raw_events(row):
                before = time.perf_counter_ns()
                result = pipeline.process(raw)
                latencies_ms.append((time.perf_counter_ns() - before) / 1_000_000)
                events += 1
                status_counts[result.quality.status] += 1
                source_counts[result.source_type] += 1
                role_counts[role] += 1
                issue_counts.update(result.quality.issues)
                redaction_counts.update(result.redactions)
                quality_sum += result.quality.score
                if output_handle is not None:
                    output_handle.write(json.dumps(result.to_dict(), ensure_ascii=False) + "\n")
                if not result.text:
                    empty_text += 1
                if not result.occurred_at:
                    timestamp_failures += 1
                if progress_every and events % progress_every == 0:
                    elapsed = time.perf_counter() - started
                    print(f"progress events={events} rate={events / elapsed:.1f}/s", flush=True)
                if limit_events and events >= limit_events:
                    stop = True
                    break
            if stop:
                break
    finally:
        if output_handle is not None:
            output_handle.close()

    elapsed = time.perf_counter() - started
    return {
        "dataset": str(path),
        "file_bytes": path.stat().st_size,
        "questions": questions,
        "sessions": sessions,
        "events": events,
        "events_output": str(events_output) if events_output is not None else None,
        "elapsed_seconds": elapsed,
        "throughput_events_per_second": events / elapsed if elapsed else 0.0,
        "quality_score_mean": quality_sum / events if events else 0.0,
        "status_counts": dict(status_counts),
        "source_counts": dict(source_counts),
        "role_counts": dict(role_counts),
        "question_type_counts": dict(question_type_counts),
        "empty_text": empty_text,
        "timestamp_failures": timestamp_failures,
        "redaction_counts": dict(redaction_counts),
        "issue_counts": dict(issue_counts),
        "latency_ms": {
            "mean": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
            "p50": percentile(latencies_ms, 0.50),
            "p95": percentile(latencies_ms, 0.95),
            "p99": percentile(latencies_ms, 0.99),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream LongMemEval messages through the ingestion pipeline.")
    parser.add_argument("--data", default="evaluation/datasets/longmemeval/longmemeval_s_cleaned.json")
    parser.add_argument("--limit-events", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=100_000)
    parser.add_argument("--output", help="Optional JSON report path")
    parser.add_argument("--events-output", help="Optional JSONL path for normalized per-event output")
    args = parser.parse_args()
    report = evaluate(
        Path(args.data),
        limit_events=args.limit_events,
        progress_every=args.progress_every,
        events_output=Path(args.events_output) if args.events_output else None,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered + "\n")


if __name__ == "__main__":
    main()
