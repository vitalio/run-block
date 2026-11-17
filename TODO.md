# 🎯 [NEXT] F60: Unify [python] operation tree expansion in BLOCK PLAN

- Update `_emit_py_op()` in `src/safety.py` so `[python]` operations expand into nested child items (`├─` / `└─`) consistently whenever a Python block touches multiple files or combines reads and writes (`total_paths > 1`), regardless of whether those files live in different subdirectories (`len(dir_buckets) > 1`) or in the same directory / repository root (such as `build.py, run_block`), keeping the single-line summary only for trivial 0–1 file Python blocks.
- Ensure `_group_operations_for_display()` in `src/ui.py` preserves `├─` / `└─` tree markers for expanded `[python]` child `[write]` / `[read]` entries even when all operations are in the repository root (`dir == ""`).
- Acceptance criteria: multi-file `[python]` blocks in the same directory or root render with `├─` / `└─` child `[write]` / `[read]` rows matching cross-directory `[python]` blocks; single-file `[python]` blocks remain compact; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F59: Redraw active TUI box in place on terminal resize (SIGWINCH)

- Monitor terminal window resize events (`SIGWINCH` via a self-pipe registered in `select()`) while waiting for user input in `read_clipboard_key()` and `read_confirm_key()` in `src/ui.py`, debouncing rapid resize events (~25ms) and restoring the previous `SIGWINCH` handler cleanly on exit.
- When terminal width (`_hr_width()`) changes during `offer_clipboard_copy()`, `confirm_execution()`, or `prompt_yes_no_box()` in `src/ui.py`, recalculate the visual row count of the previously rendered box under the new width (`_box_rows_above_prompt()`), erase the old box in place, and re-render the active box (`START BUNDLE`, `BLOCK PLAN`, `END`, or confirmation dialog) for the new width with the cursor restored at the prompt.
- Acceptance criteria: shrinking or widening a POSIX TTY while an interactive TUI prompt is waiting redraws the active box cleanly in place without broken `│ ` borders or duplicate lines, and subsequent `e(dit)` redraws remain aligned; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F58: Wrap long lines inside all TUI boxes while preserving hanging indents

- Enforce terminal-width wrapping (`_hr_width() - 2`) inside `_render_block()` in `src/ui.py` for all rendered TUI boxes (`START BUNDLE`, `BLOCK PLAN`, `END`, `NOT RUN`, `SYNTAX ERROR`, `MISSING PREVIOUS STEP`, `STEP ALREADY EXISTS`, and `prompt_yes_no_box`), so no content or prompt line exceeds the terminal width and breaks the left `│ ` border.
- Preserve hanging indentation on wrapped lines: align continuation lines under the value column for `Key:   value` rows, preserve leading list/tree indentation (`  `, `    `, `├─ `, `└─ `) on already-indented items without double-wrapping lines that already fit, and clamp `_extract_last_error_line()` in `src/ui.py` to the available box content width.
- Acceptance criteria: on narrow terminals (40–70 columns), long `Workdir:`, `Output:`, `Error:`, `Stats:`, `Steps:`, headers, and prompt lines wrap cleanly with `│ ` on every visual row and aligned continuation indents across all TUI box types; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F57: Add a(ppend) prompt editor action in START BUNDLE — *Commit backlog task for START BUNDLE prompt append*

- Add an `a(ppend)` action to the `START BUNDLE` prompt in `src/ui.py` (`-> Copy to clipboard? [Enter/a(ppend)/e(dit)/Esc]:`), recognizing `a`/`A` (and `append` in line-input mode) without affecting `END` or conflicting with `e(dit)`, `i(nfo)`, or `d(etails)`.
- On `a(ppend)`, open an empty temporary `.md` file in the configured editor (`resolve_editor_command()` in `src/ui.py`), remove the temporary file on exit, and abort cleanly without modifying `<session>/0` or creating `<session>/0.orig` when the entered text is empty or whitespace-only.
- Before the first non-empty append, preserve the original bundle in `<session>/0.orig` via `_write_orig_backup_once()`, then append the prompt text to `<session>/0` in `src/ui.py` / `src/bundle.py` (appending into the trailing `===== Prompt =====` section when already present so repeated `a(ppend)` calls do not duplicate the header, or creating `===== Prompt =====` at the end otherwise).
- Refresh bundle metadata (`refresh_bundle_meta()`), recalculate line/byte/token `Stats:` with the `(edited)` marker, and redraw `START BUNDLE` in place so pressing `Enter` copies the updated bundle to the clipboard.
- Acceptance criteria: `a(ppend)` opens an empty temp file and appends non-empty prompt text into `===== Prompt =====` in `<session>/0`; empty input leaves `<session>/0` and `<session>/0.orig` untouched; `0.orig` is saved once and `Stats:` updates with `(edited)`; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F56: Align operation progress lines, update status colors, and collapse silent steps

