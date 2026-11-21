# 🎯 [NEXT] F82: Support Bundle-Protocol: 1, task/context fragment kinds, and RUN_BLOCK_STEP_STDOUT_INO

- Implement the Runner side of `context-bundle-protocol` v1 per `todo_flow` `docs/adr/0002-context-bundle-protocol-and-self-contained-producers.md`:
  - Move `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` to `agents/blocks/bash.md` and `agents/blocks/pwsh.md` (updating `build.py` and `get_embedded_block_rule()` in `src/bundle_plan.py`) so all tool rule files reside under the canonical root `agents/` directory.
  - In `src/bundle_plan.py`, support `Bundle-Protocol: 1` in transport headers and handle `"task"` and `"context"` fragment `kind` values across `parse_bundle_fragments()`, `inject_embedded_prompt()` (appending CLI `-p` prompts cleanly after upstream `"task"`/`"context"` fragments in `===== Prompt =====`), `_collect_hierarchy_rows()`, and `analyze_bundle_warnings()`.
  - In `src/runner.py`, export `RUN_BLOCK_STEP_STDOUT_INO` (`f"{st.st_dev}:{st.st_ino}"` of the step capture stdout pipe) in the child step environment so upstream producers (`todo_md`) distinguish direct step console output (`todo_md <ID>`) from a shell pipeline inside a step (`todo_md <ID> | agents_bundle | run_block`).
  - Target files: `src/bundle_plan.py`, `src/runner.py`, `agents/blocks/bash.md`, `agents/blocks/pwsh.md`, `build.py`, `AGENTS.md`, `README.md`, `tests/test_bundle.py`, `tests/test_runner.py`.

# 🎯 [NEXT] B8: Preserve stdout/stderr interleaving order in captured out after separate stderr capture

- Depends on: B12, F80
- Since separate `stderr` capture was introduced, `_iter_child_streams()` in `src/runner.py` reads `stdout` and `stderr` from two separate descriptors, so lines in `<session>/<step>/out` can follow descriptor read timing rather than exact write order when fast interleaved output occurs.
- Reproduce with a deterministic unit test in `tests/test_runner.py` that interleaves `stdout` and `stderr` lines alongside `__RB_STEP__` markers in `_prepare_progress_script()` and `run_script()` (`src/runner.py`).
- Preserve write-order interleaving in `<session>/<step>/out` while still capturing `<session>/<step>/err` for root-cause `Error:` extraction in `END STEP` (`run_script()` in `src/runner.py`).
- Document `<session>/<step>/out`, `err`, `error`, `aborted`, and `meta.json` ordering and artifact guarantees in `README.md` and `AGENTS.md`.
- Target files: `src/runner.py`, `README.md`, `AGENTS.md`, `tests/test_runner.py`.

# 🎯 [NEXT] F85: Export non-interactive pager defaults in child step execution environment

