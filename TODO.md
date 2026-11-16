# 🎯 [NEXT] B7: Capture child stderr separately to extract accurate Error lines in END box

- In `src/runner.py`, block execution currently merges child `stdout` and `stderr` into a single descriptor (`stdout=slave_fd, stderr=slave_fd` in PTY mode and `stdout=PIPE, stderr=STDOUT` in pipe mode), so `src/ui.py` (`_extract_last_error_line`) only sees the combined `step_dir / "out"` file and picks its last non-empty line when `rc != 0`.
- When a command writes an error to `stderr` mid-run and then continues printing normal output to `stdout` before exiting non-zero (for example `head -n 25 dev/*` printing `head: error reading 'dev/__pycache__': Is a directory` to `stderr` followed by file contents on `stdout`), `END` displays the last line of `stdout` in `Error:` instead of the diagnostic from `stderr`.
- Read child `stderr` via a separate descriptor alongside `stdout` in `src/runner.py`, continuing to stream both to the terminal and into `step_dir / "out"` while also saving `stderr` to `step_dir / "err"`, and update `_extract_last_error_line` in `src/ui.py` to prefer the last non-empty line from `step_dir / "err"` (falling back to `step_dir / "out"` only when `stderr` is empty), with unit tests in `tests/test_run_block.py`.

# 🎯 [NEXT] F43: Brighten Error line styling and keep confirmation prompt distinct from Safety warnings

- In `src/ui.py`, `_ERROR_COLOR` uses non-bold `\x1b[31m`, making `Error:` values in `END` and `SYNTAX ERROR` boxes appear dim on dark terminal themes compared to bold tags and headers.
- In `format_safety_box` and `confirm_execution` (`src/ui.py`), when `findings` is non-empty, `-> Execute this block?` is wrapped in `_WARN_COLOR` (`\x1b[1;31m`), making the interactive prompt the exact same color as `Safety warnings`.
- Update `_ERROR_COLOR` in `src/ui.py` to bright bold red (`\x1b[1;91m`), keep `-> Execute this block?` distinct from `_WARN_COLOR` when safety warnings are present, and update ANSI styling unit tests in `tests/test_run_block.py`.

# 🎯 [NEXT] F42: Support marking sessions as completed (--done) with confirmation before reopening

- Persist session completion state (`"completed": true`, `"completed_at": "<YYYY-MM-DDTHH:MM:SSZ>"`, optional `"completed_note"`) in `<session>/meta.json` via helpers in `src/config.py` (`is_session_completed`, `set_session_completed`), preserving completion fields in `write_session_meta()` and resetting automatically when a session is recreated (`--start --force`).
- Add `run_block --done [session] [-m "<note>"]` in `src/cli.py` and `src/runner.py` (allowed both directly in terminal and inside the final block of a session) and display `[DONE]` status badges in `run_block --list` / `-l`.
- Check session completion before `BLOCK PLAN` across normal runs (`<session>/<step>`), `--fix`, and `--retry`:
  - Interactive TTY: display a `SESSION COMPLETED` confirmation box (`prompt_yes_no_box`, default `No`); on confirmation (`y`/`Enter`), clear the completion marker in `meta.json` and proceed to `BLOCK PLAN`, otherwise exit with `NOT RUN`.
  - Non-interactive / headless: auto-reopen and run when `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) is set; otherwise fail with `NOT RUN: session <session> is marked as completed (pass -y/--yes to reopen and run)`.
- Document session completion rules synchronously in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` (bundled via `src/bundles/run_block.bundle`), plus `src/header.py`, `README.md`, and unit tests in `tests/test_run_block.py`.

# ⚪ [NEW] F15: Move exported rules/bundles to agents/ and forbid trailing prose after closing fence

- Depends on: agents_bundle:F7, agents_bundle:F15
- Move `src/rules/` and `src/bundles/` to `agents/` using the unified logical bundle/rule layout once `agents_bundle` supports it, updating `AGENTS.md`, `README.md`, `build.py`, and tests.
- Tighten Rule 1 in `bash.md` and `pwsh.md` so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).

# ⚪ [NEW] F16: Prevent unintended interactive pagers during block execution

- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Hide `Bundle-Command` from TUI box headers in `src/ui.py` (`HIDDEN_SESSION_HEADER_KEYS`) to avoid noisy or multi-line `-p` headers in `START BUNDLE` / `BLOCK PLAN` / `END`, while preserving it in `meta.json` for `--info`.
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `meta.json`/`0`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers (including `Bundle-Command`) from `meta.json`/`0`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_run_block.py`.

# ⚪ [NEW] F34: Design workspace state fingerprinting and drift detection across steps

- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`BLOCK PLAN` / `END`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_run_block.py`.

# ⚪ [NEW] F35: Design tamper-evident hash chain and parent-step verification for session history

- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_run_block.py`.

# ⚪ [NEW] F36: Design pre-flight sandbox dry-run preview via temporary git worktree

- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `BLOCK PLAN` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_run_block.py`.

# ⚪ [NEW] F37: Design session execution policies and post-step revert guards

- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate declarative session-level execution constraints in `meta.json` / `.agents_bundle` (`src/bundle.py`, `src/config.py`), such as allowed write path globs, maximum modified file count, or network-access restrictions.
- Define enforcement and rollback semantics in `src/runner.py` and `src/safety.py` (pre-execution policy checks plus post-step diff verification with automatic revert on violation) and cover with `tests/test_run_block.py`.

# ⚪ [NEW] F38: Design explicit parent-step DAG lineage for session branches and retries

- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_run_block.py`.