- Remove the 2-space leading indentation on step completion lines in `_ProgressLineFilter._format_step_done()` (`src/runner.py`) so `✓` and `✗` (plus ASCII `+` and `x`) align at column 0 directly beneath `▸` and `>`.
- Update `_ProgressLineFilter` ANSI styling in `src/runner.py`: render start banners (`▸`) and successful completion lines (`✓`) in neutral gray (`\x1b[90m`), and failed completion lines (`✗`) in red (`\x1b[31m`).
- Track in `_ProgressLineFilter` (`src/runner.py`) whether any `out` text was emitted while a step was active: when a step finishes without output on a TTY, overwrite the start banner line in place (`\033[1A\r\033[2K`) with a single-line summary `✓ [N/M] [tag] desc (dur)` (truncated to `_hr_width()`); when output was emitted, keep the `▸` header above the output and print `✓ [N/M] (dur)` or `✗ [N/M] (dur)` below at column 0.
- Acceptance criteria: silent steps collapse into a single column-0 line with duration on TTY; steps with output keep `▸` above and `✓`/`✗` at column 0 below; colors use gray for normal progress and red for failures; `README.md` and unit tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F54: Remove Steps from END box and add hybrid i(nfo) metadata viewer across TUI blocks

- Remove the `Steps: 1. [tag] ...` summary line from the main `END` box in `build_box_body_lines()` (`src/ui.py`), keeping `END` focused on `Block`, `Workdir`, active `Sandbox`, `Exit`/`Error`/`Fix` on failure, `Output`, and `Stats`.
- Add an interactive `i(nfo)` action across all interactive TUI prompts (`START BUNDLE`, `BLOCK PLAN`, `END`, and confirmation dialogs such as `NOT RUN`, `SYNTAX ERROR`, `STEP ALREADY EXISTS`, `SESSION COMPLETED`) in `src/ui.py` and `src/runner.py`:
  - Update prompt hints to include `i(nfo)` without conflicting with existing hotkeys (`[Enter/e(dit)/i(nfo)/Esc]:` on `START BUNDLE` and `END`, `[Y/n/e(dit)/i(nfo)]:` / `[y/n/e(dit)/i(nfo)]:` on `BLOCK PLAN`).
  - Pressing `i` opens a styled alternate-screen TUI info panel showing unfiltered headers (including `Sandbox: off` and all `meta.json` headers), artifact paths and edit backups (`0.orig`, `block.orig.*`, `out.orig`), line/byte/token counts, per-operation execution timings with percentage shares and `(failed)` markers from `<session>/<step>/meta.json` (`src/config.py`), and the original pre-execution `BLOCK PLAN` analysis (`analyze_script()` on `block.orig.*` when edited, else `block.*`).
  - Support keyboard scrolling (`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn`), returning cleanly to the active block prompt on `q`/`Esc`/`Enter`/`i`, and opening the plain-text report in the configured viewer/editor (`resolve_editor_command()`) when pressing `v` (`v(iew)`).
- Acceptance criteria: `END` box omits `Steps:`; pressing `i` in `START BUNDLE`, `BLOCK PLAN`, `END`, and confirmation boxes displays complete headers, stats, operation timings, and original plan in the TUI info screen; pressing `v` inside `i(nfo)` opens the report in the external viewer/editor; closing returns cleanly to the prompt; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] D2: Design nested run_block contract (IN_RUN_BLOCK=1) for session initialization and subcommand guards

