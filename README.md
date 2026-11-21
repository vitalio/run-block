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
and copy `<session>/0` to your clipboard. Pass repeatable `-p TEXT` / `--prompt TEXT`
options on bare `run_block`, `<command> | run_block`, or `run_block --start` to
embed or append prompt text into the trailing `===== Prompt =====` section (joining
multiple non-empty values with `\n\n`, ignoring whitespace-only values, and
registering `kind: "prompt"` in `bundle_plan`).
Optional leading `Key: Value` header lines on `stdin` (separated from the
body by a blank line) are parsed into `<session>/meta.json`. Exposed
non-transport headers (such as `Role:`, `Task:`, `Title:`) are displayed in
TUI headers (clamped to a single line with `…` when longer than the box
width), while `Bundle-*` transport headers (`Bundle-Command`, `Bundle-Boundary`,
`Bundle-Expose`, `Bundle-Hide`) stay in `<session>/meta.json` only (excluded
from `<session>/0` and TUI boxes), and
`Bundle-Expose` / `Bundle-Hide` control which remaining `stdin` headers are
forwarded into `<session>/0` alongside `run_block`'s own headers (`Session`,
`Next-Block`, `Workdir`, `Date`, plus `Sandbox` when a non-`off` sandbox mode is
active; `Sandbox: off` is omitted from `<session>/0` and clipboard text while
remaining visible in `i(nfo)`). When `Bundle-Boundary: <nonce>` is
present, `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->`
markers are parsed into per-part `bundle_plan` metrics (lines, chars, GPT/Claude
tokens, percentage share) in `<session>/meta.json` and stripped cleanly from
`<session>/0` while preserving boundary markup in `<session>/0.raw` so `e(dit)`
in `START SESSION` edits boundary-annotated text and re-parses clean metrics
(falling back to `===== ... =====` sections when no boundary is
provided). The inline `START SESSION` box stays compact (retaining core headers, `Bundle:`,
dim `Stats:`, and `Bundle warnings` when present, while full per-part tables
stay in `run_block --bundle-plan`); press `i` at any interactive prompt to open
the borderless alternate-screen fullscreen `i(nfo)` metadata viewer
(`INFO · <label> · <~path>` title bar with `(edited)` suffix when modified,
`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn` to scroll, `e(dit)`/`s(cript)`/`o(utput)`
to edit artifacts, `p(rompt)` on clipboard-copyable screens to append prompt
or output notes, `v(iew)` to open the plain-text report in your editor,
`Tab` (`Tab: parts` in `START SESSION`) to toggle the table row selection cursor
top-to-bottom across sequential numbered rows `1..M` (`Up`/`Down` or `j`/`k`
move the cursor across both `[bundle]` folder rows and leaf part rows, `Enter`
opens `PART N/M` for a leaf part or `BUNDLE R/M` with constituent part
delimiters for a multi-part `[bundle]` folder row, `n`/`N` steps across rows
`1..M`, `e(dit)` edits the bundle, and `Tab`/`Esc` exits cursor
mode), `Enter` to copy, and `Esc`/`q`/`i` to return) without leaving duplicate
headers or stale lines in scrollback. All inline TUI boxes
(`START SESSION`, `START STEP`, `END STEP`, and confirmation dialogs) clamp overflowing sections
to the visible terminal height (`... +N more`) and reflow cleanly across both
width and height `SIGWINCH` resizes.
The `Summary` / `Parts` tables (`i(nfo)` and `--bundle-plan`) start with a
`top`-style header row (`%`, `CHARS`, `LINES`, `~TOK`, `KIND`, `SOURCE` with a
dim sequential row-number column without a `#` label)
followed by a top `100.0%` `[total]` row and ending with a bottom `100.0%`
`[total]` row (`<N> parts`, or `<N> parts (edited)` when modified). All non-`[total]`
table rows are numbered sequentially `1..M` top-to-bottom in dim gray (including
parent `[bundle]` folder rows and leaf part rows, starting with
`1 [header] Headers & spacing` when leading session/preamble headers exist
through `M [prompt]` at the end), with tree hierarchy built purely from each
part's `chain` metadata and nested `%` shares indented by tree depth (`depth * 2`
spaces). `chain`-backed nodes and single-part bundle inclusions are `[bundle]`,
while `[rule]` marks leaf and root rules. Non-`[total]` rows with a share of at
least 10% or ~3k tokens are accented, and rows with at least 25% or ~10k tokens
are highlighted in the warning color (keeping the leading row number dim).

