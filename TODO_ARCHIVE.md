# ✅ [DONE] B10: Forward all session headers into END and fix session dir resolution — *2026-11-18, Fixed _resolve_session_dir(), passed sdir into offer_clipboard_copy(), added regression tests, and rebuilt run_block.*

- Fix `_resolve_session_dir()` in `src/ui.py` so a step directory containing step metadata (`<session>/<step>/meta.json`) never masks the parent session directory (`<session>/0` and `<session>/meta.json`).
- Pass `sdir` explicitly from `src/runner.py` to `offer_clipboard_copy()` (and forward it to `format_clipboard_box()` / `build_box_body_lines()` in `src/ui.py`) so `END`, `NOT RUN`, and `SYNTAX ERROR` boxes always receive the session directory directly.
- Acceptance criteria: `END` (as well as `NOT RUN` and `SYNTAX ERROR`) renders all exposed session headers (`Workdir`, `Role`, `Task`, `Title`, etc.) identically to `PLAN` even after `<session>/<step>/meta.json` has been written; add regression tests in `tests/test_run_block.py` covering `END`, `NOT RUN`, and `SYNTAX ERROR` with real `<session>/<step>/meta.json` files, update `README.md` if needed, and rebuild `run_block` via `build.py`.

# ✅ [DONE] F60: Unify [python] operation tree expansion in BLOCK PLAN — *2026-11-18, Unified [python] operation tree expansion in BLOCK PLAN*

- Update `_emit_py_op()` in `src/safety.py` so `[python]` operations expand into nested child items (`├─` / `└─`) consistently whenever a Python block touches multiple files or combines reads and writes (`total_paths > 1`), regardless of whether those files live in different subdirectories (`len(dir_buckets) > 1`) or in the same directory / repository root (such as `build.py, run_block`), keeping the single-line summary only for trivial 0–1 file Python blocks.
- Ensure `_group_operations_for_display()` in `src/ui.py` preserves `├─` / `└─` tree markers for expanded `[python]` child `[write]` / `[read]` entries even when all operations are in the repository root (`dir == ""`).
- Acceptance criteria: multi-file `[python]` blocks in the same directory or root render with `├─` / `└─` child `[write]` / `[read]` rows matching cross-directory `[python]` blocks; single-file `[python]` blocks remain compact; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F55: Hide Bundle-* transport headers from TUI boxes and clamp long Title headers — *2026-11-18, Exclude Bundle-* transport headers from TUI boxes and clamp long exposed headers*

- Depends on: F46
- Ensure `Bundle-*` transport headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) are excluded from TUI boxes (`START BUNDLE`, `BLOCK PLAN`, `END`, and confirmation dialogs) while remaining available in `meta.json`, `--info`, and the `i(nfo)` screen (`src/bundle_plan.py`, `src/config.py`, `src/ui.py`).
- Truncate overly long exposed header values (such as `Title:`) with an ellipsis (`…`) in `format_session_header_lines` (`src/ui.py`) so long task titles stay single-line without wrapping or overflowing box width.
- Sync `README.md` and unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F47: Add bundle diagnostics, START BUNDLE details view, and --bundle-plan CLI — *2026-11-18*

- Depends on: F46
- Extend `src/bundle_plan.py`, `src/ui.py`, `src/cli.py`, and `src/header.py` to surface bundle analysis and diagnostics.
- Detect and report bundle warnings: non-zero command `rc` or empty command output, oversized fragments or total token budget exceedance, and accidental secrets in non-rule content by reusing `src/safety.py` secret detection without duplicating patterns.
- Render a compact grouped summary (grouping parts by `kind` + `group`) plus warnings inside `START BUNDLE`, and add a `d(etails)` action in the `START BUNDLE` prompt to inspect the full per-part breakdown.
- Add `run_block --bundle-plan [<session>] [--json] [--full]` (reading `stdin` when no session is given, or `meta.json` / `<session>/0` for an existing session), and sync `README.md`, `src/rules/blocks/*.md`, and `tests/test_run_block.py`.

# ✅ [DONE] F46: Implement Bundle Input Protocol header filtering and fragment marker parser — *2026-11-18*

- Define `src/bundle_plan.py` and integrate with `src/bundle.py` and `src/config.py` to implement the generator-agnostic Bundle Input Protocol.
- Treat `Bundle-*` preamble headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) as transport metadata stored in `<session>/meta.json` only, and forward `stdin` headers into `<session>/0` per `Bundle-Expose` / `Bundle-Hide` without overriding `Session`, `Next-Block`, `Workdir`, `Sandbox`, or `Date`.
- When `Bundle-Boundary: <nonce>` is present, parse `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->` markers, strip them cleanly from `<session>/0`, and fall back to `===== ... =====` section splitting when no boundary is present.
- Compute per-part lines, bytes, GPT/Claude token counts, and percentage share, persisting structured `bundle_plan` metadata (without raw text bodies) in `<session>/meta.json`, with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F53: Hide Sandbox: off in TUI boxes and show Sandbox only when enabled — *2026-11-18, Omit Sandbox: off in TUI boxes while keeping it in session bundles and --sandbox status*

- Omit the `Sandbox:` header line in `format_session_header_lines()` (`src/ui.py`) when the normalized sandbox mode is `off` (or empty), so `START BUNDLE`, `BLOCK PLAN`, `END`, `NOT RUN`, and `SYNTAX ERROR` boxes only display `Sandbox: <mode>` when sandboxing is enabled (`strict`, `nonet`, or a custom wrapper).
- Preserve `Sandbox: off` in `<session>/0` bundle headers (`src/bundle.py`), explicit `run_block --sandbox` status output (`src/runner.py`), and the full `i(nfo)` metadata view.
- Acceptance criteria: `Sandbox: off` is hidden across standard TUI boxes; active sandbox modes (`strict`, `nonet`, custom) still render with full details; `<session>/0` and `run_block --sandbox` remain unchanged; offline unit tests in `tests/test_run_block.py` cover both `off` and active sandbox rendering.

