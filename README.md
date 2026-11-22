# run_block

**Safe, sequential terminal block execution protocol for AI coding agents.**

`run_block` is a zero-dependency Python 3 CLI that connects any chat LLM to your
local terminal without API keys or background daemons. It initializes a
rule-only session on bare TTY invocation (`run_block`) or ingests a context
bundle on `stdin` (`<command> | run_block` -> `~/.local/state/run_block/<session>/0`),
then executes numbered Bash or PowerShell blocks (`<session>/1`, `<session>/2`,
...) with syntax validation, a pre-execution safety scanner, PTY streaming, and
one-keystroke clipboard handoff with Claude/GPT/Gemini token counts.

## Key Features

- **Zero-daemon chat-to-terminal loop** — single-file Python 3 standard-library
  CLI that bridges any web or desktop chat LLM to your local shell via
  clipboard-ready session bundles and numbered `<session>/<step>` execution
  blocks.
- **AST & regex safety scanner** — pre-execution `START STEP` analysis
  classifies shell and Python operations, expands multi-file AST actions,
  requires explicit confirmation on risky commands, and supports `--plan`,
  `--sandbox`, and external `RUN_BLOCK_APPROVE_CMD` validators.
- **Interactive TUI cards & fullscreen `i(nfo)` inspector** — compact inline
  cards (`START SESSION`, `START STEP`, `END STEP`, `END SESSION`) with
  `SIGWINCH` reflow, in-place `p(rompt)` note appending, and a borderless
  alternate-screen `i(nfo)` viewer with `Tab` part navigation and artifact
  editing (`e`/`s`/`o`/`m`/`v`).
- **Context bundle protocol & token accounting** — parses `Key: Value` and
  `Bundle-*` preamble headers, strips `Bundle-Boundary` part markers into
  hierarchical `bundle_plan` token/share tables (`--bundle-plan`, `--part N`),
  and preserves raw markup in `<session>/0.raw` for lossless editing.
- **Targeted `--fix` patching & session lifecycle** — recovers failed steps via
  small Python patches (`<target>_1`, `<target>_2`), tracks session completion
  and accumulated statistics with `--done`, and supports deferred nested
  session chaining inside running blocks (`IN_RUN_BLOCK=1`).

## Quick Installation

### Linux & macOS

```bash
curl -fsSL https://raw.githubusercontent.com/vitalio/run_block/main/install.sh | sh
```

### Windows (PowerShell 7+)

```powershell
irm https://raw.githubusercontent.com/vitalio/run_block/main/install.ps1 | iex
```

## Quick Start

### 1. Start a session (`run_block` or `<cmd> | run_block`)

```bash
run_block
run_block -p "Investigate failing test"
cat context.txt | run_block -p "Focus on edge cases"
run_block --start --session s1 -p "Implement feature" < context.txt
```

Run bare `run_block` (or `run_block --start`) in an interactive TTY to create a
rule-only `<session>/0` bundle with embedded `bash` or `pwsh` rules, or pipe any
context bundle on `stdin` to inject rules and copy `<session>/0` to the
clipboard. Repeatable `-p TEXT` / `--prompt TEXT` flags append prompt sections
to `===== Prompt =====` (joining multiple non-empty values with `\n\n`).

### 2. Run numbered blocks (`<session>/<step>`)

```bash
run_block s1/1 <<'RUN_BLOCK'
git status -sb
python3 -m unittest
RUN_BLOCK
```

Before execution, `START STEP` displays the resolved working directory,
numbered operations (with AST-expanded Python sub-items), and any safety
warnings. During execution, live `[N/M]` progress markers and per-operation
timings stream to the terminal, and `END STEP` offers one-keystroke clipboard
copy of the combined step header, output, and token stats.

Child `stdout` and `stderr` share one descriptor, so `<session>/<step>/out`
keeps the exact write order of interleaved output. `out` is written once the
block finishes and ends with the `[<session>/<step>] END` line; `END STEP` takes
its `Error:` line from the last meaningful line of `out`. There is no separate
`stderr` file. `aborted` marks a block that was declined or rejected, `error`
holds a pre-execution failure message, and `meta.json` stores the structured
outcome, exit code, and duration.

### 3. Patch a failed block (`--fix`)

```bash
run_block --fix s1/1 <<'RUN_FIX'
old = 'wrong_arg'
new = 'right_arg'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```

