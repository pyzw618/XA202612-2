from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import memoryhub.safety_rules.components as component_module
import memoryhub.safety_rules.loader as loader_module
from memoryhub.adapter.schemas import SafetyAction
from memoryhub.config import SafetyConfig
from memoryhub.core.safety import SensitiveDetector
from memoryhub.safety_rules import (
    BUILTIN_COMPONENTS,
    ComponentRegistry,
    MaskerCapability,
    RuleIntegrityError,
    RuleLibraryError,
    RuleSetNotFoundError,
    list_builtin_rule_versions,
    load_builtin_rule_set,
    load_rule_set_file,
    path_matches,
    resolve_masker,
    resolve_validator,
)
from memoryhub.safety_rules.loader import (
    _CatalogEntry,
    _RuleCatalog,
    _validate_rule_history,
)


def _enum_value(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


def _jsonable(value: Any) -> Any:
    """Turn immutable rule-library values into JSON fixture data."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    return value


def _rule_id(rule: Any) -> str:
    return str(rule.rule_id)


def _find_rule(snapshot: Any, *needles: str) -> Any:
    normalized_needles = tuple(needle.lower() for needle in needles)
    for rule in snapshot.rules:
        rule_id = _rule_id(rule).lower().replace("-", "_").replace(".", "_")
        if all(needle in rule_id for needle in normalized_needles):
            return rule
    raise AssertionError(
        f"builtin rule containing {normalized_needles!r} was not found; "
        f"available={[_rule_id(rule) for rule in snapshot.rules]!r}"
    )


def _source_index(snapshot: Any) -> dict[str, Any]:
    sources = snapshot.sources
    if isinstance(sources, Mapping):
        return {str(source_id): source for source_id, source in sources.items()}

    indexed: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, Mapping):
            source_id = (
                source.get("source_id") or source.get("ref_id") or source.get("id")
            )
        else:
            source_id = (
                getattr(source, "source_id", None)
                or getattr(source, "ref_id", None)
                or getattr(source, "id", None)
            )
        assert source_id, f"provenance source lacks a stable id: {source!r}"
        indexed[str(source_id)] = source
    return indexed


def _standard_ref_ids(rule: Any) -> tuple[str, ...]:
    references = rule.standard_ref
    if isinstance(references, str):
        references = (references,)

    result: list[str] = []
    for reference in references:
        if isinstance(reference, str):
            source_id = reference
        elif isinstance(reference, Mapping):
            source_id = (
                reference.get("source_id")
                or reference.get("ref_id")
                or reference.get("id")
            )
        else:
            source_id = (
                getattr(reference, "source_id", None)
                or getattr(reference, "ref_id", None)
                or getattr(reference, "id", None)
            )
        assert source_id, f"rule provenance link lacks a source id: {reference!r}"
        result.append(str(source_id))
    return tuple(result)


def _provenance_text(snapshot: Any, rule: Any) -> str:
    sources = _source_index(snapshot)
    linked_sources = [sources[source_id] for source_id in _standard_ref_ids(rule)]
    return json.dumps(
        {
            "standard_ref": _jsonable(rule.standard_ref),
            "sources": _jsonable(linked_sources),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).lower()


def _compiled_rule_values(snapshot: Any) -> tuple[Any, ...]:
    compiled = snapshot.compiled_rules
    if isinstance(compiled, Mapping):
        return tuple(compiled.values())
    return tuple(compiled)


def _compiled_rule_id(rule: Any) -> str:
    for attribute in ("rule_id", "name"):
        value = getattr(rule, attribute, None)
        if value:
            return str(value)
    definition = getattr(rule, "definition", None) or getattr(rule, "spec", None)
    if definition is not None:
        return _rule_id(definition)
    raise AssertionError(f"compiled rule has no rule identity: {rule!r}")


def _compiled_rule_action(rule: Any) -> Any:
    for attribute in ("action", "safety_action"):
        if hasattr(rule, attribute):
            return getattr(rule, attribute)
    raise AssertionError(f"compiled rule has no runtime action: {rule!r}")


def _manifest_from_snapshot(snapshot: Any) -> dict[str, Any]:
    """Build a valid standalone manifest before applying one invalid mutation."""
    return {
        "schema_version": getattr(snapshot, "schema_version", "1.0"),
        "rule_set_id": "test.fixture",
        "version": "9.0.0",
        "sources": _jsonable(snapshot.sources),
        "governance_ref": _jsonable(snapshot.governance_ref),
        "rules": [_jsonable(rule) for rule in snapshot.rules],
    }


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> Path:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _cn_id_check_character(first_seventeen_digits: str) -> str:
    assert re.fullmatch(r"\d{17}", first_seventeen_digits)
    weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    check_characters = "10X98765432"
    checksum = sum(
        int(digit) * weight
        for digit, weight in zip(first_seventeen_digits, weights, strict=True)
    )
    return check_characters[checksum % 11]


def _always_valid(value: str) -> bool:
    del value
    return True


def _never_valid(value: str) -> bool:
    del value
    return False


def _zero_argument_validator() -> bool:
    return True


def _integer_validator(value: str) -> int:
    del value
    return 1


def _identity_masker(value: str, replacement: str) -> str:
    del replacement
    return value


class _CallableValidator:
    def __call__(self, value: str) -> bool:
        return bool(value)


def test_builtin_catalog_load_is_deterministic_and_cwd_independent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first = load_builtin_rule_set()
    monkeypatch.chdir(tmp_path)
    second = load_builtin_rule_set()

    assert first.rule_set_id == second.rule_set_id
    assert first.version == second.version
    assert first.digest == second.digest
    assert re.fullmatch(r"[0-9a-f]{64}", first.digest)
    assert [_jsonable(rule) for rule in first.rules] == [
        _jsonable(rule) for rule in second.rules
    ]

    versions = tuple(list_builtin_rule_versions())
    assert versions
    assert len(versions) == len(set(versions))
    assert first.version in versions
    explicitly_loaded = load_builtin_rule_set(version=first.version)
    assert explicitly_loaded.digest == first.digest


def test_snapshot_exposes_immutable_rule_and_compilation_views() -> None:
    snapshot = load_builtin_rule_set()

    assert snapshot.rules
    assert isinstance(snapshot.rules, tuple)
    assert snapshot.sources
    assert len(_compiled_rule_values(snapshot)) == len(snapshot.rules)

    compiled_by_id = {
        _compiled_rule_id(compiled): compiled
        for compiled in _compiled_rule_values(snapshot)
    }
    for rule in snapshot.rules:
        for field_name in (
            "rule_id",
            "category",
            "risk_level",
            "default_action",
            "pattern",
            "validator",
            "masker",
            "target_paths",
            "priority",
            "standard_ref",
            "rule_version",
            "enabled",
        ):
            assert hasattr(
                rule, field_name
            ), f"{rule.rule_id} is missing required field {field_name}"
        assert snapshot.get_rule(rule.rule_id) == rule
        assert rule.rule_id in compiled_by_id


def test_config_and_detector_preserve_the_declarative_snapshot_digest() -> None:
    snapshot = load_builtin_rule_set()
    config = SafetyConfig(
        rule_set_id=snapshot.rule_set_id,
        rule_set_version=snapshot.version,
    )
    detector = SensitiveDetector.from_config(config)

    assert config.rule_set_digest == snapshot.digest
    assert detector.rule_set_id == snapshot.rule_set_id
    assert detector.rule_set_digest == snapshot.digest
    assert detector.rules == snapshot.compiled_rules
    assert detector.rule_snapshot is snapshot
    assert detector.rule_snapshot.resolve_validator(snapshot.get_rule("id_card"))(
        "11010519491231002X"
    )


def test_custom_snapshot_can_be_injected_without_losing_its_registry(
    tmp_path: Path,
) -> None:
    builtin = load_builtin_rule_set()
    payload = _manifest_from_snapshot(builtin)
    path = _write_manifest(tmp_path / "custom-snapshot.json", payload)
    validators = dict(BUILTIN_COMPONENTS.validators)
    validators["builtin.cn_resident_id@1.0"] = _never_valid
    registry = ComponentRegistry(
        validators=validators,
        maskers=BUILTIN_COMPONENTS.maskers,
        masker_capabilities=BUILTIN_COMPONENTS.masker_capabilities,
    )
    snapshot = load_rule_set_file(path, registry=registry)
    config = SafetyConfig(rule_snapshot=snapshot)
    detector = SensitiveDetector.from_config(config)

    assert detector.rule_snapshot is snapshot
    assert detector.rule_set_digest == snapshot.digest
    assert (
        snapshot.resolve_validator(snapshot.get_rule("id_card"))("11010519491231002X")
        is False
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        SafetyConfig(
            rule_snapshot=snapshot,
            sensitive_patterns=list(snapshot.compiled_rules),
        )


def test_component_behavior_is_bound_into_the_snapshot_digest(tmp_path: Path) -> None:
    builtin = load_builtin_rule_set()
    path = _write_manifest(
        tmp_path / "component-digest.json",
        _manifest_from_snapshot(builtin),
    )
    true_validators = dict(BUILTIN_COMPONENTS.validators)
    false_validators = dict(BUILTIN_COMPONENTS.validators)
    true_validators["builtin.cn_resident_id@1.0"] = _always_valid
    false_validators["builtin.cn_resident_id@1.0"] = _never_valid
    true_snapshot = load_rule_set_file(
        path,
        registry=ComponentRegistry(
            validators=true_validators,
            maskers=BUILTIN_COMPONENTS.maskers,
            masker_capabilities=BUILTIN_COMPONENTS.masker_capabilities,
        ),
    )
    false_snapshot = load_rule_set_file(
        path,
        registry=ComponentRegistry(
            validators=false_validators,
            maskers=BUILTIN_COMPONENTS.maskers,
            masker_capabilities=BUILTIN_COMPONENTS.masker_capabilities,
        ),
    )

    assert true_snapshot.digest != false_snapshot.digest
    assert (
        true_snapshot.component_registry_digest
        != false_snapshot.component_registry_digest
    )


def test_redact_allow_compiles_to_mask_without_coupling_risk_to_action() -> None:
    snapshot = load_builtin_rule_set()
    compiled_by_id = {
        _compiled_rule_id(compiled): compiled
        for compiled in _compiled_rule_values(snapshot)
    }
    redact_rules = [
        rule
        for rule in snapshot.rules
        if _enum_value(rule.default_action) == "redact_allow" and rule.enabled
    ]

    assert redact_rules, "the builtin set must exercise redact-then-allow semantics"
    for rule in redact_rules:
        assert _compiled_rule_action(compiled_by_id[rule.rule_id]) is SafetyAction.MASK

    high_risk_actions = {
        _enum_value(rule.default_action)
        for rule in snapshot.rules
        if _enum_value(rule.risk_level) == "high" and rule.enabled
    }
    assert {"reject", "redact_allow"} <= high_risk_actions


def test_missing_builtin_version_never_falls_back_to_default() -> None:
    with pytest.raises(RuleSetNotFoundError):
        load_builtin_rule_set(version="9999.9999.9999")


def test_builtin_rules_keep_credentials_and_personal_information_separate() -> None:
    snapshot = load_builtin_rule_set()
    rules_by_category: dict[str, list[Any]] = {}
    for rule in snapshot.rules:
        if rule.enabled:
            rules_by_category.setdefault(_enum_value(rule.category), []).append(rule)

    assert {"credential", "personal", "sensitive_personal"} <= set(rules_by_category)

    credential_ids = {_rule_id(rule) for rule in rules_by_category["credential"]}
    personal_ids = {
        _rule_id(rule)
        for category in ("personal", "sensitive_personal")
        for rule in rules_by_category[category]
    }
    assert credential_ids.isdisjoint(personal_ids)
    assert any(
        _enum_value(rule.default_action) == "reject"
        for rule in rules_by_category["credential"]
    )

    id_card_rule = _find_rule(snapshot, "id", "card")
    assert _enum_value(id_card_rule.category) == "sensitive_personal"
    assert _enum_value(id_card_rule.default_action) == "redact_allow"


def test_every_builtin_rule_has_resolvable_structured_provenance() -> None:
    snapshot = load_builtin_rule_set()
    sources = _source_index(snapshot)
    assert sources

    referenced: set[str] = set()
    for rule in snapshot.rules:
        reference_ids = _standard_ref_ids(rule)
        assert reference_ids, f"{rule.rule_id} has no provenance"
        assert set(reference_ids) <= set(sources), (
            f"{rule.rule_id} has dangling provenance: "
            f"{set(reference_ids) - set(sources)}"
        )
        referenced.update(reference_ids)

    assert referenced <= set(sources)
    governance_roles = {row["role"] for row in snapshot.traceability_matrix}
    assert {"lifecycle", "effectiveness", "audit"} <= governance_roles

    id_card_text = _provenance_text(snapshot, _find_rule(snapshot, "id", "card"))
    assert "11643" in id_card_text
    assert any(
        marker in id_card_text
        for marker in ("个人信息保护法", "pipl", "article 28", "第28")
    )

    credential_text = "\n".join(
        _provenance_text(snapshot, rule)
        for rule in snapshot.rules
        if _enum_value(rule.category) == "credential"
    )
    assert any(marker in credential_text for marker in ("owasp", "vendor", "project"))


def test_all_builtin_component_references_resolve() -> None:
    snapshot = load_builtin_rule_set()

    for rule in snapshot.rules:
        assert callable(resolve_validator(rule.validator))
        if rule.masker:
            assert callable(resolve_masker(rule.masker))
        if _enum_value(rule.default_action) == "redact_allow":
            assert rule.masker

    with pytest.raises(RuleLibraryError):
        resolve_validator("builtin.unknown_validator@999")
    with pytest.raises(RuleLibraryError):
        resolve_masker("builtin.unknown_masker@999")


def test_component_registry_rejects_bad_signatures_and_return_types() -> None:
    with pytest.raises(RuleLibraryError, match="accept"):
        ComponentRegistry(
            validators={"custom.zero@1.0": _zero_argument_validator},
            maskers={},
        )

    registry = ComponentRegistry(
        validators={"custom.integer@1.0": _integer_validator},
        maskers={},
    )
    with pytest.raises(RuleLibraryError, match="return bool"):
        registry.resolve_validator("custom.integer@1.0")("candidate")


def test_cn_id_validator_checks_birthday_and_checksum() -> None:
    snapshot = load_builtin_rule_set()
    rule = _find_rule(snapshot, "id", "card")
    validator = resolve_validator(rule.validator)

    valid = "11010519491231002X"
    assert validator(valid) is True

    wrong_checksum = valid[:-1] + ("1" if valid[-1] != "1" else "2")
    assert validator(wrong_checksum) is False

    invalid_date_prefix = "11010519990230002"
    invalid_date = invalid_date_prefix + _cn_id_check_character(invalid_date_prefix)
    assert validator(invalid_date) is False


def test_ipv4_validator_rejects_out_of_range_octets() -> None:
    snapshot = load_builtin_rule_set()
    rule = _find_rule(snapshot, "ip")
    validator = resolve_validator(rule.validator)

    assert validator("192.168.1.1") is True
    assert validator("255.255.255.255") is True
    assert validator("999.999.999.999") is False
    assert validator("192.168.1") is False


@pytest.mark.parametrize(
    ("target", "json_path", "expected"),
    [
        ("/text", "/text", True),
        ("/text", "/payload/text", False),
        ("/payload/**", "/payload/profile/email", True),
        ("/payload/**", "/tool_calls/0/result/payload/email", False),
        (
            "/tool_calls/*/arguments/**",
            "/tool_calls/0/arguments/api_key",
            True,
        ),
        (
            "/tool_calls/*/arguments/**",
            "/tool_calls/12/arguments/nested/password",
            True,
        ),
        (
            "/tool_calls/*/arguments/**",
            "/tool_calls/0/result/api_key",
            False,
        ),
        ("/payload/a~1b/~0email", "/payload/a~1b/~0email", True),
        ("/**/api_key", "/payload//api_key", True),
        ("/payload/*", "/payload/*", True),
        ("/payload/token", "/payload/tokenized", False),
    ],
)
def test_target_path_globs_are_anchored_rfc6901_templates(
    target: str,
    json_path: str,
    expected: bool,
) -> None:
    assert path_matches(target, json_path) is expected


def test_credential_field_paths_are_ascii_case_insensitive() -> None:
    snapshot = load_builtin_rule_set()
    rule = snapshot.get_rule("credential_field")
    compiled = next(
        item for item in snapshot.compiled_rules if item.name == rule.rule_id
    )

    assert re.search(compiled.path_pattern, "/headers/Authorization")
    assert re.search(compiled.path_pattern, "/payload/PASSWORD")
    assert re.search(compiled.path_pattern, "/payload/client_secret")
    assert re.search(compiled.path_pattern, "/payload/secretKey")


@pytest.mark.parametrize("component_field", ["validator", "masker"])
def test_rule_file_rejects_unknown_component_references(
    component_field: str,
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    rule = next(
        item
        for item in payload["rules"]
        if component_field == "validator" or item.get("masker")
    )
    rule[component_field] = f"builtin.unknown_{component_field}@999"
    path = _write_manifest(tmp_path / f"unknown-{component_field}.json", payload)

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path)


def test_rule_file_rejects_dangling_provenance_source(tmp_path: Path) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    payload["rules"][0]["standard_ref"] = ["source.does_not_exist"]
    path = _write_manifest(tmp_path / "dangling-source.json", payload)

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path)


def test_rule_file_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate-key.json"
    path.write_text(
        '{"schema_version":"1.0",'
        '"rule_set_id":"first",'
        '"rule_set_id":"second",'
        '"version":"1.0.0",'
        '"sources":[],'
        '"rules":[]}',
        encoding="utf-8",
    )

    with pytest.raises(RuleIntegrityError):
        load_rule_set_file(path)


@pytest.mark.parametrize(
    "rule_version",
    ["01.0", "1.0-alpha..1", "1.0-01", "1.0+build"],
)
def test_rule_file_rejects_ambiguous_versions(
    rule_version: str,
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    payload["rules"][0]["rule_version"] = rule_version
    path = _write_manifest(tmp_path / "bad-version.json", payload)

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path)


@pytest.mark.parametrize("enabled", ["false", "yes", 0, 1])
def test_rule_file_requires_a_strict_boolean_enabled(
    enabled: object,
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    payload["rules"][0]["enabled"] = enabled
    path = _write_manifest(tmp_path / "bad-enabled.json", payload)

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path)


@pytest.mark.parametrize("pattern", [r"(a+)+$", r"(?:a|aa)+$"])
def test_rule_file_rejects_obvious_catastrophic_regex(
    pattern: str,
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    payload["rules"][0]["pattern"] = pattern
    path = _write_manifest(tmp_path / "unsafe-regex.json", payload)

    with pytest.raises(RuleLibraryError, match="repeat"):
        load_rule_set_file(path)


@pytest.mark.parametrize(
    "reference",
    [
        "custom.validator@01.0",
        "custom.validator@1+.",
        "custom.validator@1.0-alpha..1",
        "custom.validator@1.0-01",
    ],
)
def test_component_registry_rejects_malformed_component_versions(
    reference: str,
) -> None:
    with pytest.raises(RuleLibraryError):
        ComponentRegistry(
            validators={reference: _always_valid},
            maskers={},
        )


@pytest.mark.parametrize(
    "version",
    ["01.0", "1.0-alpha..1", "1.0-01", "1.0+build"],
)
def test_catalog_entry_versions_are_strict(version: str) -> None:
    with pytest.raises(ValidationError):
        _CatalogEntry.model_validate(
            {
                "version": version,
                "resource": "builtin-invalid.json",
                "snapshot_digest": "0" * 64,
            }
        )


@pytest.mark.parametrize(
    "version",
    ["01.0", "1.0-alpha..1", "1.0-01", "1.0+build"],
)
def test_catalog_default_version_is_strict_even_for_preconstructed_entries(
    version: str,
) -> None:
    entry = _CatalogEntry.model_construct(
        version=version,
        resource="builtin-invalid.json",
        snapshot_digest="0" * 64,
    )

    with pytest.raises(ValidationError):
        _RuleCatalog.model_validate(
            {
                "schema_version": "1.0",
                "rule_set_id": "test.fixture",
                "default_version": version,
                "versions": (entry,),
            }
        )


def test_catalog_rejects_normalized_duplicate_versions() -> None:
    with pytest.raises(ValidationError):
        _RuleCatalog.model_validate(
            {
                "schema_version": "1.0",
                "rule_set_id": "test.fixture",
                "default_version": "1.0",
                "versions": (
                    {
                        "version": "1.0",
                        "resource": "builtin-1.0.json",
                        "snapshot_digest": "0" * 64,
                    },
                    {
                        "version": "1.0.0",
                        "resource": "builtin-1.0.0.json",
                        "snapshot_digest": "1" * 64,
                    },
                ),
            }
        )


@pytest.mark.parametrize(
    ("scope", "field_name"),
    [
        ("document", "released_on"),
        ("document", "status_as_of"),
        ("source", "published_on"),
        ("source", "effective_on"),
        ("source", "status_as_of"),
    ],
)
def test_rule_file_rejects_numeric_dates(
    scope: str,
    field_name: str,
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    if scope == "document":
        payload[field_name] = 0
    else:
        payload["sources"][0][field_name] = 0
    path = _write_manifest(
        tmp_path / f"numeric-{scope}-{field_name}.json",
        payload,
    )

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path)


def test_redact_allow_rejects_identity_masker_without_full_redaction_capability(
    tmp_path: Path,
) -> None:
    snapshot = load_builtin_rule_set()
    payload = _manifest_from_snapshot(snapshot)
    rule = next(
        item for item in payload["rules"] if item["default_action"] == "redact_allow"
    )
    rule["masker"] = "custom.identity@1.0"
    payload["rules"] = [rule]
    registry = ComponentRegistry(
        validators={
            rule["validator"]: BUILTIN_COMPONENTS.validators[rule["validator"]],
        },
        maskers={"custom.identity@1.0": _identity_masker},
    )
    path = _write_manifest(tmp_path / "identity-masker.json", payload)

    with pytest.raises(RuleLibraryError):
        load_rule_set_file(path, registry=registry)


@pytest.mark.parametrize(
    "pattern",
    [
        r"(a+){20}$",
        r"(?:a|aa){20}$",
        r"(?:a{1,3}){1000}$",
        r"^(?:a|aa){1,10000}$",
        r"^(?:a?){10000}b$",
        r"^a*a*b$",
    ],
)
def test_regex_gate_rejects_bounded_and_adjacent_backtracking_patterns(
    pattern: str,
    tmp_path: Path,
) -> None:
    payload = _manifest_from_snapshot(load_builtin_rule_set())
    payload["rules"][0]["pattern"] = pattern
    path = _write_manifest(tmp_path / "bounded-unsafe-regex.json", payload)

    with pytest.raises(RuleLibraryError, match="repeat"):
        load_rule_set_file(path)


def test_target_path_escape_can_address_literal_asterisk_keys() -> None:
    assert path_matches("/payload/~2", "/payload/*")
    assert not path_matches("/payload/~2", "/payload/value")
    assert path_matches("/payload/~2~2", "/payload/**")
    assert not path_matches("/payload/~2~2", "/payload/*")


@pytest.mark.parametrize(
    "resource",
    [
        r"..\outside.json",
        r"C:\temp\outside.json",
        "../outside.json",
        "/outside.json",
    ],
)
def test_catalog_rejects_cross_platform_resource_paths(resource: str) -> None:
    with pytest.raises(ValidationError):
        _RuleCatalog.model_validate(
            {
                "schema_version": "1.0",
                "rule_set_id": "test.fixture",
                "default_version": "1.0",
                "versions": [
                    {
                        "version": "1.0",
                        "resource": resource,
                        "snapshot_digest": "0" * 64,
                    }
                ],
            }
        )


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_rule_file_rejects_non_finite_json_numbers(
    constant: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "non-finite.json"
    path.write_text(
        '{"schema_version":"1.0","value":' + constant + "}",
        encoding="utf-8",
    )

    with pytest.raises(RuleIntegrityError, match="non-finite"):
        load_rule_set_file(path)


def test_deep_json_is_reported_as_integrity_error(tmp_path: Path) -> None:
    path = tmp_path / "deep.json"
    path.write_text("[" * 5000 + "0" + "]" * 5000, encoding="utf-8")

    with pytest.raises(RuleIntegrityError):
        load_rule_set_file(path)


def test_component_registry_rejects_semantically_equivalent_references() -> None:
    with pytest.raises(RuleLibraryError, match="semantically unique"):
        ComponentRegistry(
            validators={"custom.v@1.0": _always_valid},
            maskers={"custom.v@1.0.0": _identity_masker},
        )


def test_component_registry_rejects_callable_objects_cleanly() -> None:
    with pytest.raises(RuleLibraryError, match="Python functions"):
        ComponentRegistry(
            validators={"custom.callable@1.0": _CallableValidator()},
            maskers={},
        )


def test_declared_component_fingerprint_must_match_implementation() -> None:
    with pytest.raises(RuleLibraryError, match="do not match"):
        ComponentRegistry(
            validators={"custom.valid@1.0": _always_valid},
            maskers={},
            component_fingerprints={"custom.valid@1.0": "0" * 64},
        )


def test_full_redaction_capability_is_enforced_on_every_call() -> None:
    registry = ComponentRegistry(
        validators={},
        maskers={"custom.identity@1.0": _identity_masker},
        masker_capabilities={
            "custom.identity@1.0": {MaskerCapability.FULL_REDACTION},
        },
    )
    masker = registry.resolve_masker("custom.identity@1.0")

    with pytest.raises(RuleLibraryError, match="exactly the replacement"):
        masker("secret", "[REDACTED]")


def test_snapshot_digest_covers_compiled_rules(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    payload = _manifest_from_snapshot(load_builtin_rule_set())
    path = _write_manifest(tmp_path / "compiler-digest.json", payload)
    baseline = load_rule_set_file(path)
    monkeypatch.setattr(
        loader_module,
        "compile_target_paths",
        lambda target_paths, *, case_sensitive=True: r"\Achanged\Z",
    )
    changed = load_rule_set_file(path)

    assert baseline.compiled_rules != changed.compiled_rules
    assert baseline.digest != changed.digest


def test_snapshot_digest_ignores_unreferenced_registry_components(
    tmp_path: Path,
) -> None:
    payload = _manifest_from_snapshot(load_builtin_rule_set())
    path = _write_manifest(tmp_path / "scoped-components.json", payload)
    baseline = load_rule_set_file(path)
    validators = dict(BUILTIN_COMPONENTS.validators)
    validators["custom.unused@1.0"] = _always_valid
    expanded = load_rule_set_file(
        path,
        registry=ComponentRegistry(
            validators=validators,
            maskers=BUILTIN_COMPONENTS.maskers,
            masker_capabilities=BUILTIN_COMPONENTS.masker_capabilities,
        ),
    )

    assert baseline.component_registry_digest == expanded.component_registry_digest
    assert baseline.digest == expanded.digest


def test_component_module_dependency_changes_are_detected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = load_builtin_rule_set()
    rule = snapshot.get_rule("credential.jwt")
    monkeypatch.setattr(
        component_module.base64,
        "urlsafe_b64decode",
        lambda value: b"{}",
    )

    with pytest.raises(RuleLibraryError, match="implementation changed"):
        snapshot.resolve_validator(rule)


def test_source_id_cannot_change_meaning_across_snapshots() -> None:
    first = load_builtin_rule_set()
    changed_source = first.sources[0].model_copy(
        update={"caveat": first.sources[0].caveat + " changed"}
    )
    second = first.model_copy(update={"sources": (changed_source, *first.sources[1:])})

    with pytest.raises(RuleIntegrityError, match="new source_id"):
        _validate_rule_history((first, second))


def test_traceability_matrix_preserves_source_locator() -> None:
    snapshot = load_builtin_rule_set()
    assert all("locator" in row for row in snapshot.traceability_matrix)
    assert any(row["locator"] for row in snapshot.traceability_matrix)
