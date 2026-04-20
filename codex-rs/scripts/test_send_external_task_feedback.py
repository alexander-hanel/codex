from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("send_external_task_feedback.py")


class SendExternalTaskFeedbackTest(unittest.TestCase):
    def test_lists_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            sessions_dir = codex_home / "ipc" / "sessions"
            sessions_dir.mkdir(parents=True)
            registration = {
                "thread_id": "thread-123",
                "process_id": 42,
                "cwd": "/repo",
                "inbox_path": str(
                    codex_home / "ipc" / "external-task-feedback" / "inbox"
                ),
                "created_at": 1_700_000_000,
            }
            (sessions_dir / "thread-123.json").write_text(
                json.dumps(registration), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--codex-home",
                    str(codex_home),
                    "--list-sessions",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"thread_id": "thread-123"', completed.stdout)
            self.assertEqual(completed.stderr, "")

    def test_list_sessions_filters_stale_registrations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            sessions_dir = codex_home / "ipc" / "sessions"
            sessions_dir.mkdir(parents=True)
            live_registration = {
                "thread_id": "thread-live",
                "process_id": os.getpid(),
                "cwd": "/repo",
                "inbox_path": str(
                    codex_home / "ipc" / "external-task-feedback" / "inbox"
                ),
                "created_at": 1_700_000_001,
            }
            stale_registration = {
                "thread_id": "thread-stale",
                "process_id": 999999,
                "cwd": "/repo",
                "inbox_path": str(
                    codex_home / "ipc" / "external-task-feedback" / "inbox"
                ),
                "created_at": 1_700_000_000,
            }
            (sessions_dir / "thread-live.json").write_text(
                json.dumps(live_registration), encoding="utf-8"
            )
            stale_path = sessions_dir / "thread-stale.json"
            stale_path.write_text(json.dumps(stale_registration), encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--codex-home",
                    str(codex_home),
                    "--list-sessions",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            self.assertIn('"thread_id": "thread-live"', completed.stdout)
            self.assertNotIn('"thread_id": "thread-stale"', completed.stdout)
            self.assertFalse(stale_path.exists())
            self.assertIn("removed stale session registry", completed.stderr)

    def test_writes_feedback_envelope_for_discovered_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            codex_home = Path(temp_dir)
            sessions_dir = codex_home / "ipc" / "sessions"
            sessions_dir.mkdir(parents=True)
            inbox_path = codex_home / "ipc" / "external-task-feedback" / "inbox"
            registration = {
                "thread_id": "thread-abc",
                "process_id": 7,
                "cwd": "/repo",
                "inbox_path": str(inbox_path),
                "created_at": 1_700_000_000,
            }
            (sessions_dir / "thread-abc.json").write_text(
                json.dumps(registration), encoding="utf-8"
            )

            subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_PATH),
                    "--codex-home",
                    str(codex_home),
                    "--message",
                    "command blocked by external process",
                    "--scope-type",
                    "command",
                    "--command",
                    "git status",
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            inbox_files = list(inbox_path.glob("thread-abc.command.*.json"))
            self.assertEqual(len(inbox_files), 1)
            envelope = json.loads(inbox_files[0].read_text(encoding="utf-8"))
            self.assertEqual(
                envelope,
                {
                    "version": 1,
                    "thread_id": "thread-abc",
                    "feedback": {
                        "source": "external_process",
                        "severity": "warning",
                        "disposition": "failed_by_external_actor",
                        "scope": {
                            "type": "command",
                            "command": "git status",
                        },
                        "message": "command blocked by external process",
                        "observed_at": envelope["feedback"]["observed_at"],
                    },
                },
            )
            self.assertIsInstance(envelope["feedback"]["observed_at"], int)


if __name__ == "__main__":
    unittest.main()
