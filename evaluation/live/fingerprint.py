"""环境指纹：证明数字确实来自「麒麟 SDK + Milvus」的真机服务。

报告里必须携带环境指纹，否则读者无法区分"真机结果"与"进程内 mock 结果"。
本模块只读 ``GET /api/memory/system/status``，从中提取验收关心的字段，
并支持用 ``key=value`` 形式的断言（例如
``runtime_mode=production,embedding.provider=kylin``）在评测开始前拦截误跑。

字段路径用点号展开嵌套结构：``embedding.provider``、``vector_engine.connected``。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# 真机验收要求的最小指纹。缺任何一项都不构成"麒麟 SDK + Milvus"证据。
PRODUCTION_REQUIREMENTS: tuple[str, ...] = (
    "runtime_mode=production",
    "embedding.provider=kylin",
    "embedding.dimension=768",
    "vector_engine.provider=milvus",
    "vector_engine.connected=True",
)


class FingerprintMismatch(RuntimeError):
    """环境指纹不满足验收要求，对应 runner 退出码 2。"""

    def __init__(self, mismatches: list[str]) -> None:
        self.mismatches = mismatches
        detail = "；".join(mismatches)
        super().__init__(f"环境指纹不匹配：{detail}")


def flatten(source: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    """把嵌套字典展开成 ``{"a.b.c": value}`` 的点号键形式。"""
    flat: dict[str, Any] = {}
    for key, value in source.items():
        path = f"{prefix}{key}"
        if isinstance(value, Mapping):
            flat.update(flatten(value, prefix=f"{path}."))
        else:
            flat[path] = value
    return flat


def read_system_status(client: Any) -> dict[str, Any]:
    """读取服务状态；服务不可达时由客户端抛 :class:`ServiceUnavailable`。"""
    status = client.get_system_status()
    if not isinstance(status, dict):
        raise FingerprintMismatch([f"系统状态响应不是对象：{type(status).__name__}"])
    return status


def build_environment_fingerprint(
    status: Mapping[str, Any],
    *,
    base_url: str = "",
    service_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """从系统状态构建报告用的环境指纹。

    保留原始状态快照（``system_status``）以便复核，同时抽出验收关心的扁平字段。
    """
    fingerprint: dict[str, Any] = {
        "base_url": base_url,
        "runtime_mode": status.get("runtime_mode"),
        "service": status.get("service"),
        "version": status.get("version"),
        "embedding": dict(status.get("embedding") or {}),
        "vector_engine": dict(status.get("vector_engine") or {}),
        "llm": dict(status.get("llm") or {}),
        "retrieval": dict(status.get("retrieval") or {}),
        "system_status": dict(status),
    }
    if service_config is not None:
        fingerprint["system_config"] = dict(service_config)
    return fingerprint


def check_fingerprint(
    fingerprint: Mapping[str, Any], requirements: Iterable[str]
) -> list[str]:
    """逐条比对要求，返回不匹配描述列表；空列表表示全部满足。"""
    flat = flatten(fingerprint)
    mismatches: list[str] = []
    for requirement in requirements:
        requirement = requirement.strip()
        if not requirement:
            continue
        if "=" not in requirement:
            mismatches.append(f"要求格式非法（应为 key=value）：{requirement!r}")
            continue
        key, _, expected = requirement.partition("=")
        key, expected = key.strip(), expected.strip()
        if key not in flat:
            mismatches.append(f"{key} 在环境指纹中缺失（期望 {expected}）")
            continue
        actual = flat[key]
        # 布尔值在状态里可能是 True/False，而命令行写的是 True/False 字符串。
        if isinstance(actual, bool):
            normalized = "True" if actual else "False"
        else:
            normalized = str(actual)
        if normalized != expected:
            mismatches.append(f"{key}={normalized}（期望 {expected}）")
    return mismatches


def assert_fingerprint(
    client: Any,
    requirements: Iterable[str],
    *,
    service_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """读取并校验环境指纹，不满足即抛 :class:`FingerprintMismatch`。"""
    status = read_system_status(client)
    fingerprint = build_environment_fingerprint(
        status, base_url=getattr(client, "base_url", ""), service_config=service_config
    )
    mismatches = check_fingerprint(fingerprint, requirements)
    if mismatches:
        raise FingerprintMismatch(mismatches)
    return fingerprint


def check_preconditions(
    fingerprint: Mapping[str, Any],
) -> list[str]:
    """检查会让某项指标失去意义的前置条件，返回警告列表（不抛错）。

    这些不是硬门禁：即使不满足，指标仍可测量，但**必须**在报告里标注，否则
    读者会把"配置缺失"误读成"算法不行"。

    典型例子：部署未配置 LLM 密钥时，``PreferenceExtractor._llm_extract``
    直接返回空，隐式偏好一条都抽不出来——偏好准确率会从"算法能力"退化为
    "规则覆盖度"。
    """
    warnings: list[str] = []
    config = fingerprint.get("system_config")
    llm = (config or {}).get("llm") if isinstance(config, Mapping) else None
    if isinstance(llm, Mapping):
        if llm.get("api_key_configured") is False:
            warnings.append(
                "LLM 密钥未配置（llm.api_key_configured=false）：隐式偏好抽取路径不可用，"
                "偏好提取准确率仅反映规则路径覆盖度；冲突的 LLM 仲裁同样不生效。"
                "补齐密钥后需重测这两项。"
            )
    elif llm is None:
        warnings.append("无法读取 llm 配置，偏好/冲突指标的 LLM 路径状态未知。")
    return warnings
