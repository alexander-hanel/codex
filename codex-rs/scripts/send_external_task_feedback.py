#!/usr/bin/env python3
"""Send external task feedback to a running Codex session.

This helper discovers live sessions from the shared registry under CODEX_HOME
and writes an inbox file that the Codex core watcher will ingest.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any


ENVELOPE_VERSION = 1

SOURCE_CHOICES = [
    "external_process",
    "security_software",
    "operating_system",
    "user",
    "other",
]

SEVERITY_CHOICES = [
    "info",
    "warning",
    "error",
]

DISPOSITION_CHOICES = [
    "informational",
    "failed_by_external_actor",
    "do_not_retry",
]

SCOPE_CHOICES = [
    "session",
    "turn",
    "tool_call",
    "command",
    "path",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send external task feedback to a running Codex session.",
    )
    parser.add_argument(
        "--codex-home",
        type=Path,
        default=default_codex_home(),
        help="Path to CODEX_HOME. Defaults to $CODEX_HOME or ~/.codex.",
    )
    parser.add_argument(
        "--thread-id",
        help="Target thread id. Required unless --discover-first is used or only one live session exists.",
    )
    parser.add_argument(
        "--discover-first",
        action="store_true",
        help="Target the first discovered session when multiple session registrations exist.",
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="Print discovered session registrations and exit.",
    )
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="external_process",
        help="Who is reporting the feedback.",
    )
    parser.add_argument(
        "--severity",
        choices=SEVERITY_CHOICES,
        default="warning",
        help="How severe the feedback is.",
    )
    parser.add_argument(
        "--disposition",
        choices=DISPOSITION_CHOICES,
        default="failed_by_external_actor",
        help="How Codex should interpret retry behavior.",
    )
    parser.add_argument(
        "--message",
        help="Human-readable explanation for the feedback.",
    )
    parser.add_argument(
        "--observed-at",
        type=int,
        help="Unix timestamp override. Defaults to current time.",
    )
    parser.add_argument(
        "--scope-type",
        choices=SCOPE_CHOICES,
        default="session",
        help="What part of the current task the feedback applies to.",
    )
    parser.add_argument(
        "--turn-id",
        help="Turn id for turn, tool_call, command, or path scopes.",
    )
    parser.add_argument(
        "--call-id",
        help="Tool call id for tool_call scope.",
    )
    parser.add_argument(
        "--tool-name",
        help="Tool name for tool_call scope.",
    )
    parser.add_argument(
        "--command",
        help="Command text for command scope.",
    )
    parser.add_argument(
        "--path",
        help="Filesystem path for path scope.",
    )
    return parser.parse_args()


def default_codex_home() -> Path:
    codex_home = os.environ.get("CODEX_HOME")
    if codex_home:
        return Path(codex_home).expanduser()
    return Path.home() / ".codex"


def sessions_dir(codex_home: Path) -> Path:
    return codex_home / "ipc" / "sessions"


def inbox_dir(codex_home: Path) -> Path:
    return codex_home / "ipc" / "external-task-feedback" / "inbox"


def load_sessions(codex_home: Path) -> list[dict[str, Any]]:
    directory = sessions_dir(codex_home)
    if not directory.is_dir():
        return []

    sessions: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"warning: failed to read {path}: {exc}", file=sys.stderr)
            continue
        process_id = session.get("process_id")
        if isinstance(process_id, int) and not process_exists(process_id):
            remove_stale_session(path, process_id)
            continue
        session["_registry_path"] = str(path)
        sessions.append(session)
    return sessions


def process_exists(process_id: int) -> bool:
    if process_id <= 0:
        return False

    if os.name == "nt":
        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(  # type: ignore[attr-defined]
            process_query_limited_information,
            False,
            process_id,
        )
        if handle == 0:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
        return True

    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_stale_session(path: Path, process_id: int) -> None:
    try:
        path.unlink()
    except OSError as exc:
        print(
            f"warning: failed to remove stale session registry {path}: {exc}",
            file=sys.stderr,
        )
        return
    print(
        f"warning: removed stale session registry {path} for dead pid {process_id}",
        file=sys.stderr,
    )


def select_thread_id(
    codex_home: Path, thread_id: str | None, discover_first: bool
) -> str:
    if thread_id:
        return thread_id

    sessions = load_sessions(codex_home)
    if not sessions:
        raise SystemExit(
            f"no session registrations found under {sessions_dir(codex_home)}; pass --thread-id explicitly"
        )

    if len(sessions) == 1 or discover_first:
        return str(sessions[0]["thread_id"])

    raise SystemExit(
        "multiple sessions discovered; pass --thread-id or use --discover-first"
    )


def build_scope(args: argparse.Namespace) -> dict[str, Any]:
    scope_type = args.scope_type
    if scope_type == "session":
        return {"type": "session"}
    if scope_type == "turn":
        require_arg(args.turn_id, "--turn-id is required for --scope-type turn")
        return {"type": "turn", "turn_id": args.turn_id}
    if scope_type == "tool_call":
        require_arg(args.call_id, "--call-id is required for --scope-type tool_call")
        scope = {"type": "tool_call", "call_id": args.call_id}
        if args.turn_id:
            scope["turn_id"] = args.turn_id
        if args.tool_name:
            scope["tool_name"] = args.tool_name
        return scope
    if scope_type == "command":
        require_arg(args.command, "--command is required for --scope-type command")
        scope = {"type": "command", "command": args.command}
        if args.turn_id:
            scope["turn_id"] = args.turn_id
        return scope
    if scope_type == "path":
        require_arg(args.path, "--path is required for --scope-type path")
        scope = {"type": "path", "path": args.path}
        if args.turn_id:
            scope["turn_id"] = args.turn_id
        return scope
    raise SystemExit(f"unsupported scope type: {scope_type}")


def require_arg(value: str | None, error_message: str) -> None:
    if not value:
        raise SystemExit(error_message)


def build_envelope(thread_id: str, args: argparse.Namespace) -> dict[str, Any]:
    require_arg(args.message, "--message is required unless --list-sessions is used")
    observed_at = args.observed_at if args.observed_at is not None else int(time.time())
    return {
        "version": ENVELOPE_VERSION,
        "thread_id": thread_id,
        "feedback": {
            "source": args.source,
            "severity": args.severity,
            "disposition": args.disposition,
            "scope": build_scope(args),
            "message": args.message,
            "observed_at": observed_at,
        },
    }


def file_suffix(scope: dict[str, Any]) -> str:
    scope_type = scope["type"]
    if scope_type == "tool_call":
        return "tool-call"
    return str(scope_type)


def write_envelope(codex_home: Path, thread_id: str, envelope: dict[str, Any]) -> Path:
    target_dir = inbox_dir(codex_home)
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = file_suffix(envelope["feedback"]["scope"])
    target_path = target_dir / f"{thread_id}.{suffix}.{uuid.uuid4().hex}.json"
    payload = json.dumps(envelope, indent=2, sort_keys=True) + "\n"

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target_dir,
        prefix=f".{thread_id}.{suffix}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        temp_path = Path(handle.name)

    os.replace(temp_path, target_path)
    return target_path


def print_sessions(codex_home: Path) -> int:
    sessions = load_sessions(codex_home)
    if not sessions:
        print(f"no sessions found in {sessions_dir(codex_home)}")
        return 0

    for session in sessions:
        print(json.dumps(session, indent=2, sort_keys=True))
    return 0


def main() -> int:
    args = parse_args()
    codex_home = args.codex_home.expanduser().resolve()

    if args.list_sessions:
        return print_sessions(codex_home)

    thread_id = select_thread_id(codex_home, args.thread_id, args.discover_first)
    envelope = build_envelope(thread_id, args)
    path = write_envelope(codex_home, thread_id, envelope)
    print(json.dumps({"thread_id": thread_id, "inbox_file": str(path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
