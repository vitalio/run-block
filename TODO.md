# 🎯 [NEXT] F69: Preserve boundary markup during bundle e(dit) and count clean bundle size without markers

- Preserve the raw boundary-annotated bundle source (e.g. in `<session>/0.raw` or an editable staging file) during `format_start_bundle()` and `cmd_start()` (`src/bundle.py`, `src/bundle_plan.py`, `src/config.py`) instead of stripping `<!-- bundle:<nonce>:part ... -->` / `<!-- bundle:<nonce>:end -->` markers irreversibly on initialization.
- When `e(dit)` is triggered on `BUNDLE` (`src/ui.py`), open the markup-preserving editable content so manual edits preserve fragment boundaries, then re-parse with `parse_bundle_fragments()` and update both the raw source and clean `<session>/0`.
- Compute `Stats:`, `bundle_plan`, and clipboard content strictly from the clean stripped text (excluding boundary marker comments), and finalize `<session>/0` without boundary markers on disk once `BUNDLE` exits (`Enter`, `Esc`, or non-interactive mode), keeping `0.orig` backup and `F57` `a(ppend)` compatibility intact.
- Acceptance criteria: editing a boundary-annotated bundle via `e(dit)` preserves full `Summary`/`Parts` fragment detail instead of collapsing to fallback sections; `Stats:` counts clean content without marker comments; final `<session>/0` contains no boundary markup; offline tests in `tests/test_run_block.py` verify the roundtrip.

- Coordinate with `F66`: preserve `<session>/0.raw` after embedded block-rule injection (or keep re-parsing idempotent) so `e(dit)` neither drops nor duplicates `run_block:blocks/*`.

# 🎯 [NEXT] B11: Fix TUI box height overflow, header duplication on redraw, and keep inline boxes minimal

- Keep inline TUI boxes compact so they stay within visible terminal height (`shutil.get_terminal_size().lines`): remove the `Summary:` table from the inline `BUNDLE` box (retaining core headers, `Bundle:`, dim `Stats:`, and `Bundle warnings` when present), and clamp long inline sections in `PLAN`, `END`, and confirmation dialogs to available `term_rows` with a `... +N more` hint so the top border (`╭─ ...`) never scrolls into scrollback before a redraw.
- Display expanded bundle details in an alternate-screen fullscreen panel (`\033[?1049h` / `\033[?1049l`, modeled after `top`/`less`) with keyboard scrolling (`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn`), clean return (`Esc`/`q`/`d`/`i`), and clipboard copy on `Enter` so toggling details never leaves duplicate headers or stale lines in scrollback.
- Fix `display_width()` in `src/ui.py` to count Unicode combining and zero-width format characters (`Mn`, `Me`, `Cf`) as width `0` and normalize/expand tabs (`\t`) during rendering so `_box_rows_above_prompt()` always matches actual terminal row wrapping.
- Track both `cols` and `rows` (`term_rows`) across `offer_clipboard_copy()`, `confirm_execution()`, and `prompt_yes_no_box()` (`src/ui.py`) so `SIGWINCH` height or width changes reflow cleanly without leaving stale `╭─ ...` rows.
- Target files: `src/ui.py`, `src/runner.py`, `src/bundle.py`, `README.md`, `tests/test_run_block.py`.
- Acceptance criteria: toggling details, resizing terminal width or height, or returning from `e(dit)` never produces duplicate `╭─ ...` headers; inline boxes fit within `term_rows`; fullscreen details scroll cleanly on alternate screen; `README.md` and offline tests in `tests/test_run_block.py` cover height clamping, alternate-screen redraw, and `display_width()` edge cases.

# 🎯 [NEXT] F66: Embed terminal block rules in run_block and start rule-only session on bare invocation