- Design candidate for `role=design` (coordinates with `F42` and `F48`).
- Problem: when a block executes `<cmd> | run_block` inside an active step (e.g., `todo_md F21 | agents_bundle role=work | run_block` inside `s53/1`), `IN_RUN_BLOCK=1` disables clipboard copy and prints the inner `START BUNDLE` box inside the outer step's `[s53/1] START ... [s53/1] END` output, leaving outer wrappers around the new bundle and lacking an explicit contract for nested `run_block` invocations.
- Define the behavior matrix when `IN_RUN_BLOCK=1` (and optional `RUN_BLOCK_PARENT_SESSION` / `RUN_BLOCK_PARENT_STEP` env metadata):
  1. Subcommand guards: allow read-only inspection (`--list`, `--show`, `--info`, `--bundle-plan`) and completing the current session (`--done`), while blocking recursive step execution (`<session>/<step>`, `--fix`, `--retry`) unless explicitly overridden.
  2. Nested session initialization (`<cmd> | run_block` / `--start`): specify console framing, clipboard handoff policy (copying the spawned `<session>/0` bundle vs suppressing outer step clipboard copy), and `parent_session` / `spawned_sessions` linkage in `<session>/meta.json`.
  3. Headless / machine-readable (`--json` in `F48`) interaction when a step spawns a child session.
- Target files for downstream implementation: `src/bundle.py`, `src/runner.py`, `src/config.py`, `src/cli.py`, `src/ui.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, `tests/test_run_block.py`.

- Concrete reproduction scenario: running a nested session initializer inside an active step (`todo_md <ID> | agents_bundle role=execute | run_block`) prints the inner `START BUNDLE` box (`<child>/0`) inside the outer `[sN/k] START ... [sN/k] END` block output, skips copying `<child>/0` to the clipboard because `IN_RUN_BLOCK=1`, and then triggers the outer `END` box's `-> Copy to clipboard?` prompt for the outer step log (with `[sN/k]` wrappers) instead of copying the clean `<child>/0` bundle and suppressing the outer clipboard prompt.

# 🎯 [NEXT] D1: Design session lifecycle states, step outcome labels, and run_block -l display

- Design candidate for `role=design` (coordinates with `F42` `--done` session completion and `F20` session inspection CLI).
- Problem: `cmd_list()` and `_step_status()` in `src/runner.py` parse the trailing `[sN/k] END` output marker of the last script in `_iter_session_scripts(sdir)` and render `last: sN/k (END)`, conflating individual step completion with overall session completion and obscuring whether a session is still active or finished.
- Define clear separation between:
  1. Step execution outcome (`ok`, `exit <rc>`, `not-run`, `syntax-error`, `aborted`, `saved`) derived from structured step metadata or output markers without overloading `END`.
  2. Session lifecycle state (`active` / `bundle-only` / `done` via `<session>/meta.json` `completed` from `F42`) and next actionable step (`Next-Block: sN/<k>`).
  3. Consistent `run_block -l` / `--list` and `--info` formatting across summary rows and recent-block listings (including fix-step ordering and optional `Task` / `Workdir` context).
- Target files for downstream implementation: `src/runner.py`, `src/config.py`, `src/ui.py`, `src/cli.py`, `src/header.py`, `README.md`, `tests/test_run_block.py`.

# 🎯 [NEXT] F42: Support marking sessions as completed (--done) with confirmation before reopening

- Persist session completion state (`"completed": true`, `"completed_at": "<YYYY-MM-DDTHH:MM:SSZ>"`, optional `"completed_note"`) in `<session>/meta.json` via helpers in `src/config.py` (`is_session_completed`, `set_session_completed`), preserving completion fields in `write_session_meta()` and resetting automatically when a session is recreated (`--start --force`).
- Add `run_block --done [session] [-m "<note>"]` in `src/cli.py` and `src/runner.py` (allowed both directly in terminal and inside the final block of a session) and display `[DONE]` status badges in `run_block --list` / `-l`.
- Check session completion before `BLOCK PLAN` across normal runs (`<session>/<step>`), `--fix`, and `--retry`:
  - Interactive TTY: display a `SESSION COMPLETED` confirmation box (`prompt_yes_no_box`, default `No`); on confirmation (`y`/`Enter`), clear the completion marker in `meta.json` and proceed to `BLOCK PLAN`, otherwise exit with `NOT RUN`.
  - Non-interactive / headless: auto-reopen and run when `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) is set; otherwise fail with `NOT RUN: session <session> is marked as completed (pass -y/--yes to reopen and run)`.
