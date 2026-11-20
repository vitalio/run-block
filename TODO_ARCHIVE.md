# ✅ [DONE] F57: Add a(ppend) prompt editor action across clipboard TUI cards (START SESSION, END STEP, SYNTAX ERROR, NOT RUN) — *2026-11-21*

- Add a shared `a(ppend)` action across all clipboard-copy prompts (`START SESSION`, `END STEP`, `SYNTAX ERROR`, `NOT RUN`) in `src/ui.py`, `src/bundle.py`, and `src/runner.py` (`[Y/n/a(ppend)/...]:` or compatible prompt suffix), recognizing `a`/`A` (and `append` in line-input mode).
- On `a(ppend)`, open an empty temporary `.md` file in the configured editor (`resolve_editor_command()` in `src/ui.py`), remove the temporary file on exit, and abort cleanly without modifying the target file or creating a `.orig` backup when the entered text is empty or whitespace-only.
- Before the first non-empty append, preserve the original file via `_write_orig_backup_once()` (`0.orig` for `START SESSION`, `out.orig` for step output cards), then append the text:
  - In `START SESSION`: append into the trailing `===== Prompt =====` section of `<session>/0` (creating it if absent) and call `refresh_bundle_meta()`.
  - In `END STEP`, `SYNTAX ERROR`, and `NOT RUN`: append the user note/question to the clipboard target output (`out`) and refresh clipboard command/target if needed.
- Recalculate line/byte/token `Stats:` with the `(edited)` marker and redraw the box in place so pressing `Enter`/`y` copies the updated content to the clipboard.
- Acceptance criteria: `a(ppend)` works uniformly across `START SESSION`, `END STEP`, `SYNTAX ERROR`, and `NOT RUN`; empty input leaves files and `.orig` backups untouched; `.orig` is saved once and `Stats:` updates with `(edited)`; `README.md` and offline tests in `tests/test_bundle.py` and `tests/test_runner.py` are updated.

# ✅ [DONE] F42: Support marking sessions as completed (--done) with confirmation before reopening — *2026-11-21*

- Persist session completion state (`"completed": true`, `"completed_at": "<YYYY-MM-DDTHH:MM:SSZ>"`, optional `"completed_note"`) and accumulated session statistics (`"stats"`: total steps, ok/failed/`--fix`/renumbered counts, total execution `duration_ms`, started/completed timestamps) in `<session>/meta.json` via helpers in `src/config.py` (`is_session_completed`, `set_session_completed`, `update_session_stats`), preserving completion and stats fields in `write_session_meta()` and resetting automatically when a session is recreated (`--start --force`).
- Add `run_block --done [session] [-m "<note>"]` in `src/cli.py` and `src/runner.py` (allowed both directly in terminal and inside the final block of a session), render an `END SESSION` summary card displaying the accumulated session statistics, and show `[DONE]` status badges in `run_block --list` / `-l`.
- Check session completion before `START STEP` (`PLAN`) across normal runs (`<session>/<step>`), `--fix`, and `--retry`:
  - Interactive TTY: display a `SESSION COMPLETED` confirmation box (`-> Reopen session <session>? [y/N/i(nfo)]:` / `prompt_yes_no_box`, default `No`); on confirmation (`y`), clear the completion marker in `meta.json` and proceed directly into `START STEP`, otherwise exit with `NOT RUN`.
  - Non-interactive / headless: auto-reopen and run when `-y`/`--yes` (`RUN_BLOCK_HEADLESS=1`) is set; otherwise fail with `NOT RUN: session <session> is marked as completed (pass -y/--yes to reopen and run)`.
- Document `END SESSION` and session completion rules synchronously in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md`, plus `src/header.py`, `README.md`, and unit tests in `tests/test_runner.py` and `tests/test_cli.py`.

# ❌ [CANCELED] F48: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Re-prefixed as D9 per ADR 0001*

- Depends on: F42, D2
- Role: design
- Design candidate for `role=design` to let an external API/TUI client drive `run_block` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Evaluate structured `--json` execution output for `<session>/<step>` (status: `ok`/`syntax_error`/`not_run`/`completed`, `exit_code`, safety findings, and clean `[sN/k]` LLM payload), two-phase `plan -> approve -> execute` non-TTY handshake, and env sanitization so client LLM API keys do not leak into executed step scripts.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).

# ❌ [CANCELED] F38: Design explicit parent-step DAG lineage for session branches and retries — *Re-prefixed as D8 per ADR 0001*

- Depends on: F35
- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_runner.py` and `tests/test_cli.py`.

# ❌ [CANCELED] F36: Design pre-flight sandbox dry-run preview via temporary git worktree — *Re-prefixed as D7 per ADR 0001*

