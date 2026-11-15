# 🔵 [WIP] F22: Replace box-drawing horizontal rules with plain [TITLE] section headers

- Replace box-drawing horizontal rules (`── <TITLE> ───...` and bottom `───...`) in `src/ui.py` with plain bracketed section headers (`[<TITLE>]`) and no trailing bottom rule so TUI sections never wrap or misalign when the terminal is resized.
- Simplify interactive prompt redraws in `prompt_yes_no_box`, `confirm_execution`, and `offer_clipboard_copy` in `src/ui.py` to update the prompt line in place without redrawing a bottom separator line.
- Update `AGENTS.md` and TUI formatting assertions in `tests/test_run_block.py` to match the plain `[<TITLE>]` section format.

# 🎯 [NEXT] F24: Remove blank lines between directory groups in BLOCK PLAN Operations

- Remove blank separator lines between directory groups inside `Operations:` in `src/ui.py` so grouped directory entries render compactly without vertical gaps.
- Update `BLOCK PLAN` formatting assertions in `tests/test_run_block.py` to verify compact directory group rendering.

# 🎯 [NEXT] F23: Format session bundle Date header in UTC (YYYY-MM-DD HH:MM UTC)

- Format the `Date:` header in `src/bundle.py` using UTC (`datetime.now(timezone.utc)` or `now.astimezone(timezone.utc)`) formatted as `YYYY-MM-DD HH:MM UTC` to match bundle rules.
- Update `tests/test_run_block.py` to verify the `YYYY-MM-DD HH:MM UTC` format in both `<session>/0` bundle headers and session initialization summary output.

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