- Document session completion rules synchronously in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` (bundled via `src/bundles/run_block.bundle`), plus `src/header.py`, `README.md`, and unit tests in `tests/test_run_block.py`.

# 🎯 [NEXT] F55: Hide Bundle-* transport headers from TUI boxes and clamp long Title headers

- Depends on: F46
- Ensure `Bundle-*` transport headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) are excluded from TUI boxes (`START BUNDLE`, `BLOCK PLAN`, `END`, and confirmation dialogs) while remaining available in `meta.json`, `--info`, and the `i(nfo)` screen (`src/bundle_plan.py`, `src/config.py`, `src/ui.py`).
- Truncate overly long exposed header values (such as `Title:`) with an ellipsis (`…`) in `format_session_header_lines` (`src/ui.py`) so long task titles stay single-line without wrapping or overflowing box width.
- Sync `README.md` and unit tests in `tests/test_run_block.py`.

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

# ⚪ [NEW] B8: Preserve stdout/stderr interleaving order in captured out after separate stderr capture

- Since the separate stderr capture, `src/runner.py` reads stdout and stderr via two descriptors on two reader threads (`_iter_child_streams`), so the order of lines in `step_dir / "out"` follows read timing instead of write order; previously the shared PTY descriptor kept the exact write order in interactive mode.
- Impact on the model: a traceback or diagnostic may be separated from the command that produced it, and `__RB_STEP__` progress markers (stdout) may drift relative to stderr lines of the same step, which can mislead error attribution in long blocks with interleaved output.
- Reproduce first with a unit test that interleaves `echo` and `echo >&2` in a loop and compares the order in `out` with the write order; then pick an approach (for example keep one shared descriptor for `out` and obtain `err` separately, such as a per-command stderr tee in the instrumented script, or accept and document the ordering limits).
- After the approach is decided, document the `err` file and the ordering guarantees in `README.md` (step directory contents: `out`, `err`, `error`, `aborted`) and keep `AGENTS.md` in sync in the same commit.

# ⚪ [NEW] F46: Implement Bundle Input Protocol header filtering and fragment marker parser

- Define `src/bundle_plan.py` and integrate with `src/bundle.py` and `src/config.py` to implement the generator-agnostic Bundle Input Protocol.
- Treat `Bundle-*` preamble headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) as transport metadata stored in `<session>/meta.json` only, and forward `stdin` headers into `<session>/0` per `Bundle-Expose` / `Bundle-Hide` without overriding `Session`, `Next-Block`, `Workdir`, `Sandbox`, or `Date`.
- When `Bundle-Boundary: <nonce>` is present, parse `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->` markers, strip them cleanly from `<session>/0`, and fall back to `===== ... =====` section splitting when no boundary is present.
- Compute per-part lines, bytes, GPT/Claude token counts, and percentage share, persisting structured `bundle_plan` metadata (without raw text bodies) in `<session>/meta.json`, with unit tests in `tests/test_run_block.py`.

# ⚪ [NEW] F47: Add bundle diagnostics, START BUNDLE details view, and --bundle-plan CLI

- Depends on: F46
- Extend `src/bundle_plan.py`, `src/ui.py`, `src/cli.py`, and `src/header.py` to surface bundle analysis and diagnostics.
- Detect and report bundle warnings: non-zero command `rc` or empty command output, oversized fragments or total token budget exceedance, and accidental secrets in non-rule content by reusing `src/safety.py` secret detection without duplicating patterns.
- Render a compact grouped summary (grouping parts by `kind` + `group`) plus warnings inside `START BUNDLE`, and add a `d(etails)` action in the `START BUNDLE` prompt to inspect the full per-part breakdown.
- Add `run_block --bundle-plan [<session>] [--json] [--full]` (reading `stdin` when no session is given, or `meta.json` / `<session>/0` for an existing session), and sync `README.md`, `src/rules/blocks/*.md`, and `tests/test_run_block.py`.

# ⚪ [NEW] F48: Design machine-readable runner contract (--json step output and plan/execute handshake)

- Design candidate for `role=design` to let an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Evaluate structured `--json` execution output for `<session>/<step>` (status: `ok`/`syntax_error`/`not_run`/`completed`, `exit_code`, safety findings, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` non-TTY handshake, and env sanitization so client LLM API keys do not leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).
