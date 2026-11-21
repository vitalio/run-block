# 🎯 [NEXT] B12: Stabilize flaky test_f56_progress_alignment_colors_and_silent_collapse (stdout/stderr ordering in live progress output)

Intermittent failure observed in `tests/test_ui.py` `test_f56_progress_alignment_colors_and_silent_collapse`: the `live_e2e` assertion expects `hello_f56` directly followed by the `✓ [2/3] (` line, but `err_f56` from the next operation (`echo err_f56 >&2`) sometimes appears in between.
- Suspected cause (unconfirmed): ordering race between separately read child `stdout` and `stderr` descriptors merged into `out` in `src/runner.py`.
- Step 1: read the stream merge and progress rendering in `src/runner.py`, reproduce with a loop of about 30 runs of the single test.
- Step 2: if cross-stream ordering is intentionally not guaranteed, relax the test; if it is an output defect, fix `src/runner.py` and keep the assertion.
- Acceptance criteria: 50 consecutive isolated runs of the test pass; full offline suite passes.

# 🎯 [NEXT] D1: Design session lifecycle states, step outcome labels, and run_block -l display

- Depends on: F42
- Design candidate for `role=design` (coordinates with `F42` `--done` / `END SESSION` session completion, `F71` `START SESSION`/`START STEP`/`END STEP` lifecycle naming, and `F20` session inspection CLI).
- Problem: `cmd_list()` and `_step_status()` in `src/runner.py` parse the trailing `[sN/k] END` output marker of the last script in `_iter_session_scripts(sdir)` and render `last: sN/k (END)`, conflating individual step completion with overall session completion and obscuring whether a session is still active or finished.
- Define clear separation between:
  1. Step execution outcome (`ok`, `exit <rc>`, `not-run`, `syntax-error`, `aborted`, `saved`) derived from structured step metadata or output markers without overloading `END`.
  2. Session lifecycle state (`active` / `bundle-only` / `done` via `<session>/meta.json` `completed` and accumulated `"stats"` from `F42`), `END SESSION` summary metrics, and next actionable step (`Next-Block: sN/<k>`).
  3. Consistent `run_block -l` / `--list` and `--info` formatting across summary rows and recent-block listings (including fix-step ordering and optional `Task` / `Workdir` context).
- Target files for downstream implementation: `src/runner.py`, `src/config.py`, `src/ui.py`, `src/cli.py`, `src/header.py`, `README.md`, `tests/test_runner.py`, `tests/test_cli.py`.

# 🎯 [NEXT] F74: Diagnose broken blocks, root-cause errors, and interactively repair --fix anchors

- Depends on: F57, B8
- Diagnose `--fix` anchor mismatches in `_format_fix_exception()` and `cmd_fix()` (`src/runner.py`): when `assert text.count(old) == 1` fails with `actual: 0 == 1` (or `fix made no changes`), inspect `old` against `text` using `difflib.SequenceMatcher` over matching line windows and append a concrete `Hint:` line to `NOT RUN` (`not_run_exit()`) showing the closest match, line number in `block.*`, and similarity score.
- Detect common `--fix` authoring mistakes in `cmd_fix()` (`src/runner.py`): report explicit hints when `old` is absent from `block.*` but exists in a repository file referenced by the target script (guiding the agent to emit a fresh `<session>/<step+1>` block instead of `--fix`), when `old.rstrip("\n")` matches once (trailing newline mismatch), when `old` matches multiple times (`actual: N == 1`), or when top-level `text.replace(...)` / `re.sub(...)` is called without assigning back to `text = ...`.
- Offer interactive anchor repair in `NOT RUN` (`src/runner.py`, `src/ui.py` `offer_clipboard_copy()`): when running in an interactive TTY and a single unambiguous high-confidence anchor match is found in `block.*` (`>= 0.85` similarity with clear margin over the runner-up), display a compact diff (`old` -> matched line) and allow accepting the replacement (`f(ix)` / `i(nfo)`), re-evaluating `fix.py` in memory, and proceeding straight into `START STEP` without an extra agent turn; never auto-apply fuzzy replacements in headless `-y` mode or on ambiguous matches.
- Improve root-cause `Error:` extraction and failure hints in `END STEP` (`src/runner.py` `run_script()`): parse structured `Traceback` / `AssertionError` / `SyntaxError` (`file:line` and exception summary) from captured `stderr` instead of showing only generic runner tails like `FAILED (failures=1)`, and when `AssertionError: '<needle>' not found in ...` occurs, surface the closest matching line from the captured output.
- Add code-context snippets (`+-2` lines) and escaping hints on `SyntaxError` / `IndentationError` in `--fix` (`cmd_fix()`) and shell/heredoc syntax failures (`_validate_step_script_syntax()` in `src/runner.py`, `src/safety.py`), including truncated heredoc or accidental fence/delimiter breakages.
- Coordinate prompt keys and box titles with `F71` (`START STEP` / `END STEP` and `[Y/n/...]` conventions) and `F54` (`i(nfo)` unified viewer).
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `README.md`, `tests/test_runner.py`, `tests/test_ui.py`.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Depends on: D1
- Hide `Bundle-Command` from TUI box headers in `src/ui.py` (`HIDDEN_SESSION_HEADER_KEYS`) to avoid noisy or multi-line `-p` headers in `START SESSION` / `START STEP` / `END STEP`, while preserving it in `meta.json` for `--info`.
- Extend `--list` / `-l` in `src/cli.py` and `src/runner.py` with filtering by `Workdir`/path or query substring, and display session `Workdir`, `Role`/`Task` headers from `meta.json`/`0`, block count, size, timestamp, and last step status.
- Add `--info [session]` (and `--show <session>` without step number) to display all parsed headers (including `Bundle-Command`) from `meta.json`/`0`, storage path, total size, and full block list with statuses and action summaries.
- Enhance `--show` to accept `<session>`, `<session>/0` (bundle), or `<session>/<step>`, with optional `--script` or `--out` flags to print only the script or only the output.
- Enhance `--retry` to accept either `<session>/<step>` or `<session>` (re-running the latest block of that session) and update `src/header.py`, `README.md`, and `tests/test_runner.py` and `tests/test_cli.py`.

