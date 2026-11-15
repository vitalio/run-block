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

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Depends on: F19
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `0.txt`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers from `0.txt`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_run_block.py`.
