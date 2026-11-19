# run_block

**Safe, sequential terminal block execution protocol for AI coding agents.**

`run_block` is a zero-dependency Python 3 CLI that connects any chat LLM to your local
terminal without API keys or background daemons. It starts a rule-only session on bare TTY
invocation (`run_block`) or receives a session context bundle on `stdin`
(`<command> | run_block` -> `~/.local/state/run_block/<session>/0`) and executes numbered
Bash or PowerShell blocks (`<session>/1`, `<session>/2`, ...) with syntax validation, a
pre-execution `START STEP` safety scanner, PTY streaming, and one-keystroke clipboard copy
with Claude/GPT/Gemini token counts.

## Quick Installation

### Linux & macOS

```bash
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh
```

### Windows (PowerShell 7+)

```powershell
irm https://raw.githubusercontent.com/vitalio/run_block/main/install.ps1 | iex
```

## Starting a Session

Run bare `run_block` (or `run_block --start`) in an interactive TTY to initialize
a rule-only `~/.local/state/run_block/<session>/0` session with embedded
terminal block rules (`bash` or `pwsh`, selected from `RUN_BLOCK_SHELL` / OS)
and open `START SESSION`, or pipe any context bundle on `stdin` into `run_block` to
inject the terminal block rules into `===== Rules =====` (deduplicating against
existing `blocks/bash` / `blocks/pwsh` rule parts or `## Terminal blocks (`
headings, and wrapping unlabeled plain `stdin` text under `===== Prompt =====`)
and copy
`<session>/0` to your clipboard.
Optional leading `Key: Value` header lines on `stdin` (separated from the
body by a blank line) are parsed into `<session>/meta.json`. Exposed
non-transport headers (such as `Role:`, `Task:`, `Title:`) are displayed in
TUI headers (clamped to a single line with `…` when longer than the box
width), while `Bundle-*` transport headers (`Bundle-Command`, `Bundle-Boundary`,
`Bundle-Expose`, `Bundle-Hide`) stay in `<session>/meta.json` only (excluded
from `<session>/0` and TUI boxes), and
`Bundle-Expose` / `Bundle-Hide` control which remaining `stdin` headers are
forwarded into `<session>/0` alongside `run_block`'s own headers (`Session`,
`Next-Block`, `Workdir`, `Sandbox`, `Date`). When `Bundle-Boundary: <nonce>` is
present, `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->`
markers are parsed into per-part `bundle_plan` metrics (lines, chars, GPT/Claude
tokens, percentage share) in `<session>/meta.json` and stripped cleanly from
`<session>/0` (falling back to `===== ... =====` sections when no boundary is
provided). The inline `START SESSION` box stays compact (retaining core headers, `Bundle:`, dim
`Stats:`, and `Bundle warnings` when present, while full per-part tables stay
in `run_block --bundle-plan`); press `d` (or `i`) at the `START SESSION` prompt to
open an alternate-screen fullscreen `d(etails)` panel (`Up`/`Down`, `j`/`k`,
`PgUp`/`PgDn` to scroll, `Enter` to copy, `Esc`/`q`/`d`/`i` to return) without
leaving duplicate headers or stale lines in scrollback. All inline TUI boxes
(`START SESSION`, `START STEP`, `END STEP`, and confirmation dialogs) clamp overflowing sections
to the visible terminal height (`... +N more`) and reflow cleanly across both
width and height `SIGWINCH` resizes.
When `RUN_BLOCK_CWD` is `auto` and the `stdin` preamble provides an existing
`Workdir` directory, that path is preferred over the current directory or
Git root and written to `<session>/0`:

```bash
run_block
cat context.txt | run_block
run_block --start --session s1 < context.txt
```

## Running and Fixing Blocks

### 1. Running numbered blocks (`<session>/<step>`)

```bash
run_block s1/1 <<'RUN_BLOCK'
git status -sb
RUN_BLOCK
```

### 2. Inspecting the `START STEP` before execution

```bash
run_block s1/2 <<'RUN_BLOCK'
python3 -m unittest
RUN_BLOCK
```

Before running, `run_block` displays the `START STEP` (working directory, numbered
operations with nested AST-expanded sub-items for multi-file or read+write
Python blocks, and any safety warnings). Press
`Enter`/`y` to run, `n`/`Esc` to abort, or `e` (or `v`) to edit the script in your
terminal editor. The first edit preserves the original script as
`<session>/<step>/block.orig.sh` (or `.ps1`), recalculates operations, statistics, and
safety warnings in place, and re-validates syntax before execution. During execution,
`run_block` records wall-clock block duration (excluding confirmation prompts) and
per-operation elapsed timings in `<session>/<step>/meta.json`, `[<session>/<step>] END
(<duration>)`, `Stats:`, and live progress output (silent steps collapse in
place on a TTY into a single aligned `✓ [N/M] [tag] desc (dur)` line, while
steps with output keep the `▸` header above and align `✓`/`✗` at column 0
below). When a block targets a step number that already exists on disk,
`STEP ALREADY EXISTS` prompts to copy existing `out` (`[Y/n/r(enumber)/...]`) or
`r(enumber)` to the next free step (preserving existing outputs and recording a
renumber notice in `out`), while `MISSING PREVIOUS STEP` prompts to `r(enumber)` to
the first missing step (`[r(enumber)/n]`); use `--retry` to re-run an existing step.
Across all interactive TUI confirmation prompts (`START STEP`, `END STEP`,
`STEP ALREADY EXISTS`, `MISSING PREVIOUS STEP`, and `CLEAN SESSIONS`), `[Y/n]` /
`[y/N]` brackets highlight the `Enter` default in uppercase and `Esc` consistently
cancels or exits without proceeding. In the `END STEP` clipboard prompt (and
`START SESSION`), press `e` (or `v`) to edit `<session>/<step>/out` (preserving
`<session>/<step>/out.orig`) or `<session>/0` (preserving `<session>/0.orig`),
recalculating line/char/token statistics, `Error:` lines, and clipboard targets
in place. While any interactive TUI box (`START SESSION`, `START STEP`, `END STEP`, or
confirmation prompt) is waiting for input on a POSIX TTY, resizing the
terminal window (`SIGWINCH`) automatically erases and redraws the active box
in place to match the new width. Long lines inside TUI boxes (paths, outputs,
errors, stats, steps, headers, and prompts) wrap cleanly to the terminal width
with `│ ` borders and aligned hanging indents.