- Depends on: F37
- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_runner.py` and `tests/test_safety.py`.

# ❌ [CANCELED] F37: Design session execution policies and post-step revert guards — *Re-prefixed as D6 per ADR 0001*

- Depends on: F34
- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate declarative session-level execution constraints in `meta.json` / `.agents_bundle` (`src/bundle.py`, `src/config.py`), such as allowed write path globs, maximum modified file count, or network-access restrictions.
- Define enforcement and rollback semantics in `src/runner.py` and `src/safety.py` (pre-execution policy checks plus post-step diff verification with automatic revert on violation) and cover with `tests/test_runner.py` and `tests/test_safety.py`.

# ❌ [CANCELED] F35: Design tamper-evident hash chain and parent-step verification for session history — *Re-prefixed as D5 per ADR 0001*

- Depends on: F34
- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`), a `run_block --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

# ❌ [CANCELED] F34: Design workspace state fingerprinting and drift detection across steps — *Re-prefixed as D4 per ADR 0001*

- Role: design
- Design candidate for `role=design` before decomposing into implementation tasks.
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ❌ [CANCELED] F16: Prevent unintended interactive pagers during block execution — *Re-prefixed as D3 per ADR 0001*

- Role: design
- Encountered a stall during block execution when a model-generated inspection command (`git diff HEAD`) opened an interactive pager inside the PTY, forcing manual `q` / `Ctrl+C` intervention.
- Need to design a balanced approach in `run_block` rules (and/or runner defaults) that prevents trivial interactive pagination/stalls when reading output without blocking intentional human-in-the-loop prompts, keeping in mind a future automation layer that will introduce stricter non-interactive rules.

# ✅ [DONE] F15: Forbid trailing prose after closing fence in block rules — *2026-11-20, Already enforced in Rule 1 of src/rules/blocks/bash.md and pwsh.md*

- Tighten Rule 1 in `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` so any prose must appear strictly BEFORE the opening code fence and the closing fence must be the exact final 3 characters of the response (never emit text after the closing fence).
- Rebuild `./run_block` via `build.py` and update `tests/test_bundle.py`.

# ✅ [DONE] F78: Speed up test suite and CLI startup (remove tiktoken, lazy urllib, in-process runner) and split test_run_block.py into modular tests/test_*.py — *2026-11-20, Removed tiktoken, made urllib.request lazy, split tests/ into modular files with in-process runner, and fixed test_f59 SIGWINCH race*

- Role: work
- In `src/ui.py` (`gpt_encoder()`, `count_tokens()`) and `src/bundle_plan.py` (`parse_bundle_fragments()`), remove the optional third-party `import tiktoken` (`o200k_base`) path so `run_block` strictly obeys `stack/python-stdlib`, has deterministic token estimates across machines, and avoids the ~190 ms BPE load penalty on every CLI and test invocation.
- Move `import urllib.request` out of top-level `src/header.py` into `fetch_remote_script()` in `src/cli.py` so regular CLI startups do not pay the `urllib.request` import overhead (~40 ms), and verify in tests that `urllib.request` and `tiktoken` are not loaded during normal commands.
- Create `tests/helpers.py` containing `ROOT`, `SCRIPT`, `INSTALL_SH`, `load_module()`, and a shared base class `RunBlockTestCase(unittest.TestCase)` that loads `./run_block` once, preserves/restores `RUN_BLOCK_*` environment variables in `setUp()`/`tearDown()`, and provides in-process CLI helpers `_assert_ok()`, `_run_in_process()`, `_run_subprocess()`, and `_run()` (capturing `stdout`/`stderr` via `contextlib.redirect_stdout` / `redirect_stderr` and including diagnostic `stdout`/`stderr` in `msg=` on exit-code checks, keeping real `subprocess.run` for CLI entrypoint and `install.sh` smoke tests and using `sys.executable` instead of `"python3"` literals).
- Fix the `SIGWINCH` race in `test_f59_sigwinch_in_place_box_redraw` and tighten PTY driver sleeps across `test_f59_sigwinch_in_place_box_redraw` and `test_b11_height_clamping_altscreen_details_and_display_width`.
- Programmatically slice all 61 `test_*` methods from `tests/test_run_block.py` via `ast.parse()` (`node.lineno`..`node.end_lineno`) without re-emitting test bodies in chat into modular test files mirroring `src/`:
  - `tests/test_cli.py` (`--help`, `--version`, `build.py --check`, `install.sh`, self-update, session cleaning, state dir and prune controls)
  - `tests/test_safety.py` (`src/safety.py` risk categories, AST/regex scanner, custom safety rules, unicode spoof, quotes/continuations/eval, sandbox env scrubbing, explicit warning choice)
  - `tests/test_ui.py` (`src/ui.py` ASCII fallback, border/tag colors, box wrapping and hanging indents, height clamping, altscreen details, `SIGWINCH` redraw, progress alignment and silent collapse)
  - `tests/test_bundle.py` (`src/bundle.py` and `src/bundle_plan.py` stdin bundle start, preamble headers and `Workdir:` preference, `Bundle-*` protocol and fragment parser, top-style table, `--bundle-plan` / `--part`, `i(nfo)` part viewer, embedded block-rule injection, `START SESSION` `e(dit)` flow, `-p`/`--prompt`)
  - `tests/test_runner.py` (`src/runner.py` step execution, `--plan`, `--fix` chaining and AST validation, step collision renumbering, operation lines and durations, `START STEP` and `END STEP` `e(dit)`, separate stderr capture, `--list`/`--show`/`--retry`)
- Remove monolithic `tests/test_run_block.py`, document the modular `tests/` layout in `AGENTS.md`, rebuild `./run_block` via `build.py`, verify `python3 build.py --check`, ensure `python3 -m unittest discover -s tests` runs all 61 tests in `<3s` (with `test_f59_sigwinch_in_place_box_redraw` passing 50 consecutive runs), and bump `VERSION` for a PATCH release.

# ✅ [DONE] F73: Support -p/--prompt flag to embed prompt text into session bundle — *2026-11-20, Added repeatable -p/--prompt flag to embed prompt text into session bundle across TTY and piped start modes*

- Depends on: F66
- Add repeatable `-p TEXT` / `--prompt TEXT` CLI options in `src/cli.py` and `cmd_start()` (`src/bundle.py`), joining multiple non-empty values with `\n\n` (ignoring whitespace-only values) symmetrically with `agents_bundle`.
- Support `-p` / `--prompt` across all session-creation modes: bare `run_block -p "..."` and `run_block --start -p "..."` in TTY without `stdin`, and piped `<cmd> | run_block -p "..."` / `<cmd> | run_block --start -p "..."`, combined with `--session`, `--sandbox`, and `--force`.
- Reject `-p` / `--prompt` with an explicit CLI usage error when passed to incompatible commands (`<session>/<step>`, `--fix`, `--retry`, `--list`, `--show`, `--plan`, `--bundle-plan`, `--clean`, `--sandbox`, `--update`, `--check-update`).
- Embed the prompt cleanly into the bundle body in `format_start_bundle()` (`src/bundle.py`) and `src/bundle_plan.py`:
  - When `stdin` is empty (or wrapped as `===== Prompt =====` by `F66`), include `===== Prompt =====` with the `-p` text alongside embedded `===== Rules =====`.
  - When `stdin` already ends with a `===== Prompt =====` section (including boundary-marked fragments from `agents_bundle`), append `\n\n<prompt>` inside that trailing `===== Prompt =====` section (before `<!-- bundle:<nonce>:end -->` if present) without duplicating the section header.
  - When `stdin` has other sections without a trailing `===== Prompt =====`, append `===== Prompt =====\n<prompt>` at the end and register it in `bundle_plan` as `kind: "prompt"` (`name: "Prompt"`) even when `Bundle-Boundary` is active.
- Coordinate with `F69` (`0.raw` preservation) and `F57` (`a(ppend)`): ensure `0.raw` and clean `<session>/0` stay consistent and `bundle_plan` counts the embedded prompt accurately.
- Update `--help` in `src/header.py`, `README.md`, `src/rules/blocks/bash.md` / `src/rules/blocks/pwsh.md` if applicable, add offline tests in `tests/test_run_block.py`, and rebuild `./run_block` via `build.py`.

# ✅ [DONE] F64: Record part line ranges and support viewing individual parts by number in Details and CLI — *2026-11-19*

- Depends on: F63, F54, F68
- Record 1-based `line_start` and `line_end` line ranges in the final cleaned `<session>/0` for each part in `src/bundle_plan.py` and `src/bundle.py` (`format_start_bundle()`, `refresh_bundle_plan_meta()`), covering both boundary-marked fragments and `_split_section_fallback()` while accounting for `<session>/0` header lines and collapsed blank lines (and body-relative 1-based ranges for `stdin` `--bundle-plan`) without duplicating fragment text in `meta.json`.
- When `i(nfo)` is active in `START SESSION` (`src/ui.py`), allow selecting a part directly (e.g. cursor selection in the fullscreen list and/or `p(art)` prompt by 1..N index without cluttering the `Parts` tree with numeric prefixes) to inspect that fragment's content (with an action to open `<session>/0` in the configured editor) and return cleanly to `START SESSION`.
- Add `--part N` option to `run_block --show` and `run_block --bundle-plan` in `src/cli.py`, `src/runner.py`, `src/bundle_plan.py`, and `src/header.py`; accept `--show <session> --part N`, `--show <session>/0 --part N`, and `--show --part N` (latest session `/0`), failing cleanly on non-zero steps or out-of-range part numbers.
- Update `README.md` and unit tests in `tests/test_run_block.py`, and rebuild `run_block` via `build.py`.

# ✅ [DONE] F68: Redesign bundle breakdown table in top style, fix header/kind attribution, and highlight heavy parts — *2026-11-19*

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

# ✅ [DONE] F76: Show only Parts without duplicate Summary in START SESSION i(nfo) — *2026-11-19*

- Role: work
- Update `_collect_info_report()` in `src/ui.py` for `title_kind == "START SESSION"` to remove the redundant `Summary (N parts):` block (`format_bundle_summary_lines()`) and display only `Parts (N parts):` via `_build_start_bundle_parts(..., details=True)` (`format_bundle_parts_lines()`) alongside `Bundle warnings`.
- Keep `Summary` in `run_block --bundle-plan` (`src/bundle_plan.py`, with `--full` adding `Parts`) and keep `Session Bundle Summary` in step `i(nfo)` views (`START STEP`, `END STEP`, etc.) unchanged.
- Coordinate with `F68`, `F64`, and `F69`: `Parts` retains the full tree hierarchy with group totals and leaf parts needed by `F64` part selection and `F69` markup-preserving edits, without duplicating the collapsed tree in `START SESSION` `i(nfo)`.
- Acceptance criteria: opening `i(nfo)` in `START SESSION` shows `Parts (...)` without a duplicate `Summary (...)` section; `README.md` (if applicable) and offline tests in `tests/test_run_block.py` are updated, and `./run_block` is rebuilt via `build.py`.

# ✅ [DONE] F75: Require explicit choice on safety warnings without default N — *2026-11-20*

- Role: work
- Update `_safety_prompt_suffix()`, `_safety_prompt_prefix()`, `format_safety_box()`, and `confirm_execution()` in `src/ui.py` so when `default_yes` is `False` (safety warnings `findings` present or `RUN_BLOCK_APPROVE_CMD` returns `prompt`), the `START STEP` prompt renders `[y/n/i(nfo)]:` (no capitalized default) instead of `[y/N/i(nfo)]:`.
- Pass `default_no=False` alongside `default_yes=False` to `read_confirm_key()` in `confirm_execution()` (`src/ui.py`) when safety warnings or explicit approval prompt are active so pressing `Enter` is ignored until the user explicitly chooses `y` (run), `n`/`q`/`Esc` (abort), or `i` (inspect).
- Verify `_parse_confirm_line()` (`src/ui.py`) returns `"invalid"` on empty newline `"\n"` when both `default_yes` and `default_no` are `False`, while still returning `"no"` on EOF (`""`) and keeping `[Y/n/i(nfo)]:` (`default_yes=True`) unchanged when no safety warnings are present (also distinct from `F42` `SESSION COMPLETED` `[y/N/i(nfo)]:`).
- Acceptance criteria: `START STEP` with safety warnings displays `[y/n/i(nfo)]:` and ignores `Enter`; `y` executes and `n`/`q`/`Esc` aborts; clean blocks keep `[Y/n/i(nfo)]:`; `README.md` and offline tests in `tests/test_run_block.py` are updated, and `./run_block` is rebuilt via `build.py`.

# ✅ [DONE] F54: Remove Steps from END box and add hybrid i(nfo) metadata viewer across TUI blocks — *2026-11-20, Remove Steps from END STEP box and unify fullscreen i(nfo) viewer across TUI prompts*

- Depends on: B11
- Remove the `Steps: 1. [tag] ...` summary line from the main `END STEP` (`END`) box in `build_box_body_lines()` (`src/ui.py`), keeping `END STEP` focused on `Step`/`Block`, `Workdir`, active `Sandbox`, `Exit`/`Error`/`Fix` on failure, `Output`, and `Stats`.
- Unify detail inspection and editing behind a single `i(nfo)` hotkey across all interactive TUI prompts (`START SESSION`, `START STEP`, `END STEP`, `NOT RUN`, `SYNTAX ERROR`, `STEP ALREADY EXISTS`, `MISSING PREVIOUS STEP`, `SESSION COMPLETED`) in `src/ui.py`, `src/bundle.py`, and `src/runner.py`:
  - Move `e(dit)` (for `<session>/0`, `block.*`, and `out`), `s(cript)`/`o(utput)` view/edit, and rare collision overwrite/re-run inside the fullscreen `i(nfo)` inspector so compact inline prompts drop `e(dit)`, `s(cript)`, `o(utput)`, and `d(etails)`:
    - `START SESSION` / `END STEP` / `SYNTAX ERROR` / `NOT RUN`: `[Y/n/a(ppend)/i(nfo)]:` (coordinating `a(ppend)` with `F57`)
    - `START STEP`: `[Y/n/i(nfo)]:` / `[y/N/i(nfo)]:`
    - `STEP ALREADY EXISTS`: `[Y/n/r(enumber)/i(nfo)]:` (with `out`) or `[r(enumber)/n/i(nfo)]:` (without `out`)
    - `MISSING PREVIOUS STEP`: `[r(enumber)/n/i(nfo)]:` (no `Enter` default)
    - `SESSION COMPLETED`: `[y/N/i(nfo)]:`
  - Pressing `i` opens a styled alternate-screen fullscreen `i(nfo)` view showing unfiltered headers (including `Sandbox: off` and all `meta.json` headers), artifact paths and edit backups (`0.orig`, `block.orig.*`, `out.orig`), line/char/token counts with `Stats:` value rendered in white foreground (while keeping inline `Stats:` dimmed in the compact box), full `START SESSION` `Summary`/`Parts`/warnings breakdown, per-operation execution timings with percentage shares and `(failed)` markers from `<session>/<step>/meta.json` (`src/config.py`), and pre-execution `START STEP` analysis (`analyze_script()` on `block.orig.*` when edited, else `block.*`).
  - Inside `i(nfo)`, support keyboard scrolling (`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn`), `e(dit)` on the active artifact (recalculating plan/stats on return), `s(cript)`/`o(utput)` inspection/editing and `o(verwrite)` on step collisions, `v(iew)` to open the plain-text report in `resolve_editor_command()`, and clean return to the active prompt on `q`/`Esc`/`i`.
- Acceptance criteria: compact inline boxes stay minimal (`i(nfo)` replaces `d(etails)`/`e(dit)`/`s(cript)`/`o(utput)`); `END STEP` omits `Steps:`; `i(nfo)` shows full metadata, white `Stats:`, bundle breakdown, operation timings, and original plan on alternate screen with `e(dit)` and `v(iew)` actions; `README.md` and offline tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F71: Rename TUI boxes to START SESSION / START STEP / END STEP, unify [Y/n] prompts, and improve renumber UX — *2026-11-19, v0.23.2*

- Rename TUI box titles in `src/ui.py`, `src/bundle.py`, and `src/runner.py`: `BUNDLE` -> `START SESSION`, `PLAN` -> `START STEP`, `END` -> `END STEP`, and display `Step: <label>` in step boxes (keeping `Next-Block:` / `# Block:` in agent protocol headers).
- Standardize prompt suffixes in `src/ui.py` and `src/runner.py`: omit `Enter` and `Esc` labels from `[...]` brackets (replace `[Enter/.../Esc]:` with `[Y/n/...]:`), use a single uppercase letter exclusively for the `Enter` default (fixing `START STEP` warnings `[y/n/...]` -> `[y/N/...]`), remove `r`/`R` case-sensitive collisions, while preserving `Enter`, `n`/`q`/`Esc` behavior.
- Remove the interactive `SESSION ALREADY EXISTS` overwrite dialog from `start_session()` (`src/runner.py`) so `--start`/`--session` on an existing session without `--force` fails immediately with an explicit error.
- Redesign `STEP ALREADY EXISTS` in `src/runner.py` and `src/ui.py`:
  - When `out` exists, prompt `-> Copy out to clipboard? [Y/n/r(enumber)/s(cript)/o(utput)]:` (until `F54` moves `s`/`o` into `i(nfo)`): `Enter`/`y` copies existing `out` to clipboard and exits, `r` renumbers to `Next` and proceeds into `START STEP`, `n`/`q`/`Esc` exits (with `--retry` available when an explicit re-run is desired prior to `F54`).
  - When `out` is missing, prompt `-> Renumber to <next_label>? [r(enumber)/n/s(cript)]:` with no `Enter` default.
