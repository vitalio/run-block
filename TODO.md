# 🎯 [NEXT] F86: Unify fullscreen i(nfo) inspector with END STEP output breakdown table, step-output slice viewer, and artifact hotkeys

- Depends on: F81, B8
- Bump: `MINOR`
- Replace generic `INFO · <label> · <~path>` fullscreen title bar in `_build_info_screen()` (`src/ui.py:3190-3324`) with the card title (`<CARD TITLE> · <label> · <~path>`, e.g. `END STEP · s229/2 · ~/.local/state/run_block/s229/2/out`, `START SESSION · s229/0 · ~/.local/state/run_block/s229/0`, `START STEP · s229/2 · ~/.local/state/run_block/s229/2/block.sh`, with `(edited)` suffix when modified).
- Unify fullscreen header keys and bright styling across `START SESSION`, `START STEP`, `END STEP`, and other cards (`_format_info_header_lines()`, `_collect_info_report()`, `_colorize_kv_line()` in `src/ui.py:1443-1465`, `src/ui.py:2813-3180`):
  - Keep `Session`/`Next-Block` or `Step`, `Workdir`, `Sandbox` (including `Sandbox: off` in fullscreen), `Date`, exposed session headers (`Task`, `Title`, `Role`, etc.), and `Bundle-Command`, while omitting internal transport/meta headers (`Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`, `Bundle-Protocol`, `Chat-Lang`) from the fullscreen header block (they remain inspectable via `m(eta)`).
  - Show artifact file paths uniformly in both `START SESSION` (`Bundle: <path>`, optional `Bundle-Orig:`, `Meta: <sdir>/meta.json`) and step cards (`Exit:`/`Error:`/`Fix:` when `rc != 0`, `Script: <path>`, optional `Script-Orig:`, `Output: <path>`, optional `Output-Orig:`, `Meta: <step_dir>/meta.json`).
  - Remove `Stats:` and `Script-Stats:` from the fullscreen header block (statistics live in the breakdown table and its top/bottom `[total]` rows).
  - Render all fullscreen header lines in uniform readable brightness without dimming (`\x1b[2m`) `Workdir:`, `Sandbox:`, `Output:`, `Fix:`, or header keys.
- Track per-operation output line ranges and token/size metrics in `_ProgressLineFilter` and `run_script()` (`src/runner.py:389-602`, `src/runner.py:850-1035`):
  - Record 1-based `out_line_start` and `out_line_end` into the cleaned `<session>/<step>/out` file (plus `lines`, `chars`, `bytes`, `gpt`, `claude`, `share_pct`) for each executed operation in `<session>/<step>/meta.json` (`operations` list), alongside `step`, `tag`, `desc`, `duration_ms`, and script `line`..`end_line`.
- Render a unified tabular breakdown with top/bottom `[total]` rows in fullscreen `END STEP` and `START STEP` (`_collect_info_report()`, `_format_info_operation_timings()`, `_format_info_plan_section()` in `src/ui.py:2868-3180` and table helpers in `src/bundle_plan.py:1187-1438`):
  - In `END STEP`, replace the old `Operations (N timed):` list and duplicate `Pre-execution Plan (block.sh):` section with a unified output breakdown table (`#  %  CHARS  LINES  ~TOK  TIME  KIND  SOURCE`) showing each operation's share of `<step>/out`, character/line/token counts, execution duration, `[tag]`, and command description (with `(failed)` marker on the failing operation and heavy-row highlighting), bracketed by top and bottom `100.0%` `[total]` rows (including total step output stats, total duration, operation count, and `(edited)` suffix when modified).
  - In `START STEP`, render the pre-execution operation breakdown table (`#  %  CHARS  LINES  ~TOK  KIND  SOURCE`) with top and bottom `[total]` rows and optional `Safety warnings`.
