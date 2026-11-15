# 🔵 [WIP] B2: Fix BLOCK PLAN analyzer for backslash continuations, external paths, quoted echo, and multi-dir Python AST

- Join shell line continuations (trailing `\`) outside heredoc and Python blocks before classifying commands and scanning risks.
- Ignore `>` inside single or double quotes when filtering non-redirected `echo`/`printf` statements.
- Recognize absolute external paths under `$HOME` (e.g. `/home/<user>/<repo>/...`) and `*_CWD=/path` environment prefixes in `_infer_op_dir` so commands operating on sibling repositories are grouped under their target directory.
- In `_analyze_python_ast` and `_emit_py_op`, track loop target variables (`for x in (...):`), surface `Path.unlink()` / `Path.rmdir()` deletions (including `fs-destructive` risk warnings), and group or summarize Python file operations across all target directories without silently dropping paths past 12 items.

# 🎯 [NEXT] F18: Reassemble split run_block payloads caused by inner triple backticks on paste/stdin

- When a model emits literal triple backticks inside a `run_block` heredoc (for example when editing `README.md` code fences), chat Markdown renderers split the single block into multiple fenced snippets separated by ```text` or ```python` fences, leaving the outer heredoc unclosed until the final `RUN_BLOCK` terminator.
- Detect an unclosed `run_block ... <<'RUN_BLOCK'` (or `RUN_FIX`) header in pasted/piped input before the closing terminator and reconstruct the original payload by stripping intermediate Markdown fence lines that split the block, or emit a clear diagnostic if the terminator is missing.

# 🎯 [NEXT] B5: Resolve Python <stdin> traceback lines on failure and enrich END/NOT RUN TUI cards

- When a block exits with non-zero status and its output contains `File "<stdin>", line <N>` from an embedded `python3` heredoc in `src/runner.py`, extract line `<N>` from the heredoc body and append `[<label>] <stdin> line <N>: <source_line>` to the output before `[<label>] END (exit <rc>)` so the failing statement is visible in clipboard output.
- In `END` TUI boxes when `rc != 0` (`src/runner.py`, `src/ui.py`), display `Error: <last_error_line>` from the script output and a `Fix:` status line showing either `run_block --fix <label> (<used>/<max> failed attempts)` or the `STOP --fix` guard state.
- In `NOT RUN` TUI boxes (`not_run_exit` and `cmd_fix` in `src/runner.py`), show `Target: <session>/<target> -> <label>` for `--fix` steps and render any `[<label>] STOP --fix: ...` continuation line as a clean `Guard: ...` line without a duplicate `[<label>]` prefix inside the box (while keeping the full lines in the `.txt` clipboard file).
- Cover `<stdin>` traceback line resolution and the updated `END` / `NOT RUN` box fields with unit tests in `tests/test_run_block.py`.

# 🎯 [NEXT] F11: Recursive step directory layout and intermediate sub-blocks (e.g. s28/8.1) — *Add B4 for --fix diagnostics and loop guard; scope F11 to recursive step directories*

- Store each step in its own directory (`<session>/<step>/block.sh`, `out.txt`) so every step (top-level, intermediate sub-step, or fix) shares a uniform recursive structure.
- Support intermediate sub-blocks after an executed step `<N>` before `<N+1>` (e.g. `s28/8.1` -> `s28/8/1/`, `s28/8.1.1` -> `s28/8/1/1/`) and nested fixes (`fix_1/`), so an already-emitted `<session>/<N+1>` block in chat remains valid without reprinting.

# ⚪ [NEW] B3: Keep subproject working directory when initializing session from subdir — *Use invocation directory (or .agents_bundle directory) instead of forcing git rev-parse --show-toplevel when starting a session in a subdirectory project*

- In `src/config.py`, resolving default `Workdir` via `git rev-parse --show-toplevel` jumps to the monorepo root (e.g. `/home/vitaly/chrome`) even when `agents_bundle | run_block` is invoked inside a self-contained subproject directory (`/home/vitaly/chrome/canary`) that has its own `.agents_bundle`, `AGENTS.md`, and `TODO.md`.
- This causes a mismatch between bundle command outputs in `0.txt` (which run in `pwd`) and subsequent `run_block` steps (which run in the top-level Git root).
- Keep the current working directory when it contains `.agents_bundle` / `AGENTS.md` (or preserve `pwd` at session init) instead of unconditionally climbing to `--show-toplevel`.

# ⚪ [NEW] F15: Move exported rules/bundles to agents/ and forbid trailing prose after closing fence

- Depends on: vitalio/agents_bundle#F7
- Move src/rules/ and src/bundles/ to agents/ once agents_bundle supports the root agents/ directory, updating AGENTS.md and tests.
- Tighten Rule 1 in bash.md and pwsh.md so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).

# ⚪ [NEW] F16: Prevent unintended interactive pagers during block execution

- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] F17: Limit --fix to small targeted patches rather than full-block replacements

- Update run_block rules/instructions to specify that run_block --fix should only be used for small, targeted patches; if a fix is comparable in size to the original block or requires rewriting multiple sections, emit a fresh <session>/<step+1> block directly instead.