- Redesign `MISSING PREVIOUS STEP` in `src/runner.py` and `src/ui.py`: compute `<first_missing_label>` as the first missing/free step starting from `1` for strictly sequential steps, prompt `-> Renumber to <first_missing_label>? [r(enumber)/n]:` with no `Enter` default (until `F54` adds `i(nfo)`), and on `r` renumber and proceed into `START STEP`.
- When a step is renumbered (`STEP ALREADY EXISTS` or `MISSING PREVIOUS STEP`), record an explicit notice in the captured step output `out` (alongside `renumbered_from` in `meta.json`) informing the agent of the executed step number, and update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` so the agent trusts and continues from the renumbered step.
- Target files: `src/ui.py`, `src/runner.py`, `src/bundle.py`, `src/header.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, `tests/test_run_block.py`.

# ✅ [DONE] B11: Fix TUI box height overflow, header duplication on redraw, and keep inline boxes minimal — *2026-11-19*

- Keep inline TUI boxes compact so they stay within visible terminal height (`shutil.get_terminal_size().lines`): remove the `Summary:` table from the inline `START SESSION` (`BUNDLE`) box (retaining core headers, `Bundle:`, dim `Stats:`, and `Bundle warnings` when present), and clamp long inline sections in `START STEP` (`PLAN`), `END STEP` (`END`), and confirmation dialogs to available `term_rows` with a `... +N more` hint so the top border (`╭─ ...`) never scrolls into scrollback before a redraw.
- Display expanded bundle details in an alternate-screen fullscreen panel (`\033[?1049h` / `\033[?1049l`, modeled after `top`/`less`) with keyboard scrolling (`Up`/`Down`, `j`/`k`, `PgUp`/`PgDn`), clean return (`Esc`/`q`/`d`/`i`), and clipboard copy on `Enter` so toggling details never leaves duplicate headers or stale lines in scrollback.
- Fix `display_width()` in `src/ui.py` to count Unicode combining and zero-width format characters (`Mn`, `Me`, `Cf`) as width `0` and normalize/expand tabs (`\t`) during rendering so `_box_rows_above_prompt()` always matches actual terminal row wrapping.
- Track both `cols` and `rows` (`term_rows`) across `offer_clipboard_copy()`, `confirm_execution()`, and `prompt_yes_no_box()` (`src/ui.py`) so `SIGWINCH` height or width changes reflow cleanly without leaving stale `╭─ ...` rows.
- Target files: `src/ui.py`, `src/runner.py`, `src/bundle.py`, `README.md`, `tests/test_run_block.py`.
- Acceptance criteria: toggling details, resizing terminal width or height, or returning from `e(dit)` never produces duplicate `╭─ ...` headers; inline boxes fit within `term_rows`; fullscreen details scroll cleanly on alternate screen; `README.md` and offline tests in `tests/test_run_block.py` cover height clamping, alternate-screen redraw, and `display_width()` edge cases.

# ✅ [DONE] F67: Remove obsolete src/bundles/run_block.bundle export and bundle references — *2026-11-19*

- Depends on: F66
- Delete `src/bundles/run_block.bundle` (and empty `src/bundles/`) and remove `bundle vitalio/run_block` from `.agents_bundle` once downstream repositories stop referencing `vitalio/run_block`.
- Update `AGENTS.md` (documenting `src/rules/blocks/*.md` as internal embedded sources instead of an exported `vitalio/run_block` bundle), `README.md`, and `tests/test_run_block.py`.

# ✅ [DONE] F66: Embed terminal block rules in run_block and start rule-only session on bare invocation — *2026-11-19, Embed bash/pwsh terminal block rules in built run_block, inject/deduplicate into session bundles, and start rule-only sessions on bare TTY invocation.*

- Embed `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` into the built `./run_block` script via `build.py` (with `--check` verifying embedded rules match `src/rules/blocks/*.md`), stripping leading `# Description:` lines, selecting `bash` vs `pwsh` via `get_setting("shell")` / `_is_powershell()`, and substituting `{cmd:run_block}` with `prog_name()`.
- Inject the embedded rule in `format_start_bundle()` (`src/bundle.py`) and register it in `src/bundle_plan.py`:
  - When `Bundle-Boundary` is present, insert into the top-level `===== Rules =====` section only outside `<!-- bundle:<nonce>:part ... --> ... <!-- bundle:<nonce>:end -->` blocks (or prepend `===== Rules =====` before the first part if absent), tracking the fragment in `bundle_plan` as `kind: "rule"`, `id: "run_block:blocks/bash"` (or `"blocks/pwsh"`), `chain: ["run_block"]` so `d(etails)`/`i(nfo)`, `--bundle-plan`, `line_start`/`line_end`, and `secret_detected` exemption work uniformly.
  - In fallback mode without `Bundle-Boundary`, inspect only the start of the body: insert after leading `===== Rules =====` if present, otherwise prepend `===== Rules =====` and wrap unlabeled plain stdin text under `===== Prompt =====` so user input is not merged into `Rules`.
  - Deduplicate against legacy `vitalio/run_block` input by checking `bundle_plan` parts (`blocks/bash` / `blocks/pwsh`) or an existing `## Terminal blocks (` heading.
- Update `main()` and `cmd_start()` in `src/cli.py` and `src/bundle.py` so bare `run_block` (no args with TTY `stdin`) and `run_block --start` in TTY start a rule-only `<session>/0` bundle and open `START SESSION` (`BUNDLE`) instead of exiting 2 with usage, while keeping `run_block --sandbox <mode>` mapped to `cmd_sandbox()`.
- Update `src/header.py` (`--help`), `AGENTS.md`, `README.md`, and `tests/test_run_block.py` (coordinating with `F71` if `START SESSION` / renumber rules have already landed), rebuild `./run_block`, and bump `VERSION` for a MINOR release.

# ✅ [DONE] F56: Align operation progress lines, update status colors, and collapse silent steps — *2026-11-19*

- Remove the 2-space leading indentation on step completion lines in `_ProgressLineFilter._format_step_done()` (`src/runner.py`) so `✓` and `✗` (plus ASCII `+` and `x`) align at column 0 directly beneath `▸` and `>`.
- Update `_ProgressLineFilter` ANSI styling in `src/runner.py`: render start banners (`▸`) and successful completion lines (`✓`) in neutral gray (`\x1b[90m`), and failed completion lines (`✗`) in red (`\x1b[31m`).
- Track in `_ProgressLineFilter` (`src/runner.py`) whether any `out` text was emitted while a step was active: when a step finishes without output on a TTY, overwrite the start banner line in place (`\033[1A\r\033[2K`) with a single-line summary `✓ [N/M] [tag] desc (dur)` (truncated to `_hr_width()`); when output was emitted, keep the `▸` header above the output and print `✓ [N/M] (dur)` or `✗ [N/M] (dur)` below at column 0.
- Acceptance criteria: silent steps collapse into a single column-0 line with duration on TTY; steps with output keep `▸` above and `✓`/`✗` at column 0 below; colors use gray for normal progress and red for failures; `README.md` and unit tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F58: Wrap long lines inside all TUI boxes while preserving hanging indents — *2026-11-18, Enforced terminal-width wrapping with hanging indents across all TUI boxes*

- Enforce terminal-width wrapping (`_hr_width() - 2`) inside `_render_block()` in `src/ui.py` for all rendered TUI boxes (`BUNDLE`, `PLAN`, `END`, `NOT RUN`, `SYNTAX ERROR`, `MISSING PREVIOUS STEP`, `STEP ALREADY EXISTS`, and `prompt_yes_no_box`), so no content or prompt line exceeds the terminal width and breaks the left `│ ` border.
- Preserve hanging indentation on wrapped lines: align continuation lines under the value column for `Key:   value` rows, preserve leading list/tree indentation (`  `, `    `, `├─ `, `└─ `) on already-indented items without double-wrapping lines that already fit, and clamp `_extract_last_error_line()` in `src/ui.py` to the available box content width.
- Acceptance criteria: on narrow terminals (40–70 columns), long `Workdir:`, `Output:`, `Error:`, `Stats:`, `Steps:`, headers, and prompt lines wrap cleanly with `│ ` on every visual row and aligned continuation indents across all TUI box types; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F59: Redraw active TUI box in place on terminal resize (SIGWINCH) — *2026-11-18, Redraw active TUI box in place on terminal resize (SIGWINCH)*