Each part in `bundle_plan` also records 1-based `line_start` / `line_end` line
ranges inside the final cleaned `<session>/0` (body-relative for `stdin`
`--bundle-plan`), without duplicating fragment text in `meta.json`. Print a
single part with `run_block --show <session> --part N` or
`run_block --bundle-plan <session> --part N` (`N` is the 1-based part `index` from
`--bundle-plan --json`); the part text goes to `stdout` and a one-line
description to `stderr`.

When `RUN_BLOCK_CWD` is `auto` and the `stdin` preamble provides an existing
`Workdir` directory, that path is preferred over the current directory or
Git root and written to `<session>/0`:

```bash
run_block
run_block -p "Investigate failing test"
cat context.txt | run_block -p "Focus on edge cases"
run_block --start --session s1 -p "Implement feature" < context.txt
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
Python blocks, and any safety warnings). For clean blocks (`[Y/n/i(nfo)]:`),
press `Enter`/`y` to run, `n`/`Esc` to abort, or `i` to open the fullscreen
`i(nfo)` inspector; when safety warnings or an explicit approval prompt are
present, `START STEP` displays `[y/n/i(nfo)]:` and ignores `Enter`, requiring an
explicit `y`, `n`/`Esc`, or `i` choice. Inside `i(nfo)`, you can inspect unfiltered headers including `Sandbox: off`,
artifact paths, backups, and pre-execution plans, and press `e` to edit the
script or `v` to open the report in your terminal editor. The first edit preserves `<session>/<step>/block.orig.sh`
(or `.ps1`), recalculates operations, statistics, and safety warnings in place,
and re-validates syntax before execution. During execution, `run_block` records
wall-clock block duration (excluding confirmation prompts) and per-operation
elapsed timings in `<session>/<step>/meta.json`, `[<session>/<step>] END
(<duration>)`, `Stats:`, and live progress output (silent steps collapse in
place on a TTY into a single aligned `✓ [N/M] [tag] desc (dur)` line, while
steps with output keep the `▸` header above and align `✓`/`✗` at column 0
below), while per-operation timing breakdowns with percentage shares stay inside
`END STEP`'s `i(nfo)` panel so the inline `END STEP` box remains compact. When a
block targets a step number that already exists on disk, `STEP ALREADY EXISTS`
prompts `[Y/n/r(enumber)/i(nfo)]:` (with `out`) or `[r(enumber)/n/i(nfo)]:`
(without `out`) to copy existing `out`, `r(enumber)` to the next free step
(preserving existing outputs and recording a renumber notice in `out`), or open
`i(nfo)` to inspect/edit `s(cript)`/`o(utput)` or trigger `O(verwrite)` /
`o(verwrite)`, while `MISSING PREVIOUS STEP` prompts `[r(enumber)/n/i(nfo)]:`
to `r(enumber)` to the first missing step; use `--retry` to re-run an existing
step. Across all interactive TUI confirmation prompts (`START SESSION`,
`START STEP`, `END STEP`, `NOT RUN`, `SYNTAX ERROR`, `STEP ALREADY EXISTS`,
`MISSING PREVIOUS STEP`, and `CLEAN SESSIONS`), `[Y/n]` / `[y/N]` brackets
highlight the `Enter` default in uppercase (while `START STEP` safety warnings
use lowercase `[y/n/i(nfo)]:` with no `Enter` default), `Esc` consistently
cancels or exits without proceeding, and `i(nfo)` unifies inspection and
`e(dit)` (preserving
`0.orig`, `block.orig.*`, and `out.orig`, and recalculating line/char/token
statistics, `Error:` lines, and clipboard targets in place). While any interactive TUI box (`START SESSION`, `START STEP`, `END STEP`, or
confirmation prompt) is waiting for input on a POSIX TTY, resizing the
terminal window (`SIGWINCH`) automatically erases and redraws the active box
in place to match the new width. Long lines inside TUI boxes (paths, outputs,
errors, stats, steps, headers, and prompts) wrap cleanly to the terminal width
with `│ ` borders and aligned hanging indents.

At the clipboard prompts (`START SESSION`, `END STEP`, `SYNTAX ERROR`, and
`NOT RUN`, shown as `[Y/n/p(rompt)/i(nfo)]:`, as well as `p(rompt)` inside
their fullscreen `i(nfo)` views), `p(rompt)` opens an empty temporary `.md`
file in your editor and appends the saved text: into the trailing
`===== Prompt =====` section of `<session>/0` (created when absent, followed by
a bundle metadata refresh) or at the end of the step `out`. The temporary file
is always removed; empty or whitespace-only text changes nothing and creates no
backup. Otherwise the original is preserved once as `0.orig` / `out.orig`,
`Stats:` and `[total]` rows are recalculated with the `(edited)` marker, and
`Enter`/`y` copies the updated content to the clipboard.

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

### 4. Completing a session (`--done`)

```bash
run_block --done [session] [-m "wrap-up note"]
```

Marks a session (default: the active parent session inside a block, or the
most recent session otherwise) as completed: `completed`, `completed_at`, and
an optional `completed_note` are stored in `<session>/meta.json` together with
the statistics accumulated while blocks ran (`stats`: steps,
ok/failed/`--fix`/renumbered counts, total duration), and an `END SESSION`
card prints the summary. `--done` and nested session initialization
(`<cmd> | run_block` or `run_block --start`) are allowed inside a running block
(`IN_RUN_BLOCK=1`, which permits read-only `--list`, `--show`, `--bundle-plan`,
`--plan`, and `--sandbox` inspection while rejecting nested `<session>/<step>`,
`--fix`, and `--retry` step execution with exit code `2`): inside the step log
they emit concise single-line notices (`run_block: session <name> marked
completed` and `run_block: initialized session <child> (<child>/0)`), link
`"parent_session"` / `"parent_step"` and `"spawned_sessions"` in `meta.json`,
and defer their `END SESSION` (counting the completing step itself) and
`START SESSION` TUI cards until after the outer `END STEP` card (suppressing
the outer step's clipboard prompt when a new `<child>/0` session bundle is
spawned so clipboard handoff targets `<child>/0`). `--list` shows completed
sessions with a `[DONE]` badge.

Running another block (`<session>/<step>`, `--fix`, or `--retry`) on a
completed session first shows a `SESSION COMPLETED` confirmation
(`Reopen session <session>? [y/N/i(nfo)]`, default `No`); `y` clears the
completion marker and continues into `START STEP`. With `-y`/`--yes` (or
`RUN_BLOCK_HEADLESS=1`) the session is reopened automatically; on a
non-interactive stdout without `-y` the step exits with `NOT RUN: session
<session> is marked as completed (pass -y/--yes to reopen and run)`.
Recreating a session with `--start --force` resets the completion state and
statistics.

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
| `VISUAL` / `EDITOR` | `vim`/`less`/`nano` | Terminal editor/viewer for `e(dit)`/`s(cript)`/`o(utput)`/`v(iew)` inside `i(nfo)` |
| `RUN_BLOCK_SAFETY_DISABLE` | *(none)* | Comma-separated built-in risk categories to disable |
| `RUN_BLOCK_SAFETY_RULES` | *(none)* | Semicolon-separated `<cat>=<regex>` rules |

## CLI Reference

| Command | Description |
| :--- | :--- |
| `run_block [-p TEXT]` | Start a rule-only session on TTY `stdin` (or read context bundle from piped `stdin`), embedding optional repeatable `-p`/`--prompt` text |
| `<command> \| run_block [-p TEXT]` | Start a new session from `stdin` context bundle into `<session>/0`, appending optional `-p`/`--prompt` text |
| `run_block [-y] <session>/<step>` | Run a block from `stdin` (`-y` for non-interactive headless mode; also reopens a completed session) |
| `run_block --plan` | Analyze script from `stdin` and print JSON execution and safety plan |
| `run_block --bundle-plan [<session>] [--json] [--full] [--part N]` | Summarize bundle parts and diagnostics from `stdin` or an existing session (`--part N` prints only that part's text) |
| `run_block --fix [-y] <session>/<target>` | Patch `<target>` script via Python on `stdin` and run as `<target>_N` |
| `run_block --retry [-y] [session/step]` | Re-run the last (or specified) block |
| `run_block --list`, `-l [session]` | List sessions and blocks with their status and summary (`[DONE]` marks completed sessions) |
| `run_block --done [-y] [session] [-m NOTE]` | Mark a session (default: latest) as completed and print the `END SESSION` summary with accumulated statistics |
| `run_block --show [session/step]` | Show saved script and output of a block (or `<session>/0` bundle) |
| `run_block --show [<session>[/0]] --part N` | Print only part `N` (1-based part `index` from `--bundle-plan --json`) of `<session>/0` (latest session when omitted); exits non-zero for non-zero steps or out-of-range parts |
| `run_block --sandbox [MODE] [session]` | Show or update session sandbox mode (`off`, `strict`, `nonet`) in `<session>/0` |
| `run_block --clean [opts] [session...]` | Prune sessions (`--keep N`, `--older-than DAYS`, `--max-size MB`, `--all`, or named sessions) |
| `run_block --start [-p TEXT] [--session NAME]` | Start session from `stdin` context bundle or rule-only on TTY into `<session>/0` |
| `run_block --update [--force]` | Self-update `run_block` from GitHub (`vitalio/run_block`) |
| `run_block --check-update` | Check GitHub for a newer version |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)
