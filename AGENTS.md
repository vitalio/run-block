# `run_block` — Project-Specific Agent Rules

Universal workflow, language, Git, SemVer, Python CLI, and single-file build
rules are loaded via `.ctx.bundle`.

## Architecture & Module Boundaries

- `src/header.py` — `--help` row tables (`HELP_*`), standard library imports,
  version constants, and the embedded block rule placeholder
  (`EMBEDDED_RULE_BASH`) populated by `build.py`.
- `src/config.py` — zero-config environment variable settings (`RUN_BLOCK_*`,
  `VISUAL`/`EDITOR`), non-interactive child pager variable tuple
  (`CHILD_PAGER_ENV_VARS` controlled by `RUN_BLOCK_PAGER`, default `cat`),
  working directory resolution, and `usage_text()`, which renders `--help` from
  the `HELP_*` tables (aligned description column per section, lines <= 100
  columns).
- `agents/blocks/bash.md` — internal embedded terminal block execution rule
  source injected by `build.py` into `src/header.py`. Update
  `agents/blocks/bash.md` in the same commit whenever CLI flags, step
  numbering, `--fix` constraints, or session rules change.
- `src/safety.py` — AST/regex operation classifier, safety risk scanner,
  `run_block --plan` JSON output, and `RUN_BLOCK_APPROVE_CMD` validator hook.
- `src/ui.py` — thin open-right box-drawing (`╭─ TITLE ───`, `│ `, `╰───`, ASCII fallback) TUI blocks with aligned metadata and TTY colors
  (`START STEP`, `START SESSION`, `END STEP`, `NOT RUN`, `SYNTAX ERROR`), token
  statistics, and clipboard integration.
- `src/runner.py` — sequential session/step execution (`<session>/<step>`),
  `--fix` patching, `--retry`, `--list`, `--show`, `--clean`, and `-y`/`--yes`
  headless mode. Child `stdout` and `stderr` share one descriptor (the PTY
  slave or the capture pipe write end), so `out` keeps exact write order and
  the `END STEP` box takes its `Error:` line from the last meaningful line of
  `out`; there is no separate `err` artifact. Exports non-interactive
  pager defaults (`CHILD_PAGER_ENV_VARS` set to `get_setting("pager")[0]`,
  default `cat`, unless disabled via `RUN_BLOCK_PAGER=inherit|off|0|false`) in
  the child execution environment while keeping PTY `stdin` connected for
  intentional interactive prompts. Exports `RUN_BLOCK_STEP_STDOUT_INO`
  (`<st_dev>:<st_ino>` of the step capture stdout descriptor: the PTY slave or
  the capture pipe write end) in the child environment so upstream producers
  can tell direct step console output from a shell pipeline inside a step.
- `src/bundle_parse.py` — Bundle Input Protocol header constants and filtering,
  embedded terminal block rule and prompt injection, section metadata
  inference, fragment deduplication/overlap detection, and
  `analyze_bundle_warnings()` diagnostics (pure parsing and analysis, no
  session I/O or rendering).
- `src/bundle_plan.py` — `bundle_plan` data model and provenance chain helpers,
  line range assignment and `--part N` extraction, plan construction and header
  reconciliation (`parse_bundle_fragments()`, `reconcile_bundle_plan()`), and
  `<session>/meta.json` persistence (`refresh_bundle_plan_meta()`,
  `load_session_bundle_plan()`).
- `src/bundle_view.py` — provenance tree construction, heavy-row classification,
  hierarchical table rendering, summary/parts/warning item formatters, and
  `--bundle-plan` text/CLI output (`cmd_bundle_plan()`).
- `src/bundle.py` — session initialization from TTY `stdin` (rule-only) or
  piped `stdin` (`run_block` / `<command> | run_block` -> `<session>/0` and
  `<session>/meta.json`), injecting embedded `bash` terminal block rules via
  `format_start_bundle()`. Parses
  optional leading `Key: Value` header lines (separated from the body by a
  blank line) into `<session>/meta.json`, keeping `<session>/0` limited to
  `run_block`'s own headers (`Session`, `Next-Block`, `Workdir`, `Sandbox`,
  `Date`) and the prompt body.