Use `--fix <session>/<target>` for small, targeted patches to a failed step
(`text` and `re` are preloaded; each attempt allocates `<target>_1`,
`<target>_2`, up to `RUN_BLOCK_MAX_FIX_ATTEMPTS`). When a fix requires rewriting
multiple sections, emit a fresh `<session>/<step+1>` block instead.

### 4. Complete or chain sessions (`--done`)

```bash
run_block --done s1 -m "Completed feature and tests"
```

`--done` persists completion metadata (`completed`, `completed_at`,
`completed_note`) and accumulated step statistics in `<session>/meta.json` and
renders the `END SESSION` summary card (`--list` marks completed sessions with
`[DONE]`). Inside a running step (`IN_RUN_BLOCK=1`), `--done` and piped
`<cmd> | run_block` session initialization queue deferred `END SESSION` ->
`START SESSION` cards after the outer `END STEP` and hand off the clipboard to
the newly spawned `<child>/0` bundle.

## Interactive TUI & Keyboard Shortcuts

All inline TUI cards clamp overflowing sections to the visible terminal height
(`... +N more`), wrap long lines with `│ ` borders, and automatically redraw in
place on terminal resize (`SIGWINCH`). Bracketed prompts highlight the `Enter`
default in uppercase (`[Y/n]`, `[y/N]`), while `START STEP` safety warnings use
lowercase `[y/n/i(nfo)]:` and require an explicit `y` or `n`.

### TUI Cards & Confirmation Prompts

| TUI Card / Prompt | Prompt Format | Behavior & Options |
| :--- | :--- | :--- |
| `START SESSION` | `[Y/n/p(rompt)/i(nfo)]:` | Copy initialized `<session>/0` bundle to clipboard, append a `p(rompt)` note, or inspect bundle parts in `i(nfo)` |
| `START STEP` (clean) | `[Y/n/i(nfo)]:` | `Enter`/`y` runs the block; `n`/`Esc` aborts (`NOT RUN`); `i` opens pre-execution plan and script editor |
| `START STEP` (warning) | `[y/n/i(nfo)]:` | `Enter` is ignored when safety warnings or approval prompts exist; requires explicit `y`, `n`/`Esc`, or `i` |
| `END STEP` / `SYNTAX ERROR` / `NOT RUN` | `[Y/n/p(rompt)/i(nfo)]:` | Copy formatted `[<session>/<step>]` result to clipboard, append a trailing `p(rompt)` note to `out`, or open `i(nfo)` |
| `END SESSION` | *(summary card)* | Displays session completion note, step counts (ok/failed/`--fix`/renumbered), and total duration |
| `STEP ALREADY EXISTS` | `[Y/n/r(enumber)/i(nfo)]:` | Copy existing `out` (`[r(enumber)/n/i(nfo)]:` when `out` is absent), `r(enumber)` to the next free step, or overwrite via `i(nfo)` |
| `MISSING PREVIOUS STEP` | `[r(enumber)/n/i(nfo)]:` | `r(enumber)` block to the first missing sequential step number, cancel with `n`/`Esc`, or inspect in `i(nfo)` |
| `SESSION COMPLETED` | `[y/N/i(nfo)]:` | Shown before running a block on a completed session (default `No`); `y` (or `-y`/`--yes`) clears completion and reopens |
| `CLEAN SESSIONS` | `[y/N]:` | Confirm pruning target sessions during interactive `run_block --clean` |

### Prompt Action Keys

| Key | Action |
| :--- | :--- |
| `Enter` / `y` | Accept the uppercase default action (run clean step or copy output/bundle to clipboard) |
| `n` / `Esc` | Cancel or skip the current prompt without proceeding |
| `p` (`p(rompt)`) | Open a temporary `.md` file in `$VISUAL`/`$EDITOR` and append saved text to `===== Prompt =====` in `<session>/0` or step `out` (preserving `0.orig` / `out.orig`) |
| `r` (`r(enumber)`) | Renumber a colliding or out-of-order block to the expected sequential `<session>/<step>` and record a notice in `out` |
| `i` (`i(nfo)`) | Open the borderless alternate-screen fullscreen metadata and artifact inspector |

### Fullscreen `i(nfo)` Inspector Shortcuts

