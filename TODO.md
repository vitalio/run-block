# 🎯 [NEXT] F96: Align context-bundle-protocol parser and prompt-note merger with canonical 4 fragment kinds (rule, file, cmd, prompt)

- Depends on: F95
- Remove producer-specific `task` and `context` fragment kind assumptions from `run_block` so `context-bundle-protocol` uses the 4 canonical fragment kinds (`rule`, `file`, `cmd`, `prompt`):
  - In `src/bundle_parse.py`, normalize legacy `"include"` -> `"file"` and `"task"` / `"context"` -> `"prompt"`, and check `kind == "prompt"` (plus legacy `"task"`, `"context"`) for `fragment_empty` warnings so any empty prompt fragment from an upstream producer warns cleanly.
  - In `src/bundle_parse.py` (`append_note_to_raw_bundle()` and `_dedupe_fragments()`) and `src/bundle_plan.py` (`refresh_bundle_plan_after_edit()`), distinguish upstream/bundle prompt fragments (which carry a non-empty `chain`, such as `chain: ["todo_md"]` or `chain: [".agents_bundle"]`) from the user's root session prompt fragment (`chain: []`, `name: "Prompt"`): allow deduplication on upstream/bundle prompt fragments with non-empty `chain`, and when appending a user `p(rompt)` note, merge only into a trailing root user prompt fragment (`chain: []`) and otherwise append a new `{"kind": "prompt", "name": "Prompt"}` fragment.
  - Update `tests/test_bundle.py`, `README.md`, and `AGENTS.md`.
- Target files: `src/bundle_parse.py`, `src/bundle_plan.py`, `tests/test_bundle.py`, `README.md`.

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

# 🎯 [NEXT] D10: Design built-in API agent mode in run_block (single run_block tool, reasoning in BLOCK PLAN, prompt caching, and key isolation)

- Depends on: F86, F89, F82, F74, F95
- Design candidate for `role=design` adding a built-in LLM API agent transport mode directly inside `run_block` (preserving `c(opy)` clipboard workflow and `run_block -r` full-reply paste mode as fallbacks, and remaining directly runnable via `todo_md <ID> | agents_bundle | run_block`):
  1. Model profiles and secret isolation: configure provider profiles (Anthropic Messages, OpenAI-compatible, local models) and load API keys (env / macOS Keychain / config) in memory while stripping secret env vars from child `run_block` executions (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  2. Single polymorphic `run_block` tool & resilient reply recovery:
     - Register a single `run_block` tool with `disable_parallel_tool_use: true` / `parallel_tool_calls: false` accepting structured `edits: [{path, old, new}]` (atomic in-memory anchor + syntax validation before disk write, strict `Workdir` path boundary enforcement, pre-execution diff preview in `START STEP` / `i(nfo)`, and `difflib` anchor repair from `F74`), `script` (batch `bash` commands without heredoc/fence wrappers or manual step numbers), optional `fix_target`, and optional `done` / `done_note`.
     - Reuse the reply extraction and repair pipeline from `F84` (`extract_reply_block()` in `src/runner.py`) to automatically strip accidental Markdown/heredoc wrappers inside `script`, deduplicate or queue unexpected multi-block responses, auto-resolve `<session>/<next_step>`, convert misplaced bash scripts in `fix_target` into sequential steps, and fall back to extracting blocks from plain text replies when a model responds without a tool call; support interactive terminal replies when the model asks a question without emitting a block.
  3. Safety & sandbox integration: integrate with existing `src/safety.py` static checks and OS sandbox policies (`nonet` / `strict`), keeping advanced workspace drift/revert policies decoupled in `D4` -> `D6`.
  4. TUI integration in `START SESSION`, `START STEP`, `END STEP`, and `END SESSION` (`src/ui.py`): replace default `Enter`/`Y` action with `Send to model (<profile>)` while keeping `c(opy)` for clipboard mode, render model reasoning/commentary and structured `edits` diffs directly inside `START STEP`, and persist conversation transcript and exact provider token/cache usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) in `<session>/chat.json` and `<session>/meta.json` (keeping fast offline stdlib heuristic estimation for pre-flight TUI cards).
  5. Prompt caching & prefix stability (cross-session and intra-session) on top of `Bundle-Protocol: 1` (`F82`):
     - Split `<session>/0` using `bundle_plan` fragment boundaries (`src/bundle_plan.py`, `format_start_bundle()` in `src/bundle.py`) so static `===== Rules =====` (`kind: "rule"`, with invariant rules first and role/transport-gated rules last) and static project instructions (`AGENTS.md`) form an immutable cacheable prefix (`system` prompt / leading `cache_control` breakpoint), while per-session headers (`Session`, `Next-Block`, `Date`, `Role`, `Task`, `Title`), dynamic command outputs (`kind: "cmd"`), file includes (`kind: "file"` / `"include"`), `task`/`context` fragments, and `===== Prompt =====` (`kind: "prompt"`) go into the initial `user` message.
     - Keep intra-session step history strictly append-only across turns (advancing the trailing `cache_control` breakpoint to the latest `<session>/<step>/out` turn) and use threshold/chunked context compaction rather than per-turn sliding-window truncation so prior step prefixes remain cache-valid across consecutive steps.
     - Surface provider token and cache hit statistics in `Stats:` across `END STEP` and `END SESSION`.
  6. Stdlib-first HTTP/SSE streaming client (`urllib.request`) with no required third-party dependencies, coordinating with `F85` (`GIT_PAGER=cat`).