# ✅ [DONE] F43: Brighten Error line, title and border colors, and keep confirmation prompt distinct from Safety warnings — *2026-11-17, Brighten Error, title, and border colors and keep confirmation prompt distinct from safety warnings*

- In `src/ui.py`, `_ERROR_COLOR` uses non-bold `\x1b[31m`, so `Error:` values in `END` and `SYNTAX ERROR` boxes look dim on dark terminal themes compared to bold tags and headers.
- `_TITLE_COLORS` (`START BUNDLE`, `BLOCK PLAN`, `END`, `SYNTAX ERROR`, `NOT RUN`, `MISSING PREVIOUS STEP`, `STEP ALREADY EXISTS`) use the regular-intensity bold palette (`1;36`, `1;33`, `1;32`, `1;31`), and the fallback for unknown titles in `src/ui.py` is `\x1b[1;36m`. Make them brighter (`1;96`, `1;93`, `1;92`, `1;91`).
- `_BORDER_COLOR` (`\x1b[2;36m`) is dim, and the box builder derives border color from the title color by replacing the bold prefix with `2;` (`"\x1b[2;" + t_col[4:]`). Change the derivation so the border keeps the brightness of the title color instead of being forced to dim, and make the default `_BORDER_COLOR` non-dim.
- In `format_safety_box` and `confirm_execution` (`src/ui.py`), when `findings` is non-empty, `-> Execute this block?` is wrapped in `_WARN_COLOR` (`\x1b[1;31m`), which is the same color as the `Safety warnings` header. Keep the prompt visually distinct from `_WARN_COLOR`.
- Update `_ERROR_COLOR` to bright bold red (`\x1b[1;91m`).
- Update the ANSI styling unit tests in `tests/test_run_block.py` to match the new codes, including a check that the border of a bold title is not dim.
- Out of scope: `_KEY_COLOR` (metadata keys) and `_TAG_COLORS` (operation tags).

# ✅ [DONE] F49: Record and display execution duration for blocks and numbered operations — *2026-11-17, Record block/operation durations and nest AST sub-items in BLOCK PLAN*

- Measure wall-clock block execution duration (`time.monotonic()`) around child process execution (`subprocess.Popen` to `wait()`, excluding `BLOCK PLAN` confirmation wait) in `src/runner.py`.
- Include formatted duration in the trailing `[<session>/<step>] END` marker written to `out` (e.g. `[s1/1] END (3.4s)` or `[s1/1] END (exit 1, 3.4s)`, keeping `_step_status()` parsing compatible) and append duration to `Stats:` in the `END` box (`src/ui.py`).
- Track per-operation elapsed durations in `_ProgressLineFilter` (`src/runner.py`) via `__RB_STEP__:N` markers, showing step timing in live progress output and surfacing per-operation timings (plus step `duration_ms` metadata) for `END` diagnostics and `run_block -l` / `--info` (`D1`, `F20`).
- Visually distinguish unnumbered AST-expanded sub-items (`[read]`, `[write]`) under a numbered parent step (such as `1. [python]`) in `BLOCK PLAN` (`src/ui.py`, `src/safety.py`) with a subordinate marker or nested indent so sub-operations clearly belong to their parent step.
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `src/config.py`, `README.md`, `tests/test_run_block.py`.

# ✅ [DONE] F52: Support e(dit) on END output (and 0.orig on START BUNDLE) with original backup and stats recalculation — *2026-11-17*

- Replace `v(iew)` with `e(dit)` in the `END` clipboard prompt (`src/ui.py`, keeping `v` as a compatibility alias) and preserve the unmodified output as `<session>/<step>/out.orig` on the first edit without overwriting it on subsequent edits; also preserve `<session>/0.orig` on the first `e(dit)` in `START BUNDLE`.
- Recompute `stats_line()` (lines, bytes, and Claude/GPT/Gemini token counts), re-extract `Error:` when `rc != 0`, refresh the clipboard copy target (`resolve_clipboard_target`), and redraw the full `END` box in place with an explicit `(edited)` indicator (`src/ui.py`, `src/runner.py`).
- Surface `(edited)` markers in `run_block --show` when `block.orig.*`, `out.orig`, or `0.orig` exists (`src/runner.py`), sync `README.md` and `src/header.py`, and add unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F51: Support e(dit) on BLOCK PLAN script with original backup and plan/token recalculation — *2026-11-17*

- Replace `v(iew)` with `e(dit)` in the `BLOCK PLAN` confirmation prompt (`src/ui.py`, keeping `v` as a compatibility alias) and preserve the unmodified script as `<session>/<step>/block.orig.sh` (or `.ps1`) on the first edit without overwriting it on subsequent edits.
- Re-validate script syntax after editing (`bash -n` / PowerShell parser in `src/runner.py`), showing `SYNTAX ERROR` and aborting execution if the edited script fails syntax validation.
- Recompute `summarize_script_actions()` (operations list and `Script:` line/byte/token statistics), `scan_script_risks()` warnings, and default confirmation prompt (`src/ui.py`, `src/runner.py`), and redraw the full `BLOCK PLAN` box in place with an explicit `(edited)` indicator (and note original backup in `--show`).
- Sync `README.md` and `src/header.py` help text and add unit tests in `tests/test_run_block.py` covering `e(dit)` in `BLOCK PLAN`, `block.orig.*` preservation, statistics/risks recalculation, and post-edit syntax error handling.

