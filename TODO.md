# 🎯 [NEXT] B16: Fix run -r session resolution override and audit full-reply block extraction edge cases

- Depends on: F84, B15
- Bump: `PATCH`
- Fix `extract_reply_block()` in `src/runner.py` so an explicit session parsed from the block header (`chosen["session"]`, e.g. `s458` from `run s458/7 <<'RUN_BLOCK'`) is preserved rather than overwritten by `default_session` (`session = str(chosen["session"]) if chosen.get("session") else default_session`), keeping `default_session` strictly as a fallback for session-less blocks (`fenced_fallback` or bare `run <<'RUN_BLOCK'`) and as a candidate-selection hint.
- Fix `cmd_run_reply()` and `_resolve_reply_session()` in `src/runner.py` to distinguish an explicit CLI session override (`run -r <session>`, where `session_arg` is provided by the user) from an auto-inferred fallback session when `session_arg is None`:
  - When `session_arg is None` and the pasted block explicitly specifies `run s458/7 <<'RUN_BLOCK'`, execute in `s458` even if a newer session (such as `s459`) exists in the same `Workdir`.
  - When a reply contains multiple candidate blocks (e.g. a generic `run s1/1 <<'RUN_BLOCK'` rule example followed by the real `run s458/7 <<'RUN_BLOCK'` block, or trailing hallucinated blocks) and `session_arg is None`, prefer the first candidate whose session matches an existing open/known session for the current `Workdir` (or existing session in `base`, skipping non-existent template `s1` examples) without overriding the chosen candidate's own session name.
  - When `session_arg is None` and the block specifies a valid non-template session name that does not exist in `base` yet (e.g. `run s500/1 <<'RUN_BLOCK'`), respect `extracted_session` instead of silently redirecting it into an older open session in the same `Workdir`.
- Audit the full `run -r` / `--run` reply extraction and reassembly pipeline (`extract_reply_block()`, `_parse_reply_cmd_tokens()`, `_find_outer_heredoc_end()`, `_is_heredoc_terminator()`, `_reassemble_split_payload()`, `_resolve_reply_session()`, and `cmd_run_reply()`) for chat copy-paste edge cases:
  - Unfenced or half-fenced blocks with a glued closing fence on the terminator line (`RUN_BLOCK``` ` or `RUN_FIX``` ` with optional trailing spaces) and surrounding `---` horizontal rules or prose lines.
  - Multi-session workspace state where `s458` and a newer `s459` both exist in `base` for the same `Workdir` and `run -r` (without arguments) is given a block targeting `s458/7`.
  - Double-pass safety when `cmd_run_reply()` passes `extracted["payload"]` into `cmd_normal()` / `cmd_fix()` (which call `_reassemble_split_payload()`), ensuring inner heredocs or nested `run ... <<'RUN_BLOCK'` documentation examples inside `payload` are never truncated or stripped on the second pass.
  - Step renumbering (`renumbered_from` and `# run: <session>/<step>` header rewrite) when `session_arg` explicitly overrides the block's session versus when `session_arg is None` and only the step number inside the target session is adjusted.