| Key | Context | Action |
| :--- | :--- | :--- |
| `Up`/`Down`, `j`/`k`, `PgUp`/`PgDn` | All `i(nfo)` views | Scroll the fullscreen report vertically (the footer shows `Lines a-b/N` and the scroll hint only when the body overflows) |
| `Tab` (`Tab: parts`) | `START SESSION` `i(nfo)` | Toggle the row selection cursor across sequential numbered bundle rows `1..M` (`[bundle]` folders and leaf parts) |
| `Tab` (`Tab: parts`) | Step `i(nfo)` (`START STEP`, `END STEP`, `SYNTAX ERROR`, `NOT RUN`, `STEP ALREADY EXISTS`) | Toggle the row selection cursor across the numbered operation rows `1..N` of the breakdown table (`START STEP`: pre-execution script table; `END STEP`: output table with `TIME`) |
| `Enter` (in `Tab` cursor) | `START SESSION` `i(nfo)` | Open `PART N/M` for a leaf part or `BUNDLE R/M` (with constituent part delimiters) for a `[bundle]` folder row |
| `Enter` (in `Tab` cursor) | Step `i(nfo)` | Open `PART k/N` for the selected operation: `Command`, `Timing`, `Script-Range`, and `Range: lines a-b of <out>` with the operation's captured output slice from `<step>/out` (script lines in `START STEP` or without `out`); `n`/`N` step across operations, `e`/`o` edit `out`, `s` edits the script, `m` opens `meta.json` |
| `n` / `N` | `PART` / `BUNDLE` viewer | Step forward or backward across sequential numbered rows `1..M` |
| `e` (`e(dit)`) | `START SESSION` / `START STEP` | Edit `<session>/0.raw` (preserving boundary markup and `0.orig`) or `block.sh`/`.ps1` (`block.orig.*`) and re-parse in place |
| `s` (`s(cript)`) / `o` (`o(utput)`) | Step `i(nfo)` views | Edit saved block script or captured step output in `$VISUAL`/`$EDITOR` (preserving `*.orig` backups and updating stats) |
| `O` / `o` (`overwrite`) | `STEP ALREADY EXISTS` `i(nfo)` | Overwrite the existing step directory and proceed with the new block |
| `p` (`p(rompt)`) | Copyable `i(nfo)` views | Append a prompt or output note via `$VISUAL`/`$EDITOR` and recalculate token stats |
| `v` (`v(iew)`) | All `i(nfo)` views | Open the plain-text `i(nfo)` report directly in `$VISUAL`/`$EDITOR` |
| `m` (`m(eta)`) | All `i(nfo)` views | Open `<session>/meta.json` (`START SESSION`) or `<session>/<step>/meta.json` (step cards) in `$VISUAL`/`$EDITOR` |
| `Enter` | Copyable `i(nfo)` views | Copy the active bundle or step output to the clipboard and exit `i(nfo)` |
| `Esc` / `q` / `i` | All `i(nfo)` views | Exit cursor/part subview or return from `i(nfo)` to the inline prompt without scrollback clutter |

## Context Bundles & Part Inspection

- **Preamble headers & `Workdir` resolution**: Optional leading `Key: Value`
  lines on `stdin` (before the first blank line) are stored in
  `<session>/meta.json`. Exposed headers (such as `Role`, `Task`, `Title`) appear
  in TUI headers and `<session>/0`, while `Bundle-*` transport headers
  (`Bundle-Command`, `Bundle-Protocol`, `Bundle-Boundary`, `Bundle-Expose`,
  `Bundle-Hide`) remain
  in `<session>/meta.json` only. When `RUN_BLOCK_CWD=auto`, an existing piped
  `Workdir` directory is preferred over the current directory or Git root.
- **Rule injection & deduplication**: `run_block` injects embedded `bash` or
  `pwsh` execution rules into `===== Rules =====`, deduplicating against
  existing `blocks/bash` or `blocks/pwsh` parts or `## Terminal blocks (`
  headings, and wraps unlabeled plain text under `===== Prompt =====`.
  `Sandbox: off` is omitted from `<session>/0` and clipboard output while
  remaining visible inside `i(nfo)`.
