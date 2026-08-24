"""Argparse implementation of the ``memoryhub`` CLI.

The CLI is intentionally thin: every command builds a REST payload and calls
``memoryhub_client.MemoryHubClient``.  It keeps stdout deterministic for
commands and scripts while sending diagnostics to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

try:  # support running this file directly from agent-integration/
    from memoryhub_client.config import ClientConfig

    from memoryhub_client import MemoryHubClient, MemoryHubError
except ModuleNotFoundError:  # pragma: no cover - direct source checkout fallback
    import sys as _sys

    _sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from memoryhub_client.config import ClientConfig

    from memoryhub_client import MemoryHubClient, MemoryHubError

try:
    from .format import context_text, generic_text, json_text, search_text
except ImportError:  # pragma: no cover - direct ``python path/to/cli.py`` use
    from format import context_text, generic_text, json_text, search_text


class CliError(ValueError):
    """An input or safety error that should have a stable CLI exit code."""

    def __init__(self, message: str, code: str = "memoryhub.cli.invalid_input") -> None:
        super().__init__(message)
        self.code = code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memoryhub", description="MemoryHub Agent CLI")
    parser.add_argument("-u", "--user", dest="user_id", default=None)
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--project", default=None)
    parser.add_argument("--scene", default=None)
    parser.add_argument("--task-type", default=None)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("-j", "--json", action="store_true", dest="json_output")
    parser.add_argument("-c", "--compact", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search preference and knowledge memories")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=None)
    search.add_argument("--memory-types", nargs="*", default=None)
    search.add_argument("--min-confidence", type=float, default=None)
    search.add_argument("--level", choices=("short", "mid", "long"), default=None)
    search.add_argument("--session-id", default="")

    context = sub.add_parser("context", help="get prompt-ready memory context")
    context.add_argument("query")
    context.add_argument("--top-k", type=int, default=None)
    context.add_argument("--max-chars", type=int, default=4000)
    context.add_argument("--level", choices=("short", "mid", "long"), default=None)
    context.add_argument("--session-id", default="")

    event = sub.add_parser("event", aliases=["events"], help="write MemoryEvent JSON/JSONL")
    event.add_argument("input", help="JSON file, JSONL file or - for stdin")

    resume = sub.add_parser("resume", help="resume a task by task_id")
    resume.add_argument("task_id")
    resume.add_argument("--resume-token", default="")
    resume.add_argument("--expected-version", type=int, default=None)

    remember = sub.add_parser("remember", help="explicitly write a preference or knowledge")
    remember.add_argument("text")
    remember.add_argument("--type", dest="memory_type", default="preference")
    remember.add_argument("--name", default="")
    remember.add_argument("--confidence", type=float, default=0.5)

    update = sub.add_parser("update", help="update one memory")
    update.add_argument("memory_id")
    update.add_argument("--type", dest="memory_type", choices=("preference", "knowledge", "fact"), default=None)
    update.add_argument("--text", default=None)
    update.add_argument("--status", default=None)
    update.add_argument("--confidence", type=float, default=None)
    update.add_argument("--knowledge-type", default=None)

    forget = sub.add_parser("forget", help="preview or execute precise forgetting")
    forget.add_argument("instruction")
    forget.add_argument("--preview", action="store_true")
    forget.add_argument("-y", "--yes", action="store_true", help="confirm a destructive forget")
    forget.add_argument("--cascade", action=argparse.BooleanOptionalAction, default=True)

    listing = sub.add_parser("list", help="list memories")
    listing.add_argument("--type", dest="memory_type", choices=("all", "preference", "knowledge", "fact"), default="all")
    listing.add_argument("--status", default="active")
    listing.add_argument("--scene", dest="list_scene", default="")

    get = sub.add_parser("get", help="get one memory")
    get.add_argument("memory_id")
    get.add_argument("--type", dest="memory_type", default="")

    provenance = sub.add_parser("provenance", help="read lineage, evidence or audit references")
    provenance.add_argument("memory_id")
    provenance.add_argument("kind", choices=("lineage", "evidence", "audit"), nargs="?", default="lineage")

    projection = sub.add_parser("projection", help="inspect or replay projection outbox")
    projection_sub = projection.add_subparsers(dest="projection_command", required=True)
    projection_list = projection_sub.add_parser("list")
    projection_list.add_argument("--status", choices=("pending", "failed"), default="pending")
    projection_list.add_argument("--limit", type=int, default=100)
    replay = projection_sub.add_parser("replay")
    replay.add_argument("outbox_ids", nargs="*")

    feedback = sub.add_parser("feedback", help="confirm, reject or update a memory")
    feedback.add_argument("memory_id")
    feedback.add_argument("action", choices=("confirm", "reject", "update"))
    feedback.add_argument("feedback_text", nargs="?", default="")

    review = sub.add_parser("review", help="list pending conflicts")
    review.add_argument("kind", choices=("conflicts", "knowledge"), nargs="?", default="conflicts")

    resolve = sub.add_parser("resolve", help="resolve a pending conflict")
    resolve.add_argument("conflict_id")
    resolve.add_argument("decision", choices=("override", "merge", "coexist", "pending"))
    resolve.add_argument("--reason", default="")

    decide = sub.add_parser("decide", help="commit or reject a pending fact proposal")
    decide.add_argument("proposal_id")
    decide.add_argument("decision", choices=("commit", "reject"))
    decide.add_argument("--scope", choices=("global", "project"), default="global")

    knowledge = sub.add_parser("knowledge", help="knowledge-specific commands")
    knowledge_sub = knowledge.add_subparsers(dest="knowledge_command", required=True)
    fact = knowledge_sub.add_parser("fact", help="submit fact triples as knowledge candidates")
    fact_sub = fact.add_subparsers(dest="fact_command", required=True)
    propose = fact_sub.add_parser("propose")
    propose.add_argument("triples", help="JSON file containing a triple array")
    propose.add_argument("--scope", default="global")
    propose.add_argument("--source-id", default="")
    propose.add_argument("--commit", action="store_true")

    export = sub.add_parser("export", help="export user memories")
    export.add_argument("--status", default="active")
    import_cmd = sub.add_parser("import", help="import a memory export")
    import_cmd.add_argument("input")
    import_cmd.add_argument("--dry-run", action="store_true")

    sub.add_parser("status", help="show MemoryHub service status")
    service = sub.add_parser("service", help="service management placeholder")
    service.add_argument("action", choices=("status", "start", "stop"))
    completion = sub.add_parser("completion", help="print shell completion guidance")
    completion.add_argument("shell", choices=("bash", "zsh", "powershell"), nargs="?", default="bash")

    # Argparse normally accepts global options only before the subcommand.
    # Accepting them after it makes shell hooks and the documented
    # ``memoryhub search ... --json`` form less surprising.  SUPPRESS keeps a
    # subparser's absent option from overwriting a value supplied globally.
    for child in {id(parser): parser for parser in sub.choices.values()}.values():
        existing = child._option_string_actions  # argparse has no public query API
        if "-u" not in existing and "--user" not in existing:
            child.add_argument("-u", "--user", dest="user_id", default=argparse.SUPPRESS)
        for option, dest, kwargs in (
            (("--api-url",), "api_url", {}),
            (("--project",), "project", {}),
            (("--scene",), "scene", {}),
            (("--task-type",), "task_type", {}),
            (("--timeout",), "timeout", {"type": float}),
            (("-j", "--json"), "json_output", {"action": "store_true"}),
            (("-c", "--compact"), "compact", {"action": "store_true"}),
            (("-q", "--quiet"), "quiet", {"action": "store_true"}),
            (("--no-color",), "no_color", {"action": "store_true"}),
        ):
            if not any(item in existing for item in option):
                child.add_argument(*option, dest=dest, default=argparse.SUPPRESS, **kwargs)
    return parser


def _config(args: argparse.Namespace) -> ClientConfig:
    return ClientConfig.load(
        api_url=args.api_url,
        user_id=args.user_id,
        project=args.project,
        scene=args.scene,
        task_type=args.task_type,
        timeout=args.timeout,
    )


def _input_json(path: str) -> Any:
    if path == "-":
        content = sys.stdin.read()
    else:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise CliError(f"cannot read input file: {path}") from exc
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        events = []
        for line in content.splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    raise CliError("input is neither JSON nor valid JSONL") from exc
        return events


def _events(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("events"), list):
        value = value["events"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise CliError("event input must be an object, an array, or {events: [...]}")
    return value


def _result_for(args: argparse.Namespace, value: Any) -> str:
    if args.json_output:
        return json_text(value)
    if args.command == "search":
        return search_text(value, quiet=args.quiet)
    if args.command == "context":
        return context_text(value, args.max_chars)
    return generic_text(value, quiet=args.quiet)


def _run_command(args: argparse.Namespace, client: MemoryHubClient, cfg: ClientConfig) -> Any:
    if args.command in {"event", "events"}:
        return client.write_canonical_events(
            _events(_input_json(args.input)),
            tenant_id=getattr(cfg, "tenant_id", "default"),
            user_id=cfg.user_id,
        )
    if args.command == "resume":
        return client.resume_task(
            args.task_id,
            tenant_id=getattr(cfg, "tenant_id", "default"),
            user_id=cfg.user_id,
            resume_token=args.resume_token,
            expected_snapshot_version=args.expected_version,
        )
    if args.command == "search":
        payload = client.build_search_payload(
            user_id=cfg.user_id,
            query=args.query,
            top_k=args.top_k or cfg.top_k,
            memory_types=args.memory_types,
            min_confidence=cfg.min_confidence if args.min_confidence is None else args.min_confidence,
            scene=cfg.scene,
            task_type=cfg.task_type,
            app="memoryhub-cli",
            project_id=cfg.project,
            level=args.level or "",
            session_id=args.session_id,
        )
        return client.search(payload)
    if args.command == "context":
        payload = client.build_search_payload(
            user_id=cfg.user_id,
            query=args.query,
            top_k=args.top_k or cfg.top_k,
            scene=cfg.scene,
            task_type=cfg.task_type,
            app="memoryhub-cli",
            project_id=cfg.project,
            level=args.level or "",
            session_id=args.session_id,
        )
        return client.get_context(payload)
    if args.command == "remember":
        return client.remember(args.text, memory_type=args.memory_type, user_id=cfg.user_id, scene=cfg.scene, task_type=cfg.task_type, project_id=cfg.project, confidence=args.confidence, name=args.name)
    if args.command == "update":
        kind = args.memory_type or ("preference" if args.memory_id.startswith("pref_") else "knowledge")
        body = {"user_id": cfg.user_id}
        for key in ("text", "status", "confidence", "knowledge_type"):
            value = getattr(args, key, None)
            if value is not None:
                body["knowledge_type" if key == "knowledge_type" else key] = value
        if len(body) == 1:
            raise CliError("update requires --text, --status, --confidence or --knowledge-type")
        return client.update_memory(kind, args.memory_id, body)
    if args.command == "forget":
        body = {"user_id": cfg.user_id, "instruction": args.instruction, "cascade": args.cascade, "target_project_id": cfg.project}
        if args.preview:
            return client.forget_preview(body)
        if not args.yes:
            raise CliError("forget is destructive; run with --preview first, then add --yes", "memoryhub.cli.confirmation_required")
        return client.forget(body)
    if args.command == "list":
        return client.list_memories(user_id=cfg.user_id, memory_type=args.memory_type, scene=args.list_scene, status=args.status)
    if args.command == "get":
        return client.get_memory(args.memory_id, memory_type=args.memory_type, user_id=cfg.user_id)
    if args.command == "provenance":
        return client.provenance(args.memory_id, args.kind, cfg.user_id)
    if args.command == "projection":
        if args.projection_command == "list":
            return client.list_projections(status=args.status, user_id=cfg.user_id, limit=args.limit)
        return client.replay_projections(outbox_ids=args.outbox_ids or None, user_id=cfg.user_id)
    if args.command == "feedback":
        return client.feedback({"user_id": cfg.user_id, "memory_id": args.memory_id, "action": args.action, "feedback_text": args.feedback_text})
    if args.command == "review":
        return client.list_conflicts(cfg.user_id) if args.kind == "conflicts" else client.list_knowledge(cfg.user_id, status="pending")
    if args.command == "resolve":
        return client.resolve_conflict(args.conflict_id, {"user_id": cfg.user_id, "decision": args.decision, "reason": args.reason})
    if args.command == "decide":
        return client.decide_knowledge_fact(
            args.proposal_id,
            commit=args.decision == "commit",
            user_id=cfg.user_id,
            payload={"scope": args.scope, "project_id": cfg.project},
        )
    if args.command == "knowledge":
        triples = _input_json(args.triples)
        if isinstance(triples, dict) and isinstance(triples.get("triples"), list):
            triples = triples["triples"]
        if not isinstance(triples, list):
            raise CliError("fact proposal must contain a JSON array of triples")
        proposals = client.propose_knowledge_fact(triples, source_id=args.source_id, scope_hint=args.scope, project_id=cfg.project)
        if args.commit and isinstance(proposals, list):
            return [client.decide_knowledge_fact(item.get("proposal_id", ""), commit=True, user_id=cfg.user_id) for item in proposals]
        return proposals
    if args.command == "export":
        return client.export_memories(user_id=cfg.user_id, status=args.status)
    if args.command == "import":
        value = _input_json(args.input)
        if not isinstance(value, dict):
            raise CliError("memory export must be a JSON object")
        return client.import_memories(value, dry_run=args.dry_run)
    if args.command == "status":
        return client.system_status()
    if args.command == "service":
        if args.action == "status":
            return client.system_status()
        raise CliError("service start/stop is not implemented by the local CLI; start uvicorn separately", "memoryhub.cli.unsupported")
    if args.command == "completion":
        return f"# memoryhub {args.shell} completion is generated by argparse; use memoryhub --help"
    raise CliError(f"unsupported command: {args.command}")


def run(argv: Sequence[str] | None = None, *, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    parser = _parser()
    try:
        args = parser.parse_args(list(argv) if argv is not None else None)
        cfg = _config(args)
        with MemoryHubClient(cfg.api_url, cfg.timeout, cfg.user_id) as client:
            value = _run_command(args, client, cfg)
        print(_result_for(args, value), file=stdout)
        return 0
    except SystemExit:
        raise
    except (CliError, MemoryHubError) as exc:
        error = {"code": getattr(exc, "code", "memoryhub.cli.error"), "message": str(exc)}
        if isinstance(exc, MemoryHubError):
            error = exc.as_dict()
        if getattr(args, "json_output", False) if "args" in locals() else False:
            print(json_text({"error": error}), file=stderr)
        else:
            print(f"[{error['code']}] {error['message']}", file=stderr)
        return 4 if isinstance(exc, MemoryHubError) else 2


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