- Note: `HIDDEN_SESSION_HEADER_KEYS` filtering (`src/config.py`, `src/bundle_plan.py`, `src/ui.py`) is already implemented; remaining scope covers `--list` filtering/columns, `--info [session]`, `--show` `--script`/`--out`, and `--retry <session>`.

# ⚪ [NEW] F72: Rename project to run-block and CLI utility to rxb

- Rename project/repository references from `run_block` to `run-block` and CLI entrypoint from `run_block` to `rxb` (updating embedded block rules, protocol markers, and env vars/compatibility aliases per the ecosystem rename design).
- Target files: `build.py`, `install.sh`, `install.ps1`, `src/cli.py`, `src/header.py`, `src/config.py`, `src/runner.py`, `src/bundle.py`, `src/bundle_plan.py`, `src/safety.py`, `src/ui.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `.agents_bundle`, `AGENTS.md`, `README.md`, `VERSION`, `tests/helpers.py`, `tests/test_*.py`, and `.github/`.
- Acceptance criteria: `build.py` outputs `rxb`, `install.sh`/`install.ps1` install `rxb` (plus any agreed compatibility alias), `--help`/embedded rules/docs/tests reflect `run-block` and `rxb`, and `python3 -m unittest discover -s tests` passes.

# ⚪ [NEW] B8: Preserve stdout/stderr interleaving order in captured out after separate stderr capture

- Depends on: B12
- Since the separate stderr capture, `src/runner.py` reads stdout and stderr via two descriptors on two reader threads (`_iter_child_streams`), so the order of lines in `step_dir / "out"` follows read timing instead of write order; previously the shared PTY descriptor kept the exact write order in interactive mode.
- Impact on the model: a traceback or diagnostic may be separated from the command that produced it, and `__RB_STEP__` progress markers (stdout) may drift relative to stderr lines of the same step, which can mislead error attribution in long blocks with interleaved output.
- Reproduce first with a unit test that interleaves `echo` and `echo >&2` in a loop and compares the order in `out` with the write order; then pick an approach (for example keep one shared descriptor for `out` and obtain `err` separately, such as a per-command stderr tee in the instrumented script, or accept and document the ordering limits).
- After the approach is decided, document the `err` file and the ordering guarantees in `README.md` (step directory contents: `out`, `err`, `error`, `aborted`) and keep `AGENTS.md` in sync in the same commit.

# ⚪ [NEW] D3: Prevent unintended interactive pagers during block execution

- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ⚪ [NEW] D4: Design workspace state fingerprinting and drift detection across steps

- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] D6: Design session execution policies and post-step revert guards

- Depends on: D4
- Evaluate declarative session-level execution constraints in `meta.json` / `.agents_bundle` (`src/bundle.py`, `src/config.py`), such as allowed write path globs, maximum modified file count, or network-access restrictions.
- Define enforcement and rollback semantics in `src/runner.py` and `src/safety.py` (pre-execution policy checks plus post-step diff verification with automatic revert on violation) and cover with `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D7: Design pre-flight sandbox dry-run preview via temporary git worktree

- Depends on: D6
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D8: Design explicit parent-step DAG lineage for session branches and retries

- Depends on: D5
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] D9: Design machine-readable runner contract (--json step output and plan/execute handshake)

- Depends on: F79
- Design contract to let an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Evaluate structured `--json` execution output for `<session>/<step>` (status: `ok`/`syntax_error`/`not_run`/`completed`, `exit_code`, safety findings, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` non-TTY handshake, and env sanitization so client LLM API keys do not leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⏸️ [HOLD] F70: Support model-aware token counting once model API integration is added — *Waiting on built-in model API transport (todo_flow:D5)*

- Future enhancement (blocked on model API integration in `todo_flow:D5`): extend the pre-flight stdlib `~lo–hi tokens` estimator in `src/ui.py` (`count_tokens()`, `format_stats()`) and `src/bundle_plan.py` (`analyze_bundle_plan()`) with model-aware token accounting:
  - Keep fast offline stdlib heuristic estimation for pre-flight TUI cards (`START SESSION`, `START STEP`, `END STEP`, `--bundle-plan`) before a request is sent to the model.
  - Record exact post-turn token usage (`input_tokens`, `output_tokens`, cache read/write tokens) returned by the provider API response in `<session>/chat.json` and `<session>/meta.json`, and surface optional provider `count_tokens` / profile-tuned pre-flight estimates when an API profile is active.