- **Boundary markers & hierarchical `Parts` table**: When
  `Bundle-Boundary: <nonce>` is present, `<!-- bundle:<nonce>:part {...} -->` /
  `<!-- bundle:<nonce>:end -->` markers are parsed into per-part metrics and
  stripped from `<session>/0` (keeping raw markers in `<session>/0.raw` for
  `e(dit)`, and falling back to `===== ... =====` sections when no boundary is
  set). The `Parts` table (`i(nfo)` and `--bundle-plan`) shows `%`,
  `CHARS`, `LINES`, `~TOK`, `KIND`, and `SOURCE` columns bracketed by top and
  bottom `100.0%` `[total]` rows, with sequential dim row numbers `1..M`,
  `chain`-indented `[bundle]` / `[rule]` tree shares, and automatic highlights
  for large parts (>=10% or ~3k tokens accented; >=25% or ~10k tokens warning).
- **Bundle protocol version & fragment kinds**: `Bundle-Protocol: 1` declares
  `context-bundle-protocol` v1; an unsupported version prints a warning on
  `stderr` while the bundle is still ingested. Besides `rule`, `cmd`, `file`,
  `include`, and `prompt`, fragments may have kind `task` or `context`; repeatable
  `-p`/`--prompt` text is appended to `===== Prompt =====` after the upstream
  `task`/`context` fragments, and an empty `task`/`context` fragment raises a
  `fragment_empty` warning in `--bundle-plan` and `START SESSION`.
- **Fragment deduplication & overlap warnings**: With a declared boundary,
  a fragment whose text (ignoring a leading `===== ... =====` header line and
  surrounding blank lines) is identical to an earlier fragment, or is a
  contiguous block of at least 3 lines inside one, is dropped from
  `<session>/0` (`0.raw` keeps it) and reported as a `fragment_deduped`
  warning naming the kept part and the saved lines/tokens. `prompt` fragments
  are never dropped. When two remaining fragments share a contiguous block of
  at least 5 lines and 200 characters without being duplicates, a
  `fragment_overlap` warning shows the earlier part, shared line count, and
  overlap percentage in `--bundle-plan` and `START SESSION`.
- **Inspecting individual parts (`--bundle-plan` & `--part N`)**: Each part in
  `bundle_plan` records 1-based `line_start` / `line_end` offsets into cleaned
  `<session>/0`. Inspect the full table or slice a single 1-based part index `N`
  (`stdout` receives the part text; `stderr` receives a one-line summary):

```bash
run_block --bundle-plan s1
run_block --bundle-plan s1 --json
run_block --show s1 --part 1
run_block --bundle-plan s1 --part 2
```

## Safety Scanner, Sandboxing & Approval Hooks

- **Pre-execution analysis (`--plan`)**: `run_block` parses Bash and Python
  scripts via AST and regex rules before running, expanding multi-file or
  read+write Python operations into sub-items and flagging destructive commands,
  network calls, credential access, or history mutations. Pipe any script to
  `run_block --plan` to emit the structured JSON execution and risk plan without
  running it.
- **Session sandboxing (`--sandbox` & `RUN_BLOCK_SANDBOX`)**: Restrict block
  execution with `off` (default), `strict` (read-only filesystem outside working
  / temp directories and restricted network where supported), `nonet` (network
  disabled), or a custom wrapper command prefix. Query or update a session's
  sandbox mode via `run_block --sandbox [MODE] [session]`; active non-`off`
  modes are recorded in `<session>/0`'s `Sandbox:` header.
- **External approval hook (`RUN_BLOCK_APPROVE_CMD`)**: When set, `run_block`
  pipes the `--plan` JSON to this validator command before execution: exit `0`
  approves automatically, exit `2` requires interactive user confirmation with
  the validator's note, and any other exit code rejects execution (`NOT RUN`).
- **Customizing risk rules (`RUN_BLOCK_SAFETY_*`)**: Disable specific built-in
  risk categories via `RUN_BLOCK_SAFETY_DISABLE=cat1,cat2` or register custom
  regex patterns via `RUN_BLOCK_SAFETY_RULES="cat1=regex1;cat2=regex2"`.

## CLI Reference