# ✅ [DONE] B9: Fix false-positive [exec] and [remote-exec] on quoted variable assignments and --exclude-dir=eval flags — *2026-11-17, Fix false-positive [exec] and [remote-exec] on quoted variable assignments and --exclude-dir=eval flags*

- Update variable assignment matching in `src/safety.py` (`VAR_ASSIGN_RE` / assignment helper) to recognize `[export|local|readonly] VAR=...` when the value is a single- or double-quoted string containing spaces or a parenthesized array literal without trailing commands or command substitutions (`$(...)` / backticks).
- Skip pure variable assignments in `summarize_script_actions()` so lines like `EX='--exclude-dir=bumps ... --exclude-dir=eval ...'` are recorded in `sh_vars` instead of emitting a false-positive `[exec]` operation.
- Tighten `remote-exec` (`\beval\s+`) and command-level risk matching in `src/safety.py` (`RISK_RULES` and `scan_script_risks()`) so `eval` only triggers in command position (not after `=`, `-`, or `/` such as `--exclude-dir=eval`) and single-quoted string literals without shell execution do not trigger command risk rules while still scanning for `unicode-spoof` and `secrets-exposure`.
- Add unit tests in `tests/test_run_block.py` covering multiline quoted `EX='--exclude-dir=eval ...'` assignments, `--exclude-dir=eval` arguments in `grep`, and true-positive `eval` invocations (`eval "$cmd"`, `FOO=1; eval "$cmd"`).

# ✅ [DONE] F50: Recalculate and redraw bundle statistics after e(dit) in START BUNDLE — *2026-11-17, Recalculate bundle statistics and redraw full START BUNDLE box after edit*

- Recompute `stats_line(out_path)` (line count, byte size, and estimated token range) in `offer_clipboard_copy()` (`src/ui.py`) immediately after `open_script_in_editor(out_path, tty_r, tty_w)` returns from `e(dit)` on `START BUNDLE`.
- Re-render the full `START BUNDLE` box in place on the TTY (moving the cursor back to the top of the previous box, clearing stale lines, and recalculating box border width and prompt cursor offset) instead of only redrawing the bottom prompt and border lines.
- Refresh any cached bundle metadata / `bundle_plan` statistics in `<session>/meta.json` (`src/bundle.py`, `src/bundle_plan.py`) when `<session>/0` changes during `e(dit)` so `START BUNDLE` and `--bundle-plan` stay in sync.
- Add unit tests in `tests/test_run_block.py` covering `e(dit)` in `START BUNDLE` with a stub editor that modifies `<session>/0` and asserting updated `Stats:` output and box alignment.

# ✅ [DONE] F45: Prefer Workdir from the piped bundle header over the current directory — *2026-11-17, Prefer existing Workdir from stdin preamble when RUN_BLOCK_CWD is auto; synced docs, help, rules, and tests.*

- First add a test in `tests/test_run_block.py` showing whether
  `format_start_bundle` in `src/bundle.py` currently ignores a `Workdir`
  header from `stdin_headers`; it takes the directory from `get_work_dir()`.
- If ignored, use the `Workdir` value from the stdin preamble (when the
  directory exists) as `wdir` and write it into `<session>/0`, before the
  `RUN_BLOCK_CWD` auto resolution in `src/config.py`.
- Keep `src/header.py`, `README.md`, and the bundled rules in
  `src/rules/blocks/` in sync.

# ✅ [DONE] F44: Connect python-stdlib and python-annotations rules in .agents_bundle — *2026-11-16, Connected stack/python-stdlib and stack/python-annotations rules in .agents_bundle*

- In `.agents_bundle`, remove `py_min=3.9` from `stack/python-cli` and add
  `rule vitalio/agents-rules:stack/python-stdlib` and
  `rule vitalio/agents-rules:stack/python-annotations py_min=3.9`, after the
  python-cli split is released in agents-rules and the package cache is
  refreshed.
- Keep `from __future__ import annotations` only in `build.py` and
  `src/header.py`; do not add it to modules under `src/`.
- Run `python3 -m unittest discover -s tests`; if the progress line shows
  stderr noise, capture it with `contextlib.redirect_stderr` in `tests/`.

# ✅ [DONE] B7: Capture child stderr separately to extract accurate Error lines in END box — *2026-11-16*

- In `src/runner.py`, block execution currently merges child `stdout` and `stderr` into a single descriptor (`stdout=slave_fd, stderr=slave_fd` in PTY mode and `stdout=PIPE, stderr=STDOUT` in pipe mode), so `src/ui.py` (`_extract_last_error_line`) only sees the combined `step_dir / "out"` file and picks its last non-empty line when `rc != 0`.
- When a command writes an error to `stderr` mid-run and then continues printing normal output to `stdout` before exiting non-zero (for example `head -n 25 dev/*` printing `head: error reading 'dev/__pycache__': Is a directory` to `stderr` followed by file contents on `stdout`), `END` displays the last line of `stdout` in `Error:` instead of the diagnostic from `stderr`.
- Read child `stderr` via a separate descriptor alongside `stdout` in `src/runner.py`, continuing to stream both to the terminal and into `step_dir / "out"` while also saving `stderr` to `step_dir / "err"`, and update `_extract_last_error_line` in `src/ui.py` to prefer the last non-empty line from `step_dir / "err"` (falling back to `step_dir / "out"` only when `stderr` is empty), with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] B6: Track multiline quoted strings in BLOCK PLAN analyzer and step instrumentation — *2026-11-16, Track multiline single, ANSI-C, and double-quoted strings in _iter_logical_lines and instrument_script_for_progress*