- Target files: `src/config.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`, `src/cli.py`, `AGENTS.md`, `docs/adr/`.

# 🎯 [NEXT] F94: Show standard session headers and clean step/duration summary in END SESSION and SESSION COMPLETED cards

- Depends on: B14
- Bump: `PATCH`
- In `render_end_session_card()` (`src/runner.py`), prepend standard session
  header lines via `format_session_header_lines(label=name, sdir=sdir)`
  (`Session`, `Workdir`, `Sandbox` when active, and exposed bundle headers such
  as `Role`, `Task`, `Title`), separated by a blank line from the session
  completion summary block.
- In `_guard_completed_session()` (`src/runner.py`), prepend
  `format_session_header_lines(label=label, sdir=sdir)` separated by a blank
  line from `Completed:` and `Note:` in the `SESSION COMPLETED` confirmation
  box (matching `STEP ALREADY EXISTS` and `MISSING PREVIOUS STEP`).
- Replace the noisy two-line `Steps:` + `Results: X ok, Y failed, Z --fix, W
  renumbered` format in `_session_stats_lines()` (`src/runner.py`) with a
  concise summary:
  - `Steps: <total> (<non-zero outcomes> · <non-zero modifiers>)` (for example
    `Steps: 15 (15 ok)` or `Steps: 21 (11 ok, 10 failed · 2 fix)`), omitting
    zero-count outcomes and zero-count modifiers (`fix`, `renumbered`) and
    using `fix` instead of `--fix`.
  - Order timestamps chronologically (`Started:` before `Completed:`) and show
    wall-clock session elapsed time alongside total script execution time in
    `Duration:` when `started_at` and `completed_at` are present (for example
    `Duration: 25m 1s (1m 20s exec)`, falling back to `Duration: <exec>` when
    timestamps are absent or equal).
  - Keep `Note: <completed_note>` at the end of the summary block, and in
    headless mode (`run_block --done -y`) print `[<session>] END SESSION`
    followed by the non-empty header and summary lines without duplicating
    `Session:`.
- Update unit tests in `tests/test_runner.py` to verify standard headers
  (`Workdir`, `Role`, `Task`, `Title`), blank-line separation, the new
  `Steps:` / `Duration:` / `Started:` / `Completed:` layout, and
  `SESSION COMPLETED` headers.
