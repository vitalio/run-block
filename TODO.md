# 🔵 [WIP] F74: Diagnose broken blocks, root-cause errors, and interactively repair --fix anchors

- Depends on: F57, B8, F81, F86
- Harden `_reassemble_split_payload()`, `cmd_normal()`, and `cmd_fix()` in `src/runner.py` against broken or duplicated blocks:
  - Stop at the first matching closing heredoc terminator (`RUN_BLOCK` or `RUN_FIX`) rather than scanning backward from the end so two blocks pasted together are never merged with intermediate prose into a corrupt script.
  - Automatically deduplicate identical repeated blocks, strip accidental nested `run_block <s/n> <<'RUN_BLOCK' ... RUN_BLOCK` wrappers or trailing/indented fence debris, recover missing closing terminators before a final closing fence, and detect when a `--fix` payload contains a fresh shell script instead of a Python `text` patch (offering to run it as the next sequential step `<session>/<next_step>`).
- Diagnose `--fix` and file-edit anchor mismatches in `_format_fix_exception()` and `cmd_fix()` (`src/runner.py`): when `assert text.count(old) == 1` fails with `actual: 0 == 1` (or `fix made no changes`), inspect `old` against `text` using `difflib.SequenceMatcher` over matching line windows and append a concrete `Hint:` line to `NOT RUN` (`not_run_exit()`) showing the closest match, line number, and similarity score.
- Detect common `--fix` authoring mistakes in `cmd_fix()` (`src/runner.py`): report explicit hints when `old` is absent from `block.*` but exists in a repository file referenced by the target script (guiding the agent to emit a fresh `<session>/<step+1>` block instead of `--fix`), when `old.rstrip("\n")` matches once (trailing newline mismatch), when `old` matches multiple times (`actual: N == 1`), or when top-level `text.replace(...)` / `re.sub(...)` is called without assigning back to `text = ...`.
- Offer interactive anchor repair in `NOT RUN` (`src/runner.py`, `src/ui.py` `offer_clipboard_copy()`): when running in an interactive TTY and a single unambiguous high-confidence anchor match is found (`>= 0.85` similarity with clear margin over the runner-up), display a compact diff (`old` -> matched line) and allow accepting the replacement (`f(ix)` / `i(nfo)`), re-evaluating in memory, and proceeding straight into `START STEP` without an extra agent turn; never auto-apply fuzzy replacements in headless `-y` mode or on ambiguous matches.
- Improve root-cause `Error:` extraction and failure hints in `END STEP` (`src/runner.py` `run_script()`): parse structured `Traceback` / `AssertionError` / `SyntaxError` (`file:line` and exception summary) from captured `stderr` instead of showing only generic runner tails like `FAILED (failures=1)`, and when `AssertionError: '<needle>' not found in ...` occurs, surface the closest matching line from the captured output.
- Add code-context snippets (`+-2` lines) and escaping hints on `SyntaxError` / `IndentationError` in `--fix` (`cmd_fix()`) and shell/heredoc syntax failures (`_validate_step_script_syntax()` in `src/runner.py`, `src/safety.py`).
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `README.md`, `tests/test_runner.py`, `tests/test_ui.py`.

# 🎯 [NEXT] F85: Export non-interactive pager defaults in child step execution environment