- When a shell script contains a multiline single-quoted (`'...'`) or double-quoted (`"..."`) argument (such as `todo_md edit ... -b $'...\n...'` or `todo_md add ... -b "..."`), `src/safety.py` (`summarize_script_actions` and `_instrument_bash_script`) splits on physical newlines without tracking open quote state.
- As a result, `BLOCK PLAN` reports each physical line inside the quoted literal as a separate `[exec]` operation, and live step instrumentation injects `printf '%s\n' '__RB_STEP__:N'` directly inside the user's string literal, corrupting written text.
- Track multiline single- and double-quote state (respecting backslash escapes inside double quotes) alongside heredoc tracking in `src/safety.py`, and add regression tests in `tests/test_run_block.py`.

# ✅ [DONE] F40: Assign distinct non-overlapping ANSI tag colors to all BLOCK PLAN operation types — *2026-11-16*

- Update `_TAG_COLORS`, `_colorize_operation_lines()`, and `_colorize_python_op_rest()` in `src/ui.py` so every operation tag in `BLOCK PLAN` uses a distinct ANSI color with zero overlap: `[read]` and `reads:` in bright blue (`\x1b[1;94m`), `[write]` and `writes:` in bold yellow (`\x1b[1;33m`), `[exec]` in bold magenta (`\x1b[1;35m`), `[git]` in bold cyan (`\x1b[1;36m`), and `[python]` in bold green (`\x1b[1;32m`).
- Color only the `[read]` tag and `reads:` keyword while keeping read file paths in neutral terminal foreground text, matching `[exec]`, `[git]`, and `[python]`.
- Update unit tests in `tests/test_run_block.py` and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F41: Highlight Exit and Error values and dim Fix, Output, and Stats in status boxes — *2026-11-16, Highlight non-zero Exit in bold red, Error in red, and dim Fix/Output/Stats in status boxes*

- Update `_colorize_kv_line()` in `src/ui.py` so non-zero `Exit:` codes render in bold red (`\x1b[1;31m`) and `Error:` descriptions render in red (`\x1b[31m`) across `END`, `SYNTAX ERROR`, and `NOT RUN` boxes.
- Render secondary metadata lines (`Fix:`, `Output:`, and `Stats:`) in dim gray (`_KEY_COLOR`, `\x1b[2m`) so failure diagnostics stand out clearly.
- Add unit tests in `tests/test_run_block.py` and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F39: Omit redundant Esc label in yes/no confirmation prompt suffixes — *2026-11-16*

- Remove `/Esc` from `_safety_prompt_suffix()` (`[Y/n/v(iew)]:` / `[y/n/v(iew)]:`) and `_build_prompt_yes_no_suffix()` (`[y/N]:`, `[y/N/s(cript)]:`, etc.) in `src/ui.py` where `n` already represents declining/canceling.
- Keep `/Esc` in `_clipboard_prompt_line()` (`[Enter/e(dit)/Esc]:` and `[Enter/v(iew)/Esc]:`) where no `n` option is shown, and preserve `Esc` (`\x1b`) key handling across all interactive TUI prompts.
- Update `README.md`, `tests/test_run_block.py`, and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F30: Display plan step numbers in BLOCK PLAN and live progress markers during execution — *2026-11-16, Numbered BLOCK PLAN operations and added live progress markers during interactive execution*

- Depends on: F29
- Number top-level operations in `format_safety_box()` (`src/ui.py`) so `BLOCK PLAN` items match live execution step numbers.
- Execute a temporary instrumented script copy in `run_script()` (`src/runner.py`) during interactive runs (with syntax validation, automatic fallback to the original script, temp-file cleanup, and opt-out via `RUN_BLOCK_PROGRESS=0` in `src/config.py`), while filtering marker lines out of `<session>/<step>/out` so saved output stays consistent with the unmodified script.
- Document `RUN_BLOCK_PROGRESS` in `src/header.py` and `README.md`, and add end-to-end execution tests in `tests/test_run_block.py`.

# ✅ [DONE] F31: Render read operations in neutral foreground instead of dim gray in BLOCK PLAN — *2026-11-16*

- Update `_colorize_operation_lines()` and `_colorize_python_op_rest()` in `src/ui.py` so `[read]` operation tags, continuation lines, and `reads:` clauses render in neutral foreground color (normal white/default terminal text) instead of dim gray (`_KEY_COLOR`).
- Add or update unit tests in `tests/test_run_block.py` verifying `[read]` ANSI styling in `BLOCK PLAN` output.

# ✅ [DONE] F32: Unify Esc cancel prompts across interactive TUI boxes — *2026-11-16, Unify Esc cancel prompts across interactive TUI boxes, README, and unit tests*

- Update interactive prompt suffixes in `src/ui.py` (`_build_prompt_yes_no_suffix()`, `format_safety_box()`, `confirm_execution()`) so all TUI confirmation boxes (`STEP ALREADY EXISTS`, `SESSION ALREADY EXISTS`, `MISSING PREVIOUS STEP`, `CLEAN SESSIONS`, `BLOCK PLAN`, `END`) consistently advertise `Esc` for canceling/exiting alongside existing key bindings.
- Update `README.md` and unit tests in `tests/test_run_block.py` to cover the unified prompt labels and `Esc` handling across TUI boxes.

# ✅ [DONE] F29: Track operation start lines and build instrumented script copies for plan progress — *2026-11-16*

- Record the 1-based starting line number (`line`) for each top-level operation in `summarize_script_actions()` inside `src/safety.py`, keeping nested Python AST sub-entries grouped under their parent Python step without separate top-level step numbers.
- Add a helper in `src/safety.py` to generate an instrumented in-memory script copy (`bash` and `pwsh`) that emits identifiable step-marker lines before each top-level operation while safely skipping heredocs, multiline `python -c` blocks, line continuations, and compound control-flow bodies (`if`/`for`/`while`/`case`).
- Cover line-number mapping and instrumented script generation (including syntax preservation and edge cases) with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F33: Replace v(iew) with e(dit) in START BUNDLE to edit session bundle in default editor — *2026-11-16*