- Monitor terminal window resize events (`SIGWINCH` via a self-pipe registered in `select()`) while waiting for user input in `read_clipboard_key()` and `read_confirm_key()` in `src/ui.py`, debouncing rapid resize events (~25ms) and restoring the previous `SIGWINCH` handler cleanly on exit.
- When terminal width (`_hr_width()`) changes during `offer_clipboard_copy()`, `confirm_execution()`, or `prompt_yes_no_box()` in `src/ui.py`, recalculate the visual row count of the previously rendered box under the new width (`_box_rows_above_prompt()`), erase the old box in place, and re-render the active box (`BUNDLE`, `PLAN`, `END`, or confirmation dialog) for the new width with the cursor restored at the prompt.
- Acceptance criteria: shrinking or widening a POSIX TTY while an interactive TUI prompt is waiting redraws the active box cleanly in place without broken `│ ` borders or duplicate lines, and subsequent `e(dit)` redraws remain aligned; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F61: Auto-detect existing step number collisions in run_block and offer interactive renumbering to the next free step — *2026-11-18, Offer interactive r(enumber) to next free step on step number collision*

- When starting a step that already exists on disk (e.g., trying to run s154/8 when it already ran), prompt the user in the interactive TUI block confirmation: `Step s154/8 already exists. r(enumber) to next free step / r(estart) / Esc [r/R/Esc]:` (or similar prompt).
- On `r` / renumber, automatically scan session directory for the next available step index (e.g. s154/9), update the block script header / metadata, and proceed without losing work.

# ✅ [DONE] F62: Colorize full PLAN operation lines with bold tags and regular body tint — *2026-11-18*

- Update `_colorize_operation_lines()` and `_colorize_python_op_rest()` in `src/ui.py` so every operation tag in `_TAG_COLORS` (`read`, `write`, `exec`, `git`, `python`) renders only the `[tag]` bracket in bold (`\x1b[1;...m`) while the operation body and any wrapped continuation lines render in the matching non-bold color (`\x1b[...m` without `1;`), keeping step numbers, tree connectors (`├─`, `└─`), and `NO_COLOR`/non-TTY output unchanged.
- In `_colorize_python_op_rest()` in `src/ui.py`, render the base Python summary (`N lines — calls: ...`) in regular green (`\x1b[32m`), and render inline `writes: ...` and `reads: ...` fragments (both label and file list) in regular yellow (`\x1b[33m`) and regular bright blue (`\x1b[94m`) respectively.
- Acceptance criteria: in TTY color mode, all `PLAN` `Operations:` lines (`[read]`, `[write]`, `[exec]`, `[git]`, `[python]`, AST-expanded sub-items, and wrapped continuation lines) show bold `[tag]` labels with non-bold matching-color bodies; `tests/test_run_block.py` (including `test_f27_visual_hierarchy_border_colors_and_block_plan_highlights`, `test_f40_distinct_operation_tag_colors`, and wrapped/inline cases) and `README.md` (if needed) are updated, and `run_block` is rebuilt via `build.py`.

# ✅ [DONE] F63: Unify Stats and hierarchical tabular bundle Summary/Details with char sizes and clean Preamble — *2026-11-18, Unify Stats/Summary/Details with char sizes, neutral chain hierarchy, and header reconciliation*

- Keep `run_block` strictly generator-agnostic under the Bundle Input Protocol (`AGENTS.md`): never special-case producer filenames (such as `.agents_bundle`), and instead derive hierarchy from neutral `chain` (with fallback to legacy `group`/`via` fields when `chain` is absent).
- Fix false `[text] Preamble` fragments in `parse_bundle_fragments()` (`src/bundle_plan.py`): ignore standalone `===== ... =====` section headers (such as `===== Rules =====`) outside `<!-- bundle:<nonce>:part ... -->` markers so only real unframed preamble text creates a `Preamble` part.
- Eliminate duplicate `<prefix>: <prefix>:<name>` labels in `format_bundle_group_items()` and `format_bundle_part_items()` (`src/bundle_plan.py`) when the item name already starts with the group/chain prefix.
- Expand root-level items (`chain: []` or empty `group`) directly in `Summary` and expand nested `chain` levels (`bundle` / `ruleset` hierarchies) in `Summary` and `d(etails)` (`src/bundle_plan.py`, `src/ui.py`).
- Unify `Stats`, `Summary`, `Parts` (`d(etails)`), and `--bundle-plan` `Total:` around `chars` as the shared size unit (`count_tokens()` and `format_stats()` in `src/ui.py`, `format_bundle_plan_text()` in `src/bundle_plan.py`, `format_start_bundle()` in `src/bundle.py`, and `Script:` sizing in `src/safety.py`), storing `chars` per part in `_build_bundle_plan()` (falling back to `bytes` for older `meta.json`).
- Visually attach `Summary` / `Parts` directly under `Stats:` in the bundle box without a blank separator line (showing part count and `(edited)` on `Stats:` and keeping `RUN_BLOCK_TOKEN_STATS=false` behavior consistent), and account for `<session>/0` headers and inter-section spacing (e.g. a `[header]` entry when non-zero) so lines, `chars`, tokens, and `%` in the breakdown reconcile to 100% of `Stats:`.
- Render `Summary` and `Parts` as right-aligned numeric columns (`%`, `chars`, `L`, `tokens`) followed by `[kind]` and the description column, wrapping only the description column cleanly on narrow terminals (`src/bundle_plan.py`, `src/ui.py`).
- Update `README.md` and unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F65: Rename TUI box titles START BUNDLE to BUNDLE and BLOCK PLAN to PLAN — *2026-11-18, Renamed START BUNDLE to BUNDLE and BLOCK PLAN to PLAN across UI, bundle start, help, docs, and tests; rebuilt standalone run_block.*

- Rename the `START BUNDLE` box title to `BUNDLE` and the `BLOCK PLAN` box title to `PLAN` across `src/ui.py` (`format_safety_box()`, `_TITLE_COLORS`, `_block_colors()`, `build_box_body_lines()`, `_clipboard_prompt_line()`, `offer_clipboard_copy()`) and `src/bundle.py` (`cmd_start()`).
- Update CLI `--help` text in `src/header.py`, project docs in `AGENTS.md` and `README.md`, and all assertions and box-title fixtures in `tests/test_run_block.py`.
- Acceptance criteria: TUI box headers render `BUNDLE`, `PLAN`, and `END` consistently with existing border/title colors and prompt behaviors; `build.py --check` and full `tests/test_run_block.py` pass; `run_block` is rebuilt via `build.py`.

# ✅ [DONE] B10: Forward all session headers into END and fix session dir resolution — *2026-11-18, Fixed _resolve_session_dir(), passed sdir into offer_clipboard_copy(), added regression tests, and rebuilt run_block.*

- Fix `_resolve_session_dir()` in `src/ui.py` so a step directory containing step metadata (`<session>/<step>/meta.json`) never masks the parent session directory (`<session>/0` and `<session>/meta.json`).
- Pass `sdir` explicitly from `src/runner.py` to `offer_clipboard_copy()` (and forward it to `format_clipboard_box()` / `build_box_body_lines()` in `src/ui.py`) so `END`, `NOT RUN`, and `SYNTAX ERROR` boxes always receive the session directory directly.
- Acceptance criteria: `END` (as well as `NOT RUN` and `SYNTAX ERROR`) renders all exposed session headers (`Workdir`, `Role`, `Task`, `Title`, etc.) identically to `PLAN` even after `<session>/<step>/meta.json` has been written; add regression tests in `tests/test_run_block.py` covering `END`, `NOT RUN`, and `SYNTAX ERROR` with real `<session>/<step>/meta.json` files, update `README.md` if needed, and rebuild `run_block` via `build.py`.

# ✅ [DONE] F60: Unify [python] operation tree expansion in BLOCK PLAN — *2026-11-18, Unified [python] operation tree expansion in BLOCK PLAN*

- Update `_emit_py_op()` in `src/safety.py` so `[python]` operations expand into nested child items (`├─` / `└─`) consistently whenever a Python block touches multiple files or combines reads and writes (`total_paths > 1`), regardless of whether those files live in different subdirectories (`len(dir_buckets) > 1`) or in the same directory / repository root (such as `build.py, run_block`), keeping the single-line summary only for trivial 0–1 file Python blocks.
- Ensure `_group_operations_for_display()` in `src/ui.py` preserves `├─` / `└─` tree markers for expanded `[python]` child `[write]` / `[read]` entries even when all operations are in the repository root (`dir == ""`).
- Acceptance criteria: multi-file `[python]` blocks in the same directory or root render with `├─` / `└─` child `[write]` / `[read]` rows matching cross-directory `[python]` blocks; single-file `[python]` blocks remain compact; `README.md` and offline unit tests in `tests/test_run_block.py` are updated.

# ✅ [DONE] F55: Hide Bundle-* transport headers from TUI boxes and clamp long Title headers — *2026-11-18, Exclude Bundle-* transport headers from TUI boxes and clamp long exposed headers*

- Depends on: F46
- Ensure `Bundle-*` transport headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) are excluded from TUI boxes (`START BUNDLE`, `BLOCK PLAN`, `END`, and confirmation dialogs) while remaining available in `meta.json`, `--info`, and the `i(nfo)` screen (`src/bundle_plan.py`, `src/config.py`, `src/ui.py`).
- Truncate overly long exposed header values (such as `Title:`) with an ellipsis (`…`) in `format_session_header_lines` (`src/ui.py`) so long task titles stay single-line without wrapping or overflowing box width.
- Sync `README.md` and unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F47: Add bundle diagnostics, START BUNDLE details view, and --bundle-plan CLI — *2026-11-18*

- Depends on: F46
- Extend `src/bundle_plan.py`, `src/ui.py`, `src/cli.py`, and `src/header.py` to surface bundle analysis and diagnostics.
- Detect and report bundle warnings: non-zero command `rc` or empty command output, oversized fragments or total token budget exceedance, and accidental secrets in non-rule content by reusing `src/safety.py` secret detection without duplicating patterns.
- Render a compact grouped summary (grouping parts by `kind` + `group`) plus warnings inside `START BUNDLE`, and add a `d(etails)` action in the `START BUNDLE` prompt to inspect the full per-part breakdown.
- Add `run_block --bundle-plan [<session>] [--json] [--full]` (reading `stdin` when no session is given, or `meta.json` / `<session>/0` for an existing session), and sync `README.md`, `src/rules/blocks/*.md`, and `tests/test_run_block.py`.

# ✅ [DONE] F46: Implement Bundle Input Protocol header filtering and fragment marker parser — *2026-11-18*

