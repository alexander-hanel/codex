#!/usr/bin/env python3
"""Generate a multiple-choice quiz from docs/model-interaction-report.md.

The quiz is based on a curated high-level question bank aligned with the report.
Questions and answer options can be randomized with a seed for repeatable runs.
"""

from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


DEFAULT_REPORT_PATH = Path("docs/model-interaction-report.md")
MIN_QUESTION_COUNT = 15


@dataclass(frozen=True)
class Question:
    prompt: str
    choices: tuple[str, ...]
    answer_index: int
    explanation: str


QUESTION_BANK: tuple[Question, ...] = (
    Question(
        prompt="What is the main purpose of the model interaction report?",
        choices=(
            "To explain how the repository receives prompts, builds model requests, streams responses, and executes tool calls",
            "To document only the app-server RPC schema",
            "To explain only the TUI rendering layer",
            "To describe dependency installation and local setup",
        ),
        answer_index=0,
        explanation="The report maps the full prompt, model, streaming, and tool execution flow.",
    ),
    Question(
        prompt="Which file is the main turn-loop center of the request/response pipeline?",
        choices=(
            "codex-rs/core/src/tasks/regular.rs",
            "codex-rs/core/src/session/turn.rs",
            "codex-rs/tui/src/chatwidget.rs",
            "codex-rs/protocol/src/openai_models.rs",
        ),
        answer_index=1,
        explanation="The report identifies core/src/session/turn.rs as the main turn-loop location.",
    ),
    Question(
        prompt="Which type represents the main turn payload before it is converted into a transport request?",
        choices=(
            "ResponsesApiRequest",
            "ResponseEvent",
            "Prompt",
            "ToolCall",
        ),
        answer_index=2,
        explanation="Prompt is the abstract turn payload built before transport conversion.",
    ),
    Question(
        prompt="Where is the Prompt type defined according to the report?",
        choices=(
            "codex-rs/core/src/client_common.rs",
            "codex-rs/core/src/session/mod.rs",
            "codex-rs/codex-api/src/endpoint/responses.rs",
            "codex-rs/core/src/tools/router.rs",
        ),
        answer_index=0,
        explanation="The report points to core/src/client_common.rs for the Prompt definition.",
    ),
    Question(
        prompt="What converts a Prompt into a ResponsesApiRequest?",
        choices=(
            "ToolRouter::build_tool_call(...)",
            "ModelClientSession::build_responses_request(...)",
            "handle_output_item_done(...)",
            "run_turn(...)",
        ),
        answer_index=1,
        explanation="The report names ModelClientSession::build_responses_request(...) as that conversion step.",
    ),
    Question(
        prompt="Which method is responsible for streaming requests to the model over WebSocket or HTTP?",
        choices=(
            "ModelClientSession::stream(...)",
            "build_prompt(...)",
            "stream_request(...)",
            "handle_tool_call(...)",
        ),
        answer_index=0,
        explanation="ModelClientSession::stream(...) is the top-level streaming method in the client layer.",
    ),
    Question(
        prompt="What arrives back from the model as the streamed output primitive?",
        choices=(
            "ResponseEvent",
            "ResponseInputItem",
            "TurnItem",
            "ToolPayload",
        ),
        answer_index=0,
        explanation="The model output is streamed back as ResponseEvent values.",
    ),
    Question(
        prompt="Which ResponseEvent branch is especially important for triggering tool execution?",
        choices=(
            "Created",
            "Completed",
            "OutputItemDone",
            "ReasoningSummaryDelta",
        ),
        answer_index=2,
        explanation="OutputItemDone is the key branch where Codex decides whether to execute a tool call.",
    ),
    Question(
        prompt="Where does the TUI gather raw prompt content before it is turned into core input items?",
        choices=(
            "codex-rs/core/src/tasks/regular.rs",
            "codex-rs/tui/src/chatwidget.rs",
            "codex-rs/core/src/client.rs",
            "codex-rs/app-server/src/server.rs",
        ),
        answer_index=1,
        explanation="The report identifies tui/src/chatwidget.rs as the TUI entry point for raw prompt collection.",
    ),
    Question(
        prompt="What special behavior does the TUI apply to input starting with !cmd?",
        choices=(
            "It sends the raw shell text to the model as hidden context",
            "It drops the message and emits a warning",
            "It runs a local shell command directly instead of sending it to the model",
            "It converts the command into an MCP tool call",
        ),
        answer_index=2,
        explanation="The report notes that !cmd is special-cased to run locally instead of going to the model.",
    ),
    Question(
        prompt="Where does the app-server map incoming RPC input into core input items?",
        choices=(
            "codex-rs/core/src/session/turn.rs",
            "codex-rs/app-server/src/codex_message_processor.rs",
            "codex-rs/core/src/stream_events_utils.rs",
            "codex-rs/core/src/tools/parallel.rs",
        ),
        answer_index=1,
        explanation="The app-server input mapping happens in codex_message_processor.rs.",
    ),
    Question(
        prompt="What is one of the key responsibilities of build_prompt(...)?",
        choices=(
            "Executing tool calls in parallel",
            "Constructing model-visible history, tool specs, base instructions, and output schema",
            "Posting HTTP requests to the model provider",
            "Writing TUI deltas to the screen",
        ),
        answer_index=1,
        explanation="build_prompt(...) decides what the model sees for the turn.",
    ),
    Question(
        prompt="What can build_prompt(...) filter out before the request is sent?",
        choices=(
            "Completed assistant text deltas",
            "Deferred dynamic tools the model should not know about yet",
            "Conversation history older than one turn",
            "MCP server credentials",
        ),
        answer_index=1,
        explanation="The report says deferred dynamic tools can be filtered out before prompt submission.",
    ),
    Question(
        prompt="Which file implements the HTTP /responses request path?",
        choices=(
            "codex-rs/core/src/client.rs",
            "codex-rs/core/src/session/turn.rs",
            "codex-rs/codex-api/src/endpoint/responses.rs",
            "codex-rs/core/src/tools/router.rs",
        ),
        answer_index=2,
        explanation="The HTTP transport implementation lives in codex-api/src/endpoint/responses.rs.",
    ),
    Question(
        prompt="Which utility recognizes completed model output items as tool calls and queues their execution?",
        choices=(
            "handle_output_item_done(...) in stream_events_utils.rs",
            "build_prompt(...) in session/turn.rs",
            "stream_request(...) in responses.rs",
            "submit(...) in the session thread",
        ),
        answer_index=0,
        explanation="The report points to handle_output_item_done(...) as the tool-call detection point.",
    ),
    Question(
        prompt="What does ToolRouter::build_tool_call(...) do at a high level?",
        choices=(
            "It converts model-emitted tool items into internal ToolCall values",
            "It applies patch diffs to the filesystem",
            "It serializes HTTP requests to the Responses API",
            "It renders reasoning summaries in the TUI",
        ),
        answer_index=0,
        explanation="ToolRouter::build_tool_call(...) translates model items into internal tool calls.",
    ),
    Question(
        prompt="Where is tool execution performed once an internal ToolCall exists?",
        choices=(
            "codex-rs/core/src/tools/parallel.rs",
            "codex-rs/core/src/client_common.rs",
            "codex-rs/protocol/src/protocol.rs",
            "codex-rs/core/src/state/session.rs",
        ),
        answer_index=0,
        explanation="ToolCallRuntime::handle_tool_call(...) in tools/parallel.rs executes the tool.",
    ),
    Question(
        prompt="What form do successful tool results take before they are fed back into the next model request?",
        choices=(
            "Only plain text assistant messages",
            "Environment variable updates",
            "ResponseInputItem values such as FunctionCallOutput or CustomToolCallOutput",
            "Serialized Prompt objects",
        ),
        answer_index=2,
        explanation="The report says tool results become ResponseInputItem values like FunctionCallOutput.",
    ),
    Question(
        prompt="Why is the tool-result feedback loop important to Codex agent behavior?",
        choices=(
            "It lets the TUI avoid rendering streamed text",
            "It ensures tool outputs are appended to history and included in the next model request",
            "It prevents the model from ever using parallel tool calls",
            "It replaces the need for base instructions",
        ),
        answer_index=1,
        explanation="Agent behavior depends on feeding tool outputs back into subsequent requests.",
    ),
    Question(
        prompt="What is the shortest high-level chain for following a normal turn through the system?",
        choices=(
            "User input -> run_turn -> build_prompt -> client stream -> ResponseEvent handling -> tool routing/execution -> next turn iteration",
            "User input -> protocol.rs -> config schema -> tool registry -> shutdown",
            "TUI input -> apply_patch -> MCP startup -> final answer",
            "Prompt template -> markdown report -> app-server schema -> HTTP headers",
        ),
        answer_index=0,
        explanation="That sequence matches the report's end-to-end model interaction path.",
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a multiple-choice quiz for docs/model-interaction-report.md.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to the model interaction report markdown file.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=MIN_QUESTION_COUNT,
        help="Number of questions to include. Default: 15.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Optional seed for deterministic shuffling of questions and choices.",
    )
    parser.add_argument(
        "--show-answers",
        action="store_true",
        help="Print the answer key and explanations after the quiz.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Render the quiz as markdown instead of plain text.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run the quiz interactively in the terminal.",
    )
    return parser.parse_args()


def validate_report(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"failed to read report at {path}: {exc}") from exc

    required_markers = (
        "# Model Interaction Report",
        "## Executive Summary",
        "## Core Concepts",
        "## High-Level Architecture",
        "## Sending Requests to the Model",
        "## Receiving Streamed Model Output",
        "## Acting on Model Tool Calls",
    )
    missing = [marker for marker in required_markers if marker not in content]
    if missing:
        joined = ", ".join(missing)
        raise SystemExit(
            f"report at {path} does not look like the expected model interaction report; missing: {joined}"
        )
    return content


def shuffled_question(question: Question, rng: random.Random) -> tuple[Question, int]:
    indexed_choices = list(enumerate(question.choices))
    rng.shuffle(indexed_choices)
    shuffled_choices = tuple(choice for _, choice in indexed_choices)
    correct_index = next(
        new_index
        for new_index, (old_index, _) in enumerate(indexed_choices)
        if old_index == question.answer_index
    )
    return (
        Question(
            prompt=question.prompt,
            choices=shuffled_choices,
            answer_index=correct_index,
            explanation=question.explanation,
        ),
        correct_index,
    )


def build_quiz(question_count: int, seed: int | None) -> list[Question]:
    if question_count < MIN_QUESTION_COUNT:
        raise SystemExit(
            f"--count must be at least {MIN_QUESTION_COUNT} to meet the requested quiz length"
        )
    if question_count > len(QUESTION_BANK):
        raise SystemExit(
            f"--count cannot exceed {len(QUESTION_BANK)} because the current question bank has {len(QUESTION_BANK)} questions"
        )

    rng = random.Random(seed)
    selected = list(QUESTION_BANK)
    rng.shuffle(selected)
    selected = selected[:question_count]
    return [shuffled_question(question, rng)[0] for question in selected]


def label_for_index(index: int) -> str:
    return chr(ord("A") + index)


def render_plain_text(questions: Sequence[Question], show_answers: bool) -> str:
    lines: list[str] = []
    lines.append("Model Interaction Quiz")
    lines.append("======================")
    lines.append("")
    for question_index, question in enumerate(questions, start=1):
        lines.append(f"{question_index}. {question.prompt}")
        for choice_index, choice in enumerate(question.choices):
            lines.append(f"   {label_for_index(choice_index)}. {choice}")
        lines.append("")

    if show_answers:
        lines.append("Answer Key")
        lines.append("==========")
        lines.append("")
        for question_index, question in enumerate(questions, start=1):
            answer_label = label_for_index(question.answer_index)
            lines.append(f"{question_index}. {answer_label}")
            lines.append(f"   {question.explanation}")
        lines.append("")
    return "\n".join(lines)


def render_markdown(questions: Sequence[Question], show_answers: bool) -> str:
    lines: list[str] = []
    lines.append("# Model Interaction Quiz")
    lines.append("")
    for question_index, question in enumerate(questions, start=1):
        lines.append(f"## Question {question_index}")
        lines.append("")
        lines.append(question.prompt)
        lines.append("")
        for choice_index, choice in enumerate(question.choices):
            lines.append(f"- `{label_for_index(choice_index)}` {choice}")
        lines.append("")

    if show_answers:
        lines.append("## Answer Key")
        lines.append("")
        for question_index, question in enumerate(questions, start=1):
            answer_label = label_for_index(question.answer_index)
            lines.append(f"{question_index}. `{answer_label}` {question.explanation}")
        lines.append("")
    return "\n".join(lines)


def run_interactive(questions: Sequence[Question], show_answers: bool) -> int:
    print("Model Interaction Quiz")
    print("======================")
    print("")
    print("Enter the letter for each answer and press Enter.")
    print("")

    correct_answers = 0

    for question_index, question in enumerate(questions, start=1):
        print(f"Question {question_index}: {question.prompt}")
        for choice_index, choice in enumerate(question.choices):
            print(f"  {label_for_index(choice_index)}. {choice}")

        valid_answers = {label_for_index(i): i for i in range(len(question.choices))}
        while True:
            response = input("Your answer: ").strip().upper()
            if response in valid_answers:
                break
            print(f"Please enter one of: {', '.join(valid_answers)}")

        chosen_index = valid_answers[response]
        correct_label = label_for_index(question.answer_index)
        if chosen_index == question.answer_index:
            correct_answers += 1
            print("Correct.")
        else:
            print(f"Incorrect. Correct answer: {correct_label}.")

        if show_answers or chosen_index != question.answer_index:
            print(question.explanation)
        print("")

    total_questions = len(questions)
    percentage = (correct_answers / total_questions) * 100
    print(
        f"Final score: {correct_answers}/{total_questions} "
        f"({percentage:.1f}%)"
    )
    return 0


def main() -> int:
    args = parse_args()
    validate_report(args.report)
    questions = build_quiz(args.count, args.seed)
    if args.interactive:
        return run_interactive(questions, args.show_answers)
    output = (
        render_markdown(questions, args.show_answers)
        if args.markdown
        else render_plain_text(questions, args.show_answers)
    )
    sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
