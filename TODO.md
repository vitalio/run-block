# 🎯 [NEXT] F69: Preserve boundary markup during bundle e(dit) and count clean bundle size without markers

- Preserve the raw boundary-annotated bundle source (e.g. in `<session>/0.raw` or an editable staging file) during `format_start_bundle()` and `cmd_start()` (`src/bundle.py`, `src/bundle_plan.py`, `src/config.py`) instead of stripping `<!-- bundle:<nonce>:part ... -->` / `<!-- bundle:<nonce>:end -->` markers irreversibly on initialization.
- When `e(dit)` is triggered on `START SESSION` (`BUNDLE` before `F71`, inline or via `i(nfo)` in `F54`, `src/ui.py`), open the markup-preserving editable content so manual edits preserve fragment boundaries, then re-parse with `parse_bundle_fragments()` and update both the raw source and clean `<session>/0`.
- Compute `Stats:`, `bundle_plan`, and clipboard content strictly from the clean stripped text (excluding boundary marker comments), and finalize `<session>/0` without boundary markers on disk once `START SESSION` exits (`Y`/`Enter`, `n`/`Esc`, or non-interactive mode), keeping `0.orig` backup and `F57` `a(ppend)` compatibility intact.
- Acceptance criteria: editing a boundary-annotated bundle via `e(dit)` preserves full `Summary`/`Parts` fragment detail instead of collapsing to fallback sections; `Stats:` counts clean content without marker comments; final `<session>/0` contains no boundary markup; offline tests in `tests/test_run_block.py` verify the roundtrip.

- Coordinate with `F66`: preserve `<session>/0.raw` after embedded block-rule injection (or keep re-parsing idempotent) so `e(dit)` neither drops nor duplicates `run_block:blocks/*`.

# 🎯 [NEXT] F57: Add a(ppend) prompt editor action across clipboard TUI cards (START SESSION, END STEP, SYNTAX ERROR, NOT RUN)

- Add a shared `a(ppend)` action across all clipboard-copy prompts (`START SESSION`, `END STEP`, `SYNTAX ERROR`, `NOT RUN`) in `src/ui.py`, `src/bundle.py`, and `src/runner.py` (`[Y/n/a(ppend)/...]:` or compatible prompt suffix), recognizing `a`/`A` (and `append` in line-input mode).
- On `a(ppend)`, open an empty temporary `.md` file in the configured editor (`resolve_editor_command()` in `src/ui.py`), remove the temporary file on exit, and abort cleanly without modifying the target file or creating a `.orig` backup when the entered text is empty or whitespace-only.
- Before the first non-empty append, preserve the original file via `_write_orig_backup_once()` (`0.orig` for `START SESSION`, `out.orig` for step output cards), then append the text:
  - In `START SESSION`: append into the trailing `===== Prompt =====` section of `<session>/0` (creating it if absent) and call `refresh_bundle_meta()`.
  - In `END STEP`, `SYNTAX ERROR`, and `NOT RUN`: append the user note/question to the clipboard target output (`out`) and refresh clipboard command/target if needed.
- Recalculate line/byte/token `Stats:` with the `(edited)` marker and redraw the box in place so pressing `Enter`/`y` copies the updated content to the clipboard.
- Acceptance criteria: `a(ppend)` works uniformly across `START SESSION`, `END STEP`, `SYNTAX ERROR`, and `NOT RUN`; empty input leaves files and `.orig` backups untouched; `.orig` is saved once and `Stats:` updates with `(edited)`; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# 🎯 [NEXT] D2: Design nested run_block contract (IN_RUN_BLOCK=1) for session initialization and subcommand guards

- Design candidate for `role=design` (coordinates with `F42` and `F48`).
- Problem: when a block executes `<cmd> | run_block` inside an active step (e.g., `todo_md F21 | agents_bundle role=work | run_block` inside `s53/1`), `IN_RUN_BLOCK=1` disables clipboard copy and prints the inner `START SESSION` (`BUNDLE`) box inside the outer step's `[s53/1] START ... [s53/1] END` output, leaving outer wrappers around the new bundle and lacking an explicit contract for nested `run_block` invocations.
- Define the behavior matrix when `IN_RUN_BLOCK=1` (and optional `RUN_BLOCK_PARENT_SESSION` / `RUN_BLOCK_PARENT_STEP` env metadata):
  1. Subcommand guards: allow read-only inspection (`--list`, `--show`, `--info`, `--bundle-plan`) and completing the current session (`--done` / `END SESSION`), while blocking recursive step execution (`<session>/<step>`, `--fix`, `--retry`) unless explicitly overridden.
  2. Nested session initialization (`<cmd> | run_block` / `--start`): specify console framing, clipboard handoff policy (copying the spawned `<session>/0` bundle vs suppressing outer step clipboard copy), and `parent_session` / `spawned_sessions` linkage in `<session>/meta.json`.
  3. Headless / machine-readable (`--json` in `F48`) interaction when a step spawns a child session.