- Update `format_clipboard_box()` and `offer_clipboard_copy()` in `src/ui.py` so `START BUNDLE` renders `-> Copy to clipboard? [Enter/e(dit)/Esc]:` while `END`, `NOT RUN`, and `SYNTAX ERROR` keep `[Enter/v(iew)/Esc]:`.
- Update `read_clipboard_key()` and `offer_clipboard_copy()` in `src/ui.py` to handle `e`/`E` for `START BUNDLE`, opening `<session>/0` via `open_script_in_editor()` (`RUN_BLOCK_EDITOR`, `VISUAL`, `EDITOR`, or default editor) and returning to the `START BUNDLE` prompt after the editor exits so `Enter` copies the updated `<session>/0` to the clipboard and `Esc` skips copying.
- Update `README.md` if clipboard prompt shortcuts are documented, and add unit tests in `tests/test_run_block.py` covering the `START BUNDLE` `e(dit)` prompt, key handling, and editor return flow.

# ✅ [DONE] F28: Parse stdin header preamble into session metadata and exclude from session 0 bundle — *2026-11-16*

- Parse optional leading `Key: Value` header lines (separated from body by a blank line) from `stdin` during `format_start_bundle()` and `cmd_start()` in `src/bundle.py` and `src/config.py`.
- Persist parsed `stdin` headers in session metadata (`<session>/meta.json`) instead of writing them into `<session>/0`, keeping `<session>/0` limited to `run_block`'s own headers (`Session`, `Next-Block`, `Workdir`, `Sandbox`, `Date`) and the prompt body.
- Read session display headers in `src/ui.py` (`format_session_header_lines`) and `src/runner.py` from session metadata (with fallback to `<session>/0` for existing sessions) and remove `agents_bundle`-specific keys (`bundle-command`, `chat-lang`) from `HIDDEN_SESSION_HEADER_KEYS`.
- Document the `stdin` header/body separation contract in `README.md` (user-facing) and `AGENTS.md` (architectural invariant), and cover with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F27: Improve BLOCK PLAN and TUI block visual hierarchy and colors — *2026-11-16, Removed brackets around block titles, matched dim border colors to titles, and added BLOCK PLAN color hierarchy for Workdir, Sandbox, Operations, and Safety warnings.*

- Update `src/ui.py` to remove `[...]` brackets around block titles in `_format_top_rule` (e.g. `╭─ BLOCK PLAN ───`).
- Match block border color (`╭─`, `│`, `╰─`) to the block title color in dim ANSI style, keeping plain output unchanged when `NO_COLOR` or non-TTY.
- Highlight `Safety warnings (N):`, risk category tags, and the `-> Execute this block?` prompt when safety warnings are present.
- Color-code `Operations:` in `BLOCK PLAN`: dim read-only / `reads:` parts, and highlight `writes:` targets and mutating / `[git]` tags.
- Dim `Workdir` in `BLOCK PLAN` when it matches `os.getcwd()` and highlight it when it differs; dim routine header fields such as `Sandbox: off`.
- Update and add unit tests in `tests/test_run_block.py` for the updated title format, border colors, warning/operation highlighting, and `Workdir` emphasis.

# ✅ [DONE] F23: Format session bundle Date header in UTC (YYYY-MM-DD HH:MM UTC) — *2026-11-16*

- Format the `Date:` header in `src/bundle.py` using UTC (`datetime.now(timezone.utc)` or `now.astimezone(timezone.utc)`) formatted as `YYYY-MM-DD HH:MM UTC` to match bundle rules.
- Update `tests/test_run_block.py` to verify the `YYYY-MM-DD HH:MM UTC` format in both `<session>/0` bundle headers and session initialization summary output.

# ✅ [DONE] F26: Refine TUI block borders, key-value alignment, and TTY status colors — *2026-11-16*

- Update `src/ui.py` (`_format_top_rule`, `_format_bottom_rule`, `_prefix_block_line`, `_render_block`, and key-value formatting in `format_session_header_lines` and `build_box_body_lines`) to replace `#` borders with thin open-right box-drawing borders (`╭─ [TITLE] ───`, `│ `, `╰───`) of compact width, with an ASCII fallback (`+-`, `| `) when `stdout` is not UTF-8.
- Align contiguous `Key: value` metadata lines in columns (`Session:`, `Next-Block:`, `Workdir:`, `Sandbox:`, `Role:`, `Task:`, `Bundle:`, `Output:`, `Stats:`, etc.) for cleaner scanning.
- Add TTY-aware ANSI colors (disabled when not a TTY or `NO_COLOR` is set): dimmed/tinted borders, bold status-colored `[TITLE]` (`START BUNDLE`, `BLOCK PLAN`, `END`, `SYNTAX ERROR`, `NOT RUN`), and dimmed keys.
- Update `tests/test_run_block.py` to verify the new border style, ASCII fallback, key-value alignment, and `NO_COLOR`/non-TTY behavior.

# ✅ [DONE] F24: Remove blank lines between directory groups in BLOCK PLAN Operations — *2026-11-16*

- Remove blank separator lines between directory groups inside `Operations:` in `src/ui.py` so grouped directory entries render compactly without vertical gaps.
- Update `BLOCK PLAN` formatting assertions in `tests/test_run_block.py` to verify compact directory group rendering.

# ✅ [DONE] F25: Add # prefix and compact # borders around TUI blocks — *2026-11-16, Rendered all TUI blocks with compact # borders and # line prefixes*

