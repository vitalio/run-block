# 🔵 [WIP] F28: Parse stdin header preamble into session metadata and exclude from session 0 bundle

- Parse optional leading `Key: Value` header lines (separated from body by a blank line) from `stdin` during `format_start_bundle()` and `cmd_start()` in `src/bundle.py` and `src/config.py`.
- Persist parsed `stdin` headers in session metadata (`<session>/meta.json`) instead of writing them into `<session>/0`, keeping `<session>/0` limited to `run_block`'s own headers (`Session`, `Next-Block`, `Workdir`, `Sandbox`, `Date`) and the prompt body.
- Read session display headers in `src/ui.py` (`format_session_header_lines`) and `src/runner.py` from session metadata (with fallback to `<session>/0` for existing sessions) and remove `agents_bundle`-specific keys (`bundle-command`, `chat-lang`) from `HIDDEN_SESSION_HEADER_KEYS`.
- Document the `stdin` header/body separation contract in `README.md` (user-facing) and `AGENTS.md` (architectural invariant), and cover with unit tests in `tests/test_run_block.py`.

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