- Embed `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` into the built `./run_block` script via `build.py` (with `--check` verifying embedded rules match `src/rules/blocks/*.md`), stripping leading `# Description:` lines, selecting `bash` vs `pwsh` via `get_setting("shell")` / `_is_powershell()`, and substituting `{cmd:run_block}` with `prog_name()`.
- Inject the embedded rule in `format_start_bundle()` (`src/bundle.py`) and register it in `src/bundle_plan.py`:
  - When `Bundle-Boundary` is present, insert into the top-level `===== Rules =====` section only outside `<!-- bundle:<nonce>:part ... --> ... <!-- bundle:<nonce>:end -->` blocks (or prepend `===== Rules =====` before the first part if absent), tracking the fragment in `bundle_plan` as `kind: "rule"`, `id: "run_block:blocks/bash"` (or `"blocks/pwsh"`), `chain: ["run_block"]` so `d(etails)`, `--bundle-plan`, `line_start`/`line_end`, and `secret_detected` exemption work uniformly.
  - In fallback mode without `Bundle-Boundary`, inspect only the start of the body: insert after leading `===== Rules =====` if present, otherwise prepend `===== Rules =====` and wrap unlabeled plain stdin text under `===== Prompt =====` so user input is not merged into `Rules`.
  - Deduplicate against legacy `vitalio/run_block` input by checking `bundle_plan` parts (`blocks/bash` / `blocks/pwsh`) or an existing `## Terminal blocks (` heading.
- Update `main()` and `cmd_start()` in `src/cli.py` and `src/bundle.py` so bare `run_block` (no args with TTY `stdin`) and `run_block --start` in TTY start a rule-only `<session>/0` bundle and open `BUNDLE` instead of exiting 2 with usage, while keeping `run_block --sandbox <mode>` mapped to `cmd_sandbox()`.
- Update `src/header.py` (`--help`), `AGENTS.md`, `README.md`, and `tests/test_run_block.py`, rebuild `./run_block`, and bump `VERSION` for a MINOR release.

# 🎯 [NEXT] F57: Add a(ppend) prompt editor action in BUNDLE

- Add an `a(ppend)` action to the `BUNDLE` prompt in `src/ui.py` (`-> Copy to clipboard? [Enter/a(ppend)/e(dit)/Esc]:`), recognizing `a`/`A` (and `append` in line-input mode) without affecting `END` or conflicting with `e(dit)`, `i(nfo)`, or `d(etails)`.
- On `a(ppend)`, open an empty temporary `.md` file in the configured editor (`resolve_editor_command()` in `src/ui.py`), remove the temporary file on exit, and abort cleanly without modifying `<session>/0` or creating `<session>/0.orig` when the entered text is empty or whitespace-only.
- Before the first non-empty append, preserve the original bundle in `<session>/0.orig` via `_write_orig_backup_once()`, then append the prompt text to `<session>/0` in `src/ui.py` / `src/bundle.py` (appending into the trailing `===== Prompt =====` section when already present so repeated `a(ppend)` calls do not duplicate the header, or creating `===== Prompt =====` at the end otherwise).
- Refresh bundle metadata (`refresh_bundle_meta()`), recalculate line/byte/token `Stats:` with the `(edited)` marker, and redraw `BUNDLE` in place so pressing `Enter` copies the updated bundle to the clipboard.
- Acceptance criteria: `a(ppend)` opens an empty temp file and appends non-empty prompt text into `===== Prompt =====` in `<session>/0`; empty input leaves `<session>/0` and `<session>/0.orig` untouched; `0.orig` is saved once and `Stats:` updates with `(edited)`; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F56: Align operation progress lines, update status colors, and collapse silent steps

- Remove the 2-space leading indentation on step completion lines in `_ProgressLineFilter._format_step_done()` (`src/runner.py`) so `✓` and `✗` (plus ASCII `+` and `x`) align at column 0 directly beneath `▸` and `>`.
- Update `_ProgressLineFilter` ANSI styling in `src/runner.py`: render start banners (`▸`) and successful completion lines (`✓`) in neutral gray (`\x1b[90m`), and failed completion lines (`✗`) in red (`\x1b[31m`).
- Track in `_ProgressLineFilter` (`src/runner.py`) whether any `out` text was emitted while a step was active: when a step finishes without output on a TTY, overwrite the start banner line in place (`\033[1A\r\033[2K`) with a single-line summary `✓ [N/M] [tag] desc (dur)` (truncated to `_hr_width()`); when output was emitted, keep the `▸` header above the output and print `✓ [N/M] (dur)` or `✗ [N/M] (dur)` below at column 0.
- Acceptance criteria: silent steps collapse into a single column-0 line with duration on TTY; steps with output keep `▸` above and `✓`/`✗` at column 0 below; colors use gray for normal progress and red for failures; `README.md` and unit tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] D2: Design nested run_block contract (IN_RUN_BLOCK=1) for session initialization and subcommand guards

