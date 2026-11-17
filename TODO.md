# 🎯 [NEXT] B9: Fix false-positive [exec] and [remote-exec] on quoted variable assignments and --exclude-dir=eval flags

- Update variable assignment matching in `src/safety.py` (`VAR_ASSIGN_RE` / assignment helper) to recognize `[export|local|readonly] VAR=...` when the value is a single- or double-quoted string containing spaces or a parenthesized array literal without trailing commands or command substitutions (`$(...)` / backticks).
- Skip pure variable assignments in `summarize_script_actions()` so lines like `EX='--exclude-dir=bumps ... --exclude-dir=eval ...'` are recorded in `sh_vars` instead of emitting a false-positive `[exec]` operation.
- Tighten `remote-exec` (`\beval\s+`) and command-level risk matching in `src/safety.py` (`RISK_RULES` and `scan_script_risks()`) so `eval` only triggers in command position (not after `=`, `-`, or `/` such as `--exclude-dir=eval`) and single-quoted string literals without shell execution do not trigger command risk rules while still scanning for `unicode-spoof` and `secrets-exposure`.
- Add unit tests in `tests/test_run_block.py` covering multiline quoted `EX='--exclude-dir=eval ...'` assignments, `--exclude-dir=eval` arguments in `grep`, and true-positive `eval` invocations (`eval "$cmd"`, `FOO=1; eval "$cmd"`).

# 🎯 [NEXT] F49: Record and display execution duration for blocks and numbered operations

- Measure wall-clock block execution duration (`time.monotonic()`) around child process execution (`subprocess.Popen` to `wait()`, excluding `BLOCK PLAN` confirmation wait) in `src/runner.py`.
- Include formatted duration in the trailing `[<session>/<step>] END` marker written to `out` (e.g. `[s1/1] END (3.4s)` or `[s1/1] END (exit 1, 3.4s)`, keeping `_step_status()` parsing compatible) and append duration to `Stats:` in the `END` box (`src/ui.py`).
- Track per-operation elapsed durations in `_ProgressLineFilter` (`src/runner.py`) via `__RB_STEP__:N` markers, showing step timing in live progress output and surfacing per-operation timings (plus step `duration_ms` metadata) for `END` diagnostics and `run_block -l` / `--info` (`D1`, `F20`).
- Visually distinguish unnumbered AST-expanded sub-items (`[read]`, `[write]`) under a numbered parent step (such as `1. [python]`) in `BLOCK PLAN` (`src/ui.py`, `src/safety.py`) with a subordinate marker or nested indent so sub-operations clearly belong to their parent step.
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `src/config.py`, `README.md`, `tests/test_run_block.py`.

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

# 🎯 [NEXT] F43: Brighten Error line, title and border colors, and keep confirmation prompt distinct from Safety warnings

- In `src/ui.py`, `_ERROR_COLOR` uses non-bold `\x1b[31m`, so `Error:` values in `END` and `SYNTAX ERROR` boxes look dim on dark terminal themes compared to bold tags and headers.
- `_TITLE_COLORS` (`START BUNDLE`, `BLOCK PLAN`, `END`, `SYNTAX ERROR`, `NOT RUN`, `MISSING PREVIOUS STEP`, `STEP ALREADY EXISTS`) use the regular-intensity bold palette (`1;36`, `1;33`, `1;32`, `1;31`), and the fallback for unknown titles in `src/ui.py` is `\x1b[1;36m`. Make them brighter (`1;96`, `1;93`, `1;92`, `1;91`).
- `_BORDER_COLOR` (`\x1b[2;36m`) is dim, and the box builder derives border color from the title color by replacing the bold prefix with `2;` (`"\x1b[2;" + t_col[4:]`). Change the derivation so the border keeps the brightness of the title color instead of being forced to dim, and make the default `_BORDER_COLOR` non-dim.
- In `format_safety_box` and `confirm_execution` (`src/ui.py`), when `findings` is non-empty, `-> Execute this block?` is wrapped in `_WARN_COLOR` (`\x1b[1;31m`), which is the same color as the `Safety warnings` header. Keep the prompt visually distinct from `_WARN_COLOR`.
- Update `_ERROR_COLOR` to bright bold red (`\x1b[1;91m`).
- Update the ANSI styling unit tests in `tests/test_run_block.py` to match the new codes, including a check that the border of a bold title is not dim.
- Out of scope: `_KEY_COLOR` (metadata keys) and `_TAG_COLORS` (operation tags).

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

# ⚪ [NEW] F50: Recalculate and redraw bundle statistics after e(dit) in START BUNDLE

- Recompute `stats_line(out_path)` (line count, byte size, and estimated token range) in `offer_clipboard_copy()` (`src/ui.py`) immediately after `open_script_in_editor(out_path, tty_r, tty_w)` returns from `e(dit)` on `START BUNDLE`.
- Re-render the full `START BUNDLE` box in place on the TTY (moving the cursor back to the top of the previous box, clearing stale lines, and recalculating box border width and prompt cursor offset) instead of only redrawing the bottom prompt and border lines.
- Refresh any cached bundle metadata / `bundle_plan` statistics in `<session>/meta.json` (`src/bundle.py`, `src/bundle_plan.py`) when `<session>/0` changes during `e(dit)` so `START BUNDLE` and `--bundle-plan` stay in sync.
- Add unit tests in `tests/test_run_block.py` covering `e(dit)` in `START BUNDLE` with a stub editor that modifies `<session>/0` and asserting updated `Stats:` output and box alignment.