- Open the selected operation's captured step output from `<step>/out` on `Tab` -> `Enter` in `END STEP` (`_open_operation_viewer()`, `_build_operation_screen()` in `src/ui.py:2623-2712`, `src/ui.py:3558-3616`):
  - In `END STEP` (when `<step>/out` and recorded output line ranges exist), pressing `Enter` on a selected operation opens `PART <k>/<N> · <label> · <~out_path>` showing header metadata (`Command: [<tag>] <desc>`, `Timing: <duration>`, `Script-Range: lines <line>-<end_line> of <~script_path>`, and `Range: lines <out_line_start>-<out_line_end> of <~out_path>` or `(no output)`) followed by the extracted output lines from `<step>/out` (falling back to script lines in `START STEP` or when no output file exists).
  - Support `n`/`N` next/prev operation navigation, `e(dit)`/`o(utput)` to edit `<step>/out` (preserving `out.orig` and refreshing table metrics), `s(cript)` to edit `block.sh` (preserving `block.orig.sh`), `m(eta)` to open `meta.json`, and `Esc` (`q`/`i`/`Tab`) to return to the table at the active cursor row.
- Add `m(eta)` hotkey and clean up fullscreen footer hints (`_parse_pager_line()`, `_read_pager_key()`, `_compose_pager_frame()`, `_build_info_screen()`, `_show_info_fullscreen()` in `src/ui.py:2400-2585`, `src/ui.py:3286-3324`, `src/ui.py:3663-3746`):
  - Support `m(eta)` (`m`/`M` in raw TTY mode and `m`/`meta` in line mode) across all fullscreen views to open `<session>/meta.json` (in `START SESSION`) or `<session>/<step>/meta.json` (in step cards), while keeping `e(dit)` and `o(utput)` as synonyms for editing `<step>/out` in `END STEP` and `s(cript)` for `block.sh`.
  - Omit `Lines 1-N/N` and `Up/Down j/k PgUp/PgDn: scroll` from the footer bar when all body rows fit within a single viewport (`total_items <= viewport_rows`), show scroll position only when `total_items > viewport_rows`, show `Part <k>/<N>` in `Tab` cursor mode, and shorten the footer back hint to `Esc: back` (while keeping `Esc`, `q`, and `i` active as back keys).
- Target files: `src/runner.py:389-602`, `src/runner.py:850-1035`, `src/bundle_plan.py:1187-1438`, `src/ui.py:1443-1572`, `src/ui.py:2400-3770`, `README.md`, `tests/test_ui.py:1800-2027`, `tests/test_runner.py:1350-1508`.

# 🎯 [NEXT] F85: Export non-interactive pager defaults in child step execution environment