- Design candidate for `role=design` (coordinates with `F42` and `F48`).
- Problem: when a block executes `<cmd> | run_block` inside an active step (e.g., `todo_md F21 | agents_bundle role=work | run_block` inside `s53/1`), `IN_RUN_BLOCK=1` disables clipboard copy and prints the inner `BUNDLE` box inside the outer step's `[s53/1] START ... [s53/1] END` output, leaving outer wrappers around the new bundle and lacking an explicit contract for nested `run_block` invocations.
- Define the behavior matrix when `IN_RUN_BLOCK=1` (and optional `RUN_BLOCK_PARENT_SESSION` / `RUN_BLOCK_PARENT_STEP` env metadata):
  1. Subcommand guards: allow read-only inspection (`--list`, `--show`, `--info`, `--bundle-plan`) and completing the current session (`--done`), while blocking recursive step execution (`<session>/<step>`, `--fix`, `--retry`) unless explicitly overridden.
  2. Nested session initialization (`<cmd> | run_block` / `--start`): specify console framing, clipboard handoff policy (copying the spawned `<session>/0` bundle vs suppressing outer step clipboard copy), and `parent_session` / `spawned_sessions` linkage in `<session>/meta.json`.
  3. Headless / machine-readable (`--json` in `F48`) interaction when a step spawns a child session.
- Target files for downstream implementation: `src/bundle.py`, `src/runner.py`, `src/config.py`, `src/cli.py`, `src/ui.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, `tests/test_run_block.py`.

- Concrete reproduction scenario: running a nested session initializer inside an active step (`todo_md <ID> | agents_bundle role=execute | run_block`) prints the inner `BUNDLE` box (`<child>/0`) inside the outer `[sN/k] START ... [sN/k] END` block output, skips copying `<child>/0` to the clipboard because `IN_RUN_BLOCK=1`, and then triggers the outer `END` box's `-> Copy to clipboard?` prompt for the outer step log (with `[sN/k]` wrappers) instead of copying the clean `<child>/0` bundle and suppressing the outer clipboard prompt.

# 🎯 [NEXT] D1: Design session lifecycle states, step outcome labels, and run_block -l display

- Design candidate for `role=design` (coordinates with `F42` `--done` session completion and `F20` session inspection CLI).
- Problem: `cmd_list()` and `_step_status()` in `src/runner.py` parse the trailing `[sN/k] END` output marker of the last script in `_iter_session_scripts(sdir)` and render `last: sN/k (END)`, conflating individual step completion with overall session completion and obscuring whether a session is still active or finished.
- Define clear separation between:
  1. Step execution outcome (`ok`, `exit <rc>`, `not-run`, `syntax-error`, `aborted`, `saved`) derived from structured step metadata or output markers without overloading `END`.
  2. Session lifecycle state (`active` / `bundle-only` / `done` via `<session>/meta.json` `completed` from `F42`) and next actionable step (`Next-Block: sN/<k>`).
  3. Consistent `run_block -l` / `--list` and `--info` formatting across summary rows and recent-block listings (including fix-step ordering and optional `Task` / `Workdir` context).
- Target files for downstream implementation: `src/runner.py`, `src/config.py`, `src/ui.py`, `src/cli.py`, `src/header.py`, `README.md`, `tests/test_run_block.py`.

# 🎯 [NEXT] F42: Support marking sessions as completed (--done) with confirmation before reopening

- Persist session completion state (`"completed": true`, `"completed_at": "<YYYY-MM-DDTHH:MM:SSZ>"`, optional `"completed_note"`) in `<session>/meta.json` via helpers in `src/config.py` (`is_session_completed`, `set_session_completed`), preserving completion fields in `write_session_meta()` and resetting automatically when a session is recreated (`--start --force`).
- Add `run_block --done [session] [-m "<note>"]` in `src/cli.py` and `src/runner.py` (allowed both directly in terminal and inside the final block of a session) and display `[DONE]` status badges in `run_block --list` / `-l`.
- Check session completion before `PLAN` across normal runs (`<session>/<step>`), `--fix`, and `--retry`:
  - Interactive TTY: display a `SESSION COMPLETED` confirmation box (`prompt_yes_no_box`, default `No`); on confirmation (`y`/`Enter`), clear the completion marker in `meta.json` and proceed to `PLAN`, otherwise exit with `NOT RUN`.
  - Non-interactive / headless: auto-reopen and run when `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) is set; otherwise fail with `NOT RUN: session <session> is marked as completed (pass -y/--yes to reopen and run)`.
