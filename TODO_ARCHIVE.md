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