### 3. Patching a failed block (`--fix`)

Use `--fix` for small, targeted patches; emit a fresh `<session>/<step+1>` block directly
when changes span multiple sections or rival the original block size.

```bash
run_block --fix s1/2 <<'RUN_FIX'
old = 'wrong_arg'
new = 'right_arg'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

## Environment Variables

`run_block` works out of the box with zero configuration files and honors standard environment variables:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `RUN_BLOCK_DIR` | `~/.local/state/run_block` | Session storage directory (`$XDG_STATE_HOME/run_block` on POSIX; `%LOCALAPPDATA%\run_block\state` on Windows) |
| `RUN_BLOCK_CWD` | `auto` | `auto` (existing `Workdir` preamble header or session `Workdir` from `<session>/0`, nearest `.agents_bundle`/`AGENTS.md` dir up to Git root, Git root, or `$PWD`), `cwd` (always `$PWD`), or explicit path |
| `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (interactive `[Y/n]` prompt), `auto` (copy automatically), `never` |
| `RUN_BLOCK_HEADLESS` | `0` | Set to `1` (or pass `-y`/`--yes`) for raw stdout protocol without TUI sections |
| `RUN_BLOCK_SANDBOX` | `off` | Execution sandbox mode (`off`, `strict`, `nonet`, or custom wrapper prefix; also persisted in `<session>/0` `Sandbox:` header) |
| `RUN_BLOCK_APPROVE_CMD` | *(none)* | External/LLM validator command receiving `--plan` JSON on `stdin` (`0`=approve, `2`=prompt user with stdout note, other=reject) |
| `RUN_BLOCK_TOKEN_STATS` | `true` | Show char size and Claude/GPT/Gemini token counts (`true` / `false`) |
| `RUN_BLOCK_BUNDLE_MAX_TOKENS` | `100000` | Warn in `START SESSION` / `--bundle-plan` when total tokens exceed budget (`0` disables) |
| `RUN_BLOCK_FRAGMENT_MAX_TOKENS` | `20000` | Warn in `START SESSION` / `--bundle-plan` when a single fragment exceeds limit (`0` disables) |
| `RUN_BLOCK_PROGRESS` | `1` | Show live `[N/M]` step progress markers and elapsed timings during interactive execution (`0`/`false` to disable) |
| `RUN_BLOCK_MAX_FIX_ATTEMPTS` | `2` | Max consecutive failed `--fix` attempts per base step before requiring `<session>/<step+1>` |
| `RUN_BLOCK_MAX_STATE_MB` | `100` | Warn on `stderr` when total session state size exceeds this threshold in MB (`0` disables) |
| `RUN_BLOCK_SHELL` | `bash` | Shell binary (`bash`, `sh`, or `pwsh`/`powershell` on Windows) |
| `VISUAL` / `EDITOR` | `vim`/`less`/`nano` | Terminal editor/viewer for `e` in `START STEP`, `END STEP`, and `START SESSION` |
| `RUN_BLOCK_SAFETY_DISABLE` | *(none)* | Comma-separated built-in risk categories to disable |
| `RUN_BLOCK_SAFETY_RULES` | *(none)* | Semicolon-separated `<cat>=<regex>` rules |

## CLI Reference

| Command | Description |
| :--- | :--- |
| `run_block` | Start a rule-only session on TTY `stdin` (or read context bundle from piped `stdin`) |
| `<command> \| run_block` | Start a new session from `stdin` context bundle into `<session>/0` |
| `run_block [-y] <session>/<step>` | Run a block from `stdin` (`-y` for non-interactive headless mode) |
| `run_block --plan` | Analyze script from `stdin` and print JSON execution and safety plan |
| `run_block --bundle-plan [<session>] [--json] [--full]` | Summarize bundle parts and diagnostics from `stdin` or an existing session |
| `run_block --fix [-y] <session>/<target>` | Patch `<target>` script via Python on `stdin` and run as `<target>_N` |
| `run_block --retry [-y] [session/step]` | Re-run the last (or specified) block |
| `run_block --list`, `-l [session]` | List sessions and blocks with their status and summary |
| `run_block --show [session/step]` | Show saved script and output of a block (or `<session>/0` bundle) |
| `run_block --sandbox [MODE] [session]` | Show or update session sandbox mode (`off`, `strict`, `nonet`) in `<session>/0` |
| `run_block --clean [opts] [session...]` | Prune sessions (`--keep N`, `--older-than DAYS`, `--max-size MB`, `--all`, or named sessions) |
| `run_block --start [--session NAME]` | Start session from `stdin` context bundle or rule-only on TTY into `<session>/0` |
| `run_block --update [--force]` | Self-update `run_block` from GitHub (`vitalio/run_block`) |
| `run_block --check-update` | Check GitHub for a newer version |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)