- Document session completion rules synchronously in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` (bundled via `src/bundles/run_block.bundle`), plus `src/header.py`, `README.md`, and unit tests in `tests/test_run_block.py`.

# 🎯 [NEXT] F54: Remove Steps from END box and add hybrid i(nfo) metadata viewer across TUI blocks

- Depends on: B11
- Remove the `Steps: 1. [tag] ...` summary line from the main `END` box in `build_box_body_lines()` (`src/ui.py`), keeping `END` focused on `Block`, `Workdir`, active `Sandbox`, `Exit`/`Error`/`Fix` on failure, `Output`, and `Stats`.
- Unify detail inspection behind a single `i(nfo)` hotkey across all interactive TUI prompts (`BUNDLE`, `PLAN`, `END`, and confirmation dialogs such as `NOT RUN`, `SYNTAX ERROR`, `STEP ALREADY EXISTS`, `SESSION COMPLETED`) in `src/ui.py`, `src/bundle.py`, and `src/runner.py`:
  - Replace `d(etails)` in `BUNDLE` with `i(nfo)` (`[Enter/e(dit)/i(nfo)/Esc]:` on `BUNDLE` and `END`, `[Y/n/e(dit)/i(nfo)]:` / `[y/n/e(dit)/i(nfo)]:` on `PLAN`).
  - Pressing `i` opens a styled alternate-screen fullscreen `i(nfo)` view showing unfiltered headers (including `Sandbox: off` and all `meta.json` headers), artifact paths and edit backups (`0.orig`, `block.orig.*`, `out.orig`), line/char/token counts with `Stats:` value rendered in white foreground (while keeping inline `Stats:` dimmed in the compact box), full `BUNDLE` `Summary`/`Parts`/warnings breakdown, per-operation execution timings with percentage shares and `(failed)` markers from `<session>/<step>/meta.json` (`src/config.py`), and pre-execution `PLAN` analysis (`analyze_script()` on `block.orig.*` when edited, else `block.*`).
  - Support keyboard scrolling (`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn`), returning cleanly to the active block prompt on `q`/`Esc`/`i` (and `Enter`, or copying on `Enter` in `BUNDLE`/`END` if configured), and opening the plain-text report in the configured viewer/editor (`resolve_editor_command()`) on `v(iew)`.
- Acceptance criteria: `BUNDLE` uses `i(nfo)` instead of `d(etails)`; `END` omits `Steps:`; compact inline boxes stay minimal while `i(nfo)` shows full metadata, white `Stats:`, bundle breakdown, operation timings, and original plan on alternate screen; `v(iew)` opens the external viewer/editor; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F68: Redesign bundle breakdown table in top style, fix header/kind attribution, and highlight heavy parts

- Depends on: F54
- Redesign `Summary` and `Parts` tables in `src/bundle_plan.py` and `src/ui.py` (displayed in fullscreen `i(nfo)` and `--bundle-plan`) with a `top`-inspired column header row showing units once (`%`, `CHARS`, `LINES`, `~TOK`, `KIND`, `SOURCE`) and omitting repeated unit suffixes (`ch`, `L`, `tok`) from data rows while retaining `%` and `~` markers.
- Remove automatic numeric prefixes (`1.`, `2.`, ...) from `Parts` rows in `_collect_hierarchy_rows()` / `_render_bundle_table()` (`src/bundle_plan.py`) so the tree structure stays clean.
- Highlight heavy fragments visually (bold and/or accent/warning color) using clear defaults (e.g. warn/bold at `>= 25%` share or `>= 10k` tokens, accent at `>= 10%` share or `>= 3k` tokens) so dominant context contributors stand out immediately.
- Preserve the white `Stats:` foreground rendering inside fullscreen `i(nfo)` (`src/ui.py`) while keeping `Stats:` dimmed in compact inline boxes (introduced in `F54`).
- Fix `reconcile_bundle_plan()` (`src/bundle_plan.py`) so `[header] Headers & spacing` is computed reliably from `<session>/0` headers and inter-section spacing in `boundary` mode instead of disappearing when raw fragment sums differ due to collapsed blank lines.
- Clarify provenance and `kind` attribution entirely within `src/bundle_plan.py` using existing `Bundle-Boundary` and `chain` metadata (no `agents_bundle` changes required):
  - Display all `chain`-backed container nodes (such as `vitalio/agents-rules:default`, `vitalio/agents-rules:core`) and single-part `bundle` inclusions (`chain != []`, such as `vitalio/agents_bundle`) as `[bundle]` rather than `[rule]`, reserving `[rule]` for leaf rules and direct root `rule` directives (`chain == []`).
  - Clearly separate `.agents_bundle`-originated fragments (boundary-marked rules, root `$ <cmd>` entries, and includes) from non-`.agents_bundle` items (`[header]`, local/appended `[prompt]`, and unframed external stdin sections) via consistent table grouping/labeling.
- Acceptance criteria: `top`-style column header with units, no repeated cell unit suffixes, no `Parts` numeric prefixes, heavy items highlighted, white `Stats:` preserved inside `i(nfo)`, `[header]` visible in `boundary` mode, `.agents_bundle` vs external provenance and `[bundle]` vs `[rule]` kinds clear; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] F64: Record part line ranges and support viewing individual parts by number in Details and CLI

- Depends on: F63, F54, F68
- Record 1-based `line_start` and `line_end` line ranges in the final cleaned `<session>/0` for each part in `src/bundle_plan.py` and `src/bundle.py` (`format_start_bundle()`, `refresh_bundle_plan_meta()`), covering both boundary-marked fragments and `_split_section_fallback()` while accounting for `<session>/0` header lines and collapsed blank lines (and body-relative 1-based ranges for `stdin` `--bundle-plan`) without duplicating fragment text in `meta.json`.
- When `i(nfo)` is active in `BUNDLE` (`src/ui.py`), allow selecting a part directly (e.g. cursor selection in the fullscreen list and/or `p(art)` prompt by 1..N index without cluttering the `Parts` tree with numeric prefixes) to inspect that fragment's content (with an action to open `<session>/0` in the configured editor) and return cleanly to `BUNDLE`.
- Add `--part N` option to `run_block --show` and `run_block --bundle-plan` in `src/cli.py`, `src/runner.py`, `src/bundle_plan.py`, and `src/header.py`; accept `--show <session> --part N`, `--show <session>/0 --part N`, and `--show --part N` (latest session `/0`), failing cleanly on non-zero steps or out-of-range part numbers.
- Update `README.md` and unit tests in `tests/test_run_block.py`, and rebuild `run_block` via `build.py`.

# ⚪ [NEW] F15: Forbid trailing prose after closing fence in block rules

- Tighten Rule 1 in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).
- Rebuild `./run_block` via `build.py` and update `tests/test_run_block.py`.

# ⚪ [NEW] F16: Prevent unintended interactive pagers during block execution

- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Hide `Bundle-Command` from TUI box headers in `src/ui.py` (`HIDDEN_SESSION_HEADER_KEYS`) to avoid noisy or multi-line `-p` headers in `BUNDLE` / `PLAN` / `END`, while preserving it in `meta.json` for `--info`.
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `meta.json`/`0`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers (including `Bundle-Command`) from `meta.json`/`0`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_run_block.py`.