- Target files for downstream implementation: `src/bundle.py`, `src/runner.py`, `src/config.py`, `src/cli.py`, `src/ui.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, `tests/test_run_block.py`.

- Concrete reproduction scenario: running a nested session initializer inside an active step (`todo_md <ID> | agents_bundle role=execute | run_block`) prints the inner `START SESSION` (`BUNDLE`) box (`<child>/0`) inside the outer `[sN/k] START ... [sN/k] END` block output, skips copying `<child>/0` to the clipboard because `IN_RUN_BLOCK=1`, and then triggers the outer `END STEP` (`END`) box's `-> Copy to clipboard?` prompt for the outer step log (with `[sN/k]` wrappers) instead of copying the clean `<child>/0` bundle and suppressing the outer clipboard prompt.

# 🎯 [NEXT] D1: Design session lifecycle states, step outcome labels, and run_block -l display

- Design candidate for `role=design` (coordinates with `F42` `--done` / `END SESSION` session completion, `F71` `START SESSION`/`START STEP`/`END STEP` lifecycle naming, and `F20` session inspection CLI).
- Problem: `cmd_list()` and `_step_status()` in `src/runner.py` parse the trailing `[sN/k] END` output marker of the last script in `_iter_session_scripts(sdir)` and render `last: sN/k (END)`, conflating individual step completion with overall session completion and obscuring whether a session is still active or finished.
- Define clear separation between:
  1. Step execution outcome (`ok`, `exit <rc>`, `not-run`, `syntax-error`, `aborted`, `saved`) derived from structured step metadata or output markers without overloading `END`.
  2. Session lifecycle state (`active` / `bundle-only` / `done` via `<session>/meta.json` `completed` and accumulated `"stats"` from `F42`), `END SESSION` summary metrics, and next actionable step (`Next-Block: sN/<k>`).
  3. Consistent `run_block -l` / `--list` and `--info` formatting across summary rows and recent-block listings (including fix-step ordering and optional `Task` / `Workdir` context).
- Target files for downstream implementation: `src/runner.py`, `src/config.py`, `src/ui.py`, `src/cli.py`, `src/header.py`, `README.md`, `tests/test_run_block.py`.

# 🎯 [NEXT] F42: Support marking sessions as completed (--done) with confirmation before reopening

- Persist session completion state (`"completed": true`, `"completed_at": "<YYYY-MM-DDTHH:MM:SSZ>"`, optional `"completed_note"`) and accumulated session statistics (`"stats"`: total steps, ok/failed/`--fix`/renumbered counts, total execution `duration_ms`, started/completed timestamps) in `<session>/meta.json` via helpers in `src/config.py` (`is_session_completed`, `set_session_completed`, `update_session_stats`), preserving completion and stats fields in `write_session_meta()` and resetting automatically when a session is recreated (`--start --force`).
- Add `run_block --done [session] [-m "<note>"]` in `src/cli.py` and `src/runner.py` (allowed both directly in terminal and inside the final block of a session), render an `END SESSION` summary card displaying the accumulated session statistics, and show `[DONE]` status badges in `run_block --list` / `-l`.
- Check session completion before `START STEP` (`PLAN`) across normal runs (`<session>/<step>`), `--fix`, and `--retry`:
  - Interactive TTY: display a `SESSION COMPLETED` confirmation box (`-> Reopen session <session>? [y/N/i(nfo)]:` / `prompt_yes_no_box`, default `No`); on confirmation (`y`), clear the completion marker in `meta.json` and proceed directly into `START STEP`, otherwise exit with `NOT RUN`.
  - Non-interactive / headless: auto-reopen and run when `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) is set; otherwise fail with `NOT RUN: session <session> is marked as completed (pass -y/--yes to reopen and run)`.
- Document `END SESSION` and session completion rules synchronously in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md`, plus `src/header.py`, `README.md`, and unit tests in `tests/test_run_block.py`.

# ⚪ [NEW] F15: Forbid trailing prose after closing fence in block rules

- Tighten Rule 1 in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).
- Rebuild `./run_block` via `build.py` and update `tests/test_run_block.py`.

# ⚪ [NEW] F16: Prevent unintended interactive pagers during block execution

- Role: design
- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Role: plan
- Hide `Bundle-Command` from TUI box headers in `src/ui.py` (`HIDDEN_SESSION_HEADER_KEYS`) to avoid noisy or multi-line `-p` headers in `START SESSION` / `START STEP` / `END STEP`, while preserving it in `meta.json` for `--info`.
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `meta.json`/`0`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers (including `Bundle-Command`) from `meta.json`/`0`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_run_block.py`.