| Command | Description |
| :--- | :--- |
| `run_block [-p TEXT]` | Start a rule-only session on TTY `stdin` (or read context bundle from piped `stdin`), embedding optional repeatable `-p`/`--prompt` text |
| `<command> \| run_block [-p TEXT]` | Start a new session from `stdin` context bundle into `<session>/0`, appending optional `-p`/`--prompt` text |
| `run_block [-y] <session>/<step>` | Run a block from `stdin` (`-y` for non-interactive headless mode; also reopens a completed session) |
| `run_block --plan` | Analyze script from `stdin` and print JSON execution and safety plan |
| `run_block --bundle-plan [<session>] [--json] [--part N]` | Print the `Parts (<N>):` table and diagnostics from `stdin` or an existing session (`--part N` prints only that part's text) |
| `run_block --fix [-y] <session>/<target>` | Patch `<target>` script via Python on `stdin` and run as `<target>_N` |
| `run_block --retry [-y] [session[/step]]` | Re-run a block, or the latest block of a session when only `<session>` is given (default: latest block overall) |
| `run_block --list`, `-l [session \| --filter TEXT]` | List sessions with block count, size, UTC timestamp, `Workdir`/`Role`/`Task` headers, the last step outcome (`ok (<duration>)`, `exit <rc> (<duration>)`, `syntax-error (exit <rc>)`, `not-run`, `aborted`, `saved`) and `next: <session>/<step>` for open sessions (`[DONE]` marks completed sessions without `next:`); `--filter TEXT` keeps only sessions whose name or any header value contains `TEXT` (case-insensitive) |
| `run_block --done [-y] [session] [-m NOTE]` | Mark a session (default: latest) as completed and print the `END SESSION` summary with accumulated statistics |
| `run_block --info [session]` | Show session path, state, size, update time, statistics, all headers (including `Bundle-*` transport headers), and every block with its status and action summary (default: latest session); `--show <session>` is equivalent |
| `run_block --show [session/step] [--script \| --out]` | Show saved script and output of a block, the `<session>/0` bundle, or the summary of a bare `<session>`; `--script` / `--out` print only the script or only the captured output (a bare `<session>` selects its latest block) |
| `run_block --show [<session>[/0]] --part N` | Print only part `N` (1-based part `index` from `--bundle-plan --json`) of `<session>/0` (latest session when omitted); exits non-zero for non-zero steps or out-of-range parts |
| `run_block --sandbox [MODE] [session]` | Show or update session sandbox mode (`off`, `strict`, `nonet`) in `<session>/0` |
| `run_block --clean [opts] [session...]` | Prune sessions (`--keep N`, `--older-than DAYS`, `--max-size MB`, `--all`, or named sessions) |
| `run_block --start [-p TEXT] [--session NAME]` | Start session from `stdin` context bundle or rule-only on TTY into `<session>/0` |
| `run_block --update [--force]` | Self-update `run_block` from GitHub (`vitalio/run_block`) |
| `run_block --check-update` | Check GitHub for a newer version |
| `run_block -V`, `--version` | Print version and exit `0` |
| `run_block -h`, `--help` | Print usage help and exit `0` |

## Environment Variables

`run_block` works out of the box with zero configuration files and honors
standard environment variables:

| Environment Variable | Default | Description |
| :--- | :--- | :--- |
| `RUN_BLOCK_DIR` | `~/.local/state/run_block` | Session storage directory (`$XDG_STATE_HOME/run_block` on POSIX; `%LOCALAPPDATA%\run_block\state` on Windows) |
| `RUN_BLOCK_CWD` | `auto` | `auto` (existing `Workdir` preamble header or session `Workdir` from `<session>/0`, nearest `.agents_bundle`/`AGENTS.md` dir up to Git root, Git root, or `$PWD`), `cwd` (always `$PWD`), or explicit path |
| `RUN_BLOCK_CLIPBOARD` | `prompt` | `prompt` (interactive `[Y/n]` prompt), `auto` (copy automatically), `never` |
| `RUN_BLOCK_HEADLESS` | `0` | Set to `1` (or pass `-y`/`--yes`) for raw stdout protocol without TUI sections |
| `RUN_BLOCK_SANDBOX` | `off` | Execution sandbox mode (`off`, `strict`, `nonet`, or custom wrapper prefix; active non-`off` modes are persisted in `<session>/0` `Sandbox:` header) |
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

### Variables Exported to Step Processes

Every block runs with these variables in its environment:

| Environment Variable | Description |
| :--- | :--- |
| `IN_RUN_BLOCK` | Always `1` inside a running step |
| `RUN_BLOCK_PARENT_SESSION` / `RUN_BLOCK_PARENT_STEP` | Session name and step directory of the running block |
| `RUN_BLOCK_STEP_STDOUT_INO` | `<st_dev>:<st_ino>` of the step capture stdout (PTY slave or pipe write end); a producer compares it with `fstat(1)` to tell direct step console output from a shell pipeline inside the step |

## License

[MIT](LICENSE) © 2026 [vitalio](https://github.com/vitalio)