- Session completion state (`--done`) and nested `IN_RUN_BLOCK=1` contract:
  persist `"completed": true` and `"completed_at"` (UTC ISO timestamp),
  optional `"completed_note"`, accumulated `"stats"` (updated by `run_script`
  via `update_session_stats`), and parent/child session linkage
  (`"parent_session"`, `"parent_step"`, `"spawned_sessions"`) in
  `<session>/meta.json` without altering `<session>/0` headers. `run_script`
  exports `IN_RUN_BLOCK=1`, `RUN_BLOCK_PARENT_SESSION`, and
  `RUN_BLOCK_PARENT_STEP`; inside a running step, nested step execution
  (`<session>/<step>`, `--fix`, `--retry`) and sandbox mutations exit `2`,
  while `--done` and `--start` / piped bundle initialization log a single plain
  line to `stdout` and queue `end_session` / `start_session` events in
  `<parent_sdir>/<parent_step>/deferred.json` so `run_script` renders
  `END STEP` -> `END SESSION` -> `START SESSION` in order after updating step
  stats (suppressing the outer `END STEP` clipboard prompt when a child session
  is spawned). Before running any block (`<session>/<step>`, `--fix`, or
  `--retry`) on a completed session, warn and prompt for confirmation
  (`SESSION COMPLETED`, default `No`), clearing the completed flag only when
  confirmed (or when `-y`/`--yes` is explicitly passed).
- Session lifecycle states and step outcome labels (`src/config.py`,
  `src/runner.py`):
  - Session lifecycle state (`get_session_state(sdir)`): `done` when
    `<session>/meta.json` has `"completed": true`; `active` when not completed
    and at least one step directory (`_iter_session_steps(sdir)`) exists;
    `bundle-only` when `<session>/0` exists without step directories (or
    `empty` when neither exists).
  - Step execution outcomes (`write_step_meta`, `_step_outcome`,
    `_step_status`): persist structured `"outcome"` (`"ok"`, `"failed"`,
    `"syntax-error"`, `"not-run"`, `"aborted"`, `"saved"`), `"exit_code"`,
    `"duration_ms"`, optional `"reason"`, and `"fix_target"` in
    `<session>/<step>/meta.json` across all exit paths (falling back to
    `aborted`/`out`/`error`/`block.*` artifacts for legacy step directories).
    Keep `[<session>/<step>] END (...)` exclusively as the agent stream marker
    inside `<step>/out`, while rendering human/CLI step status labels as
    `ok (<duration>)`, `exit <rc> (<duration>)`, `syntax-error (exit <rc>)`,
    `not-run`, `aborted`, or `saved`.
  - `_iter_session_steps(sdir)` enumerates all step directories (`\d+(?:_\d+)?`)
    containing script, fix, output, error, abort, or metadata artifacts sorted
    by `_step_sort_key` (including `not-run` `--fix` attempts that failed before
    emitting `block.sh`), while `_iter_session_scripts(sdir)` returns runnable
    script paths.
  - Step artifacts in `<session>/<step>/`: `out` holds the START line, optional
    headers, child output in exact write order (`stdout` and `stderr` share one
    descriptor), diagnostics, and the END line, written once after the child
    exits; `error` holds a pre-execution failure message shown by `--show`;
    `aborted` marks a declined or rejected block and is removed when the block
    runs; `meta.json` records the structured outcome. Legacy `err` files are
    ignored.
  - `run_block -l` / `--list [session]` displays session lifecycle state,
    `last: <ref> (<step_status>)`, and `next: <session>/<next_free_step>` for
    open sessions (`active` / `bundle-only`) or `[DONE]` without `next:` for
    completed sessions.