- Note: `HIDDEN_SESSION_HEADER_KEYS` filtering (`src/config.py`, `src/bundle_plan.py`, `src/ui.py`) is already implemented; remaining scope covers `--list` filtering/columns, `--info [session]`, `--show` `--script`/`--out`, and `--retry <session>`.

# ⚪ [NEW] F34: Design workspace state fingerprinting and drift detection across steps

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_run_block.py`.

# ⚪ [NEW] F35: Design tamper-evident hash chain and parent-step verification for session history

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_run_block.py`.

# ⚪ [NEW] F36: Design pre-flight sandbox dry-run preview via temporary git worktree

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_run_block.py`.

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

- Role: plan
- Since the separate stderr capture, `src/runner.py` reads stdout and stderr via two descriptors on two reader threads (`_iter_child_streams`), so the order of lines in `step_dir / "out"` follows read timing instead of write order; previously the shared PTY descriptor kept the exact write order in interactive mode.
- Impact on the model: a traceback or diagnostic may be separated from the command that produced it, and `__RB_STEP__` progress markers (stdout) may drift relative to stderr lines of the same step, which can mislead error attribution in long blocks with interleaved output.
- Reproduce first with a unit test that interleaves `echo` and `echo >&2` in a loop and compares the order in `out` with the write order; then pick an approach (for example keep one shared descriptor for `out` and obtain `err` separately, such as a per-command stderr tee in the instrumented script, or accept and document the ordering limits).
- After the approach is decided, document the `err` file and the ordering guarantees in `README.md` (step directory contents: `out`, `err`, `error`, `aborted`) and keep `AGENTS.md` in sync in the same commit.

# ⚪ [NEW] F48: Design machine-readable runner contract (--json step output and plan/execute handshake)

- Role: design
- Design candidate for `role=design` to let an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Evaluate structured `--json` execution output for `<session>/<step>` (status: `ok`/`syntax_error`/`not_run`/`completed`, `exit_code`, safety findings, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` non-TTY handshake, and env sanitization so client LLM API keys do not leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⚪ [NEW] F70: Support model-aware token counting once model API integration is added

- Role: work
- Future enhancement (blocked on model API integration in `todo_flow:D5`): extend the pre-flight stdlib `~lo–hi tokens` estimator in `src/ui.py` (`count_tokens()`, `format_stats()`) and `src/bundle_plan.py` (`analyze_bundle_plan()`) with model-aware token accounting:
  - Keep fast offline stdlib heuristic estimation for pre-flight TUI cards (`START SESSION`, `START STEP`, `END STEP`, `--bundle-plan`) before a request is sent to the model.
  - Record exact post-turn token usage (`input_tokens`, `output_tokens`, cache read/write tokens) returned by the provider API response in `<session>/chat.json` and `<session>/meta.json`, and surface optional provider `count_tokens` / profile-tuned pre-flight estimates when an API profile is active.

# ⚪ [NEW] F72: Rename project to run-block and CLI utility to rxb

