from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_core.conflict import KnowledgeConflictDetector, KnowledgeItem


def load_dataset(path: Path, drop_metadata: bool = False) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if drop_metadata:
                row["old"] = {"text": row["old"]["text"], "id": row["old"].get("id", f"old_{line_no}")}
                row["new"] = {"text": row["new"]["text"], "id": row["new"].get("id", f"new_{line_no}")}
            rows.append(row)
    return rows


def evaluate(path: Path, drop_metadata: bool = False) -> dict:
    detector = KnowledgeConflictDetector()
    rows = load_dataset(path, drop_metadata=drop_metadata)
    total = len(rows)
    correct = 0
    label_counter = Counter()
    confusion = defaultdict(Counter)
    mistakes = []

    for idx, row in enumerate(rows, 1):
        old = KnowledgeItem.from_dict(row["old"])
        new = KnowledgeItem.from_dict(row["new"])
        gold = row["label"]
        pred = detector.detect(old, new)
        label_counter[gold] += 1
        confusion[gold][pred.label] += 1
        if pred.label == gold:
            correct += 1
        else:
            mistakes.append(
                {
                    "index": idx,
                    "gold": gold,
                    "pred": pred.to_dict(),
                    "old": old.to_dict(),
                    "new": new.to_dict(),
                    "type": row.get("type", ""),
                }
            )

    accuracy = correct / total if total else 0.0
    return {
        "dataset": str(path),
        "drop_metadata": drop_metadata,
        "total": total,
        "correct": correct,
        "accuracy": accuracy,
        "label_counter": dict(label_counter),
        "confusion": {key: dict(value) for key, value in confusion.items()},
        "mistakes": mistakes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate old-new knowledge conflict detection accuracy.")
    parser.add_argument("--data", default="evaluation/datasets/conflict_dataset.jsonl", help="JSONL dataset path")
    parser.add_argument("--drop-metadata", action="store_true", help="Evaluate raw-text-only mode")
    parser.add_argument("--show-mistakes", action="store_true", help="Print mistake details")
    args = parser.parse_args()

    report = evaluate(Path(args.data), drop_metadata=args.drop_metadata)
    print(f"dataset: {report['dataset']}")
    print(f"mode: {'raw-text-only' if report['drop_metadata'] else 'structured-memory'}")
    print(f"total: {report['total']}")
    print(f"correct: {report['correct']}")
    print(f"accuracy: {report['accuracy']:.2%}")
    print(f"label_counter: {report['label_counter']}")
    print(f"confusion: {report['confusion']}")
    if args.show_mistakes and report["mistakes"]:
        print("\nMistakes:")
        for mistake in report["mistakes"]:
            print(json.dumps(mistake, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