- `src/cli.py` — CLI argument routing and self-update (`--update`,
  `--check-update`).
- `tests/helpers.py` — shared `ROOT`, `SCRIPT`, `INSTALL_SH`, cached
  `load_module()`, and `RunBlockTestCase` with in-process CLI helpers (`_run`,
  `_run_in_process`, `_run_subprocess`, `_assert_ok`) and `RUN_BLOCK_*`
  environment isolation.
- `tests/test_cli.py`, `tests/test_safety.py`, `tests/test_ui.py`,
  `tests/test_bundle.py`, `tests/test_runner.py` — modular offline unit test
  suites mirroring `src/` boundaries.

## Bundle Input Protocol

- Header contract: Treat `Bundle-*` preamble headers (`Bundle-Name`,
  `Bundle-Command`, `Bundle-Protocol`, `Bundle-Boundary`) as transport metadata
  for `<session>/meta.json` only, never forwarding them into `<session>/0`.
  Forward all non-transport, non-hidden `stdin` preamble headers into
  `<session>/0` by default (never overriding `Session`, `Next-Block`, `Workdir`,
  `Sandbox`, or `Date`).
- Fragment parsing & stripping: When `Bundle-Boundary: <nonce>` is present,
  parse `<!-- bundle:<nonce>:part {...} -->` / `<!-- bundle:<nonce>:end -->`
  markers (agnostic of generator internals via `kind`, `group`, `name`, `via`,
  `rc`, `ms`), compute per-part line/byte/token counts, strip all markers from
  `<session>/0`, and persist structured `bundle_plan` metadata in
  `<session>/meta.json`. Fall back to `===== ... =====` section splitting when
  no boundary is declared.
- Protocol version and fragment kinds: `get_bundle_protocol()` reads
  `Bundle-Protocol`; `format_start_bundle()` warns on `stderr` for versions
  outside `SUPPORTED_BUNDLE_PROTOCOLS` without rejecting the bundle.
  `normalize_fragment_kind()` normalizes `context-bundle-protocol` fragment
  kinds for the 4 canonical kinds (`rule`, `file`, `cmd`, `prompt`). Upstream prompt
  fragments carry a non-empty `chain` (and can be deduplicated by
  `_dedupe_fragments()`), whereas the user's root session prompt fragment has
  `chain: []` (`name: "Prompt"`): `inject_embedded_prompt()`,
  `append_note_to_raw_bundle()`, and `refresh_bundle_plan_after_edit()` merge
  only into a trailing root user prompt fragment (`chain: []`) and otherwise
  append a new root `Prompt` part, and `analyze_bundle_warnings()` flags any
  empty prompt fragment (`fragment_empty`).
- Part line ranges: each part entry records 1-based `line_start` / `line_end`
  into the cleaned `<session>/0` (body-relative for `stdin`; `line_offset`
  tracks the header shift applied by `reconcile_bundle_plan`, which keeps the
  shift idempotent). Never store fragment text in `meta.json`; `--part N`
  slices `<session>/0` using these ranges (`extract_bundle_part`).
- Analyzer & diagnostics: Keep parsing and size/error/secret diagnostics in
  `src/bundle_parse.py`, plan state and persistence in `src/bundle_plan.py`,
  and `--bundle-plan` rendering in `src/bundle_view.py`, reusing
  `src/safety.py` secret detection without duplicating patterns.
- Fragment dedup and overlap: `parse_bundle_fragments()` drops duplicate or
  contained boundary fragments via `_dedupe_fragments()` before ranges are
  assigned, so `<session>/0`, `bundle_plan` ranges, and `0.raw` re-parsing
  stay consistent; `fragment_deduped` warnings carry pre-header part indices
  and `reconcile_bundle_plan()` shifts both `part_index` and `overlap_with`.
  `analyze_bundle_warnings()` emits `fragment_overlap` through
  `_detect_fragment_overlaps()` using `OVERLAP_MIN_LINES` / `OVERLAP_MIN_CHARS`.