- Define `src/bundle_plan.py` and integrate with `src/bundle.py` and `src/config.py` to implement the generator-agnostic Bundle Input Protocol.
- Treat `Bundle-*` preamble headers (`Bundle-Command`, `Bundle-Boundary`, `Bundle-Expose`, `Bundle-Hide`) as transport metadata stored in `<session>/meta.json` only, and forward `stdin` headers into `<session>/0` per `Bundle-Expose` / `Bundle-Hide` without overriding `Session`, `Next-Block`, `Workdir`, `Sandbox`, or `Date`.
- When `Bundle-Boundary: <nonce>` is present, parse `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->` markers, strip them cleanly from `<session>/0`, and fall back to `===== ... =====` section splitting when no boundary is present.
- Compute per-part lines, bytes, GPT/Claude token counts, and percentage share, persisting structured `bundle_plan` metadata (without raw text bodies) in `<session>/meta.json`, with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F53: Hide Sandbox: off in TUI boxes and show Sandbox only when enabled — *2026-11-18, Omit Sandbox: off in TUI boxes while keeping it in session bundles and --sandbox status*

- Omit the `Sandbox:` header line in `format_session_header_lines()` (`src/ui.py`) when the normalized sandbox mode is `off` (or empty), so `START BUNDLE`, `BLOCK PLAN`, `END`, `NOT RUN`, and `SYNTAX ERROR` boxes only display `Sandbox: <mode>` when sandboxing is enabled (`strict`, `nonet`, or a custom wrapper).
- Preserve `Sandbox: off` in `<session>/0` bundle headers (`src/bundle.py`), explicit `run_block --sandbox` status output (`src/runner.py`), and the full `i(nfo)` metadata view.
- Acceptance criteria: `Sandbox: off` is hidden across standard TUI boxes; active sandbox modes (`strict`, `nonet`, custom) still render with full details; `<session>/0` and `run_block --sandbox` remain unchanged; offline unit tests in `tests/test_run_block.py` cover both `off` and active sandbox rendering.

# ✅ [DONE] F43: Brighten Error line, title and border colors, and keep confirmation prompt distinct from Safety warnings — *2026-11-17, Brighten Error, title, and border colors and keep confirmation prompt distinct from safety warnings*

- In `src/ui.py`, `_ERROR_COLOR` uses non-bold `\x1b[31m`, so `Error:` values in `END` and `SYNTAX ERROR` boxes look dim on dark terminal themes compared to bold tags and headers.
- `_TITLE_COLORS` (`START BUNDLE`, `BLOCK PLAN`, `END`, `SYNTAX ERROR`, `NOT RUN`, `MISSING PREVIOUS STEP`, `STEP ALREADY EXISTS`) use the regular-intensity bold palette (`1;36`, `1;33`, `1;32`, `1;31`), and the fallback for unknown titles in `src/ui.py` is `\x1b[1;36m`. Make them brighter (`1;96`, `1;93`, `1;92`, `1;91`).
- `_BORDER_COLOR` (`\x1b[2;36m`) is dim, and the box builder derives border color from the title color by replacing the bold prefix with `2;` (`"\x1b[2;" + t_col[4:]`). Change the derivation so the border keeps the brightness of the title color instead of being forced to dim, and make the default `_BORDER_COLOR` non-dim.
- In `format_safety_box` and `confirm_execution` (`src/ui.py`), when `findings` is non-empty, `-> Execute this block?` is wrapped in `_WARN_COLOR` (`\x1b[1;31m`), which is the same color as the `Safety warnings` header. Keep the prompt visually distinct from `_WARN_COLOR`.
- Update `_ERROR_COLOR` to bright bold red (`\x1b[1;91m`).
- Update the ANSI styling unit tests in `tests/test_run_block.py` to match the new codes, including a check that the border of a bold title is not dim.
- Out of scope: `_KEY_COLOR` (metadata keys) and `_TAG_COLORS` (operation tags).

# ✅ [DONE] F49: Record and display execution duration for blocks and numbered operations — *2026-11-17, Record block/operation durations and nest AST sub-items in BLOCK PLAN*

- Measure wall-clock block execution duration (`time.monotonic()`) around child process execution (`subprocess.Popen` to `wait()`, excluding `BLOCK PLAN` confirmation wait) in `src/runner.py`.
- Include formatted duration in the trailing `[<session>/<step>] END` marker written to `out` (e.g. `[s1/1] END (3.4s)` or `[s1/1] END (exit 1, 3.4s)`, keeping `_step_status()` parsing compatible) and append duration to `Stats:` in the `END` box (`src/ui.py`).
- Track per-operation elapsed durations in `_ProgressLineFilter` (`src/runner.py`) via `__RB_STEP__:N` markers, showing step timing in live progress output and surfacing per-operation timings (plus step `duration_ms` metadata) for `END` diagnostics and `run_block -l` / `--info` (`D1`, `F20`).
- Visually distinguish unnumbered AST-expanded sub-items (`[read]`, `[write]`) under a numbered parent step (such as `1. [python]`) in `BLOCK PLAN` (`src/ui.py`, `src/safety.py`) with a subordinate marker or nested indent so sub-operations clearly belong to their parent step.
- Target files: `src/runner.py`, `src/ui.py`, `src/safety.py`, `src/config.py`, `README.md`, `tests/test_run_block.py`.

# ✅ [DONE] F52: Support e(dit) on END output (and 0.orig on START BUNDLE) with original backup and stats recalculation — *2026-11-17*

- Replace `v(iew)` with `e(dit)` in the `END` clipboard prompt (`src/ui.py`, keeping `v` as a compatibility alias) and preserve the unmodified output as `<session>/<step>/out.orig` on the first edit without overwriting it on subsequent edits; also preserve `<session>/0.orig` on the first `e(dit)` in `START BUNDLE`.
- Recompute `stats_line()` (lines, bytes, and Claude/GPT/Gemini token counts), re-extract `Error:` when `rc != 0`, refresh the clipboard copy target (`resolve_clipboard_target`), and redraw the full `END` box in place with an explicit `(edited)` indicator (`src/ui.py`, `src/runner.py`).
- Surface `(edited)` markers in `run_block --show` when `block.orig.*`, `out.orig`, or `0.orig` exists (`src/runner.py`), sync `README.md` and `src/header.py`, and add unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F51: Support e(dit) on BLOCK PLAN script with original backup and plan/token recalculation — *2026-11-17*

- Replace `v(iew)` with `e(dit)` in the `BLOCK PLAN` confirmation prompt (`src/ui.py`, keeping `v` as a compatibility alias) and preserve the unmodified script as `<session>/<step>/block.orig.sh` (or `.ps1`) on the first edit without overwriting it on subsequent edits.
- Re-validate script syntax after editing (`bash -n` / PowerShell parser in `src/runner.py`), showing `SYNTAX ERROR` and aborting execution if the edited script fails syntax validation.
- Recompute `summarize_script_actions()` (operations list and `Script:` line/byte/token statistics), `scan_script_risks()` warnings, and default confirmation prompt (`src/ui.py`, `src/runner.py`), and redraw the full `BLOCK PLAN` box in place with an explicit `(edited)` indicator (and note original backup in `--show`).
- Sync `README.md` and `src/header.py` help text and add unit tests in `tests/test_run_block.py` covering `e(dit)` in `BLOCK PLAN`, `block.orig.*` preservation, statistics/risks recalculation, and post-edit syntax error handling.

# ✅ [DONE] B9: Fix false-positive [exec] and [remote-exec] on quoted variable assignments and --exclude-dir=eval flags — *2026-11-17, Fix false-positive [exec] and [remote-exec] on quoted variable assignments and --exclude-dir=eval flags*

- Update variable assignment matching in `src/safety.py` (`VAR_ASSIGN_RE` / assignment helper) to recognize `[export|local|readonly] VAR=...` when the value is a single- or double-quoted string containing spaces or a parenthesized array literal without trailing commands or command substitutions (`$(...)` / backticks).
- Skip pure variable assignments in `summarize_script_actions()` so lines like `EX='--exclude-dir=bumps ... --exclude-dir=eval ...'` are recorded in `sh_vars` instead of emitting a false-positive `[exec]` operation.
- Tighten `remote-exec` (`\beval\s+`) and command-level risk matching in `src/safety.py` (`RISK_RULES` and `scan_script_risks()`) so `eval` only triggers in command position (not after `=`, `-`, or `/` such as `--exclude-dir=eval`) and single-quoted string literals without shell execution do not trigger command risk rules while still scanning for `unicode-spoof` and `secrets-exposure`.
- Add unit tests in `tests/test_run_block.py` covering multiline quoted `EX='--exclude-dir=eval ...'` assignments, `--exclude-dir=eval` arguments in `grep`, and true-positive `eval` invocations (`eval "$cmd"`, `FOO=1; eval "$cmd"`).

# ✅ [DONE] F50: Recalculate and redraw bundle statistics after e(dit) in START BUNDLE — *2026-11-17, Recalculate bundle statistics and redraw full START BUNDLE box after edit*

- Recompute `stats_line(out_path)` (line count, byte size, and estimated token range) in `offer_clipboard_copy()` (`src/ui.py`) immediately after `open_script_in_editor(out_path, tty_r, tty_w)` returns from `e(dit)` on `START BUNDLE`.
- Re-render the full `START BUNDLE` box in place on the TTY (moving the cursor back to the top of the previous box, clearing stale lines, and recalculating box border width and prompt cursor offset) instead of only redrawing the bottom prompt and border lines.
- Refresh any cached bundle metadata / `bundle_plan` statistics in `<session>/meta.json` (`src/bundle.py`, `src/bundle_plan.py`) when `<session>/0` changes during `e(dit)` so `START BUNDLE` and `--bundle-plan` stay in sync.
- Add unit tests in `tests/test_run_block.py` covering `e(dit)` in `START BUNDLE` with a stub editor that modifies `<session>/0` and asserting updated `Stats:` output and box alignment.

# ✅ [DONE] F45: Prefer Workdir from the piped bundle header over the current directory — *2026-11-17, Prefer existing Workdir from stdin preamble when RUN_BLOCK_CWD is auto; synced docs, help, rules, and tests.*

- First add a test in `tests/test_run_block.py` showing whether
  `format_start_bundle` in `src/bundle.py` currently ignores a `Workdir`
  header from `stdin_headers`; it takes the directory from `get_work_dir()`.
- If ignored, use the `Workdir` value from the stdin preamble (when the
  directory exists) as `wdir` and write it into `<session>/0`, before the
  `RUN_BLOCK_CWD` auto resolution in `src/config.py`.
- Keep `src/header.py`, `README.md`, and the bundled rules in
  `src/rules/blocks/` in sync.

