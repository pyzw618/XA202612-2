"""规则集、规则和组件共用的严格版本标识校验。"""

from __future__ import annotations

import re

from memoryhub.safety_rules.errors import RuleLibraryError


_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_VERSION_IDENTIFIER = r"(?:0|[1-9][0-9]*|[A-Za-z-][0-9A-Za-z-]*)"
_VERSION_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:\.(?:0|[1-9][0-9]*))?"
    rf"(?:-{_VERSION_IDENTIFIER}(?:\.{_VERSION_IDENTIFIER})*)?$"
)


def normalized_version(value: str) -> str:
    """把兼容的 ``major.minor`` 规范为三段，用于等价性和冲突判断。"""
    if not isinstance(value, str) or _VERSION_RE.fullmatch(value) is None:
        raise RuleLibraryError("invalid two- or three-part semantic version")
    core, separator, prerelease = value.partition("-")
    parts = core.split(".")
    if len(parts) == 2:
        parts.append("0")
    normalized = ".".join(parts)
    return normalized + (separator + prerelease if separator else "")


def component_reference_identity(reference: str) -> tuple[str, str]:
    """返回组件名及规范化版本，用于发现 ``1.0``/``1.0.0`` 别名。"""
    if not isinstance(reference, str):
        raise RuleLibraryError(
            "component references must be allow-listed, versioned identifiers"
        )
    name, separator, version = reference.rpartition("@")
    if separator != "@" or _IDENTIFIER_RE.fullmatch(name) is None or not version:
        raise RuleLibraryError(
            "component references must be allow-listed, versioned identifiers"
        )
    try:
        normalized_version(version)
    except RuleLibraryError as exc:
        raise RuleLibraryError(
            "component references must use strict two- or three-part versions"
        ) from exc
    return name, normalized_version(version)


def validate_component_reference(reference: str) -> str:
    """校验 ``component.name@major.minor[.patch][-prerelease]`` 引用。"""
    component_reference_identity(reference)
    return reference
