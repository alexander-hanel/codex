from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).with_name("model_interaction_quiz.py")
REPORT_PATH = Path(__file__).resolve().parents[2] / "docs" / "model-interaction-report.md"


class ModelInteractionQuizTest(unittest.TestCase):
    def run_script(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--report",
                str(REPORT_PATH),
                *args,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_default_output_has_at_least_fifteen_questions(self) -> None:
        completed = self.run_script()
        question_lines = [
            line
            for line in completed.stdout.splitlines()
            if line.split(". ", 1)[0].isdigit() and ". " in line
        ]
        self.assertGreaterEqual(len(question_lines), 15)

    def test_seed_makes_output_deterministic(self) -> None:
        first = self.run_script("--seed", "7").stdout
        second = self.run_script("--seed", "7").stdout
        third = self.run_script("--seed", "8").stdout

        self.assertEqual(first, second)
        self.assertNotEqual(first, third)

    def test_markdown_with_answers_includes_answer_key(self) -> None:
        completed = self.run_script("--markdown", "--show-answers", "--count", "16")
        self.assertIn("# Model Interaction Quiz", completed.stdout)
        self.assertIn("## Answer Key", completed.stdout)
        self.assertIn("Question 1", completed.stdout)

    def test_interactive_mode_accepts_answers_and_reports_score(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_PATH),
                "--report",
                str(REPORT_PATH),
                "--interactive",
                "--count",
                "15",
                "--seed",
                "3",
            ],
            input="\n".join(["A"] * 15) + "\n",
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertIn("Question 1:", completed.stdout)
        self.assertIn("Your answer:", completed.stdout)
        self.assertIn("Final score:", completed.stdout)


if __name__ == "__main__":
    unittest.main()