- Depends on: D3
- Bump: `MINOR`
- In `src/config.py`, define canonical `CHILD_PAGER_ENV_VARS = ("PAGER", "GIT_PAGER", "GH_PAGER", "MANPAGER", "SYSTEMD_PAGER", "BAT_PAGER", "AWS_PAGER", "PSQL_PAGER", "DELTA_PAGER")` and add `get_setting("pager")` reading `RUN_BLOCK_PAGER` (default `"cat"`; values `"0"`, `"false"`, `"no"`, `"off"`, `"inherit"`, `"keep"`, `"passthrough"` return `""` to preserve the parent environment's pager variables unchanged).
- In `src/runner.py` (`run_script()`), populate `CHILD_PAGER_ENV_VARS` with `get_setting("pager")[0]` in `child_env` (when non-empty, overriding parent `os.environ` pager variables before `scrub_child_env()`) so TTY-aware commands (`git diff`, `git log`, `gh api`, `man`, `systemctl`, `bat`, etc.) never stall inside `run_block`'s PTY while keeping `/dev/tty` `stdin` attached for intentional human-in-the-loop prompts.
- Document `RUN_BLOCK_PAGER=cat|inherit` in `src/header.py` (`--help` `Environment:` section aligned to column width invariants) and the `Environment Variables` table in `README.md`.
- Add unit tests in `tests/test_runner.py` and `tests/test_cli.py` covering default `CHILD_PAGER_ENV_VARS` injection (`cat`), custom `RUN_BLOCK_PAGER` override, `RUN_BLOCK_PAGER=inherit` / `off` passthrough, and `--help` alignment.
- Target files: `src/config.py:23-116`, `src/runner.py:945-960`, `src/header.py:24-35`, `README.md:245-270`, `tests/test_runner.py`, `tests/test_cli.py`.

# 🎯 [NEXT] F74: Diagnose broken blocks, root-cause errors, and interactively repair --fix anchors

- Depends on: F57, B8, F81
- Harden `_reassemble_split_payload()`, `cmd_normal()`, and `cmd_fix()` in `src/runner.py` against broken or duplicated blocks:
  - Stop at the first matching closing heredoc terminator (`RUN_BLOCK` or `RUN_FIX`) rather than scanning backward from the end so two blocks pasted together are never merged with intermediate prose into a corrupt script.
  - Automatically deduplicate identical repeated blocks, strip accidental nested `run_block <s/n> <<'RUN_BLOCK' ... RUN_BLOCK` wrappers or trailing/indented fence debris, recover missing closing terminators before a final closing fence, and detect when a `--fix` payload contains a fresh shell script instead of a Python `text` patch (offering to run it as the next sequential step `<session>/<next_step>`).
- Diagnose `--fix` and file-edit anchor mismatches in `_format_fix_exception()` and `cmd_fix()` (`src/runner.py`): when `assert text.count(old) == 1` fails with `actual: 0 == 1` (or `fix made no changes`), inspect `old` against `text` using `difflib.SequenceMatcher` over matching line windows and append a concrete `Hint:` line to `NOT RUN` (`not_run_exit()`) showing the closest match, line number, and similarity score.
- Detect common `--fix` authoring mistakes in `cmd_fix()` (`src/runner.py`): report explicit hints when `old` is absent from `block.*` but exists in a repository file referenced by the target script (guiding the agent to emit a fresh `<session>/<step+1>` block instead of `--fix`), when `old.rstrip("\n")` matches once (trailing newline mismatch), when `old` matches multiple times (`actual: N == 1`), or when top-level `text.replace(...)` / `re.sub(...)` is called without assigning back to `text = ...`.
- Offer interactive anchor repair in `NOT RUN` (`src/runner.py`, `src/ui.py` `offer_clipboard_copy()`): when running in an interactive TTY and a single unambiguous high-confidence anchor match is found (`>= 0.85` similarity with clear margin over the runner-up), display a compact diff (`old` -> matched line) and allow accepting the replacement (`f(ix)` / `i(nfo)`), re-evaluating in memory, and proceeding straight into `START STEP` without an extra agent turn; never auto-apply fuzzy replacements in headless `-y` mode or on ambiguous matches.
- Improve root-cause `Error:` extraction and failure hints in `END STEP` (`src/runner.py` `run_script()`): parse structured `Traceback` / `AssertionError` / `SyntaxError` (`file:line` and exception summary) from captured `stderr` instead of showing only generic runner tails like `FAILED (failures=1)`, and when `AssertionError: '<needle>' not found in ...` occurs, surface the closest matching line from the captured output.
- Add code-context snippets (`+-2` lines) and escaping hints on `SyntaxError` / `IndentationError` in `--fix` (`cmd_fix()`) and shell/heredoc syntax failures (`_validate_step_script_syntax()` in `src/runner.py`, `src/safety.py`).
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `README.md`, `tests/test_runner.py`, `tests/test_ui.py`.

# 🎯 [NEXT] F84: Add run_block -r / --run [session] full-reply editor mode with automatic block extraction, repair, and step inference

- Depends on: F83, F74
- Add `run_block -r [session]` / `run_block --run [session]` in `src/cli.py`, `src/header.py`, `src/runner.py`, and `src/ui.py` to ingest a complete model reply (chat prose + code block) without manual block extraction or fence fixing:
  - Input acquisition: when `stdin` is a TTY, open a temporary file in the user's editor (`$VISUAL` / `$EDITOR` via the editor helper in `src/ui.py`) where the user pastes the full model reply and saves; when `stdin` is piped (e.g. `wl-paste | run_block -r` or `pbpaste | run_block -r`), read the full reply directly from `stdin`.
  - Block extraction & repair engine (`extract_reply_block()` in `src/runner.py`): locate the executable `run_block [<session>/<step>] <<'RUN_BLOCK' ... RUN_BLOCK` or `run_block --fix [<session>/<target>] <<'RUN_FIX' ... RUN_FIX` block (or fenced code block when `[session]` is supplied) inside the full reply, reassemble fences split by inner triple backticks, repair missing/indented closing terminators, deduplicate repeated blocks, and prefer the final actionable block over inline prose examples.
  - Automatic session & step resolution: resolve target `<session>` from the explicit CLI `[session]` argument, the extracted block header, or `_find_latest_session()` for the current `Workdir`, and automatically derive the next sequential step number via `next_free_step(sdir)` (auto-renumbering stale or mismatched step numbers without manual editing).
  - Model reasoning display & persistence: extract the model's prose commentary preceding the block, persist it in `<session>/<step>/meta.json` (or `plan.md`), and render a compact commentary/reasoning section at the top of the `START STEP` (`BLOCK PLAN`) card in `src/ui.py` so the same reply-ingestion pipeline serves both web-chat (`-r`) and built-in API transport (`todo_flow:D5`).
- Target files: `src/cli.py`, `src/header.py`, `src/runner.py`, `src/ui.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_ui.py`.

# ⚪ [NEW] F20: Enhance session management CLI for searching, inspecting headers/bundles/blocks, and retrying steps

- Depends on: F83
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

# ⚪ [NEW] D4: Design workspace state fingerprinting and drift detection across steps

- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] D6: Design session execution policies and post-step revert guards

