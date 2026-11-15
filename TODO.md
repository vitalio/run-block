# 🔵 [WIP] B2: Fix BLOCK PLAN analyzer for backslash continuations, external paths, quoted echo, and multi-dir Python AST

- Join shell line continuations (trailing `\`) outside heredoc and Python blocks before classifying commands and scanning risks.
- Ignore `>` inside single or double quotes when filtering non-redirected `echo`/`printf` statements.
- Recognize absolute external paths under `$HOME` (e.g. `/home/<user>/<repo>/...`) and `*_CWD=/path` environment prefixes in `_infer_op_dir` so commands operating on sibling repositories are grouped under their target directory.
- In `_analyze_python_ast` and `_emit_py_op`, track loop target variables (`for x in (...):`), surface `Path.unlink()` / `Path.rmdir()` deletions (including `fs-destructive` risk warnings), and group or summarize Python file operations across all target directories without silently dropping paths past 12 items.

# 🎯 [NEXT] B4: Add --fix diagnostics, non-overwriting fix slots, and max-attempts loop guard

- In `cmd_fix` (`src/runner.py`), format rich failure diagnostics when `RUN_FIX` raises an exception: include the failing line number and statement from `fix_code`, and for `AssertionError` on `assert <compare>` evaluate and print the actual left/right values (e.g. `at line 14: assert text.count(old_3) == 2 (actual: 0 == 2)`).
- Never overwrite prior `NOT RUN` fix outputs or fail with `fix step already exists`: allocate the next free fix slot (`<step>_1`, `<step>_2`, ...) on every `--fix` call, fall back to the latest existing script in the chain if a targeted fix step had no script (`NOT RUN`), and automatically try the latest fix revision vs base script when an anchor assertion fails.
- Enforce a hard loop guard (`RUN_BLOCK_MAX_FIX_ATTEMPTS`, default `2`) on consecutive failed `--fix` attempts per base step: append a `STOP --fix` directive when the limit is reached and reject further `--fix` calls on that step with an instruction to emit `<session>/<step+1>` instead.
- Update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` to document fix chaining and the rule to switch to a fresh `<session>/<step+1>` block after at most 2 failed `--fix` attempts.

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