- Add regression unit tests in `tests/test_runner.py` covering unfenced `run s458/7 <<'RUN_BLOCK' ... RUN_BLOCK``` ` replies when a newer session `s459` exists, multi-candidate replies with `s1/1` prose examples across multiple open sessions, explicit `run -r <session>` override vs `run -r` auto-detection, and double-pass nested heredoc preservation.

# 🎯 [NEXT] F85: Export non-interactive pager defaults in child step execution environment

- Depends on: D3
- Bump: `MINOR`
- In `src/config.py`, define canonical `CHILD_PAGER_ENV_VARS = ("PAGER", "GIT_PAGER", "GH_PAGER", "MANPAGER", "SYSTEMD_PAGER", "BAT_PAGER", "AWS_PAGER", "PSQL_PAGER", "DELTA_PAGER")` and add `get_setting("pager")` reading `RUN_BLOCK_PAGER` (default `"cat"`; values `"0"`, `"false"`, `"no"`, `"off"`, `"inherit"`, `"keep"`, `"passthrough"` return `""` to preserve the parent environment's pager variables unchanged).
- In `src/runner.py` (`run_script()`), populate `CHILD_PAGER_ENV_VARS` with `get_setting("pager")[0]` in `child_env` (when non-empty, overriding parent `os.environ` pager variables before `scrub_child_env()`) so TTY-aware commands (`git diff`, `git log`, `gh api`, `man`, `systemctl`, `bat`, etc.) never stall inside `run`'s PTY while keeping `/dev/tty` `stdin` attached for intentional human-in-the-loop prompts.
- Document `RUN_BLOCK_PAGER=cat|inherit` in `src/header.py` (`--help` `Environment:` section aligned to column width invariants) and the `Environment Variables` table in `README.md`.
- Add unit tests in `tests/test_runner.py` and `tests/test_cli.py` covering default `CHILD_PAGER_ENV_VARS` injection (`cat`), custom `RUN_BLOCK_PAGER` override, `RUN_BLOCK_PAGER=inherit` / `off` passthrough, and `--help` alignment.

# 🎯 [NEXT] D10: Design built-in API agent mode in run-block (single run tool, reasoning in BLOCK PLAN, prompt caching, and key isolation)

- Depends on: F86, F89, F82, F74, F95
- Design candidate for `role=design` adding a built-in LLM API agent transport mode directly inside `run` (preserving `c(opy)` clipboard workflow and `run -r` full-reply paste mode as fallbacks, and remaining directly runnable via `todo <ID> | context | run`):
  1. Model profiles and secret isolation: configure provider profiles (Anthropic Messages, OpenAI-compatible, local models) and load API keys (env / macOS Keychain / config) in memory while stripping secret env vars from child `run` executions (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  2. Single polymorphic `run` tool & resilient reply recovery:
     - Register a single `run` tool with `disable_parallel_tool_use: true` / `parallel_tool_calls: false` accepting structured `edits: [{path, old, new}]` (atomic in-memory anchor + syntax validation before disk write, strict `Workdir` path boundary enforcement, pre-execution diff preview in `START STEP` / `i(nfo)`, and `difflib` anchor repair from `F74`), `script` (batch `bash` commands without heredoc/fence wrappers or manual step numbers), optional `fix_target`, and optional `done` / `done_note`.
     - Reuse the reply extraction and repair pipeline from `F84` (`extract_reply_block()` in `src/runner.py`) to automatically strip accidental Markdown/heredoc wrappers inside `script`, deduplicate or queue unexpected multi-block responses, auto-resolve `<session>/<next_step>`, convert misplaced bash scripts in `fix_target` into sequential steps, and fall back to extracting blocks from plain text replies when a model responds without a tool call; support interactive terminal replies when the model asks a question without emitting a block.
  3. Safety & sandbox integration: integrate with existing `src/safety.py` static checks and OS sandbox policies (`nonet` / `strict`), keeping advanced workspace drift/revert policies decoupled in `D4` -> `D6`.
  4. TUI integration in `START SESSION`, `START STEP`, `END STEP`, and `END SESSION` (`src/ui.py`): replace default `Enter`/`Y` action with `Send to model (<profile>)` while keeping `c(opy)` for clipboard mode, render model reasoning/commentary and structured `edits` diffs directly inside `START STEP`, and persist conversation transcript and exact provider token/cache usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) in `<session>/chat.json` and `<session>/meta.json` (keeping fast offline stdlib heuristic estimation for pre-flight TUI cards).
  5. Prompt caching & prefix stability (cross-session and intra-session) on top of `Bundle-Protocol: 1` (`F82`):
     - Split `<session>/0` using `bundle_plan` fragment boundaries (`src/bundle_plan.py`, `format_start_bundle()` in `src/bundle.py`) so static `===== Rules =====` (`kind: "rule"`, with invariant rules first and role/transport-gated rules last) and static project instructions (`AGENTS.md`) form an immutable cacheable prefix (`system` prompt / leading `cache_control` breakpoint), while per-session headers (`Session`, `Next-Block`, `Date`, `Role`, `Task`, `Title`), dynamic command outputs (`kind: "cmd"`), file includes (`kind: "file"`), and prompt fragments (`kind: "prompt"`, including upstream task/context parts and `===== Prompt =====`) go into the initial `user` message.
     - Keep intra-session step history strictly append-only across turns (advancing the trailing `cache_control` breakpoint to the latest `<session>/<step>/out` turn) and use threshold/chunked context compaction rather than per-turn sliding-window truncation so prior step prefixes remain cache-valid across consecutive steps.
     - Surface provider token and cache hit statistics in `Stats:` across `END STEP` and `END SESSION`.
  6. Stdlib-first HTTP/SSE streaming client (`urllib.request`) with no required third-party dependencies, coordinating with `F85` (`GIT_PAGER=cat`).

# ⚪ [NEW] F93: Split src/runner.py by responsibility

- Depends on: F94, B15, B16
src/runner.py keeps growing (about 2600 lines after F74) and mixes step execution, --fix diagnostics, payload reassembly, and session listing; this exceeds the modular cohesion guideline of roughly 300-800 lines per module.

# ⚪ [NEW] D4: Design workspace state fingerprinting and drift detection across steps

- Depends on: F92, F93
- Explore computing a lightweight workspace state fingerprint (`state_before` / `state_after`, e.g. Git `HEAD` + status/diff digest or non-Git directory metadata hash) around step execution in `src/runner.py`.
- Define how state drift between consecutive steps (manual edits or external processes modifying files after the previous step's `state_after`) is detected, surfaced in `src/ui.py` (`START STEP` / `END STEP`), and classified as mutating vs read-only in `src/safety.py` and `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D5: Design tamper-evident hash chain and parent-step verification for session history

- Depends on: D4
- Evaluate storing a SHA-256 digest per executed step (covering script text, exit code, output, and post-step state fingerprint) linked via `prev_hash` in `src/runner.py`.
- Clarify protocol details for optional parent-hash anchoring in `Next-Block` headers (`agents/run.md`), a `run --verify <session>` integrity check in `src/cli.py`, and test coverage in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] D6: Design session execution policies and post-step revert guards