- Depends on: D3
- Bump: `MINOR`
- In `src/config.py`, define canonical `CHILD_PAGER_ENV_VARS = ("PAGER", "GIT_PAGER", "GH_PAGER", "MANPAGER", "SYSTEMD_PAGER", "BAT_PAGER", "AWS_PAGER", "PSQL_PAGER", "DELTA_PAGER")` and add `get_setting("pager")` reading `RUN_BLOCK_PAGER` (default `"cat"`; values `"0"`, `"false"`, `"no"`, `"off"`, `"inherit"`, `"keep"`, `"passthrough"` return `""` to preserve the parent environment's pager variables unchanged).
- In `src/runner.py` (`run_script()`), populate `CHILD_PAGER_ENV_VARS` with `get_setting("pager")[0]` in `child_env` (when non-empty, overriding parent `os.environ` pager variables before `scrub_child_env()`) so TTY-aware commands (`git diff`, `git log`, `gh api`, `man`, `systemctl`, `bat`, etc.) never stall inside `run_block`'s PTY while keeping `/dev/tty` `stdin` attached for intentional human-in-the-loop prompts.
- Document `RUN_BLOCK_PAGER=cat|inherit` in `src/header.py` (`--help` `Environment:` section aligned to column width invariants) and the `Environment Variables` table in `README.md`.
- Add unit tests in `tests/test_runner.py` and `tests/test_cli.py` covering default `CHILD_PAGER_ENV_VARS` injection (`cat`), custom `RUN_BLOCK_PAGER` override, `RUN_BLOCK_PAGER=inherit` / `off` passthrough, and `--help` alignment.
- Target files: `src/config.py:23-116`, `src/runner.py:945-960`, `src/header.py:24-35`, `README.md:245-270`, `tests/test_runner.py`, `tests/test_cli.py`.

# 🎯 [NEXT] F74: Diagnose broken blocks, root-cause errors, and interactively repair --fix anchors

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

# 🎯 [NEXT] F84: Add run_block -r / --run [session] full-reply editor mode with automatic block extraction, repair, and step inference

- Depends on: F83, F74
- Add `run_block -r [session]` / `run_block --run [session]` in `src/cli.py`, `src/header.py`, `src/runner.py`, and `src/ui.py` to ingest a complete model reply (chat prose + code block) without manual block extraction or fence fixing:
  - Input acquisition: when `stdin` is a TTY, open a temporary file in the user's editor (`$VISUAL` / `$EDITOR` via the editor helper in `src/ui.py`) where the user pastes the full model reply and saves; when `stdin` is piped (e.g. `wl-paste | run_block -r` or `pbpaste | run_block -r`), read the full reply directly from `stdin`.
  - Block extraction & repair engine (`extract_reply_block()` in `src/runner.py`): locate the executable `run_block [<session>/<step>] <<'RUN_BLOCK' ... RUN_BLOCK` or `run_block --fix [<session>/<target>] <<'RUN_FIX' ... RUN_FIX` block (or fenced code block when `[session]` is supplied) inside the full reply, reassemble fences split by inner triple backticks, repair missing/indented closing terminators, deduplicate repeated blocks, and prefer the final actionable block over inline prose examples.
  - Automatic session & step resolution: resolve target `<session>` from the explicit CLI `[session]` argument, the extracted block header, or `_find_latest_session()` for the current `Workdir`, and automatically derive the next sequential step number via `next_free_step(sdir)` (auto-renumbering stale or mismatched step numbers without manual editing).
  - Model reasoning display & persistence: extract the model's prose commentary preceding the block, persist it in `<session>/<step>/meta.json` (or `plan.md`), and render a compact commentary/reasoning section at the top of the `START STEP` (`BLOCK PLAN`) card in `src/ui.py` so the same reply-ingestion pipeline serves both web-chat (`-r`) and built-in API transport (`todo_flow:D5`).
- Target files: `src/cli.py`, `src/header.py`, `src/runner.py`, `src/ui.py`, `README.md`, `AGENTS.md`, `tests/test_cli.py`, `tests/test_runner.py`, `tests/test_ui.py`.

# ⚪ [NEW] F72: Rename project to run-block and CLI utility to rxb

- Rename project/repository references from `run_block` to `run-block` and CLI entrypoint from `run_block` to `rxb` (updating embedded block rules, protocol markers, and env vars/compatibility aliases per the ecosystem rename design).
- Target files: `build.py`, `install.sh`, `install.ps1`, `src/cli.py`, `src/header.py`, `src/config.py`, `src/runner.py`, `src/bundle.py`, `src/bundle_plan.py`, `src/safety.py`, `src/ui.py`, `agents/blocks/bash.md`, `agents/blocks/pwsh.md`, `.agents_bundle`, `AGENTS.md`, `README.md`, `VERSION`, `tests/helpers.py`, `tests/test_*.py`, and `.github/`.
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
- Design contract to let the built-in API transport (`todo_flow:D5`) or an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` handshake, structured file-edit specifications (`edits: [{path, old, new}]`), and child environment sanitization (`scrub_child_env`) so LLM API keys never leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ⏸️ [HOLD] F70: Support model-aware token counting once model API integration is added — *Waiting on built-in model API transport (todo_flow:D5)*

- Future enhancement (blocked on model API integration in `todo_flow:D5`): extend the pre-flight stdlib `~lo–hi tokens` estimator in `src/ui.py` (`count_tokens()`, `format_stats()`) and `src/bundle_plan.py` (`analyze_bundle_plan()`) with model-aware token accounting:
  - Keep fast offline stdlib heuristic estimation for pre-flight TUI cards (`START SESSION`, `START STEP`, `END STEP`, `--bundle-plan`) before a request is sent to the model.
  - Record exact post-turn token usage (`input_tokens`, `output_tokens`, cache read/write tokens) returned by the provider API response in `<session>/chat.json` and `<session>/meta.json`, and surface optional provider `count_tokens` / profile-tuned pre-flight estimates when an API profile is active.