- Note: `HIDDEN_SESSION_HEADER_KEYS` filtering (`src/config.py`, `src/bundle_plan.py`, `src/ui.py`) is already implemented; remaining scope covers `--list` filtering/columns, `--info [session]`, `--show` `--script`/`--out`, and `--retry <session>`.

# ⚪ [NEW] F34: Design workspace state fingerprinting and drift detection across steps

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`PLAN` / `END`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_run_block.py`.

# ⚪ [NEW] F35: Design tamper-evident hash chain and parent-step verification for session history

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_run_block.py`.

# ⚪ [NEW] F36: Design pre-flight sandbox dry-run preview via temporary git worktree

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `PLAN` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_run_block.py`.

# ⚪ [NEW] F37: Design session execution policies and post-step revert guards

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate declarative session-level execution constraints in `meta.json` / `.agents_bundle` (`src/bundle.py`, `src/config.py`), such as allowed write path globs, maximum modified file count, or network-access restrictions.
- Define enforcement and rollback semantics in `src/runner.py` and `src/safety.py` (pre-execution policy checks plus post-step diff verification with automatic revert on violation) and cover with `tests/test_run_block.py`.

# ⚪ [NEW] F38: Design explicit parent-step DAG lineage for session branches and retries

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_run_block.py`.

