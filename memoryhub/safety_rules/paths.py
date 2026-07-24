"""RFC 6901 JSON Pointer 目标路径模板。"""

from __future__ import annotations

import re
from functools import lru_cache

from memoryhub.safety_rules.errors import RuleLibraryError


_POINTER_SEGMENT_RE = re.compile(r"(?:[^~/]|~[01])*")
_TARGET_POINTER_SEGMENT_RE = re.compile(r"(?:[^~/]|~[012])*")


def _split_pointer(value: str, *, allow_wildcards: bool) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.startswith("/"):
        raise RuleLibraryError("target path must be an absolute RFC 6901 JSON Pointer")

    segments = tuple(value[1:].split("/"))
    for segment in segments:
        if allow_wildcards:
            if segment in {"*", "**"}:
                continue
            if "*" in segment:
                raise RuleLibraryError(
                    "target path wildcards must occupy a complete JSON Pointer segment"
                )
        segment_pattern = (
            _TARGET_POINTER_SEGMENT_RE if allow_wildcards else _POINTER_SEGMENT_RE
        )
        if segment_pattern.fullmatch(segment) is None:
            if allow_wildcards:
                raise RuleLibraryError(
                    "target path contains an invalid escape; only ~0, ~1 and the "
                    "literal-asterisk extension ~2 are valid"
                )
            raise RuleLibraryError(
                "JSON path contains an invalid RFC 6901 escape; only ~0 and ~1 "
                "are valid"
            )
    return segments


def validate_target_path(value: str) -> str:
    """校验一个绝对、全路径锚定的 JSON Pointer glob。"""
    segments = _split_pointer(value, allow_wildcards=True)
    if any(left == right == "**" for left, right in zip(segments, segments[1:])):
        raise RuleLibraryError("adjacent ** target path segments are ambiguous")
    return value


def validate_json_path(value: str) -> str:
    """校验扫描结果使用的绝对 RFC 6901 JSON Pointer。"""
    _split_pointer(value, allow_wildcards=False)
    return value


@lru_cache(maxsize=512)
def _compiled_target_path(target_path: str) -> re.Pattern[str]:
    segments = _split_pointer(validate_target_path(target_path), allow_wildcards=True)
    parts = [r"\A"]
    for segment in segments:
        if segment == "*":
            parts.append(r"/[^/]*")
        elif segment == "**":
            parts.append(r"(?:/[^/]*)*")
        else:
            literal_segment = segment.replace("~2", "*")
            parts.append("/" + re.escape(literal_segment))
    parts.append(r"\Z")
    return re.compile("".join(parts))


def path_matches(
    target_path: str,
    json_path: str,
    *,
    case_sensitive: bool = True,
) -> bool:
    """
    判断绝对 JSON Pointer 是否匹配目标模板。

    ``*`` 匹配一个路径段（包括 RFC 6901 的空键），``**`` 匹配零个或多个路径段。两者都只能
    占据完整路径段；目标模板以 ``~2`` 表示字面星号，因此可精确匹配名为
    ``*`` 或 ``**`` 的 JSON 键。
    """
    validate_json_path(json_path)
    if case_sensitive:
        return _compiled_target_path(target_path).fullmatch(json_path) is not None
    return (
        re.fullmatch(
            _compiled_target_path(target_path).pattern,
            json_path,
            flags=re.IGNORECASE | re.ASCII,
        )
        is not None
    )


def compile_target_paths(
    target_paths: tuple[str, ...],
    *,
    case_sensitive: bool = True,
) -> str:
    """把目标模板编译为旧 ``SensitiveRule.path_pattern`` 所需的锚定正则。"""
    normalized = tuple(validate_target_path(path) for path in target_paths)
    if not normalized:
        raise RuleLibraryError("a rule must declare at least one target path")
    if "/**" in normalized:
        return ""

    expressions: list[str] = []
    for target_path in normalized:
        compiled = _compiled_target_path(target_path)
        expressions.append(compiled.pattern)
    result = (
        expressions[0] if len(expressions) == 1 else "(?:" + "|".join(expressions) + ")"
    )
    if case_sensitive:
        return result
    return f"(?ai:{result})"
