# 🎯 [NEXT] F33: Replace v(iew) with e(dit) in START BUNDLE to edit session bundle in default editor

- Update `format_clipboard_box()` and `offer_clipboard_copy()` in `src/ui.py` so `START BUNDLE` renders `-> Copy to clipboard? [Enter/e(dit)/Esc]:` while `END`, `NOT RUN`, and `SYNTAX ERROR` keep `[Enter/v(iew)/Esc]:`.
- Update `read_clipboard_key()` and `offer_clipboard_copy()` in `src/ui.py` to handle `e`/`E` for `START BUNDLE`, opening `<session>/0` via `open_script_in_editor()` (`RUN_BLOCK_EDITOR`, `VISUAL`, `EDITOR`, or default editor) and returning to the `START BUNDLE` prompt after the editor exits so `Enter` copies the updated `<session>/0` to the clipboard and `Esc` skips copying.
- Update `README.md` if clipboard prompt shortcuts are documented, and add unit tests in `tests/test_run_block.py` covering the `START BUNDLE` `e(dit)` prompt, key handling, and editor return flow.

# 🎯 [NEXT] F29: Track operation start lines and build instrumented script copies for plan progress

- Record the 1-based starting line number (`line`) for each top-level operation in `summarize_script_actions()` inside `src/safety.py`, keeping nested Python AST sub-entries grouped under their parent Python step without separate top-level step numbers.
- Add a helper in `src/safety.py` to generate an instrumented in-memory script copy (`bash` and `pwsh`) that emits identifiable step-marker lines before each top-level operation while safely skipping heredocs, multiline `python -c` blocks, line continuations, and compound control-flow bodies (`if`/`for`/`while`/`case`).
- Cover line-number mapping and instrumented script generation (including syntax preservation and edge cases) with unit tests in `tests/test_run_block.py`.

# ⚪ [NEW] F15: Move exported rules/bundles to agents/ and forbid trailing prose after closing fence

- Depends on: vitalio/agents_bundle#F7
- Move src/rules/ and src/bundles/ to agents/ once agents_bundle supports the root agents/ directory, updating AGENTS.md and tests.
- Tighten Rule 1 in bash.md and pwsh.md so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).

# ⚪ [NEW] F16: Prevent unintended interactive pagers during block execution

- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Depends on: F19
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `0.txt`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers from `0.txt`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_run_block.py`.

# ⚪ [NEW] F30: Display plan step numbers in BLOCK PLAN and live progress markers during execution

- Depends on: F29
- Number top-level operations in `format_safety_box()` (`src/ui.py`) so `BLOCK PLAN` items match live execution step numbers.
- Execute a temporary instrumented script copy in `run_script()` (`src/runner.py`) during interactive runs (with syntax validation, automatic fallback to the original script, temp-file cleanup, and opt-out via `RUN_BLOCK_PROGRESS=0` in `src/config.py`), while filtering marker lines out of `<session>/<step>/out` so saved output stays consistent with the unmodified script.
- Document `RUN_BLOCK_PROGRESS` in `src/header.py` and `README.md`, and add end-to-end execution tests in `tests/test_run_block.py`.

# ⚪ [NEW] F31: Render read operations in neutral foreground instead of dim gray in BLOCK PLAN

- Update `_colorize_operation_lines()` and `_colorize_python_op_rest()` in `src/ui.py` so `[read]` operation tags, continuation lines, and `reads:` clauses render in neutral foreground color (normal white/default terminal text) instead of dim gray (`_KEY_COLOR`).
- Add or update unit tests in `tests/test_run_block.py` verifying `[read]` ANSI styling in `BLOCK PLAN` output.

# ⚪ [NEW] F32: Unify Esc cancel prompts across interactive TUI boxes

- Update interactive prompt suffixes in `src/ui.py` (`_build_prompt_yes_no_suffix()`, `format_safety_box()`, `confirm_execution()`) so all TUI confirmation boxes (`STEP ALREADY EXISTS`, `SESSION ALREADY EXISTS`, `MISSING PREVIOUS STEP`, `CLEAN SESSIONS`, `BLOCK PLAN`, `END`) consistently advertise `Esc` for canceling/exiting alongside existing key bindings.
- Update `README.md` and unit tests in `tests/test_run_block.py` to cover the unified prompt labels and `Esc` handling across TUI boxes.
