"""数据集加载、完整性校验与「反循环标签」守卫。

两件事在这里被机械地保证：

1. **完整性**：每个数据集都对照 ``evaluation/datasets/SHA256SUMS.txt`` 校验，
   哈希不符即失败。数据漂移会污染跨轮次可比性，必须显式覆盖才能绕过。

2. **反循环**：标签必须来自规格（spec），不能来自被测实现的输出。数据集里
   每条样本的 ``label_source`` 若以 ``observed:`` / ``live:`` 开头，说明它是抄
   当前系统跑出来的结果，这种标签测出来永远是满分，直接判失败。

   反例见 ``evaluation/showcase/generate_datasets.py``：它把 ``expected_output``
   硬编码成规则抽取器的固定输出字符串，所以偏好指标恒为 100%，该数字无意义。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

#: 被视为"由被测实现派生"的标签来源前缀，出现即拒绝。
DERIVED_LABEL_PREFIXES = ("observed:", "live:", "actual:", "predicted:")

DEFAULT_SUMS_PATH = Path("evaluation/datasets/SHA256SUMS.txt")


class DatasetError(RuntimeError):
    """数据集加载或校验失败。"""


def sha256_file(path: Path) -> str:
    """计算文件的 SHA256 十六进制摘要。"""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_sha256_manifest(sums_path: Path) -> dict[str, str]:
    """读取 ``sha256sum`` 格式的清单，返回 ``{文件名: 摘要}``。"""
    if not sums_path.exists():
        raise DatasetError(f"校验清单不存在：{sums_path}")
    manifest: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        # sha256sum 的输出可能带 "*" 表示二进制模式。
        manifest[name.strip().lstrip("*")] = digest.strip().lower()
    return manifest


def verify_dataset_hash(
    path: Path, sums_path: Path | None = None
) -> tuple[bool, str, str]:
    """校验单个数据集文件，返回 ``(是否一致, 实际摘要, 期望摘要)``。

    清单里没有该文件时返回 ``(True, actual, "")``——新数据集允许尚未登记，
    由生成器负责补写清单。
    """
    manifest = load_sha256_manifest(sums_path or DEFAULT_SUMS_PATH)
    expected = manifest.get(path.name, "")
    actual = sha256_file(path)
    if not expected:
        return True, actual, ""
    return actual == expected, actual, expected


def iter_label_sources(node: Any, path: str = "") -> Iterator[tuple[str, str]]:
    """递归产出 ``(位置, label_source)`` 二元组。"""
    if isinstance(node, dict):
        source = node.get("label_source")
        if isinstance(source, str):
            yield path or "<root>", source
        for key, value in node.items():
            yield from iter_label_sources(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_label_sources(value, f"{path}[{index}]")


def assert_no_service_derived_labels(dataset: dict[str, Any]) -> None:
    """拒绝任何由被测实现派生的标签。"""
    offenders = [
        f"{location} -> {source!r}"
        for location, source in iter_label_sources(dataset)
        if source.lower().startswith(DERIVED_LABEL_PREFIXES)
    ]
    if offenders:
        raise DatasetError(
            "数据集含由被测实现派生的标签（循环自证），拒绝使用：\n  "
            + "\n  ".join(offenders[:10])
        )


def dataset_provenance(path: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    """构建报告用的数据集溯源块。"""
    metadata = dataset.get("metadata") if isinstance(dataset, dict) else None
    metadata = metadata if isinstance(metadata, dict) else {}
    variants = [
        key
        for key in (
            "samples", "queries", "memories", "pairs",
            # 延迟集用这两个键名，漏掉会让溯源块显示为空。
            "warmup_queries", "formal_queries",
        )
        if isinstance(dataset.get(key), list)
    ]
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "dataset_id": metadata.get("dataset_id", ""),
        "version": metadata.get("version", ""),
        "spec_version": metadata.get("spec_version", ""),
        "label_source": metadata.get("label_source", ""),
        "generator": metadata.get("generator", ""),
        "generator_git_commit": metadata.get("generator_git_commit", ""),
        "counts": {key: len(dataset[key]) for key in variants},
    }


def load_dataset(
    path: str | Path,
    *,
    sums_path: str | Path | None = None,
    allow_drift: bool = False,
    check_labels: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """加载数据集并校验，返回 ``(dataset, provenance)``。

    参数:
        allow_drift: 哈希不符时是否放行（报告会记 ``dataset_drift: True``）。
        check_labels: 是否执行反循环标签检查。

    异常:
        :class:`DatasetError` —— 文件缺失、JSON 非法、哈希不符或标签自证。
    """
    dataset_path = Path(path)
    if not dataset_path.exists():
        raise DatasetError(f"数据集不存在：{dataset_path}")

    sums = Path(sums_path) if sums_path is not None else DEFAULT_SUMS_PATH
    matched, actual, expected = verify_dataset_hash(dataset_path, sums)
    if not matched and not allow_drift:
        raise DatasetError(
            f"数据集哈希不符：{dataset_path.name}\n"
            f"  期望 {expected}\n  实际 {actual}\n"
            f"  若确为有意变更，请重跑生成器更新 {sums}，或用 --allow-dataset-drift 显式放行。"
        )

    try:
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise DatasetError(f"数据集 JSON 解析失败：{dataset_path}: {exc}") from exc
    if not isinstance(dataset, dict):
        raise DatasetError(f"数据集根节点必须是对象：{dataset_path}")

    if check_labels:
        assert_no_service_derived_labels(dataset)

    provenance = dataset_provenance(dataset_path, dataset)
    provenance["hash_verified"] = matched and bool(expected)
    provenance["dataset_drift"] = not matched
    return dataset, provenance