- Render all TUI section blocks (`BLOCK PLAN`, `START BUNDLE`, `END`, `NOT RUN`, `SYNTAX ERROR`, and prompt boxes) in `src/ui.py` using a shared helper with compact `#` top and bottom borders (e.g. `min(term_cols, 48)`, padded to fit the title).
- Format the top border with the embedded `[TITLE]` (e.g. `#### [TITLE] ####...`) and close every block with a matching `#` rule of the same width.
- Prefix every content and prompt line with `# ` (and render blank separator lines as `#` without trailing whitespace), accounting for the 2-character prefix when wrapping text.
- Keep interactive prompt lines (`-> ...?`) inside the block immediately above the bottom `#` border, adjusting `cursor_col_offset` and cursor positioning/redraws accordingly.
- Update TUI box assertions in `tests/test_run_block.py` and keep `AGENTS.md` / `README.md` descriptions in sync if needed.

# ✅ [DONE] F22: Replace box-drawing horizontal rules with plain [TITLE] section headers — *2026-11-15, Replaced box-drawing horizontal rules with plain [TITLE] section headers and simplified in-place prompt redraws.*

- Replace box-drawing horizontal rules (`── <TITLE> ───...` and bottom `───...`) in `src/ui.py` with plain bracketed section headers (`[<TITLE>]`) and no trailing bottom rule so TUI sections never wrap or misalign when the terminal is resized.
- Simplify interactive prompt redraws in `prompt_yes_no_box`, `confirm_execution`, and `offer_clipboard_copy` in `src/ui.py` to update the prompt line in place without redrawing a bottom separator line.
- Update `AGENTS.md` and TUI formatting assertions in `tests/test_run_block.py` to match the plain `[<TITLE>]` section format.

# ✅ [DONE] F17: Limit --fix to small targeted patches rather than full-block replacements — *2026-11-15*

- Update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` (plus `README.md` if applicable) to specify that `run_block --fix` should only be used for small, targeted patches; if a fix is comparable in size to the original block or requires rewriting multiple sections, emit a fresh `<session>/<step+1>` block directly instead.
- Bump `VERSION` (patch), rebuild `run_block` via `python3 build.py`, and update/verify tests in `tests/test_run_block.py`.

# ✅ [DONE] B3: Keep subproject working directory when initializing session from subdir — *2026-11-15, Keep subproject working directory when initializing session from subdir*

- In `src/config.py`, `get_work_dir()` currently falls back to `_git_toplevel_or_cwd()`, which climbs to `git rev-parse --show-toplevel` even when a session starts inside a self-contained subproject directory (e.g. `/home/vitaly/chrome/canary`) containing its own `.agents_bundle` or `AGENTS.md`.
- This creates a mismatch between `0` bundle outputs (collected in `pwd`) and subsequent `run_block` steps (executed in the monorepo root).
- Acceptance criteria:
  - In `src/config.py`, when `RUN_BLOCK_CWD=auto` and no session `Workdir` header exists yet, prefer the nearest directory (starting from `Path.cwd().resolve()` up to the Git toplevel) containing `.agents_bundle` or `AGENTS.md`, falling back to `git rev-parse --show-toplevel` and then `Path.cwd().resolve()`.
  - Keep `RUN_BLOCK_CWD=cwd`, explicit `RUN_BLOCK_CWD=/path`, and persisted `Workdir:` in `<session>/0` working unchanged.
  - Update `RUN_BLOCK_CWD` documentation in `README.md` and add unit tests in `tests/test_run_block.py` covering subproject session init, regular Git subdir init, and `RUN_BLOCK_CWD` overrides.

# ✅ [DONE] F11: Per-step directory layout and extensionless session/output artifacts — *2026-11-15, Implemented per-step directory layout (<session>/<step>/{block.sh|block.ps1,fix.py,out,error,aborted}) and extensionless <session>/0 bundle.*

- Store session context bundle at `<session>/0` (replacing `<session>/0.txt`) in `src/bundle.py`, `src/runner.py`, `src/config.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, and `README.md`.
- Store each executed step in its own directory `<session>/<step>/` (e.g. `s1/1/`, `s1/1_1/`) with `block.sh` or `block.ps1`, `out` (stdout/stderr), `error` (failed output), `aborted` (abort marker), and `fix.py` (for `--fix` steps, alongside the patched `block.sh`/`block.ps1`) in `src/runner.py` and `src/ui.py`.
- Remove legacy flat-file session support (`<step>.sh`, `<step>.txt`, `0.txt`) and update unit tests in `tests/test_run_block.py`, then rebuild `run_block` via `build.py`.

# ✅ [DONE] F21: Replace bordered TUI boxes with full-width horizontal rule separators — *2026-11-15, Replaced full-perimeter TUI box borders with full-width horizontal rule separators in v0.19.2*

Replace full-perimeter box-drawing borders (`┌─ ... ─┐`, `│ ... │`, `└─ ... ─┘`) in `src/ui.py` with terminal-width horizontal rule separators (`── <TITLE> ───...` and `───...`) so long lines (paths, errors, `--fix` reasons) wrap naturally without breaking box alignment.

- Update `format_safety_box`, `format_info_box`, `format_prompt_box`, `format_clipboard_box`, `prompt_yes_no_box`, `confirm_execution`, and `offer_clipboard_copy` in `src/ui.py` to render top/bottom horizontal rules sized to terminal width (`shutil.get_terminal_size`) without side `│` borders or right-padding.
- Use `\r\033[K` when rewriting interactive prompt lines and final status lines (`✓ Running ...`, `✓ Copied ...`, `✗ Aborted ...`) so shorter status text clears previous prompt text cleanly.
- Update `resolve_clipboard_target` in `src/ui.py`, unit tests in `tests/test_run_block.py`, and TUI documentation in `AGENTS.md` and `README.md`.

# ✅ [DONE] B5: Resolve Python <stdin> traceback lines on failure and enrich END/NOT RUN TUI cards — *2026-11-15, Resolve Python <stdin> traceback lines on failure and enrich END/NOT RUN TUI cards*