- Depends on: D4
- Evaluate declarative session-level execution constraints and granular per-step sandbox permissions in `meta.json` / `.context.bundle` (`src/bundle.py`, `src/config.py`, `src/runner.py`, `src/safety.py`, `src/ui.py`):
  - Role & path write policies: support role-based allowed write globs (e.g. `role=plan` restricted to `TODO*.md`, `role=design` restricted to `docs/adr/**` and `TODO*.md`), hard blocks on destructive patterns (`rm -rf /`, `rm -rf ~`, outside-`Workdir` deletes, `.git/hooks` or `~/.ssh` tampering), and pre-step working-tree snapshots (`git stash create`) with one-key `r(evert)` in `END STEP` (or automatic rollback on policy violation).
  - Granular per-step sandbox permissions in `START STEP`: default to `nonet` / `strict` filesystem isolation (hiding `~` and `~/.ssh`), automatically bind-mount discovered `.todo_projects` sibling repositories (read-only by default, read-write when targeted by `todo -C <project>`), detect when a step requires network access (`git push`/`pull`, `curl`) or extra directory mounts in `src/safety.py`, and let the user grant one-step network or extra-folder access interactively in `START STEP` via `s(andbox)` without disabling filesystem isolation for the rest of the session.
- Cover enforcement, per-step permission prompts, and rollback semantics in `tests/test_runner.py`, `tests/test_safety.py`, and `tests/test_ui.py`.

# ⚪ [NEW] D7: Design pre-flight sandbox dry-run preview via temporary git worktree

- Depends on: D6
- Explore an optional pre-flight simulation mode (`src/config.py`, `src/runner.py`) that executes a candidate block inside a temporary lightweight `git worktree` (or isolated copy) before touching the main working tree.
- Define how actual mutated files and diff summaries are presented in `START STEP` (`src/ui.py`, `src/safety.py`), how cleanup and non-Git fallbacks behave, and how to test safely in `tests/test_runner.py` and `tests/test_safety.py`.

# ⚪ [NEW] D8: Design explicit parent-step DAG lineage for session branches and retries

- Depends on: D5
- Explore recording explicit `parent_step` / `parent_hash` metadata for every step, `--fix` patch (`s1/1_1`), and `--retry` run in `src/runner.py` so session history forms an unambiguous DAG rather than relying solely on lexical step names.
- Define how branch lineage is inspected in `--list` / `--show` (`src/cli.py`, `src/ui.py`) and verified in `tests/test_runner.py` and `tests/test_cli.py`.

# ⚪ [NEW] F88: Implement built-in LLM API agent mode in run-block (single run tool, TUI loop, prompt caching, and key isolation)

- Depends on: D10, F85
- Depends on: B14 -> F92 -> F84
- Depends on: F94, B15, B16 -> F93
- Implement the built-in LLM API agent mode in `run` per `D10` so `todo <ID> | context | run` (or standalone `run`) can drive multi-step agent sessions directly over provider APIs while preserving `c(opy)` clipboard and `run -r` workflows:
  - Provider profiles, API key loading, and child environment secret scrubbing (`scrub_child_env()` in `src/runner.py`, `src/config.py`).
  - Stdlib `urllib.request` HTTP/SSE streaming client, single polymorphic `run` tool schema (`edits`, `script`, `fix_target`, `done`, `done_note`), and fallback reply extraction via `extract_reply_block()`.
  - Immutable system/prefix splitting over `Bundle-Protocol: 1` part boundaries (`src/bundle_plan.py`, `src/bundle.py`) and append-only turn caching with `<session>/chat.json` transcript persistence.
  - Exact post-turn provider token and cache usage accounting (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`) recorded in `<session>/chat.json` and `<session>/meta.json` and surfaced in `Stats:` across `END STEP` and `END SESSION` while preserving offline stdlib pre-flight estimation (`count_tokens()`, `format_stats()`).
  - Interactive TUI agent loop in `START SESSION`, `START STEP` (`BLOCK PLAN` reasoning + structured `edits` diff preview), `END STEP`, and `END SESSION` (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`).

# ⚪ [NEW] F100: Refine README.md progressive disclosure, add Options table, and update producer chain example

- Keep the introduction and `Quick Start` scenario-focused by moving low-level step descriptor/artifact details (`<session>/<step>/out`, `aborted`, `error`, `meta.json`) and `--fix` fuzzy-anchor heuristics (`similarity >= 0.85`, traceback tail extraction) into a dedicated reference section in the second half of `README.md`.
- Add a structured `Options` table under `CLI Reference` matching `run --help` and `agents/stack/cli/docs.md`.
- Update the legacy producer chain example `chain: ["todo_md"]` to `chain: ["vitalio/todo-md"]`.

# ⏸️ [HOLD] D9: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Defer external machine-readable runner contract until an external client is needed; built-in API agent mode (D10) runs in-process*

- Depends on: F79, F83, F88
- Design contract to let an external API/TUI/IDE client drive `run` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and `D10`/`F88` in-process step structures to evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload) and a two-phase `plan -> approve -> execute` CLI handshake for external clients.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).