- Depends on: D3
- Bump: `MINOR`
- In `src/config.py`, define canonical `CHILD_PAGER_ENV_VARS = ("PAGER", "GIT_PAGER", "GH_PAGER", "MANPAGER", "SYSTEMD_PAGER", "BAT_PAGER", "AWS_PAGER", "PSQL_PAGER", "DELTA_PAGER")` and add `get_setting("pager")` reading `RUN_BLOCK_PAGER` (default `"cat"`; values `"0"`, `"false"`, `"no"`, `"off"`, `"inherit"`, `"keep"`, `"passthrough"` return `""` to preserve the parent environment's pager variables unchanged).
- In `src/runner.py` (`run_script()`), populate `CHILD_PAGER_ENV_VARS` with `get_setting("pager")[0]` in `child_env` (when non-empty, overriding parent `os.environ` pager variables before `scrub_child_env()`) so TTY-aware commands (`git diff`, `git log`, `gh api`, `man`, `systemctl`, `bat`, etc.) never stall inside `run_block`'s PTY while keeping `/dev/tty` `stdin` attached for intentional human-in-the-loop prompts.
- Document `RUN_BLOCK_PAGER=cat|inherit` in `src/header.py` (`--help` `Environment:` section aligned to column width invariants) and the `Environment Variables` table in `README.md`.
- Add unit tests in `tests/test_runner.py` and `tests/test_cli.py` covering default `CHILD_PAGER_ENV_VARS` injection (`cat`), custom `RUN_BLOCK_PAGER` override, `RUN_BLOCK_PAGER=inherit` / `off` passthrough, and `--help` alignment.
- Target files: `src/config.py:23-116`, `src/runner.py:945-960`, `src/header.py:24-35`, `README.md:245-270`, `tests/test_runner.py`, `tests/test_cli.py`.

# 🎯 [NEXT] B14: Fix fullscreen i(nfo) meta hotkey in START SESSION part viewer, END STEP table refresh on out edit, and progress line range edge cases

- Depends on: F86 -> F74
- Bump: `PATCH`
- Add `m(eta)` hotkey handling and footer hint (`m(eta)`) to `_open_part_viewer()` and `_build_part_screen()` in `src/ui.py` (resolving `<session>/meta.json` via `_info_meta_path("START SESSION", resolved_sdir, None, out_path)`) so `START SESSION` `PART N/M` and `BUNDLE R/M` subviews open `<session>/meta.json` consistently with step `PART k/N` views.
- Recompute per-operation `share_pct` against current `total["chars"]` (and refresh operation/slice metrics when `block.sh` or `<step>/out` is modified) in `_format_output_breakdown()` and `_open_operation_viewer()` (`src/ui.py`) so the `END STEP` breakdown table and operation viewer stay aligned after in-place edits.
- Handle partial lines without trailing `\n` before step markers and `\r` / ANSI cleaning consistently in `_ProgressLineFilter` (`src/runner.py`) so `out_line_start`..`out_line_end` always match line numbers in cleaned `<step>/out`.
- Target files: `src/runner.py:_clean_out_text.._ProgressLineFilter`, `src/ui.py:_step_op_timings.._format_output_breakdown`, `src/ui.py:_show_info_fullscreen`, `tests/test_runner.py:test_f30_numbered_block_plan_and_live_progress_execution..test_f49_block_and_operation_durations_and_sub_items`, `tests/test_ui.py:test_f54_end_drops_steps_and_info_viewer..test_f77_borderless_info_home_shortened_title_prompt_and_tab_cursor`.

# 🎯 [NEXT] F92: Split src/ui.py into focused TUI card, fullscreen inspector, and clipboard/prompt modules and remove ticket prefixes from unit tests

- Depends on: F74 -> B14
- Bump: `PATCH`
- Split `src/ui.py` (>4,100 lines) into three single-responsibility modules under `src/`:
  - `src/ui.py`: terminal/ANSI/UTF-8 and display-width primitives, token counting and stats formatting (`count_tokens()`, `format_stats()`), and box-drawing card layout/rendering (`_wrap_box_line()`, `_clamp_body_rows()`, `_render_block()`, `format_safety_box()`, `build_box_body_lines()`, `format_clipboard_box()`).
  - `src/ui_info.py`: fullscreen `i(nfo)` inspector, pager navigation/frame composition, bundle/operation breakdown tables, and `PART N/M`, `BUNDLE R/M`, and step operation `PART k/N` subviews (`_parse_pager_line()`..`_show_bundle_details_fullscreen()`).
  - `src/ui_prompt.py`: `/dev/tty` lifecycle, `SIGWINCH` debounce watcher, editor launch and `.orig` backups, clipboard command resolution/copying, and interactive confirmation/clipboard prompts (`open_tty()`..`confirm_execution()`, `resolve_clipboard_target()`..`copy_file_to_clipboard()`, `offer_clipboard_copy()`).
- Update `MODULE_ORDER` in `build.py`, rebuild `./run_block`, and update module boundary documentation in `AGENTS.md`.
- Rename all remaining ticket-prefixed unit test methods (`test_f<N>_*` and `test_b<N>_*`) across `tests/test_bundle.py`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_safety.py`, and `tests/test_ui.py` to descriptive domain-behavior names.
- Target files: `build.py`, `src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `AGENTS.md`, `tests/test_bundle.py`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_safety.py`, `tests/test_ui.py`.

# 🎯 [NEXT] F84: Add run_block -r / --run [session] full-reply editor mode with automatic block extraction, repair, and step inference

- Depends on: F83
- Depends on: F74 -> B14 -> F92
- Add `run_block -r [session]` / `run_block --run [session]` in `src/cli.py`, `src/header.py`, `src/runner.py`, and `src/ui.py` to ingest a complete model reply (chat prose + code block) without manual block extraction or fence fixing:
  - Input acquisition: when `stdin` is a TTY, open a temporary file in the user's editor (`$VISUAL` / `$EDITOR` via the editor helper in `src/ui.py`) where the user pastes the full model reply and saves; when `stdin` is piped (e.g. `wl-paste | run_block -r` or `pbpaste | run_block -r`), read the full reply directly from `stdin`.
  - Block extraction & repair engine (`extract_reply_block()` in `src/runner.py`): locate the executable `run_block [<session>/<step>] <<'RUN_BLOCK' ... RUN_BLOCK` or `run_block --fix [<session>/<target>] <<'RUN_FIX' ... RUN_FIX` block (or fenced code block when `[session]` is supplied) inside the full reply, reassemble fences split by inner triple backticks, repair missing/indented closing terminators, deduplicate repeated blocks, and prefer the final actionable block over inline prose examples.
  - Automatic session & step resolution: resolve target `<session>` from the explicit CLI `[session]` argument, the extracted block header, or `_find_latest_session()` for the current `Workdir`, and automatically derive the next sequential step number via `next_free_step(sdir)` (auto-renumbering stale or mismatched step numbers without manual editing).
  - Model reasoning display & persistence: extract the model's prose commentary preceding the block, persist it in `<session>/<step>/meta.json` (or `plan.md`), and render a compact commentary/reasoning section at the top of the `START STEP` (`BLOCK PLAN`) card in `src/ui.py` so the same reply-ingestion pipeline serves both web-chat (`-r`) and built-in API transport (`D10`).
- Target files: `src/cli.py`, `src/header.py`, `src/runner.py`, `src/ui.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_ui.py`.

# 🎯 [NEXT] D10: Design built-in API agent mode in run_block (single run_block tool, reasoning in BLOCK PLAN, prompt caching, and key isolation)

- Depends on: F85, F86, F89, D6, D9, F82
- Depends on: F74 -> B14 -> F92 -> F84
- Design candidate for `role=design` adding a built-in LLM API agent transport mode directly inside `run_block` (preserving `c(opy)` clipboard workflow and `run_block -r` full-reply paste mode as fallbacks, and remaining directly runnable via `todo_md <ID> | agents_bundle | run_block`):
  1. Model profiles and secret isolation: configure provider profiles (Anthropic Messages, OpenAI-compatible, local models) and load API keys (env / macOS Keychain / config) in memory while stripping secret env vars from child `run_block` executions (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  2. Single polymorphic `run_block` tool & resilient reply recovery:
     - Register a single `run_block` tool with `disable_parallel_tool_use: true` / `parallel_tool_calls: false` accepting structured `edits: [{path, old, new}]` (atomic in-memory anchor + syntax validation before disk write, strict `Workdir` path boundary enforcement, pre-execution diff preview in `START STEP` / `i(nfo)`, and `difflib` anchor repair from `F74`), `script` (batch `bash`/`pwsh` commands without heredoc/fence wrappers or manual step numbers), optional `fix_target`, and optional `done` / `done_note`.
     - Reuse the reply extraction and repair pipeline from `F84` (`extract_reply_block()` in `src/runner.py`) to automatically strip accidental Markdown/heredoc wrappers inside `script`, deduplicate or queue unexpected multi-block responses, auto-resolve `<session>/<next_step>`, convert misplaced bash scripts in `fix_target` into sequential steps, and fall back to extracting blocks from plain text replies when a model responds without a tool call; support interactive terminal replies when the model asks a question without emitting a block.
  3. Defense-in-depth against prompt injection & destructive commands (coordinating with `D6`):
     - Combine deterministic static AST/policy blocks in `src/safety.py` (hard deny on `rm -rf /`, `rm -rf ~`, outside-`Workdir` writes, or `.git/hooks` tampering), default `nonet` / `strict` OS sandbox with per-step interactive permission grants in `START STEP` (one-step network or sibling `.todo_projects` directory access via `s(andbox)`), and fast pre-step git working-tree snapshots (`git stash create`) for instant rollback.
     - Support an optional context-isolated AI safety auditor hook (via `RUN_BLOCK_APPROVE_CMD` / secondary fast model profile) triggered on high-risk or non-allowlisted shell scripts: pass only the task title, role, `edits`, and candidate `script` (excluding chat history and untrusted file contents that could carry prompt injections) to verify alignment before presenting `START STEP`.
  4. TUI integration in `START SESSION`, `START STEP`, `END STEP`, and `END SESSION` (`src/ui.py`): replace default `Enter`/`Y` action with `Send to model (<profile>)` while keeping `c(opy)` for clipboard mode, render model reasoning/commentary and structured `edits` diffs directly inside `START STEP`, and persist conversation transcript/token usage in `<session>/chat.json` (unblocking `F70` and `F88`).
  5. Prompt caching & prefix stability (cross-session and intra-session) on top of `Bundle-Protocol: 1` (`F82`):
     - Split `<session>/0` using `bundle_plan` fragment boundaries (`src/bundle_plan.py`, `format_start_bundle()` in `src/bundle.py`) so static `===== Rules =====` (`kind: "rule"`, with invariant rules first and `[if role=...]` / `[if transport=api]` last) and static project instructions (`AGENTS.md`) form an immutable cacheable prefix (`system` prompt / leading `cache_control` breakpoint), while per-session headers (`Session`, `Next-Block`, `Date`, `Role`, `Task`, `Title`), dynamic command outputs (`kind: "cmd"`), file includes (`kind: "include"`), `task`/`context` fragments, and `===== Prompt =====` (`kind: "prompt"`) go into the initial `user` message.
     - Keep intra-session step history strictly append-only across turns (advancing the trailing `cache_control` breakpoint to the latest `<session>/<step>/out` turn) and use threshold/chunked context compaction rather than per-turn sliding-window truncation so prior step prefixes remain cache-valid across consecutive steps.
     - Record provider cache metrics (`cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) in `<session>/chat.json` and surface cache hit statistics in `Stats:` across `END STEP` and `END SESSION`.
  6. Stdlib-first HTTP/SSE streaming client (`urllib.request`) with no required third-party dependencies, coordinating with `D9` and `D3` / `F85` (`GIT_PAGER=cat`).