- When a block exits with non-zero status and its output contains `File "<stdin>", line <N>` from an embedded `python3` heredoc in `src/runner.py`, extract line `<N>` from the heredoc body and append `[<label>] <stdin> line <N>: <source_line>` to the output before `[<label>] END (exit <rc>)` so the failing statement is visible in clipboard output.
- In `END` TUI boxes when `rc != 0` (`src/runner.py`, `src/ui.py`), display `Error: <last_error_line>` from the script output and a `Fix:` status line showing either `run_block --fix <label> (<used>/<max> failed attempts)` or the `STOP --fix` guard state.
- In `NOT RUN` TUI boxes (`not_run_exit` and `cmd_fix` in `src/runner.py`), show `Target: <session>/<target> -> <label>` for `--fix` steps and render any `[<label>] STOP --fix: ...` continuation line as a clean `Guard: ...` line without a duplicate `[<label>]` prefix inside the box (while keeping the full lines in the `.txt` clipboard file).
- Cover `<stdin>` traceback line resolution and the updated `END` / `NOT RUN` box fields with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F19: Store sessions in persistent state directory (~/.local/state/run_block) and add size/prune controls — *2026-11-15, Store sessions in XDG/LocalAppData state directory and add size/prune controls*

- Change default session storage in `src/config.py` from `/tmp/run_block` to `$XDG_STATE_HOME/run_block` (fallback `~/.local/state/run_block` on Linux/macOS) and `%LOCALAPPDATA%\\run_block\\state` (fallback `~/AppData/Local/run_block/state`) on Windows while keeping `RUN_BLOCK_DIR` as highest-priority override.
- Ensure sandbox rules in `src/safety.py` and `src/bundle.py` treat the persistent `BASE_DIR` appropriately without conflating it with `/tmp`.
- Display per-session and total storage sizes in `src/runner.py` (`--list` / `--clean`), extend `--clean` to support `--older-than <days>`, `--max-size <MB>`, and deleting specific session names, and emit a warning when total state size exceeds `RUN_BLOCK_MAX_STATE_MB` (default `100`).
- Update usage text, agent block rules, README, and unit tests in `src/header.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, and `tests/test_run_block.py`.

# ✅ [DONE] B2: Fix BLOCK PLAN analyzer for backslash continuations, external paths, quoted echo, and multi-dir Python AST — *2026-11-15, Handled shell line continuations, quoted redirects in echo/printf, external paths and *_CWD prefixes, and multi-directory Python AST loop/deletion grouping*

- Join shell line continuations (trailing `\`) outside heredoc and Python blocks before classifying commands and scanning risks.
- Ignore `>` inside single or double quotes when filtering non-redirected `echo`/`printf` statements.
- Recognize absolute external paths under `$HOME` (e.g. `/home/<user>/<repo>/...`) and `*_CWD=/path` environment prefixes in `_infer_op_dir` so commands operating on sibling repositories are grouped under their target directory.
- In `_analyze_python_ast` and `_emit_py_op`, track loop target variables (`for x in (...):`), surface `Path.unlink()` / `Path.rmdir()` deletions (including `fs-destructive` risk warnings), and group or summarize Python file operations across all target directories without silently dropping paths past 12 items.

# ✅ [DONE] F18: Reassemble split run_block payloads caused by inner triple backticks on paste/stdin — *2026-11-15, Implemented _reassemble_split_payload in src/runner.py and added unit tests*

- When a model emits literal triple backticks inside a `run_block` heredoc (for example when editing `README.md` code fences), chat Markdown renderers split the single block into multiple fenced snippets separated by ```text` or ```python` fences, leaving the outer heredoc unclosed until the final `RUN_BLOCK` terminator.
- Detect an unclosed `run_block ... <<'RUN_BLOCK'` (or `RUN_FIX`) header in pasted/piped input before the closing terminator and reconstruct the original payload by stripping intermediate Markdown fence lines that split the block, or emit a clear diagnostic if the terminator is missing.

# ✅ [DONE] B4: Add --fix diagnostics, non-overwriting fix slots, and max-attempts loop guard — *2026-11-15, Implemented rich --fix exception diagnostics, non-overwriting fix slot allocation with chain fallback, RUN_BLOCK_MAX_FIX_ATTEMPTS loop guard, and updated bash/pwsh block rules.*

- In `cmd_fix` (`src/runner.py`), format rich failure diagnostics when `RUN_FIX` raises an exception: include the failing line number and statement from `fix_code`, and for `AssertionError` on `assert <compare>` evaluate and print the actual left/right values (e.g. `at line 14: assert text.count(old_3) == 2 (actual: 0 == 2)`).
- Never overwrite prior `NOT RUN` fix outputs or fail with `fix step already exists`: allocate the next free fix slot (`<step>_1`, `<step>_2`, ...) on every `--fix` call, fall back to the latest existing script in the chain if a targeted fix step had no script (`NOT RUN`), and automatically try the latest fix revision vs base script when an anchor assertion fails.
- Enforce a hard loop guard (`RUN_BLOCK_MAX_FIX_ATTEMPTS`, default `2`) on consecutive failed `--fix` attempts per base step: append a `STOP --fix` directive when the limit is reached and reject further `--fix` calls on that step with an instruction to emit `<session>/<step+1>` instead.
- Update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` to document fix chaining and the rule to switch to a fresh `<session>/<step+1>` block after at most 2 failed `--fix` attempts.

# ✅ [DONE] F1: Native PowerShell (`pwsh`) block execution mode on Windows — *15f24a8*

Allow `shell = pwsh` in `~/.config/run_block/config` so Windows users in PowerShell 7
can execute native PowerShell blocks in addition to Bash blocks.

# ✅ [DONE] F2: Custom user-defined safety rules in config — *15f24a8*