- Role: plan
- Rename project/repository references from `run_block` to `run-block` and CLI entrypoint from `run_block` to `rxb` (updating embedded block rules, protocol markers, and env vars/compatibility aliases per the ecosystem rename design).
- Target files: `build.py`, `install.sh`, `install.ps1`, `src/cli.py`, `src/header.py`, `src/config.py`, `src/runner.py`, `src/bundle.py`, `src/bundle_plan.py`, `src/safety.py`, `src/ui.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `.agents_bundle`, `AGENTS.md`, `README.md`, `VERSION`, `tests/test_run_block.py`, and `.github/`.
- Acceptance criteria: `build.py` outputs `rxb`, `install.sh`/`install.ps1` install `rxb` (plus any agreed compatibility alias), `--help`/embedded rules/docs/tests reflect `run-block` and `rxb`, and `tests/test_run_block.py` passes.

# ⚪ [NEW] F74: Diagnose broken blocks, root-cause errors, and interactively repair --fix anchors

- Diagnose `--fix` anchor mismatches in `_format_fix_exception()` and `cmd_fix()` (`src/runner.py`): when `assert text.count(old) == 1` fails with `actual: 0 == 1` (or `fix made no changes`), inspect `old` against `text` using `difflib.SequenceMatcher` over matching line windows and append a concrete `Hint:` line to `NOT RUN` (`not_run_exit()`) showing the closest match, line number in `block.*`, and similarity score.
- Detect common `--fix` authoring mistakes in `cmd_fix()` (`src/runner.py`): report explicit hints when `old` is absent from `block.*` but exists in a repository file referenced by the target script (guiding the agent to emit a fresh `<session>/<step+1>` block instead of `--fix`), when `old.rstrip("\n")` matches once (trailing newline mismatch), when `old` matches multiple times (`actual: N == 1`), or when top-level `text.replace(...)` / `re.sub(...)` is called without assigning back to `text = ...`.
- Offer interactive anchor repair in `NOT RUN` (`src/runner.py`, `src/ui.py` `offer_clipboard_copy()`): when running in an interactive TTY and a single unambiguous high-confidence anchor match is found in `block.*` (`>= 0.85` similarity with clear margin over the runner-up), display a compact diff (`old` -> matched line) and allow accepting the replacement (`f(ix)` / `i(nfo)`), re-evaluating `fix.py` in memory, and proceeding straight into `START STEP` without an extra agent turn; never auto-apply fuzzy replacements in headless `-y` mode or on ambiguous matches.
- Improve root-cause `Error:` extraction and failure hints in `END STEP` (`src/runner.py` `run_script()`): parse structured `Traceback` / `AssertionError` / `SyntaxError` (`file:line` and exception summary) from captured `stderr` instead of showing only generic runner tails like `FAILED (failures=1)`, and when `AssertionError: '<needle>' not found in ...` occurs, surface the closest matching line from the captured output.
- Add code-context snippets (`+-2` lines) and escaping hints on `SyntaxError` / `IndentationError` in `--fix` (`cmd_fix()`) and shell/heredoc syntax failures (`_validate_step_script_syntax()` in `src/runner.py`, `src/safety.py`), including truncated heredoc or accidental fence/delimiter breakages.
- Coordinate prompt keys and box titles with `F71` (`START STEP` / `END STEP` and `[Y/n/...]` conventions) and `F54` (`i(nfo)` unified viewer).
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `README.md`, `tests/test_run_block.py`.

# ⚪ [NEW] B12: Stabilize flaky test_f56_progress_alignment_colors_and_silent_collapse (stdout/stderr ordering in live progress output)

- Role: work
Intermittent failure observed in `tests/test_run_block.py` `test_f56_progress_alignment_colors_and_silent_collapse`: the `live_e2e` assertion expects `hello_f56` directly followed by the `✓ [2/3] (` line, but `err_f56` from the next operation (`echo err_f56 >&2`) sometimes appears in between.
- Suspected cause (unconfirmed): ordering race between separately read child `stdout` and `stderr` descriptors merged into `out` in `src/runner.py`.
- Step 1: read the stream merge and progress rendering in `src/runner.py`, reproduce with a loop of about 30 runs of the single test.
- Step 2: if cross-stream ordering is intentionally not guaranteed, relax the test; if it is an output defect, fix `src/runner.py` and keep the assertion.
- Acceptance criteria: 50 consecutive isolated runs of the test pass; full offline suite passes.

# ⚪ [NEW] F77: Select a part with the cursor in the START SESSION i(nfo) Parts list instead of typing its number

- Role: work
- Context: `p(art)` in the `START SESSION` `i(nfo)` viewer asks for a part number (`_read_part_number`, `_browse_parts` in `src/ui.py`), but the `Parts` tree shows no numbers and its order (bundle/external groups, chain nesting from `_collect_hierarchy_rows` in `src/bundle_plan.py`) differs from the plan `index` order, so users cannot tell which number to type.
- Add a cursor mode to the `Parts` list in `_build_info_screen` / `_show_info_fullscreen`: `p(art)` enters the mode, `Up`/`Down` (`j`/`k`) move a highlighted row, `Enter` opens that part in the existing part viewer (`_build_part_screen`), `Esc` returns to plain scrolling. Group/bundle node rows with several children are skipped or open their first part.
- Carry the part `index` on the table row dicts built by `_make_table_row` so a highlighted row maps to `extract_bundle_part`, without adding numeric prefixes to the tree; keep `PART N/M` in the viewer title and `n`/`N` browsing.
- Keep the numeric prompt only if it stays cheap (fallback for narrow terminals); update `README.md` `i(nfo)` description and unit tests in `tests/test_run_block.py`, rebuild `run_block` via `build.py`. Release as `PATCH`.
