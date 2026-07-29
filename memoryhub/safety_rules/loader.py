"""版本化安全规则资源的严格加载、校验和编译。"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, NoReturn

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from memoryhub.adapter.schemas import SafetyAction, SensitiveRule, canonical_sha256
from memoryhub.safety_rules.components import (
    BUILTIN_COMPONENTS,
    ComponentRegistry,
)
from memoryhub.safety_rules.errors import (
    RuleIntegrityError,
    RuleLibraryError,
    RuleSetNotFoundError,
)
from memoryhub.safety_rules.models import (
    RuleDefaultAction,
    RuleDefinition,
    RuleSetDocument,
    RuleSetSnapshot,
)
from memoryhub.safety_rules.paths import compile_target_paths
from memoryhub.safety_rules.versions import normalized_version

_MAX_RULE_RESOURCE_BYTES = 2 * 1024 * 1024
_COMPILER_SCHEMA_VERSION = "1.0"


class _CatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        normalized_version(value)
        return value


class _RuleCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    rule_set_id: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    default_version: str = Field(min_length=1)
    versions: tuple[_CatalogEntry, ...] = Field(min_length=1)

    @field_validator("default_version")
    @classmethod
    def validate_default_version(cls, value: str) -> str:
        normalized_version(value)
        return value

    @model_validator(mode="after")
    def validate_catalog(self) -> "_RuleCatalog":
        versions = [entry.version for entry in self.versions]
        normalized_versions = [normalized_version(version) for version in versions]
        resources_ = [entry.resource for entry in self.versions]
        if len(normalized_versions) != len(set(normalized_versions)):
            raise ValueError("catalog versions must be semantically unique")
        if len(resources_) != len(set(resources_)):
            raise ValueError("catalog resources must be unique")
        if self.default_version not in set(versions):
            raise ValueError("catalog default_version is not declared")
        for resource_name in resources_:
            posix_path = PurePosixPath(resource_name)
            windows_path = PureWindowsPath(resource_name)
            if (
                posix_path.is_absolute()
                or windows_path.is_absolute()
                or bool(windows_path.drive)
                or len(posix_path.parts) != 1
                or len(windows_path.parts) != 1
                or posix_path.name != resource_name
                or windows_path.name != resource_name
                or posix_path.suffix != ".json"
            ):
                raise ValueError("catalog resource must be a local JSON filename")
        return self


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RuleIntegrityError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> NoReturn:
    raise RuleIntegrityError(f"non-finite JSON number is not allowed: {value}")


def _strict_json_loads(text: str, *, source: str) -> Any:
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except RuleIntegrityError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RuleIntegrityError(f"invalid JSON in {source}: {exc}") from exc


def _read_utf8(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise RuleIntegrityError(
            f"cannot read UTF-8 rule resource {path}: {exc}"
        ) from exc
    if len(payload) > _MAX_RULE_RESOURCE_BYTES:
        raise RuleIntegrityError(f"rule resource exceeds 2 MiB: {path}")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuleIntegrityError(
            f"cannot decode UTF-8 rule resource {path}: {exc}"
        ) from exc


def _compile_rule(rule: RuleDefinition) -> SensitiveRule:
    action = {
        RuleDefaultAction.REJECT: SafetyAction.REJECT,
        RuleDefaultAction.REDACT_ALLOW: SafetyAction.MASK,
        RuleDefaultAction.REVIEW: SafetyAction.REVIEW,
        RuleDefaultAction.ALLOW: SafetyAction.ALLOW,
    }[rule.default_action]
    provenance = "; ".join(
        f"{link.source_id}[{link.role.value}]"
        + (f" {link.locator}" if link.locator else "")
        for link in rule.standard_ref
    )
    return SensitiveRule(
        name=rule.rule_id,
        version=rule.rule_version,
        pattern=rule.pattern,
        level=rule.risk_level,
        action=action,
        reason_code=rule.reason_code,
        reason=rule.reason,
        standard_source=provenance,
        replacement=rule.replacement,
        match_group=rule.match_group,
        path_pattern=compile_target_paths(
            rule.target_paths,
            case_sensitive=rule.target_path_case_sensitive,
        ),
        enabled=rule.enabled,
    )


def _snapshot(
    document: RuleSetDocument,
    *,
    registry: ComponentRegistry,
) -> RuleSetSnapshot:
    compiled: list[SensitiveRule] = []
    component_references: set[str] = set()
    for rule in document.rules:
        component_references.update((rule.validator, rule.masker))
        registry.resolve_validator(rule.validator)
        registry.resolve_masker(rule.masker)
        if rule.default_action is RuleDefaultAction.REDACT_ALLOW:
            registry.require_full_redaction_masker(
                rule.masker,
                rule.replacement,
            )
        compiled.append(_compile_rule(rule))

    component_registry_digest = registry.scoped_digest(component_references)
    digest = canonical_sha256(
        {
            "document": document.model_dump(mode="json"),
            "compiler_schema_version": _COMPILER_SCHEMA_VERSION,
            "compiled_rules": [rule.model_dump(mode="json") for rule in compiled],
            "component_registry_digest": component_registry_digest,
        }
    )
    return RuleSetSnapshot(
        schema_version=document.schema_version,
        rule_set_id=document.rule_set_id,
        version=document.version,
        released_on=document.released_on,
        status_as_of=document.status_as_of,
        sources=document.sources,
        governance_ref=document.governance_ref,
        rules=document.rules,
        compiled_rules=tuple(compiled),
        component_registry_digest=component_registry_digest,
        component_registry=registry,
        digest=digest,
    )


def _load_document(
    payload: Any,
    *,
    source: str,
    registry: ComponentRegistry,
) -> RuleSetSnapshot:
    try:
        document = RuleSetDocument.model_validate(payload)
    except ValidationError as exc:
        raise RuleLibraryError(f"invalid rule set {source}: {exc}") from exc
    return _snapshot(document, registry=registry)


def load_rule_set_file(
    path: str | Path,
    *,
    registry: ComponentRegistry = BUILTIN_COMPONENTS,
) -> RuleSetSnapshot:
    """从一个严格 JSON 文件原子加载规则集；任意一条无效都会使整体失败。"""
    resolved = Path(path)
    payload = _strict_json_loads(_read_utf8(resolved), source=str(resolved))
    return _load_document(payload, source=str(resolved), registry=registry)


def _read_builtin_resource(resource_name: str) -> str:
    try:
        resource = resources.files("memoryhub.safety_rules.data").joinpath(
            resource_name
        )
        text = resource.read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError, UnicodeDecodeError) as exc:
        raise RuleIntegrityError(
            f"cannot read packaged safety rule resource {resource_name}: {exc}"
        ) from exc
    if len(text.encode("utf-8")) > _MAX_RULE_RESOURCE_BYTES:
        raise RuleIntegrityError(
            f"packaged safety rule resource exceeds 2 MiB: {resource_name}"
        )
    return text


@lru_cache(maxsize=1)
def _load_catalog() -> _RuleCatalog:
    payload = _strict_json_loads(
        _read_builtin_resource("catalog.json"),
        source="packaged catalog.json",
    )
    try:
        return _RuleCatalog.model_validate(payload)
    except ValidationError as exc:
        raise RuleIntegrityError(f"invalid packaged rule catalog: {exc}") from exc


def list_builtin_rule_versions() -> tuple[str, ...]:
    """返回 catalog 明确声明的版本，不扫描目录或按 mtime 猜测。"""
    return tuple(entry.version for entry in _load_catalog().versions)


def _validate_rule_history(snapshots: tuple[RuleSetSnapshot, ...]) -> None:
    """规则版本和来源 ID 在不同快照中都不得悄悄改变语义。"""
    seen_rules: dict[tuple[str, str], str] = {}
    seen_sources: dict[str, str] = {}
    for snapshot in snapshots:
        for source in snapshot.sources:
            source_digest = canonical_sha256(source.model_dump(mode="json"))
            previous_source = seen_sources.setdefault(
                source.source_id,
                source_digest,
            )
            if previous_source != source_digest:
                raise RuleIntegrityError(
                    "rule source content changed without a new source_id: "
                    f"{source.source_id}"
                )
        for rule in snapshot.rules:
            key = (rule.rule_id, normalized_version(rule.rule_version))
            digest = canonical_sha256(rule.model_dump(mode="json"))
            previous = seen_rules.setdefault(key, digest)
            if previous != digest:
                raise RuleIntegrityError(
                    "rule content changed without a rule_version bump: "
                    f"{rule.rule_id}@{rule.rule_version}"
                )


@lru_cache(maxsize=1)
def _load_all_builtin() -> tuple[RuleSetSnapshot, ...]:
    catalog = _load_catalog()
    snapshots: list[RuleSetSnapshot] = []
    for entry in catalog.versions:
        payload = _strict_json_loads(
            _read_builtin_resource(entry.resource),
            source=f"packaged {entry.resource}",
        )
        snapshot = _load_document(
            payload,
            source=f"packaged {entry.resource}",
            registry=BUILTIN_COMPONENTS,
        )
        if snapshot.rule_set_id != catalog.rule_set_id:
            raise RuleIntegrityError(
                "catalog and rule resource use different rule_set_id"
            )
        if snapshot.version != entry.version:
            raise RuleIntegrityError("catalog and rule resource use different versions")
        if snapshot.digest != entry.snapshot_digest:
            raise RuleIntegrityError(
                f"snapshot digest mismatch for {snapshot.rule_set_id}@{snapshot.version}"
            )
        snapshots.append(snapshot)
    result = tuple(snapshots)
    _validate_rule_history(result)
    return result


def load_builtin_rule_set(*, version: str | None = None) -> RuleSetSnapshot:
    """加载 catalog 默认版本或调用方显式指定的内置版本。"""
    catalog = _load_catalog()
    selected = catalog.default_version if version is None else version
    if selected not in set(list_builtin_rule_versions()):
        raise RuleSetNotFoundError(
            f"rule set {catalog.rule_set_id!r} has no version {selected!r}"
        )
    return next(
        snapshot for snapshot in _load_all_builtin() if snapshot.version == selected
    )