- Target files: `src/config.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`, `src/cli.py`, `AGENTS.md`, `docs/adr/`.

# ⚪ [NEW] F72: Rename project to run-block and CLI utility to rxb

- Depends on: F89
- Rename project/repository references from `run_block` to `run-block` and CLI entrypoint from `run_block` to `rxb` (updating embedded block rules, protocol markers, and env vars/compatibility aliases per the ecosystem rename design).
- Target files: `build.py`, `install.sh`, `install.ps1`, `src/cli.py`, `src/header.py`, `src/config.py`, `src/runner.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/safety.py`, `src/ui.py`, `agents/blocks/bash.md`, `agents/blocks/pwsh.md`, `.agents_bundle`, `AGENTS.md`, `README.md`, `VERSION`, `tests/helpers.py`, `tests/test_*.py`, and `.github/`.
- Acceptance criteria: `build.py` outputs `rxb`, `install.sh`/`install.ps1` install `rxb` (plus any agreed compatibility alias), `--help`/embedded rules/docs/tests reflect `run-block` and `rxb`, and `python3 -m unittest discover -s tests` passes.

# ⚪ [NEW] D4: Design workspace state fingerprinting and drift detection across steps

- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`agents/blocks/bash.md`, `agents/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

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
- Design contract to let the built-in API transport (`D10`) or an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` handshake, structured file-edit specifications (`edits: [{path, old, new}]`), and child environment sanitization (`scrub_child_env`) so LLM API keys never leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⚪ [NEW] F70: Support model-aware token counting once model API integration is added