- Target files: `src/runner.py:_session_stats_lines.._guard_completed_session`, `src/runner.py:cmd_info`, `tests/test_runner.py:test_f42_done_stats_card_and_list_badge..test_f42_completed_session_interactive_confirmation`, `tests/test_runner.py:test_f79_deferred_end_session_and_start_session_ordering_and_clipboard_handoff..test_f79_deferred_end_session_without_child_keeps_outer_end_step_clipboard`.

# 🎯 [NEXT] F92: Split src/ui.py into focused TUI card, fullscreen inspector, and clipboard/prompt modules and remove ticket prefixes from unit tests

- Depends on: B14
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

# ⚪ [NEW] F72: Rename project to run-block and CLI utility to run

- Depends on: F89, F95
- Rename project/repository references from `run_block` to `run-block` and CLI entrypoint from `run_block` to `run` (updating `agents/blocks/bash.md`, protocol markers, and env vars/compatibility aliases per `todo_flow:D8` and ADR 0003).
- Remove transitional `Bundle-Expose` and `Bundle-Hide` header parsing/filtering compatibility (`BUNDLE_EXPOSE_HEADER`, `BUNDLE_HIDE_HEADER`) from `src/bundle_parse.py`, documentation, and tests now that `agents_bundle` (`F15` / `todo_flow:F4`) emits `export`-driven preamble headers directly.
- Acceptance criteria: `build.py` outputs `run`, `install.sh` installs `run` (plus any agreed compatibility alias), `Bundle-Expose` / `Bundle-Hide` legacy handling is removed, `--help`/embedded rules/docs/tests reflect `run-block` and `run`, and `python3 -m unittest discover -s tests` passes.
- Target files: `build.py`, `install.sh`, `src/cli.py`, `src/header.py`, `src/config.py`, `src/runner.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/safety.py`, `src/ui.py`, `agents/blocks/bash.md`, `.agents_bundle`, `AGENTS.md`, `README.md`, `VERSION`, `tests/helpers.py`, `tests/test_*.py`, and `.github/`.

# ⚪ [NEW] D4: Design workspace state fingerprinting and drift detection across steps

- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`agents/blocks/bash.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

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

# ⚪ [NEW] B15: Fix --fix anchor repair quoting/prompt flow, shell-in-fix AST bypass, headless-header split payload truncation, and AssertionError root-cause hints

- Depends on: F74
Follow-up findings from F74 review:
- `src/runner.py:_propose_anchor_repair`, `src/runner.py:cmd_fix`: `_propose_anchor_repair()` matches and replaces the missing anchor via `fix_code.count(repr(old)) == 1` and `fix_code.replace(repr(old), repr(new_old), 1)`, which fails when `old` is written with double quotes, triple quotes, or other literal forms in `fix_code`; additionally, invoking `prompt_yes_no_box("NOT RUN", ...)` before `not_run_exit()` displays two consecutive `NOT RUN` prompts when the user declines repair (and `i(nfo)` in the first prompt runs before `<step>/out` or `<step>/fix.py` exists).
- `src/runner.py:cmd_fix`, `src/runner.py:_looks_like_shell_script`: `cmd_fix()` checks `_looks_like_shell_script(fix_code)` only when `validate_fix_ast(fix_code)` fails, so shell commands that happen to parse as valid Python AST expressions (`ls -la`, `cd /tmp`, `pwd`, `git`) bypass shell detection and fail with `NameError` during `exec()` instead of reporting the shell-script hint (or offering interactive execution as `<session>/<next_step>`).
- `src/runner.py:_reassemble_split_payload`: stopping at the first heredoc terminator, dropping duplicate trailing blocks/prose, and stripping nested `SPLIT_HEADER_RE` wrappers only run when the first non-empty line on `stdin` matches `SPLIT_HEADER_RE`; when the local shell consumes the outer `run_block <s/n> <<'RUN_BLOCK'` line before piping `stdin`, an indented inner terminator followed by a duplicate block or prose falls through the `if not m:` branch without truncation.
- `src/ui.py:_traceback_root_cause`, `src/ui.py:_extract_last_error_line`: `_traceback_root_cause()` searches for `AssertionError: '<needle>' not found in ...` matches only in `lines[:tb_idx]` (ignoring the haystack text embedded in the `AssertionError` message itself when output was captured in memory), and `_extract_last_error_line()` truncates `cause` by character index (`cause[: max_len - 3]`) rather than `char_width()`.
- `src/runner.py:_fix_anchor_values`, `src/runner.py:cmd_fix`: `_fix_anchor_values()` inspects only `text.count/replace/find/index` calls (missing `assert old in text` and `re.sub(old, new, text)` anchors), and `next_seq_ref` in `cmd_fix()` uses `int(base_step) + 1` instead of `next_free_step(sdir, min_step=int(base_step) + 1)`.

- `src/cli.py`, `src/runner.py`, `src/header.py`: decouple `-y` / `--yes` (`auto_yes=True`) from `--headless` (`RUN_BLOCK_HEADLESS=1`) so `-y` / `--yes` automatically reopens a completed session and auto-confirms `START STEP` execution while preserving interactive TUI conflict cards (`STEP ALREADY EXISTS`, `MISSING PREVIOUS STEP`), `NOT RUN` / `SYNTAX ERROR` / `END STEP` cards, and clipboard copy prompts on a TTY; reserve `--headless` and `RUN_BLOCK_HEADLESS=1` for non-interactive headless output without TUI boxes or prompts.

# ⚪ [NEW] F93: Split src/runner.py by responsibility

- Depends on: F94, B15
src/runner.py keeps growing (about 2600 lines after F74) and mixes step execution, --fix diagnostics, payload reassembly, and session listing; this exceeds the modular cohesion guideline of roughly 300-800 lines per module.

# ⚪ [NEW] F88: Implement built-in LLM API agent mode in run_block (single run_block tool, TUI loop, prompt caching, and key isolation)

- Depends on: D10, F85
- Depends on: B14 -> F92 -> F84
- Implement the built-in LLM API agent mode in `run_block` per `D10` so `todo_md <ID> | agents_bundle | run_block` (or standalone `run_block`) can drive multi-step agent sessions directly over provider APIs while preserving `c(opy)` clipboard and `run_block -r` workflows:
  - Provider profiles, API key loading, and child environment secret scrubbing (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  - Stdlib `urllib.request` HTTP/SSE streaming client, single polymorphic `run_block` tool schema (`edits`, `script`, `fix_target`, `done`, `done_note`), and fallback reply extraction via `extract_reply_block()`.
  - Immutable system/prefix splitting over `Bundle-Protocol: 1` part boundaries (`src/bundle_plan.py`, `src/bundle.py`) and append-only turn caching with `<session>/chat.json` transcript persistence.
  - Exact post-turn provider token and cache usage accounting (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) recorded in `<session>/chat.json` and `<session>/meta.json` and surfaced in `Stats:` across `END STEP` and `END SESSION` while preserving offline stdlib pre-flight estimation (`count_tokens()`, `format_stats()`).
  - Interactive TUI agent loop in `START SESSION`, `START STEP` (`BLOCK PLAN` reasoning + structured `edits` diff preview), `END STEP`, and `END SESSION` (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`).
- Target files: `src/config.py`, `src/bundle.py`, `src/bundle_parse.py`, `src/bundle_plan.py`, `src/bundle_view.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`, `src/header.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_safety.py`, `tests/test_ui.py`, `tests/test_bundle.py`.

# ⏸️ [HOLD] D9: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Defer external machine-readable runner contract until an external client is needed; built-in API agent mode (D10) runs in-process*

- Depends on: F79, F83, F88
- Design contract to let an external API/TUI/IDE client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and `D10`/`F88` in-process step structures to evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload) and a two-phase `plan -> approve -> execute` CLI handshake for external clients.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).