# ✅ [DONE] F44: Connect python-stdlib and python-annotations rules in .agents_bundle — *2026-11-16, Connected stack/python-stdlib and stack/python-annotations rules in .agents_bundle*

- In `.agents_bundle`, remove `py_min=3.9` from `stack/python-cli` and add
  `rule vitalio/agents-rules:stack/python-stdlib` and
  `rule vitalio/agents-rules:stack/python-annotations py_min=3.9`, after the
  python-cli split is released in agents-rules and the package cache is
  refreshed.
- Keep `from __future__ import annotations` only in `build.py` and
  `src/header.py`; do not add it to modules under `src/`.
- Run `python3 -m unittest discover -s tests`; if the progress line shows
  stderr noise, capture it with `contextlib.redirect_stderr` in `tests/`.

# ✅ [DONE] B7: Capture child stderr separately to extract accurate Error lines in END box — *2026-11-16*

- In `src/runner.py`, block execution currently merges child `stdout` and `stderr` into a single descriptor (`stdout=slave_fd, stderr=slave_fd` in PTY mode and `stdout=PIPE, stderr=STDOUT` in pipe mode), so `src/ui.py` (`_extract_last_error_line`) only sees the combined `step_dir / "out"` file and picks its last non-empty line when `rc != 0`.
- When a command writes an error to `stderr` mid-run and then continues printing normal output to `stdout` before exiting non-zero (for example `head -n 25 dev/*` printing `head: error reading 'dev/__pycache__': Is a directory` to `stderr` followed by file contents on `stdout`), `END` displays the last line of `stdout` in `Error:` instead of the diagnostic from `stderr`.
- Read child `stderr` via a separate descriptor alongside `stdout` in `src/runner.py`, continuing to stream both to the terminal and into `step_dir / "out"` while also saving `stderr` to `step_dir / "err"`, and update `_extract_last_error_line` in `src/ui.py` to prefer the last non-empty line from `step_dir / "err"` (falling back to `step_dir / "out"` only when `stderr` is empty), with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] B6: Track multiline quoted strings in BLOCK PLAN analyzer and step instrumentation — *2026-11-16, Track multiline single, ANSI-C, and double-quoted strings in _iter_logical_lines and instrument_script_for_progress*

- When a shell script contains a multiline single-quoted (`'...'`) or double-quoted (`"..."`) argument (such as `todo_md edit ... -b $'...\n...'` or `todo_md add ... -b "..."`), `src/safety.py` (`summarize_script_actions` and `_instrument_bash_script`) splits on physical newlines without tracking open quote state.
- As a result, `BLOCK PLAN` reports each physical line inside the quoted literal as a separate `[exec]` operation, and live step instrumentation injects `printf '%s\n' '__RB_STEP__:N'` directly inside the user's string literal, corrupting written text.
- Track multiline single- and double-quote state (respecting backslash escapes inside double quotes) alongside heredoc tracking in `src/safety.py`, and add regression tests in `tests/test_run_block.py`.

# ✅ [DONE] F40: Assign distinct non-overlapping ANSI tag colors to all BLOCK PLAN operation types — *2026-11-16*

- Update `_TAG_COLORS`, `_colorize_operation_lines()`, and `_colorize_python_op_rest()` in `src/ui.py` so every operation tag in `BLOCK PLAN` uses a distinct ANSI color with zero overlap: `[read]` and `reads:` in bright blue (`\x1b[1;94m`), `[write]` and `writes:` in bold yellow (`\x1b[1;33m`), `[exec]` in bold magenta (`\x1b[1;35m`), `[git]` in bold cyan (`\x1b[1;36m`), and `[python]` in bold green (`\x1b[1;32m`).
- Color only the `[read]` tag and `reads:` keyword while keeping read file paths in neutral terminal foreground text, matching `[exec]`, `[git]`, and `[python]`.
- Update unit tests in `tests/test_run_block.py` and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F41: Highlight Exit and Error values and dim Fix, Output, and Stats in status boxes — *2026-11-16, Highlight non-zero Exit in bold red, Error in red, and dim Fix/Output/Stats in status boxes*

- Update `_colorize_kv_line()` in `src/ui.py` so non-zero `Exit:` codes render in bold red (`\x1b[1;31m`) and `Error:` descriptions render in red (`\x1b[31m`) across `END`, `SYNTAX ERROR`, and `NOT RUN` boxes.
- Render secondary metadata lines (`Fix:`, `Output:`, and `Stats:`) in dim gray (`_KEY_COLOR`, `\x1b[2m`) so failure diagnostics stand out clearly.
- Add unit tests in `tests/test_run_block.py` and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F39: Omit redundant Esc label in yes/no confirmation prompt suffixes — *2026-11-16*

- Remove `/Esc` from `_safety_prompt_suffix()` (`[Y/n/v(iew)]:` / `[y/n/v(iew)]:`) and `_build_prompt_yes_no_suffix()` (`[y/N]:`, `[y/N/s(cript)]:`, etc.) in `src/ui.py` where `n` already represents declining/canceling.
- Keep `/Esc` in `_clipboard_prompt_line()` (`[Enter/e(dit)/Esc]:` and `[Enter/v(iew)/Esc]:`) where no `n` option is shown, and preserve `Esc` (`\x1b`) key handling across all interactive TUI prompts.
- Update `README.md`, `tests/test_run_block.py`, and rebuild the standalone `run_block` executable via `build.py`.

# ✅ [DONE] F30: Display plan step numbers in BLOCK PLAN and live progress markers during execution — *2026-11-16, Numbered BLOCK PLAN operations and added live progress markers during interactive execution*

- Depends on: F29
- Number top-level operations in `format_safety_box()` (`src/ui.py`) so `BLOCK PLAN` items match live execution step numbers.
- Execute a temporary instrumented script copy in `run_script()` (`src/runner.py`) during interactive runs (with syntax validation, automatic fallback to the original script, temp-file cleanup, and opt-out via `RUN_BLOCK_PROGRESS=0` in `src/config.py`), while filtering marker lines out of `<session>/<step>/out` so saved output stays consistent with the unmodified script.
- Document `RUN_BLOCK_PROGRESS` in `src/header.py` and `README.md`, and add end-to-end execution tests in `tests/test_run_block.py`.

# ✅ [DONE] F31: Render read operations in neutral foreground instead of dim gray in BLOCK PLAN — *2026-11-16*

- Update `_colorize_operation_lines()` and `_colorize_python_op_rest()` in `src/ui.py` so `[read]` operation tags, continuation lines, and `reads:` clauses render in neutral foreground color (normal white/default terminal text) instead of dim gray (`_KEY_COLOR`).
- Add or update unit tests in `tests/test_run_block.py` verifying `[read]` ANSI styling in `BLOCK PLAN` output.

# ✅ [DONE] F32: Unify Esc cancel prompts across interactive TUI boxes — *2026-11-16, Unify Esc cancel prompts across interactive TUI boxes, README, and unit tests*

- Update interactive prompt suffixes in `src/ui.py` (`_build_prompt_yes_no_suffix()`, `format_safety_box()`, `confirm_execution()`) so all TUI confirmation boxes (`STEP ALREADY EXISTS`, `SESSION ALREADY EXISTS`, `MISSING PREVIOUS STEP`, `CLEAN SESSIONS`, `BLOCK PLAN`, `END`) consistently advertise `Esc` for canceling/exiting alongside existing key bindings.
- Update `README.md` and unit tests in `tests/test_run_block.py` to cover the unified prompt labels and `Esc` handling across TUI boxes.

# ✅ [DONE] F29: Track operation start lines and build instrumented script copies for plan progress — *2026-11-16*

- Record the 1-based starting line number (`line`) for each top-level operation in `summarize_script_actions()` inside `src/safety.py`, keeping nested Python AST sub-entries grouped under their parent Python step without separate top-level step numbers.
- Add a helper in `src/safety.py` to generate an instrumented in-memory script copy (`bash` and `pwsh`) that emits identifiable step-marker lines before each top-level operation while safely skipping heredocs, multiline `python -c` blocks, line continuations, and compound control-flow bodies (`if`/`for`/`while`/`case`).
- Cover line-number mapping and instrumented script generation (including syntax preservation and edge cases) with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F33: Replace v(iew) with e(dit) in START BUNDLE to edit session bundle in default editor — *2026-11-16*

- Update `format_clipboard_box()` and `offer_clipboard_copy()` in `src/ui.py` so `START BUNDLE` renders `-> Copy to clipboard? [Enter/e(dit)/Esc]:` while `END`, `NOT RUN`, and `SYNTAX ERROR` keep `[Enter/v(iew)/Esc]:`.
- Update `read_clipboard_key()` and `offer_clipboard_copy()` in `src/ui.py` to handle `e`/`E` for `START BUNDLE`, opening `<session>/0` via `open_script_in_editor()` (`RUN_BLOCK_EDITOR`, `VISUAL`, `EDITOR`, or default editor) and returning to the `START BUNDLE` prompt after the editor exits so `Enter` copies the updated `<session>/0` to the clipboard and `Esc` skips copying.
- Update `README.md` if clipboard prompt shortcuts are documented, and add unit tests in `tests/test_run_block.py` covering the `START BUNDLE` `e(dit)` prompt, key handling, and editor return flow.

# ✅ [DONE] F28: Parse stdin header preamble into session metadata and exclude from session 0 bundle — *2026-11-16*

- Parse optional leading `Key: Value` header lines (separated from body by a blank line) from `stdin` during `format_start_bundle()` and `cmd_start()` in `src/bundle.py` and `src/config.py`.
- Persist parsed `stdin` headers in session metadata (`<session>/meta.json`) instead of writing them into `<session>/0`, keeping `<session>/0` limited to `run_block`'s own headers (`Session`, `Next-Block`, `Workdir`, `Sandbox`, `Date`) and the prompt body.
- Read session display headers in `src/ui.py` (`format_session_header_lines`) and `src/runner.py` from session metadata (with fallback to `<session>/0` for existing sessions) and remove `agents_bundle`-specific keys (`bundle-command`, `chat-lang`) from `HIDDEN_SESSION_HEADER_KEYS`.
- Document the `stdin` header/body separation contract in `README.md` (user-facing) and `AGENTS.md` (architectural invariant), and cover with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F27: Improve BLOCK PLAN and TUI block visual hierarchy and colors — *2026-11-16, Removed brackets around block titles, matched dim border colors to titles, and added BLOCK PLAN color hierarchy for Workdir, Sandbox, Operations, and Safety warnings.*

