# IPC Feedback Bridge for Codex

This repository is a fork of OpenAI's Codex with an added IPC feedback bridge.

The goal of the bridge is simple: let a second local process tell Codex
something important about the current task, especially when Codex cannot infer
the reason for a failure by itself.

Typical examples:

- a security product blocked a command
- a file is locked by another process
- the operating system denied access to a path
- an external supervisor knows a retry should not happen
- a secondary process wants to add task-wide context before the next turn

The key outcome is that Codex can use this feedback as model-visible context and
can also change retry behavior for some tool calls.

## What This Adds

This fork adds two connected pieces:

1. A typed internal feedback path inside Codex.
2. A local file-based IPC surface that outside processes can write to.

Once feedback is ingested, Codex can:

- record it in session state
- expose it as an `ExternalTaskFeedback` event
- include it in model-visible context
- stop retrying some blocked shell and `apply_patch` actions

Today, the behavior-changing part is implemented for:

- shell commands blocked by matching command feedback
- `apply_patch` blocked by matching path feedback

## When To Use It

Use this bridge when an external process knows something Codex should take into
account, such as:

- "this command was blocked by endpoint protection"
- "this file is locked"
- "do not keep retrying this action"
- "the whole task is under external policy monitoring"

If your goal is broad steering rather than blocking one exact command, prefer
`session` scope.

If your goal is to stop retries for one exact shell command, use `command`
scope.

If your goal is to stop retries for edits to one file, use `path` scope.

## Quick Start

### Smallest live demo

Start Codex in one terminal:

```bash
cd /home/USER/repos/codex/codex-rs
unset CODEX_SANDBOX CODEX_SANDBOX_NETWORK_DISABLED
CODEX_SKIP_VENDORED_BWRAP=1 ./target/debug/codex
```

In Codex, type:

```text
Say hello, then wait for my next instruction.
```

From a second terminal, send session-scoped feedback:

```bash
cd /home/USER/repos/codex
python3 codex-rs/scripts/send_external_task_feedback.py \
  --discover-first \
  --source external_process \
  --severity warning \
  --disposition informational \
  --scope-type session \
  --message "A secondary process reports that this task is under external monitoring. Avoid repeated retries until the condition is clarified."
```

Back in Codex, type:

```text
Continue, but account for any external feedback you have received.
```

Expected result:

- Codex ingests the feedback
- the next turn sees it as developer-visible context

### Smallest automated check

```bash
cd /home/USER/repos/codex/codex-rs
unset CODEX_SANDBOX CODEX_SANDBOX_NETWORK_DISABLED
CODEX_SKIP_VENDORED_BWRAP=1 cargo test -p codex-core external_task_feedback_is_included_in_next_model_request -- --nocapture
```

## Mental Model

The bridge has two layers.

### Layer 1: internal feedback types

Codex has typed feedback objects such as:

- `ExternalFeedbackSource`
- `ExternalFeedbackSeverity`
- `ExternalFeedbackDisposition`
- `ExternalTaskFeedbackScope`
- `ExternalTaskFeedback`
- `ExternalTaskFeedbackEvent`

These let Codex treat outside feedback as first-class runtime information
instead of only plain text.

### Layer 2: local IPC transport

Codex also publishes a file-based interface under `CODEX_HOME` so an outside
process can:

- discover active sessions
- choose a target thread
- write a feedback envelope into the shared inbox

That transport is file-based on purpose. It works on Windows, Linux, and macOS
without introducing sockets, named pipes, or platform-specific services.

## How It Works

Codex exposes two IPC directories under `CODEX_HOME`:

```text
CODEX_HOME/
└── ipc/
    ├── sessions/
    │   └── <thread_id>.json
    └── external-task-feedback/
        └── inbox/
            └── <thread_id>.<scope>.<nonce>.json
```

### Session discovery

When a session starts, Codex writes:

```text
CODEX_HOME/ipc/sessions/<thread_id>.json
```

That file includes:

- `thread_id`
- `process_id`
- `cwd`
- `inbox_path`
- `created_at`

This solves the discovery problem for a second process. It does not need an
out-of-band channel to learn the active thread id.

### Feedback delivery

The second process writes a JSON envelope into:

```text
CODEX_HOME/ipc/external-task-feedback/inbox/
```

Codex watches that inbox, reads matching files, validates the payload, ingests
the feedback, and deletes the file after successful processing.

## Feedback Shape

Example envelope:

```json
{
  "version": 1,
  "thread_id": "thread-123",
  "feedback": {
    "source": "external_process",
    "severity": "warning",
    "disposition": "failed_by_external_actor",
    "scope": {
      "type": "command",
      "command": "git status"
    },
    "message": "Command blocked by endpoint security",
    "observed_at": 1710000000
  }
}
```

Supported scope values:

- `session`
- `turn`
- `tool_call`
- `command`
- `path`

Supported source values:

- `external_process`
- `security_software`
- `operating_system`
- `user`
- `other`

Supported severity values:

- `info`
- `warning`
- `error`

Supported disposition values:

- `informational`
- `failed_by_external_actor`
- `do_not_retry`

## What Codex Actually Does With Feedback

Once feedback is ingested, Codex routes it through the same internal path as
direct runtime feedback.

That means it can:

- record the feedback in session state
- emit `ExternalTaskFeedback` events
- make the feedback visible to the model
- consult the feedback before retrying some tool actions

There are two important runtime cases:

### Active turn

If Codex is already in an active turn, the feedback is injected so the current
turn can see it on the next actionable step.

### Idle session

If Codex is idle, the feedback is recorded into conversation history so it is
present on the next model request.

This matters because it means feedback does not have to arrive before Codex
starts up. It only has to arrive before the next decision point where it should
matter.