Allow adding custom regex patterns or overriding risk categories in
`~/.config/run_block/config`.

# ✅ [DONE] F3: Session cleanup command (`--clean`) — *15f24a8*

Add `run_block --clean [--keep N | --all]` to prune old session directories in
`/tmp/run_block`.

# ✅ [DONE] F4: Smart budget-aware repository map (--tree) — *15f24a8*

Add `run_block --tree` (usable in `.run_block.start` as `$ run_block --tree`) to generate a compact, token-budgeted repository file tree (respecting `.gitignore`, showing line counts for source files, and collapsing large directories into summaries instead of dumping thousands of paths).

# ✅ [DONE] F5: Modular agent rules knowledge base (--rules) — *f618c65*

Add 'run_block --rules [topic ... | all | --list]' with built-in topics (workflow, semver, python-cli) and user rules in ~/.config/run_block/rules/*.md.

# ✅ [DONE] F6: Modularize run_block source into src/ with build.py single-file bundler — *83863e7*

Split monolithic run_block into src/ Python modules and src/templates/*.md + src/rules/*.md files, compiled into standalone ./run_block by build.py.

# ✅ [DONE] F8: Extract context bundler and engineering rules catalog into standalone agents_bundle project — *99bc5e1*

Move --start, .agents_bundle spec, --tree, and universal engineering rules/presets into a separate zero-dependency 'agents_bundle' CLI with zero hardcoded coupling to run_block (connected via user config and 'run_block --bundle').

# ✅ [DONE] F7: Plugin architecture (pre/post hooks, LLM block analyzer, and headless stdout mode) — *412de9c*

Add extensible plugin hooks for pre-execution block analysis (including LLM-based script review and auto-approval of safe blocks) and post-execution output handling (clipboard box vs raw stdout protocol mode).

- Unify command classification ('[git]', '[write]', '[read]', '[exec]', '[python]') and safety risk scanning ('[git-push]', '[net-write]', '[git-destructive]', etc.) into the pre-execution analyzer plugin interface.

# ✅ [DONE] F9: Audit run_block and todo_md architecture against unix-philosophy.md — *412de9c*

Review CLI flags, stdin/stdout/stderr separation, and composability of run_block and todo_md against core/unix-philosophy.md.

# ✅ [DONE] F12: Standardize minimalist TUI box titles and Key: Value body fields; suppress duplicate boxes on interactive decline — *2026-11-14, Release v0.16.3*

# ✅ [DONE] F10: Prompt injection defenses, safe --fix AST validator, and session Sandbox contract — *2026-11-14*

- Validate `--fix` Python patch AST before `exec()` (allow only pure text/regex manipulation; reject imports, dunder access, and unsafe builtins).
- Protect `<session>/0.txt` integrity across block execution (in-memory snapshot + revert on tampering; read-only `BASE_DIR` inside OS sandboxes).
- Support `Sandbox:` header in `<session>/0.txt`, `RUN_BLOCK_SANDBOX` env setting, and `--sandbox` CLI command/flag (`off`, `strict`, `nonet`) with cross-platform secret env scrubbing, Linux `bwrap`, and macOS `sandbox-exec`.
- Enhance `src/safety.py` scanner (Python AST `subprocess`/`urllib`/`socket`/`eval`, paths outside `Workdir`, `.git/hooks`, and hidden Bidi/Zero-Width Unicode spoofing) and set `default_yes=False` when `RUN_BLOCK_APPROVE_CMD` exits `2`.

# ✅ [DONE] B1: Parse multiline python3 -c in BLOCK PLAN and prevent RUN_BLOCK closing-fence concatenation — *2026-11-14, fd3d533*

- In src/safety.py (summarize_script_actions and scan_script_risks), detect single-line and multiline python3 -c '...' / "..." invocations, analyze their body via _analyze_python_ast, and report them as a [python] operation instead of per-line [exec] items.
- Investigate and harden src/rules/blocks/bash.md and runner handling against LLM omitting the newline between RUN_BLOCK and the closing Markdown fence (which causes CommonMark to leave the code fence open).

# ✅ [DONE] F13: Add src/bundles/run_block.bundle and remove --agents CLI flag — *2026-11-14*

- Add `src/bundles/run_block.bundle` selecting `vitalio/run_block:blocks/bash` or `vitalio/run_block:blocks/pwsh` by OS.
- Remove hardcoded `v{version:}` placeholder from `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` headers.
- Remove `src/agents.py` and the `--agents` / `--agents-md` CLI flag from `src/header.py`, `src/cli.py`, `build.py`, `README.md`, `AGENTS.md`, `.agents_bundle`, and `tests/test_run_block.py`.

# ✅ [DONE] F14: Unify TUI box titles and render session headers (Block/Session, Workdir, Sandbox, Role, Task) inside every box — *2026-11-15, Unify TUI box titles and render session headers in every box*

- Strip the '<session>/<step> · ' prefix from TUI box top borders so box titles show only the block kind ('START BUNDLE', 'BLOCK PLAN', 'END', 'NOT RUN', 'SYNTAX ERROR', 'STEP ALREADY EXISTS', 'MISSING PREVIOUS STEP', 'SESSION ALREADY EXISTS').
- Parse both run_block and stdin bundle header blocks in '0.txt' (up to the first '=====' section) so session variables ('Role', 'Task', and custom headers) are available across all steps.
- Render a consistent session header section at the top of every session/step box ('Session'/'Next-Block' or 'Block: <session>/<step>', 'Workdir', 'Sandbox', plus session variables like 'Role' and 'Task' excluding noisy 'Date'/'Bundle-Command'/'Chat-Lang'), followed by a blank line and the box-specific details ('Bundle', 'Script', 'Operations', 'Output', 'Stats', etc.).