- Depends on: D10
- Extend the pre-flight stdlib `~lo–hi tokens` estimator in `src/ui.py` (`count_tokens()`, `format_stats()`) and `src/bundle_plan.py` (`analyze_bundle_plan()`) with model-aware token accounting once `D10` specifies the built-in LLM API agent mode:
  - Keep fast offline stdlib heuristic estimation for pre-flight TUI cards (`START SESSION`, `START STEP`, `END STEP`, `--bundle-plan`) before a request is sent to the model.
  - Record exact post-turn token usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) returned by the provider API response in `<session>/chat.json` and `<session>/meta.json`, and surface optional provider `count_tokens` / profile-tuned pre-flight estimates when an API profile is active.
- Target files: `src/ui.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/runner.py`, `tests/test_ui.py`, `tests/test_bundle.py`, `tests/test_runner.py`.

# ⚪ [NEW] F88: Implement built-in LLM API agent mode in run_block (single run_block tool, TUI loop, prompt caching, and key isolation)

- Depends on: D10 -> F70
- Implement the built-in LLM API agent mode in `run_block` per `D10` so `todo_md <ID> | agents_bundle | run_block` (or standalone `run_block`) can drive multi-step agent sessions directly over provider APIs while preserving `c(opy)` clipboard and `run_block -r` workflows:
  - Provider profiles, API key loading, and child environment secret scrubbing (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  - Stdlib `urllib.request` HTTP/SSE streaming client, single polymorphic `run_block` tool schema (`edits`, `script`, `fix_target`, `done`, `done_note`), and fallback reply extraction via `extract_reply_block()`.
  - Immutable system/prefix splitting over `Bundle-Protocol: 1` part boundaries (`src/bundle_plan.py`, `src/bundle.py`) and append-only turn caching with `<session>/chat.json` transcript persistence.
  - Interactive TUI agent loop in `START SESSION`, `START STEP` (`BLOCK PLAN` reasoning + structured `edits` diff preview), `END STEP`, and `END SESSION` (`src/ui.py`, `src/cli.py`), integrated with `D6` sandbox/revert policies and `F70` token/cache usage accounting.
- Target files: `src/config.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`, `src/cli.py`, `src/header.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_safety.py`, `tests/test_ui.py`, `tests/test_bundle.py`.
