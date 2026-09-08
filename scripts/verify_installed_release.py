"""End-to-end verification for an installed Kylin MemoryHub release.

The script talks only to the loopback service, creates records under a unique
QA user, and removes every created long-term memory before exiting.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = "http://127.0.0.1:8099"
# Avoid decimal timestamp-shaped identifiers: the safety scanner deliberately
# treats long digit runs as potentially sensitive account/phone data.  A QA
# identity should exercise writes without impersonating sensitive content.
_LETTER_ID = uuid.uuid4().hex.translate(str.maketrans("0123456789", "abcdefghij"))
RUN = f"qa-vtwo-{_LETTER_ID[:12]}"
HEADERS = {"X-MemoryHub-Tenant": RUN, "X-MemoryHub-User": RUN}
created_ids: set[str] = set()
passed = 0
failed = 0


def request(method: str, path: str, body=None, headers=None, expected=(200,)):
    data = None if body is None else json.dumps(body).encode("utf-8")
    all_headers = {"Accept": "application/json"}
    if body is not None:
        all_headers["Content-Type"] = "application/json"
    if headers:
        all_headers.update(headers)
    req = urllib.request.Request(BASE + path, data=data, headers=all_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    try:
        payload = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        payload = raw.decode("utf-8", errors="replace")
    if status not in expected:
        raise AssertionError(f"{method} {path}: HTTP {status}: {payload!r}")
    return status, payload


def check(name: str, condition: bool, detail="") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"[OK] {name}")
    else:
        failed += 1
        print(f"[FAIL] {name}: {detail}")


def safe(name: str, fn) -> None:
    global failed
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - verification must continue by section
        failed += 1
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")


def memory(memory_id: str, memory_type: str):
    user_id = urllib.parse.quote(RUN)
    return request("GET", f"/api/memory/{memory_type}/{memory_id}?user_id={user_id}")[1]


def remember_id(memory_id: str) -> None:
    created_ids.add(memory_id)


def verify_health_and_contract() -> None:
    _, health = request("GET", "/api/health")
    check("release health is 2.0.0", health.get("version") == "2.0.0", health)
    _, storage = request("GET", "/api/memory/health")
    check("storage health", storage.get("status") == "healthy", storage)
    _, status = request("GET", f"/api/memory/system/status?user_id={RUN}")
    check(
        "system status exposes storage", status.get("storage", {}).get("engine") == "sqlite", status
    )
    check("safety gate available", status.get("safety", {}).get("gate_available") is True, status)
    _, config = request("GET", "/api/memory/system/config")
    check("system config redacts API key", 'api_key"' not in json.dumps(config), config)
    _, spec = request("GET", "/openapi.json")
    check("OpenAPI covers vNext", "/api/memory/vnext/search" in spec.get("paths", {}))


def verify_preference_crud() -> None:
    mid = f"pref_{RUN}"
    body = {
        "memory_id": mid,
        "user_id": RUN,
        "text": "QA prefers concise Markdown answers",
        "preference_type": "output_style",
        "scope": {"scene": "qa", "task_type": "release", "app": "opencode"},
        "confidence": 0.91,
        "status": "active",
        "tags": ["release-qa"],
    }
    _, result = request("POST", "/api/memory/memories/preference", body)
    remember_id(mid)
    check(
        "create preference", result.get("status") == "ok" and result.get("memory_id") == mid, result
    )
    got = memory(mid, "preferences")
    check("read preference", got.get("text") == body["text"], got)
    _, updated = request(
        "PUT",
        f"/api/memory/preference/{mid}",
        {"user_id": RUN, "text": "QA prefers stepwise Markdown answers", "confidence": 0.95},
    )
    check(
        "update preference",
        updated.get("memory", {}).get("text", "").startswith("QA prefers stepwise"),
        updated,
    )
    _, versions = request("GET", f"/api/memory/preferences/{mid}/versions")
    check("preference version history", isinstance(versions, list) and versions, versions)
    _, listing = request("GET", f"/api/memory/preferences?user_id={RUN}&status=active")
    check("list preference", any(item.get("memory_id") == mid for item in listing), listing)


def verify_knowledge_and_fact_crud() -> None:
    for kind in ("workflow", "case", "template"):
        mid = f"know_{kind}_{RUN}"
        body = {
            "memory_id": mid,
            "user_id": RUN,
            "knowledge_type": kind,
            "name": f"QA {kind}",
            "content": f"Release verification {kind} content",
            "steps": ["prepare", "verify"] if kind == "workflow" else [],
            "tools": ["memoryhub"] if kind == "workflow" else [],
            "template_body": "# QA template" if kind == "template" else "",
            "scope": {"scene": "qa", "task_type": "release", "app": "opencode"},
            "confidence": 0.9,
            "status": "active",
        }
        _, result = request("POST", "/api/memory/memories/knowledge", body)
        remember_id(mid)
        check(f"create knowledge {kind}", result.get("status") == "ok", result)
        got = memory(mid, "knowledge")
        check(f"read knowledge {kind}", got.get("knowledge_type") == kind, got)

    workflow_id = f"know_workflow_{RUN}"
    _, updated = request(
        "PUT",
        f"/api/memory/knowledge/{workflow_id}",
        {"user_id": RUN, "content": "Updated release verification workflow", "confidence": 0.96},
    )
    check(
        "update knowledge",
        updated.get("memory", {}).get("content", "").startswith("Updated"),
        updated,
    )
    _, listing = request("GET", f"/api/memory/knowledge?user_id={RUN}&status=active")
    kinds = {item.get("knowledge_type") for item in listing}
    check("list knowledge subtypes", {"workflow", "case", "template"}.issubset(kinds), kinds)

    subject = f"MemoryHub-{RUN}"
    predicate = "release_version"
    obj = "2.0.0"
    _, proposed = request(
        "POST",
        "/api/memory/facts/propose",
        {
            "user_id": RUN,
            "source_id": RUN,
            "scope_hint": "global",
            "triples": [
                {
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "object_type": "Version",
                    "evidence": f"{subject} release version is {obj}",
                    "confidence": 0.99,
                }
            ],
        },
    )
    facts = proposed.get("created", [])
    check("propose fact persisted", len(facts) == 1 and not proposed.get("failed"), proposed)
    if facts:
        fact_id = facts[0]["fact_id"]
        remember_id(fact_id)
        _, fact = request(
            "GET", f"/api/memory/facts/{fact_id}?user_id={urllib.parse.quote(RUN)}"
        )
        check("read fact", fact.get("object_value") == obj, fact)
        _, all_facts = request("GET", f"/api/memory/facts?user_id={RUN}&status=active")
        check(
            "fact appears after refresh",
            any(x.get("fact_id") == fact_id for x in all_facts),
            all_facts,
        )
        _, evidence = request(
            "GET",
            f"/api/memory/facts/{fact_id}/evidence?user_id={urllib.parse.quote(RUN)}",
        )
        check("fact evidence endpoint", isinstance(evidence, (list, dict)), evidence)
        _, health = request("GET", f"/api/memory/memories/health?user_id={RUN}&status=active")
        check(
            "dashboard health counts fact once",
            sum(
                1
                for x in health.get("items", [])
                if x.get("memory_id") == fact_id and x.get("memory_type") == "fact"
            )
            == 1,
            health,
        )


def verify_retrieval_and_context() -> None:
    query = "release verification workflow"
    _, legacy = request("POST", "/api/memory/search", {"user_id": RUN, "query": query, "top_k": 20})
    check("legacy hybrid search", isinstance(legacy.get("knowledge"), list), legacy)
    check(
        "legacy search preserves knowledge subtype",
        any(x.get("knowledge_type") == "workflow" for x in legacy.get("knowledge", [])),
        legacy,
    )
    _, context = request(
        "POST", "/api/memory/context", {"user_id": RUN, "query": query, "top_k": 20}
    )
    check("legacy context rendering", isinstance(context.get("context_text"), str), context)
    body = {
        "request_id": f"req-{RUN}",
        "tenant_id": RUN,
        "user_id": RUN,
        "query": query,
        "requested_types": ["PREFERENCE", "SEMANTIC", "PROCEDURAL", "EPISODIC"],
        "page_size": 20,
    }
    _, result = request("POST", "/api/memory/vnext/search", body, HEADERS)
    check("vNext search contract", result.get("api_version") == "vnext/v1", result)
    _, payload = request("POST", "/api/memory/vnext/context", body, HEADERS)
    check(
        "vNext structured context",
        isinstance(payload.get("rendered_context"), str)
        and isinstance(payload.get("relevant_memory_ids"), list),
        payload,
    )


def verify_events_and_layers() -> None:
    event_id = f"evt-{RUN}"
    event = {
        "event_id": event_id,
        "source_type": "user_behavior",
        "event_type": "user_message",
        "user_id": RUN,
        "session_id": f"session-{RUN}",
        "scene": "qa",
        "task_type": "release",
        "occurred_at": "2026-09-08T12:00:00Z",
        "text": "verify MemoryHub 2.0 release",
        "payload": {"qa": True},
        "source_hash": hashlib.sha256(event_id.encode()).hexdigest(),
        "quality": {
            "score": 0.95,
            "status": "accepted",
            "completeness": 0.95,
            "validity": 0.95,
            "consistency": 0.95,
            "freshness": 0.95,
        },
    }
    _, result = request("POST", "/api/memory/events", {"events": [event]})
    check("event ingestion", result.get("accepted") == 1, result)
    _, events = request("GET", f"/api/memory/events?user_id={RUN}&limit=20")
    check(
        "event listing", any(x.get("event_id") == event_id for x in events.get("items", [])), events
    )
    _, session = request("GET", f"/api/memory/events/session/session-{RUN}")
    check("session event listing", any(x.get("event_id") == event_id for x in session), session)
    _, short_term = request("GET", f"/api/memory/short-term?user_id={RUN}&session_id=session-{RUN}")
    check("short-term layer", isinstance(short_term, list), short_term)
    _, mid_term = request("GET", f"/api/memory/mid-term?user_id={RUN}")
    check("mid-term layer", isinstance(mid_term, list), mid_term)
    _, consolidated = request("POST", f"/api/memory/lifecycle/consolidate?user_id={RUN}")
    check("memory consolidation", isinstance(consolidated, dict), consolidated)
    _, lifecycle = request("POST", "/api/memory/lifecycle/check")
    check("lifecycle scan", "promoted" in lifecycle, lifecycle)
    _, auto_forget = request("POST", "/api/memory/lifecycle/auto-forget")
    check("auto-forget scan", "archived" in auto_forget, auto_forget)
    _, settings = request("GET", "/api/memory/lifecycle/settings")
    check("lifecycle settings", "auto_forget" in settings, settings)


def verify_forget_and_recovery() -> None:
    mid = f"pref_recycle_{RUN}"
    request(
        "POST",
        "/api/memory/memories/preference",
        {"memory_id": mid, "user_id": RUN, "text": "temporary recycle QA", "confidence": 0.9},
    )
    remember_id(mid)
    _, preview = request(
        "POST",
        "/api/memory/forget/preview",
        {"user_id": RUN, "instruction": "delete QA record", "target_memory_ids": [mid]},
    )
    check("forget preview is non-destructive", mid in preview.get("candidate_ids", []), preview)
    _, deleted = request(
        "POST",
        "/api/memory/memories/delete",
        {"user_id": RUN, "memory_ids": [mid], "cascade": True},
    )
    check("soft delete", deleted.get("deleted_count") == 1, deleted)
    record_id = deleted.get("record_id")
    _, recycle = request("GET", f"/api/memory/preferences?user_id={RUN}&status=deleted")
    check("recycle bin listing", any(x.get("memory_id") == mid for x in recycle), recycle)
    _, restored = request(
        "POST",
        "/api/memory/memories/status",
        {"user_id": RUN, "memory_ids": [mid], "status": "active"},
    )
    check("restore from recycle bin", restored.get("applied") == 1, restored)
    if record_id:
        _, history = request("GET", f"/api/memory/forget/history/{record_id}")
        check("forget audit detail", history.get("record_id") == record_id, history)
    _, rule = request(
        "POST",
        "/api/memory/forget/rules",
        {"user_id": RUN, "topic": "release-qa", "keywords": [RUN], "enabled": True},
        expected=(201,),
    )
    rule_id = rule.get("rule_id")
    _, rules = request("GET", f"/api/memory/forget/rules?user_id={RUN}")
    check(
        "forget rule create/list",
        rule_id and any(x.get("rule_id") == rule_id for x in rules),
        rules,
    )
    if rule_id:
        _, removed = request("DELETE", f"/api/memory/forget/rules/{rule_id}?user_id={RUN}")
        check("forget rule delete", removed.get("deleted") is True, removed)


def verify_safety_observability_and_admin_boundaries() -> None:
    _, audit = request("GET", "/api/memory/safety/audit-logs?limit=20")
    check("safety audit listing", isinstance(audit.get("items"), list), audit)
    _, integrity = request("GET", "/api/memory/safety/audit-logs/verify")
    check("safety audit integrity", "valid" in integrity, integrity)
    _, quarantine = request("GET", "/api/memory/safety/quarantine")
    check("quarantine listing", isinstance(quarantine.get("items"), list), quarantine)
    code, unavailable = request(
        "GET",
        "/api/memory/safety/user-rules",
        headers={"X-MemoryHub-User": RUN},
        expected=(503,),
    )
    check(
        "user rules fail closed without trusted identity",
        code == 503 and "identity_unavailable" in str(unavailable),
        unavailable,
    )
    _, conflicts = request("GET", "/api/memory/conflicts?status=&page=1&size=20")
    check("conflict center", isinstance(conflicts.get("items"), list), conflicts)
    code, _ = request(
        "POST",
        "/api/memory/vnext/dashboard/explorer",
        {"request_id": RUN, "tenant_id": RUN, "user_id": RUN},
        HEADERS,
        expected=(403,),
    )
    check("dashboard admin boundary", code == 403)
    code, _ = request(
        "POST",
        "/api/memory/vnext/diagnostics",
        {
            "request_id": RUN,
            "tenant_id": RUN,
            "user_id": RUN,
            "target_type": "memory",
            "target_id": "missing",
        },
        HEADERS,
        expected=(403,),
    )
    check("diagnostics admin boundary", code == 403)
    code, _ = request("POST", "/api/memory/evaluate/retrieval", expected=(400,))
    check("evaluation validates dataset", code == 400)
    _, agent = request("GET", "/api/agent/health")
    check("agent API health", isinstance(agent, dict), agent)


def cleanup() -> None:
    for mid in sorted(created_ids):
        try:
            request(
                "DELETE",
                f"/api/memory/memories/{urllib.parse.quote(mid)}?hard=true&user_id={urllib.parse.quote(RUN)}",
                expected=(200, 404),
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] cleanup {mid}: {exc}")


try:
    for name, fn in (
        ("health and contract", verify_health_and_contract),
        ("preference CRUD", verify_preference_crud),
        ("knowledge and fact CRUD", verify_knowledge_and_fact_crud),
        ("retrieval and context", verify_retrieval_and_context),
        ("events and layers", verify_events_and_layers),
        ("forget and recovery", verify_forget_and_recovery),
        ("safety and observability", verify_safety_observability_and_admin_boundaries),
    ):
        safe(name, fn)
finally:
    cleanup()

print(f"RESULT run={RUN} passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