## Exact vs Broad Matching

This is one of the most important things to understand.

### `session` scope

Use this when you want to steer the whole task or next turn, even if no command
has run yet.

This is the best choice for messages like:

- "the task is under external monitoring"
- "repeated failures may be caused by outside enforcement"
- "avoid retries until the condition is clarified"

### `command` scope

Use this when you want to block retries for a specific shell command.

Current limitation:

- command matching is exact string matching

So feedback for:

```text
git status
```

does not automatically match:

```text
git status --short --branch
```

If you want a reliable command demo today, send feedback for the exact command
string Codex is expected to run.

### `path` scope

Use this when the outside condition applies to a file or path, such as a lock or
access restriction.

## Helper Script

The local helper for testing and external integration is:

- `codex-rs/scripts/send_external_task_feedback.py`

Common commands:

List discovered sessions:

```bash
python3 codex-rs/scripts/send_external_task_feedback.py --list-sessions
```

Send session-scoped feedback:

```bash
python3 codex-rs/scripts/send_external_task_feedback.py \
  --discover-first \
  --source external_process \
  --severity warning \
  --disposition informational \
  --scope-type session \
  --message "A secondary process reports that this task is under external monitoring. Avoid repeated retries until the condition is clarified."
```

Send exact command feedback:

```bash
python3 codex-rs/scripts/send_external_task_feedback.py \
  --discover-first \
  --source security_software \
  --severity error \
  --disposition do_not_retry \
  --scope-type command \
  --command "git status --short --branch" \
  --message "git status --short --branch was blocked by endpoint protection"
```

Send path-scoped feedback:

```bash
python3 codex-rs/scripts/send_external_task_feedback.py \
  --thread-id <thread_id> \
  --source operating_system \
  --severity error \
  --disposition do_not_retry \
  --scope-type path \
  --path /path/to/file \
  --message "Access denied by policy"
```

## Suggested Demo Prompts

### Broad session feedback

In Codex:

```text
Continue, but account for any external feedback you have received.
```

This is the simplest prompt for proving that a second process can influence
Codex even when no command has run.

### Exact command feedback

In Codex:

```text
Run exactly this command and nothing else: `git status --short --branch`
```

Use this when you want to demonstrate command blocking with the current exact
matching behavior.

### Blocked path for `apply_patch`

In Codex:

```text
Please make a small edit to `README.md`. If the file is blocked, do not keep retrying.
```

Use this when you want to demonstrate path-scoped external feedback affecting
edit retries.

## Testing

### Python helper tests

```bash
python3 -m unittest codex-rs/scripts/test_send_external_task_feedback.py
```

What this covers:

- session registration discovery
- feedback envelope creation

### Core feedback tests

```bash
cd codex-rs
CODEX_SKIP_VENDORED_BWRAP=1 cargo test -p codex-core external_task_feedback -- --nocapture
CODEX_SKIP_VENDORED_BWRAP=1 cargo test -p codex-core external_task_feedback_is_included_in_next_model_request -- --nocapture
```

What this covers:

- inbox watcher behavior
- session registration creation and cleanup
- inbox ingestion
- event emission
- active-turn model-visible injection
- idle-session model-visible injection into the next request

### Retry-behavior tests

```bash
cd codex-rs
CODEX_SKIP_VENDORED_BWRAP=1 cargo test -p codex-core shell_handler_short_circuits_blocked_command_feedback -- --nocapture
CODEX_SKIP_VENDORED_BWRAP=1 cargo test -p codex-core apply_patch_handler_short_circuits_blocked_path_feedback -- --nocapture
```

What this covers:

- shell stops retrying a blocked command
- `apply_patch` stops retrying a blocked path

## Important Limitations

- the transport is local file-based only
- `--discover-first` is convenient for local testing but weak for automation in
  multi-session setups
- retry short-circuiting is currently implemented for shell command and path
  cases, not every possible tool or failure mode
- command matching is currently exact string matching
- session-scoped feedback is the best current option when no command has run yet
- feedback affects the next actionable decision point, not an already-streaming
  model generation token-by-token

## Why This Design Was Chosen

This IPC shape is intentionally simple:

- cross-platform
- easy to inspect manually
- easy to write from any language
- durable enough for short-lived local coordination

If this evolves later, the same registry-plus-inbox contract could be wrapped by:

- a local service
- named pipes
- OS-native notifications
- an app-server RPC layer

without changing the core feedback semantics.

## Implementation Map

Primary implementation files:

- `codex-rs/core/src/external_task_feedback_inbox_watcher.rs`
- `codex-rs/core/src/session/session.rs`
- `codex-rs/core/src/session/mod.rs`
- `codex-rs/core/src/session/handlers.rs`
- `codex-rs/core/src/state/session.rs`
- `codex-rs/core/src/tools/handlers/shell.rs`
- `codex-rs/core/src/tools/handlers/apply_patch.rs`
- `codex-rs/core/src/tools/orchestrator.rs`
- `codex-rs/protocol/src/protocol.rs`

If you want to trace the broader model loop around this feature, this is the
shortest useful chain:

1. `tui/src/chatwidget.rs` or `app-server/src/codex_message_processor.rs`
2. `core/src/tasks/regular.rs`
3. `core/src/session/turn.rs::run_turn`
4. `core/src/client.rs::ModelClientSession::build_responses_request`
5. `codex-api/src/endpoint/responses.rs::stream_request`
6. `core/src/stream_events_utils.rs::handle_output_item_done`
7. `core/src/tools/router.rs::build_tool_call`
8. `core/src/tools/parallel.rs::handle_tool_call`
9. feedback ingestion in `core/src/session/mod.rs`
10. next iteration of `run_turn`