- Update `src/ui.py` to remove `[...]` brackets around block titles in `_format_top_rule` (e.g. `╭─ BLOCK PLAN ───`).
- Match block border color (`╭─`, `│`, `╰─`) to the block title color in dim ANSI style, keeping plain output unchanged when `NO_COLOR` or non-TTY.
- Highlight `Safety warnings (N):`, risk category tags, and the `-> Execute this block?` prompt when safety warnings are present.
- Color-code `Operations:` in `BLOCK PLAN`: dim read-only / `reads:` parts, and highlight `writes:` targets and mutating / `[git]` tags.
- Dim `Workdir` in `BLOCK PLAN` when it matches `os.getcwd()` and highlight it when it differs; dim routine header fields such as `Sandbox: off`.
- Update and add unit tests in `tests/test_run_block.py` for the updated title format, border colors, warning/operation highlighting, and `Workdir` emphasis.

# ✅ [DONE] F23: Format session bundle Date header in UTC (YYYY-MM-DD HH:MM UTC) — *2026-11-16*

- Format the `Date:` header in `src/bundle.py` using UTC (`datetime.now(timezone.utc)` or `now.astimezone(timezone.utc)`) formatted as `YYYY-MM-DD HH:MM UTC` to match bundle rules.
- Update `tests/test_run_block.py` to verify the `YYYY-MM-DD HH:MM UTC` format in both `<session>/0` bundle headers and session initialization summary output.

# ✅ [DONE] F26: Refine TUI block borders, key-value alignment, and TTY status colors — *2026-11-16*

- Update `src/ui.py` (`_format_top_rule`, `_format_bottom_rule`, `_prefix_block_line`, `_render_block`, and key-value formatting in `format_session_header_lines` and `build_box_body_lines`) to replace `#` borders with thin open-right box-drawing borders (`╭─ [TITLE] ───`, `│ `, `╰───`) of compact width, with an ASCII fallback (`+-`, `| `) when `stdout` is not UTF-8.
- Align contiguous `Key: value` metadata lines in columns (`Session:`, `Next-Block:`, `Workdir:`, `Sandbox:`, `Role:`, `Task:`, `Bundle:`, `Output:`, `Stats:`, etc.) for cleaner scanning.
- Add TTY-aware ANSI colors (disabled when not a TTY or `NO_COLOR` is set): dimmed/tinted borders, bold status-colored `[TITLE]` (`START BUNDLE`, `BLOCK PLAN`, `END`, `SYNTAX ERROR`, `NOT RUN`), and dimmed keys.
- Update `tests/test_run_block.py` to verify the new border style, ASCII fallback, key-value alignment, and `NO_COLOR`/non-TTY behavior.

# ✅ [DONE] F24: Remove blank lines between directory groups in BLOCK PLAN Operations — *2026-11-16*

- Remove blank separator lines between directory groups inside `Operations:` in `src/ui.py` so grouped directory entries render compactly without vertical gaps.
- Update `BLOCK PLAN` formatting assertions in `tests/test_run_block.py` to verify compact directory group rendering.

# ✅ [DONE] F25: Add # prefix and compact # borders around TUI blocks — *2026-11-16, Rendered all TUI blocks with compact # borders and # line prefixes*

- Render all TUI section blocks (`BLOCK PLAN`, `START BUNDLE`, `END`, `NOT RUN`, `SYNTAX ERROR`, and prompt boxes) in `src/ui.py` using a shared helper with compact `#` top and bottom borders (e.g. `min(term_cols, 48)`, padded to fit the title).
- Format the top border with the embedded `[TITLE]` (e.g. `#### [TITLE] ####...`) and close every block with a matching `#` rule of the same width.
- Prefix every content and prompt line with `# ` (and render blank separator lines as `#` without trailing whitespace), accounting for the 2-character prefix when wrapping text.
- Keep interactive prompt lines (`-> ...?`) inside the block immediately above the bottom `#` border, adjusting `cursor_col_offset` and cursor positioning/redraws accordingly.
- Update TUI box assertions in `tests/test_run_block.py` and keep `AGENTS.md` / `README.md` descriptions in sync if needed.

# ✅ [DONE] F22: Replace box-drawing horizontal rules with plain [TITLE] section headers — *2026-11-15, Replaced box-drawing horizontal rules with plain [TITLE] section headers and simplified in-place prompt redraws.*

- Replace box-drawing horizontal rules (`── <TITLE> ───...` and bottom `───...`) in `src/ui.py` with plain bracketed section headers (`[<TITLE>]`) and no trailing bottom rule so TUI sections never wrap or misalign when the terminal is resized.
- Simplify interactive prompt redraws in `prompt_yes_no_box`, `confirm_execution`, and `offer_clipboard_copy` in `src/ui.py` to update the prompt line in place without redrawing a bottom separator line.
- Update `AGENTS.md` and TUI formatting assertions in `tests/test_run_block.py` to match the plain `[<TITLE>]` section format.

# ✅ [DONE] F17: Limit --fix to small targeted patches rather than full-block replacements — *2026-11-15*

- Update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` (plus `README.md` if applicable) to specify that `run_block --fix` should only be used for small, targeted patches; if a fix is comparable in size to the original block or requires rewriting multiple sections, emit a fresh `<session>/<step+1>` block directly instead.
- Bump `VERSION` (patch), rebuild `run_block` via `python3 build.py`, and update/verify tests in `tests/test_run_block.py`.

# ✅ [DONE] B3: Keep subproject working directory when initializing session from subdir — *2026-11-15, Keep subproject working directory when initializing session from subdir*

- In `src/config.py`, `get_work_dir()` currently falls back to `_git_toplevel_or_cwd()`, which climbs to `git rev-parse --show-toplevel` even when a session starts inside a self-contained subproject directory (e.g. `/home/vitaly/chrome/canary`) containing its own `.agents_bundle` or `AGENTS.md`.
- This creates a mismatch between `0` bundle outputs (collected in `pwd`) and subsequent `run_block` steps (executed in the monorepo root).
- Acceptance criteria:
  - In `src/config.py`, when `RUN_BLOCK_CWD=auto` and no session `Workdir` header exists yet, prefer the nearest directory (starting from `Path.cwd().resolve()` up to the Git toplevel) containing `.agents_bundle` or `AGENTS.md`, falling back to `git rev-parse --show-toplevel` and then `Path.cwd().resolve()`.
  - Keep `RUN_BLOCK_CWD=cwd`, explicit `RUN_BLOCK_CWD=/path`, and persisted `Workdir:` in `<session>/0` working unchanged.
  - Update `RUN_BLOCK_CWD` documentation in `README.md` and add unit tests in `tests/test_run_block.py` covering subproject session init, regular Git subdir init, and `RUN_BLOCK_CWD` overrides.

# ✅ [DONE] F11: Per-step directory layout and extensionless session/output artifacts — *2026-11-15, Implemented per-step directory layout (<session>/<step>/{block.sh|block.ps1,fix.py,out,error,aborted}) and extensionless <session>/0 bundle.*

- Store session context bundle at `<session>/0` (replacing `<session>/0.txt`) in `src/bundle.py`, `src/runner.py`, `src/config.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, and `README.md`.
- Store each executed step in its own directory `<session>/<step>/` (e.g. `s1/1/`, `s1/1_1/`) with `block.sh` or `block.ps1`, `out` (stdout/stderr), `error` (failed output), `aborted` (abort marker), and `fix.py` (for `--fix` steps, alongside the patched `block.sh`/`block.ps1`) in `src/runner.py` and `src/ui.py`.
- Remove legacy flat-file session support (`<step>.sh`, `<step>.txt`, `0.txt`) and update unit tests in `tests/test_run_block.py`, then rebuild `run_block` via `build.py`.

# ✅ [DONE] F21: Replace bordered TUI boxes with full-width horizontal rule separators — *2026-11-15, Replaced full-perimeter TUI box borders with full-width horizontal rule separators in v0.19.2*

Replace full-perimeter box-drawing borders (`┌─ ... ─┐`, `│ ... │`, `└─ ... ─┘`) in `src/ui.py` with terminal-width horizontal rule separators (`── <TITLE> ───...` and `───...`) so long lines (paths, errors, `--fix` reasons) wrap naturally without breaking box alignment.

- Update `format_safety_box`, `format_info_box`, `format_prompt_box`, `format_clipboard_box`, `prompt_yes_no_box`, `confirm_execution`, and `offer_clipboard_copy` in `src/ui.py` to render top/bottom horizontal rules sized to terminal width (`shutil.get_terminal_size`) without side `│` borders or right-padding.
- Use `\r\033[K` when rewriting interactive prompt lines and final status lines (`✓ Running ...`, `✓ Copied ...`, `✗ Aborted ...`) so shorter status text clears previous prompt text cleanly.
- Update `resolve_clipboard_target` in `src/ui.py`, unit tests in `tests/test_run_block.py`, and TUI documentation in `AGENTS.md` and `README.md`.

# ✅ [DONE] B5: Resolve Python <stdin> traceback lines on failure and enrich END/NOT RUN TUI cards — *2026-11-15, Resolve Python <stdin> traceback lines on failure and enrich END/NOT RUN TUI cards*

- When a block exits with non-zero status and its output contains `File "<stdin>", line <N>` from an embedded `python3` heredoc in `src/runner.py`, extract line `<N>` from the heredoc body and append `[<label>] <stdin> line <N>: <source_line>` to the output before `[<label>] END (exit <rc>)` so the failing statement is visible in clipboard output.
- In `END` TUI boxes when `rc != 0` (`src/runner.py`, `src/ui.py`), display `Error: <last_error_line>` from the script output and a `Fix:` status line showing either `run_block --fix <label> (<used>/<max> failed attempts)` or the `STOP --fix` guard state.
- In `NOT RUN` TUI boxes (`not_run_exit` and `cmd_fix` in `src/runner.py`), show `Target: <session>/<target> -> <label>` for `--fix` steps and render any `[<label>] STOP --fix: ...` continuation line as a clean `Guard: ...` line without a duplicate `[<label>]` prefix inside the box (while keeping the full lines in the `.txt` clipboard file).
- Cover `<stdin>` traceback line resolution and the updated `END` / `NOT RUN` box fields with unit tests in `tests/test_run_block.py`.