# ⚪ [NEW] B8: Preserve stdout/stderr interleaving order in captured out after separate stderr capture

- Since the separate stderr capture, `src/runner.py` reads stdout and stderr via two descriptors on two reader threads (`_iter_child_streams`), so the order of lines in `step_dir / "out"` follows read timing instead of write order; previously the shared PTY descriptor kept the exact write order in interactive mode.
- Impact on the model: a traceback or diagnostic may be separated from the command that produced it, and `__RB_STEP__` progress markers (stdout) may drift relative to stderr lines of the same step, which can mislead error attribution in long blocks with interleaved output.
- Reproduce first with a unit test that interleaves `echo` and `echo >&2` in a loop and compares the order in `out` with the write order; then pick an approach (for example keep one shared descriptor for `out` and obtain `err` separately, such as a per-command stderr tee in the instrumented script, or accept and document the ordering limits).
- After the approach is decided, document the `err` file and the ordering guarantees in `README.md` (step directory contents: `out`, `err`, `error`, `aborted`) and keep `AGENTS.md` in sync in the same commit.

# ⚪ [NEW] F48: Design machine-readable runner contract (--json step output and plan/execute handshake)

- Role: design
- Design candidate for `role=design` to let an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Evaluate structured `--json` execution output for `<session>/<step>` (status: `ok`/`syntax_error`/`not_run`/`completed`, `exit_code`, safety findings, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` non-TTY handshake, and env sanitization so client LLM API keys do not leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⚪ [NEW] F67: Remove obsolete src/bundles/run_block.bundle export and bundle references

- Depends on: F66
- Delete `src/bundles/run_block.bundle` (and empty `src/bundles/`) and remove `bundle vitalio/run_block` from `.agents_bundle` once downstream repositories stop referencing `vitalio/run_block`.
- Update `AGENTS.md` (documenting `src/rules/blocks/*.md` as internal embedded sources instead of an exported `vitalio/run_block` bundle), `README.md`, and `tests/test_run_block.py`.

# ⚪ [NEW] F70: Support model-aware token counting once model API integration is added

- Future enhancement (blocked on model API integration): replace the current fixed `tiktoken` (`o200k_base`) / char-heuristic (`~lo–hi tokens`) estimator in `src/ui.py` and `src/bundle_plan.py` with model-specific token counting (provider tokenizer or count-tokens API) based on the active selected model.
- Retain offline stdlib/local heuristic fallback when no model API or tokenizer is configured.
