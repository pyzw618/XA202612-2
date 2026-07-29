"""规则可引用的受信任校验器与脱敏器注册表。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import inspect
import ipaddress
import json
import re
import textwrap
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType, ModuleType

from memoryhub.safety_rules.errors import RuleLibraryError
from memoryhub.safety_rules.versions import (
    component_reference_identity,
    validate_component_reference,
)

Validator = Callable[[str], bool]
Masker = Callable[[str, str], str]

_REDACTED_RE = re.compile(r"^\[REDACTED(?:_[A-Z0-9_]+)?\]$")


class MaskerCapability(str, Enum):
    """由受信任注册方显式证明的脱敏器安全能力。"""

    FULL_REDACTION = "full_redaction"


def _require_component_ref(reference: str) -> str:
    return validate_component_reference(reference)


def _implementation_digest(component: Callable[..., object]) -> str:
    """哈希 callable 及其直接/间接 Python helper 和正则常量。"""
    records: dict[str, dict[str, object]] = {}

    def visit(function: Callable[..., object]) -> None:
        if not inspect.isfunction(function):
            raise RuleLibraryError("components must be inspectable Python functions")
        identity = f"{function.__module__}.{function.__qualname__}"
        if identity in records:
            return
        if getattr(function, "__closure__", None):
            raise RuleLibraryError("components with closures are not allowed")
        try:
            source = inspect.getsource(function)
        except (OSError, TypeError) as exc:
            raise RuleLibraryError(
                "components must have inspectable Python source"
            ) from exc
        normalized = textwrap.dedent(source).replace("\r\n", "\n").strip() + "\n"
        record: dict[str, object] = {
            "source": normalized,
            "defaults": repr(getattr(function, "__defaults__", None)),
            "kwdefaults": repr(getattr(function, "__kwdefaults__", None)),
            "constants": {},
            "dependencies": [],
        }
        records[identity] = record

        globals_ = getattr(function, "__globals__", {})
        dependencies: list[str] = []
        constants: dict[str, str] = {}
        referenced_names = sorted(set(function.__code__.co_names))
        for name in referenced_names:
            dependency = globals_.get(name)
            if inspect.isfunction(dependency):
                dependency_id = f"{dependency.__module__}.{dependency.__qualname__}"
                dependencies.append(dependency_id)
                visit(dependency)
            elif isinstance(dependency, re.Pattern):
                constants[name] = repr((dependency.pattern, dependency.flags))
            elif isinstance(dependency, ModuleType):
                attributes: dict[str, str] = {}
                for attribute_name in referenced_names:
                    if not hasattr(dependency, attribute_name):
                        continue
                    attribute = getattr(dependency, attribute_name)
                    if callable(attribute):
                        attributes[attribute_name] = (
                            f"{getattr(attribute, '__module__', type(attribute).__module__)}."
                            f"{getattr(attribute, '__qualname__', type(attribute).__qualname__)}"
                        )
                    elif isinstance(
                        attribute,
                        (str, bytes, int, float, bool, tuple, frozenset),
                    ):
                        attributes[attribute_name] = repr(attribute)
                constants[name] = json.dumps(
                    {
                        "module": dependency.__name__,
                        "attributes": attributes,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            elif isinstance(dependency, type):
                constants[name] = (
                    f"type:{dependency.__module__}.{dependency.__qualname__}"
                )
            elif callable(dependency):
                constants[name] = (
                    "callable:"
                    f"{getattr(dependency, '__module__', type(dependency).__module__)}."
                    f"{getattr(dependency, '__qualname__', type(dependency).__qualname__)}"
                )
            elif isinstance(dependency, (dict, list, set, bytearray)):
                raise RuleLibraryError(
                    "components with mutable global dependencies are not allowed"
                )
            elif isinstance(
                dependency,
                (str, bytes, int, float, bool, tuple, frozenset),
            ):
                constants[name] = repr(dependency)
        record["dependencies"] = dependencies
        record["constants"] = constants

    visit(component)
    payload = json.dumps(
        records,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _regex_candidate(value: str) -> bool:
    return bool(value)


def _non_placeholder(value: str) -> bool:
    return bool(value.strip()) and _REDACTED_RE.fullmatch(value.strip()) is None


def _cn_resident_id(value: str) -> bool:
    """校验 GB 11643 的 18 位号码候选、出生日期、顺序码和 MOD 11-2 校验位。"""
    normalized = value.strip().upper()
    if re.fullmatch(r"[1-9]\d{16}[\dX]", normalized) is None:
        return False

    try:
        birthday = datetime.strptime(normalized[6:14], "%Y%m%d").date()
    except ValueError:
        return False
    # 保持 validator 可复现；“是否为未来日期”应由带 scanned_at 的策略层判断。
    if birthday.year < 1800 or birthday.year > 2099:
        return False
    if normalized[14:17] == "000":
        return False

    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    check_characters = "10X98765432"
    checksum = sum(
        int(digit) * weight
        for digit, weight in zip(normalized[:17], weights, strict=True)
    )
    return normalized[-1] == check_characters[checksum % 11]


def _cn_mobile(value: str) -> bool:
    """项目级中国大陆移动号码候选校验；号段变化仍需规则版本更新。"""
    return re.fullmatch(r"1[3-9]\d{9}", value.strip()) is not None


def _email_address(value: str) -> bool:
    """校验项目支持的 ASCII RFC 5322 addr-spec 子集。"""
    candidate = value.strip()
    if len(candidate) > 254 or candidate.count("@") != 1:
        return False
    local, domain = candidate.rsplit("@", 1)
    if not local or len(local) > 64 or local.startswith(".") or local.endswith("."):
        return False
    if (
        ".." in local
        or re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+", local) is None
    ):
        return False
    if len(domain) > 253 or domain.startswith(".") or domain.endswith("."):
        return False
    labels = domain.split(".")
    if len(labels) < 2:
        return False
    return all(
        label
        and len(label) <= 63
        and not label.startswith("-")
        and not label.endswith("-")
        and re.fullmatch(r"[A-Za-z0-9-]+", label) is not None
        for label in labels
    )


def _ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return True


def _decode_base64url_json(segment: str) -> object:
    padding = "=" * (-len(segment) % 4)
    raw = base64.urlsafe_b64decode((segment + padding).encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def _jwt(value: str) -> bool:
    parts = value.strip().split(".")
    if len(parts) != 3 or not all(parts):
        return False
    try:
        header = _decode_base64url_json(parts[0])
        payload = _decode_base64url_json(parts[1])
    except (binascii.Error, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return isinstance(header, dict) and isinstance(payload, dict)


def _pem_private_key(value: str) -> bool:
    candidate = value.strip()
    match = re.fullmatch(
        r"-----BEGIN (?P<label>(?:RSA |EC |ENCRYPTED )?PRIVATE KEY)-----"
        r"(?s:.+)"
        r"-----END (?P=label)-----",
        candidate,
    )
    return match is not None


def _luhn_account(value: str) -> bool:
    digits = re.sub(r"[\s-]", "", value)
    if re.fullmatch(r"\d{13,19}", digits) is None or len(set(digits)) == 1:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, character in enumerate(digits):
        digit = int(character)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _under_fourteen(value: str) -> bool:
    try:
        age = int(value.strip())
    except ValueError:
        return False
    return 0 <= age < 14


def _full_redact(value: str, replacement: str) -> str:
    if _REDACTED_RE.fullmatch(value.strip()) is not None:
        return value
    if not replacement:
        raise RuleLibraryError("full-redaction masker requires a replacement marker")
    return replacement


def _no_mask(value: str, replacement: str) -> str:
    del value, replacement
    raise RuleLibraryError("this rule deliberately has no masking operation")


@dataclass(frozen=True)
class ComponentRegistry:
    """仅解析进程内显式注册的版本化组件，不支持动态 import/eval。"""

    validators: Mapping[str, Validator]
    maskers: Mapping[str, Masker]
    component_fingerprints: Mapping[str, str] | None = None
    masker_capabilities: Mapping[str, Collection[MaskerCapability | str]] = field(
        default_factory=dict
    )
    digest: str = field(init=False)
    _verify_implementation: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        validators = dict(self.validators)
        maskers = dict(self.maskers)
        overlap = set(validators) & set(maskers)
        if overlap:
            raise RuleLibraryError(
                "validator and masker references must be disjoint: "
                + ", ".join(sorted(overlap))
            )
        semantic_references: dict[tuple[str, str], str] = {}
        for reference, component in (*validators.items(), *maskers.items()):
            _require_component_ref(reference)
            semantic_identity = component_reference_identity(reference)
            previous_reference = semantic_references.setdefault(
                semantic_identity,
                reference,
            )
            if previous_reference != reference:
                raise RuleLibraryError(
                    "component references must be semantically unique: "
                    f"{previous_reference}, {reference}"
                )
            if not inspect.isfunction(component) or inspect.iscoroutinefunction(
                component
            ):
                raise RuleLibraryError(
                    "registered components must be synchronous Python functions: "
                    f"{reference}"
                )
        for reference, validator in validators.items():
            try:
                parameters = tuple(inspect.signature(validator).parameters.values())
            except (TypeError, ValueError) as exc:
                raise RuleLibraryError(
                    f"validator must accept exactly one candidate value: {reference}"
                ) from exc
            if (
                len(parameters) != 1
                or parameters[0].kind
                not in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
                or parameters[0].default is not inspect.Parameter.empty
            ):
                raise RuleLibraryError(
                    f"validator must accept exactly one candidate value: {reference}"
                )
        for reference, masker in maskers.items():
            try:
                parameters = tuple(inspect.signature(masker).parameters.values())
            except (TypeError, ValueError) as exc:
                raise RuleLibraryError(
                    f"masker must accept candidate and replacement values: {reference}"
                ) from exc
            if len(parameters) != 2 or any(
                parameter.kind
                not in {
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                }
                or parameter.default is not inspect.Parameter.empty
                for parameter in parameters
            ):
                raise RuleLibraryError(
                    f"masker must accept candidate and replacement values: {reference}"
                )

        raw_capabilities = dict(self.masker_capabilities)
        unknown_capability_refs = set(raw_capabilities) - set(maskers)
        if unknown_capability_refs:
            raise RuleLibraryError(
                "masker capabilities reference unknown maskers: "
                + ", ".join(sorted(unknown_capability_refs))
            )
        capabilities: dict[str, frozenset[MaskerCapability]] = {}
        for reference, declared in raw_capabilities.items():
            if isinstance(declared, (str, bytes)) or not isinstance(
                declared, Collection
            ):
                raise RuleLibraryError(
                    f"masker capabilities must be a collection: {reference}"
                )
            try:
                normalized = frozenset(
                    (
                        capability
                        if isinstance(capability, MaskerCapability)
                        else MaskerCapability(capability)
                    )
                    for capability in declared
                )
            except (TypeError, ValueError) as exc:
                raise RuleLibraryError(
                    f"unknown masker capability declared for {reference}"
                ) from exc
            if normalized:
                capabilities[reference] = normalized

        components: dict[str, Callable[..., object]] = {**validators, **maskers}
        fingerprints = {
            reference: _implementation_digest(component)
            for reference, component in components.items()
        }
        provided_fingerprints = self.component_fingerprints
        if provided_fingerprints is not None:
            expected_fingerprints = dict(provided_fingerprints)
            if set(expected_fingerprints) != set(components):
                raise RuleLibraryError(
                    "component fingerprints must exactly cover the registry"
                )
            if any(
                re.fullmatch(r"[0-9a-f]{64}", digest) is None
                for digest in expected_fingerprints.values()
            ):
                raise RuleLibraryError(
                    "component fingerprints must be lowercase SHA-256 values"
                )
            mismatches = sorted(
                reference
                for reference, digest in fingerprints.items()
                if expected_fingerprints[reference] != digest
            )
            if mismatches:
                raise RuleLibraryError(
                    "component fingerprints do not match implementations: "
                    + ", ".join(mismatches)
                )

        registry_payload = json.dumps(
            [
                {
                    "reference": reference,
                    "kind": "validator" if reference in validators else "masker",
                    "fingerprint": fingerprints[reference],
                    "capabilities": sorted(
                        capability.value
                        for capability in capabilities.get(reference, frozenset())
                    ),
                }
                for reference in sorted(components)
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "validators", MappingProxyType(validators))
        object.__setattr__(self, "maskers", MappingProxyType(maskers))
        object.__setattr__(
            self,
            "component_fingerprints",
            MappingProxyType(fingerprints),
        )
        object.__setattr__(
            self,
            "masker_capabilities",
            MappingProxyType(capabilities),
        )
        object.__setattr__(self, "digest", hashlib.sha256(registry_payload).hexdigest())
        object.__setattr__(self, "_verify_implementation", True)

    def _assert_component_integrity(
        self,
        reference: str,
        component: Callable[..., object],
    ) -> None:
        if not self._verify_implementation:
            return
        assert self.component_fingerprints is not None
        if _implementation_digest(component) != self.component_fingerprints[reference]:
            raise RuleLibraryError(
                f"component implementation changed after snapshot creation: {reference}"
            )

    def verify_integrity(self) -> None:
        """在规则快照创建或一次扫描开始时校验全部注册组件一次。"""
        for reference, validator_component in self.validators.items():
            self._assert_component_integrity(reference, validator_component)
        for reference, masker_component in self.maskers.items():
            self._assert_component_integrity(reference, masker_component)

    def scoped_digest(self, references: Collection[str]) -> str:
        """只绑定当前规则快照实际引用的组件，避免无关注册项改变历史摘要。"""
        selected = set(references)
        available = set(self.validators) | set(self.maskers)
        unknown = selected - available
        if unknown:
            raise RuleLibraryError(
                "cannot digest unknown components: " + ", ".join(sorted(unknown))
            )
        assert self.component_fingerprints is not None
        payload = json.dumps(
            [
                {
                    "reference": reference,
                    "kind": ("validator" if reference in self.validators else "masker"),
                    "fingerprint": self.component_fingerprints[reference],
                    "capabilities": sorted(
                        (
                            capability.value
                            if isinstance(capability, MaskerCapability)
                            else capability
                        )
                        for capability in self.masker_capabilities.get(
                            reference,
                            frozenset(),
                        )
                    ),
                }
                for reference in sorted(selected)
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def resolve_validator(self, reference: str) -> Validator:
        _require_component_ref(reference)
        try:
            validator = self.validators[reference]
        except KeyError as exc:
            raise RuleLibraryError(f"unknown validator component: {reference}") from exc
        self._assert_component_integrity(reference, validator)

        def checked(candidate: str) -> bool:
            if not isinstance(candidate, str):
                raise RuleLibraryError("validator candidates must be strings")
            result = validator(candidate)
            if type(result) is not bool:
                raise RuleLibraryError(f"validator must return bool: {reference}")
            return result

        return checked

    def resolve_masker(self, reference: str) -> Masker:
        _require_component_ref(reference)
        try:
            masker = self.maskers[reference]
        except KeyError as exc:
            raise RuleLibraryError(f"unknown masker component: {reference}") from exc
        self._assert_component_integrity(reference, masker)
        capabilities = self.masker_capabilities.get(reference, frozenset())

        def checked(candidate: str, replacement: str) -> str:
            if not isinstance(candidate, str) or not isinstance(replacement, str):
                raise RuleLibraryError("masker inputs must be strings")
            result = masker(candidate, replacement)
            if not isinstance(result, str):
                raise RuleLibraryError(f"masker must return str: {reference}")
            if (
                MaskerCapability.FULL_REDACTION in capabilities
                and result != replacement
                and not (
                    result == candidate
                    and _REDACTED_RE.fullmatch(candidate.strip()) is not None
                )
            ):
                raise RuleLibraryError(
                    "full_redaction masker must return exactly the replacement: "
                    f"{reference}"
                )
            return result

        return checked

    def require_full_redaction_masker(
        self,
        reference: str,
        replacement: str,
    ) -> None:
        """
        要求注册方显式证明完整替换能力，并执行一个最小契约探针。

        capability 是安全边界；探针用于尽早发现误注册，不声称能证明任意
        第三方代码的全部行为。
        """
        _require_component_ref(reference)
        capabilities = self.masker_capabilities.get(reference, frozenset())
        if MaskerCapability.FULL_REDACTION not in capabilities:
            raise RuleLibraryError(
                f"redact_allow requires a full_redaction masker capability: {reference}"
            )
        candidate = "memoryhub-full-redaction-canary-7d8547a76a"
        result = self.resolve_masker(reference)(candidate, replacement)
        if result != replacement or candidate in result:
            raise RuleLibraryError(
                f"full_redaction masker failed its contract probe: {reference}"
            )


_BUILTIN_VALIDATORS: dict[str, Validator] = {
    "builtin.regex@1.0": _regex_candidate,
    "builtin.non_placeholder@1.0": _non_placeholder,
    "builtin.cn_resident_id@1.0": _cn_resident_id,
    "builtin.cn_mobile@1.0": _cn_mobile,
    "builtin.email_ascii@1.0": _email_address,
    "builtin.ip_address@1.0": _ip_address,
    "builtin.jwt@1.0": _jwt,
    "builtin.pem_private_key@1.0": _pem_private_key,
    "builtin.luhn_account@1.0": _luhn_account,
    "builtin.under_fourteen@1.0": _under_fourteen,
}
_BUILTIN_MASKERS: dict[str, Masker] = {
    "builtin.full_redact@1.0": _full_redact,
    "builtin.none@1.0": _no_mask,
}
BUILTIN_COMPONENTS = ComponentRegistry(
    validators=_BUILTIN_VALIDATORS,
    maskers=_BUILTIN_MASKERS,
    masker_capabilities={
        "builtin.full_redact@1.0": {MaskerCapability.FULL_REDACTION},
    },
)


def resolve_validator(reference: str) -> Validator:
    """从默认可信注册表解析校验器。"""
    return BUILTIN_COMPONENTS.resolve_validator(reference)


def resolve_masker(reference: str) -> Masker:
    """从默认可信注册表解析脱敏器。"""
    return BUILTIN_COMPONENTS.resolve_masker(reference)