# ✅ [DONE] F19: Store sessions in persistent state directory (~/.local/state/run_block) and add size/prune controls — *2026-11-15, Store sessions in XDG/LocalAppData state directory and add size/prune controls*

- Change default session storage in `src/config.py` from `/tmp/run_block` to `$XDG_STATE_HOME/run_block` (fallback `~/.local/state/run_block` on Linux/macOS) and `%LOCALAPPDATA%\\run_block\\state` (fallback `~/AppData/Local/run_block/state`) on Windows while keeping `RUN_BLOCK_DIR` as highest-priority override.
- Ensure sandbox rules in `src/safety.py` and `src/bundle.py` treat the persistent `BASE_DIR` appropriately without conflating it with `/tmp`.
- Display per-session and total storage sizes in `src/runner.py` (`--list` / `--clean`), extend `--clean` to support `--older-than <days>`, `--max-size <MB>`, and deleting specific session names, and emit a warning when total state size exceeds `RUN_BLOCK_MAX_STATE_MB` (default `100`).
- Update usage text, agent block rules, README, and unit tests in `src/header.py`, `src/rules/blocks/bash.md`, `src/rules/blocks/pwsh.md`, `README.md`, and `tests/test_run_block.py`.

# ✅ [DONE] B2: Fix BLOCK PLAN analyzer for backslash continuations, external paths, quoted echo, and multi-dir Python AST — *2026-11-15, Handled shell line continuations, quoted redirects in echo/printf, external paths and *_CWD prefixes, and multi-directory Python AST loop/deletion grouping*

- Join shell line continuations (trailing `\`) outside heredoc and Python blocks before classifying commands and scanning risks.
- Ignore `>` inside single or double quotes when filtering non-redirected `echo`/`printf` statements.
- Recognize absolute external paths under `$HOME` (e.g. `/home/<user>/<repo>/...`) and `*_CWD=/path` environment prefixes in `_infer_op_dir` so commands operating on sibling repositories are grouped under their target directory.
- In `_analyze_python_ast` and `_emit_py_op`, track loop target variables (`for x in (...):`), surface `Path.unlink()` / `Path.rmdir()` deletions (including `fs-destructive` risk warnings), and group or summarize Python file operations across all target directories without silently dropping paths past 12 items.

# ✅ [DONE] F18: Reassemble split run_block payloads caused by inner triple backticks on paste/stdin — *2026-11-15, Implemented _reassemble_split_payload in src/runner.py and added unit tests*

- When a model emits literal triple backticks inside a `run_block` heredoc (for example when editing `README.md` code fences), chat Markdown renderers split the single block into multiple fenced snippets separated by ```text` or ```python` fences, leaving the outer heredoc unclosed until the final `RUN_BLOCK` terminator.
- Detect an unclosed `run_block ... <<'RUN_BLOCK'` (or `RUN_FIX`) header in pasted/piped input before the closing terminator and reconstruct the original payload by stripping intermediate Markdown fence lines that split the block, or emit a clear diagnostic if the terminator is missing.

# ✅ [DONE] B4: Add --fix diagnostics, non-overwriting fix slots, and max-attempts loop guard — *2026-11-15, Implemented rich --fix exception diagnostics, non-overwriting fix slot allocation with chain fallback, RUN_BLOCK_MAX_FIX_ATTEMPTS loop guard, and updated bash/pwsh block rules.*

- In `cmd_fix` (`src/runner.py`), format rich failure diagnostics when `RUN_FIX` raises an exception: include the failing line number and statement from `fix_code`, and for `AssertionError` on `assert <compare>` evaluate and print the actual left/right values (e.g. `at line 14: assert text.count(old_3) == 2 (actual: 0 == 2)`).
- Never overwrite prior `NOT RUN` fix outputs or fail with `fix step already exists`: allocate the next free fix slot (`<step>_1`, `<step>_2`, ...) on every `--fix` call, fall back to the latest existing script in the chain if a targeted fix step had no script (`NOT RUN`), and automatically try the latest fix revision vs base script when an anchor assertion fails.
- Enforce a hard loop guard (`RUN_BLOCK_MAX_FIX_ATTEMPTS`, default `2`) on consecutive failed `--fix` attempts per base step: append a `STOP --fix` directive when the limit is reached and reject further `--fix` calls on that step with an instruction to emit `<session>/<step+1>` instead.
- Update `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` to document fix chaining and the rule to switch to a fresh `<session>/<step+1>` block after at most 2 failed `--fix` attempts.

# ✅ [DONE] F1: Native PowerShell (`pwsh`) block execution mode on Windows — *15f24a8*

Allow `shell = pwsh` in `~/.config/run_block/config` so Windows users in PowerShell 7
can execute native PowerShell blocks in addition to Bash blocks.

# ✅ [DONE] F2: Custom user-defined safety rules in config — *15f24a8*

Allow adding custom regex patterns or overriding risk categories in
`~/.config/run_block/config`.

# ✅ [DONE] F3: Session cleanup command (`--clean`) — *15f24a8*

Add `run_block --clean [--keep N | --all]` to prune old session directories in
`/tmp/run_block`.

# ✅ [DONE] F4: Smart budget-aware repository map (--tree) — *15f24a8*

Add `run_block --tree` (usable in `.run_block.start` as `$ run_block --tree`) to generate a compact, token-budgeted repository file tree (respecting `.gitignore`, showing line counts for source files, and collapsing large directories into summaries instead of dumping thousands of paths).

# ✅ [DONE] F5: Modular agent rules knowledge base (--rules) — *f618c65*

Add 'run_block --rules [topic ... | all | --list]' with built-in topics (workflow, semver, python-cli) and user rules in ~/.config/run_block/rules/*.md.

# ✅ [DONE] F6: Modularize run_block source into src/ with build.py single-file bundler — *83863e7*

Split monolithic run_block into src/ Python modules and src/templates/*.md + src/rules/*.md files, compiled into standalone ./run_block by build.py.

# ✅ [DONE] F8: Extract context bundler and engineering rules catalog into standalone agents_bundle project — *99bc5e1*

Move --start, .agents_bundle spec, --tree, and universal engineering rules/presets into a separate zero-dependency 'agents_bundle' CLI with zero hardcoded coupling to run_block (connected via user config and 'run_block --bundle').

# ✅ [DONE] F7: Plugin architecture (pre/post hooks, LLM block analyzer, and headless stdout mode) — *412de9c*

Add extensible plugin hooks for pre-execution block analysis (including LLM-based script review and auto-approval of safe blocks) and post-execution output handling (clipboard box vs raw stdout protocol mode).

- Unify command classification ('[git]', '[write]', '[read]', '[exec]', '[python]') and safety risk scanning ('[git-push]', '[net-write]', '[git-destructive]', etc.) into the pre-execution analyzer plugin interface.

# ✅ [DONE] F9: Audit run_block and todo_md architecture against unix-philosophy.md — *412de9c*

Review CLI flags, stdin/stdout/stderr separation, and composability of run_block and todo_md against core/unix-philosophy.md.

# ✅ [DONE] F12: Standardize minimalist TUI box titles and Key: Value body fields; suppress duplicate boxes on interactive decline — *2026-11-14, Release v0.16.3*

# ✅ [DONE] F10: Prompt injection defenses, safe --fix AST validator, and session Sandbox contract — *2026-11-14*

- Validate `--fix` Python patch AST before `exec()` (allow only pure text/regex manipulation; reject imports, dunder access, and unsafe builtins).
- Protect `<session>/0.txt` integrity across block execution (in-memory snapshot + revert on tampering; read-only `BASE_DIR` inside OS sandboxes).
- Support `Sandbox:` header in `<session>/0.txt`, `RUN_BLOCK_SANDBOX` env setting, and `--sandbox` CLI command/flag (`off`, `strict`, `nonet`) with cross-platform secret env scrubbing, Linux `bwrap`, and macOS `sandbox-exec`.
- Enhance `src/safety.py` scanner (Python AST `subprocess`/`urllib`/`socket`/`eval`, paths outside `Workdir`, `.git/hooks`, and hidden Bidi/Zero-Width Unicode spoofing) and set `default_yes=False` when `RUN_BLOCK_APPROVE_CMD` exits `2`.

# ✅ [DONE] B1: Parse multiline python3 -c in BLOCK PLAN and prevent RUN_BLOCK closing-fence concatenation — *2026-11-14, fd3d533*

- In src/safety.py (summarize_script_actions and scan_script_risks), detect single-line and multiline python3 -c '...' / "..." invocations, analyze their body via _analyze_python_ast, and report them as a [python] operation instead of per-line [exec] items.
- Investigate and harden src/rules/blocks/bash.md and runner handling against LLM omitting the newline between RUN_BLOCK and the closing Markdown fence (which causes CommonMark to leave the code fence open).

# ✅ [DONE] F13: Add src/bundles/run_block.bundle and remove --agents CLI flag — *2026-11-14*

- Add `src/bundles/run_block.bundle` selecting `vitalio/run_block:blocks/bash` or `vitalio/run_block:blocks/pwsh` by OS.
- Remove hardcoded `v{version:}` placeholder from `src/rules/blocks/bash.md` and `src/rules/blocks/pwsh.md` headers.
- Remove `src/agents.py` and the `--agents` / `--agents-md` CLI flag from `src/header.py`, `src/cli.py`, `build.py`, `README.md`, `AGENTS.md`, `.agents_bundle`, and `tests/test_run_block.py`.

# ✅ [DONE] F14: Unify TUI box titles and render session headers (Block/Session, Workdir, Sandbox, Role, Task) inside every box — *2026-11-15, Unify TUI box titles and render session headers in every box*

- Strip the '<session>/<step> · ' prefix from TUI box top borders so box titles show only the block kind ('START BUNDLE', 'BLOCK PLAN', 'END', 'NOT RUN', 'SYNTAX ERROR', 'STEP ALREADY EXISTS', 'MISSING PREVIOUS STEP', 'SESSION ALREADY EXISTS').
- Parse both run_block and stdin bundle header blocks in '0.txt' (up to the first '=====' section) so session variables ('Role', 'Task', and custom headers) are available across all steps.
- Render a consistent session header section at the top of every session/step box ('Session'/'Next-Block' or 'Block: <session>/<step>', 'Workdir', 'Sandbox', plus session variables like 'Role' and 'Task' excluding noisy 'Date'/'Bundle-Command'/'Chat-Lang'), followed by a blank line and the box-specific details ('Bundle', 'Script', 'Operations', 'Output', 'Stats', etc.).