- Depends on: D4
- Evaluate declarative session-level execution constraints and granular per-step sandbox permissions in `meta.json` / `.agents_bundle` (`src/bundle.py`, `src/config.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`):
  - Role & path write policies: support role-based allowed write globs (e.g. `role=plan` restricted to `TODO*.md`, `role=design` restricted to `docs/adr/**` and `TODO*.md`), hard blocks on destructive patterns (`rm -rf /`, `rm -rf ~`, outside-`Workdir` deletes, `.git/hooks` or `~/.ssh` tampering), and pre-step working-tree snapshots (`git stash create`) with one-key `r(evert)` in `END STEP` (or automatic rollback on policy violation).
  - Granular per-step sandbox permissions in `START STEP`: default to `nonet` / `strict` filesystem isolation (hiding `~` and `~/.ssh`), automatically bind-mount discovered `.todo_projects` sibling repositories (read-only by default, read-write when targeted by `todo_md -C <project>`), detect when a step requires network access (`git push`/`pull`, `curl`) or extra directory mounts in `src/safety.py`, and let the user grant one-step network or extra-folder access interactively in `START STEP` via `s(andbox)` without disabling filesystem isolation for the rest of the session.
- Cover enforcement, per-step permission prompts, and rollback semantics in `tests/test_runner.py`, `tests/test_safety.py`, and `tests/test_ui.py`.

# ⚪ [NEW] D7: Design pre-flight sandbox dry-run preview via temporary git worktree

- Depends on: D6
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D8: Design explicit parent-step DAG lineage for session branches and retries

- Depends on: D5
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] D9: Design machine-readable runner contract (--json step output and plan/execute handshake)

- Depends on: F79, F83
- Design contract to let the built-in API transport (`todo_flow:D5`) or an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` handshake, structured file-edit specifications (`edits: [{path, old, new}]`), and child environment sanitization (`scrub_child_env`) so LLM API keys never leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⏸️ [HOLD] F70: Support model-aware token counting once model API integration is added — *Waiting on built-in model API transport (todo_flow:D5)*

- Future enhancement (blocked on model API integration in `todo_flow:D5`): extend the pre-flight stdlib `~lo–hi tokens` estimator in `src/ui.py` (`count_tokens()`, `format_stats()`) and `src/bundle_plan.py` (`analyze_bundle_plan()`) with model-aware token accounting:
  - Keep fast offline stdlib heuristic estimation for pre-flight TUI cards (`START SESSION`, `START STEP`, `END STEP`, `--bundle-plan`) before a request is sent to the model.
  - Record exact post-turn token usage (`input_tokens`, `output_tokens`, cache read/write tokens) returned by the provider API response in `<session>/chat.json` and `<session>/meta.json`, and surface optional provider `count_tokens` / profile-tuned pre-flight estimates when an API profile is active.
