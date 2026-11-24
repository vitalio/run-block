# 🎯 [NEXT] D11: Audit run-block CLI commands, flags, settings, and TUI workflows for simplicity and user value

- Conduct an interactive architectural and UX audit of `run-block` with the user before splitting `src/runner.py` (`F93`) and landing the API agent loop (`F101`–`F103`, `F88`):
  - Walk through all current CLI subcommands, flags (`src/cli.py`, `src/header.py`), environment variables (`RUN_BLOCK_*` in `src/config.py`), TUI cards/hotkeys (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`), and step/bundle execution mechanics (`src/runner.py`, `src/bundle*.py`).
  - Classify features into daily core workflows, useful inspection/safety tools, and over-engineered or redundant options that can be simplified, consolidated, or removed.
  - Record agreed simplifications, flag/UX cleanups, and module boundaries for `F93` in `AGENTS.md` and `TODO.md`.

# 🎯 [NEXT] F105: Add clipboard ingestion for run -r (run -rc / --clipboard) and pre-allocation reply validation

- Depends on: B16
- Bump: `MINOR`
- Add direct system clipboard ingestion to `run -r` / `--run` and reject empty or non-actionable replies before allocating a step directory in `src/ui_prompt.py`, `src/runner.py`, `src/cli.py`, and `src/header.py`:
  - Add `read_clipboard_text()` in `src/ui_prompt.py` symmetric with `clipboard_command()` (`wl-paste --no-newline` under `WAYLAND_DISPLAY`, `xclip -selection clipboard -o` or `xsel --clipboard --output` under `DISPLAY`, `pbpaste` on macOS, or `powershell.exe -NoProfile -Command Get-Clipboard` under WSL).
  - Support `-c` / `--clipboard` with `-r` / `--run` (`run -rc [session]`, `run -r -c [session]`, `run -r --clipboard [session]`) in `src/cli.py` and `cmd_run_reply()` (`src/runner.py`) to read the copied model reply directly from the system clipboard without opening `$VISUAL` / `$EDITOR`.
  - Validate that the reply payload (from clipboard, editor, or piped `stdin`) is non-empty and contains an actionable block (`extract_reply_block()`) *before* allocating `<session>/<step>/` on disk, so accidental invocations with plain clipboard text fail cleanly with zero orphan step directories.
  - Document `run -rc` / `run -r --clipboard` in `src/header.py` (`--help`), `README.md`, and `AGENTS.md`, and add unit tests in `tests/test_cli.py` and `tests/test_runner.py`.

# 🎯 [NEXT] F101: Add unified config.json settings loader, model/role profile resolution, and unconditional child env API key scrubbing

- Depends on: D10, F85
- Bump: `MINOR`
- Implement a unified configuration system, model/role profile resolution, and unconditional secret isolation in `src/config.py`, `src/runner.py`, `src/cli.py`, and `src/header.py` per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Support a canonical user config file at `$XDG_CONFIG_HOME/run-block/config.json` (overridable via `RUN_BLOCK_CONFIG`, with automatic fallback to `$XDG_CONFIG_HOME/run-block/models.json`) and an optional project-level `.run-block.json` in `Workdir`.
  - Extend `get_setting(key)` to resolve all settings (`base_dir`, `work_dir`, `clipboard`, `token_stats`, `progress`, `pager`, `shell`, `editor`, `safety_disable`, `safety_rules`, `sandbox`, `approve_cmd`, `max_fix_attempts`, `max_state_mb`, `bundle_max_tokens`, `fragment_max_tokens`, `update_url`, plus `model`, `cache`, `compact_tokens`, `max_steps`) with precedence `env > project (.run-block.json) > config (config.json) > default`, returning `(value, source)` where `source` is `'env'`, `'project'`, `'config'`, or `'default'`. Restrict project-level `.run-block.json` to a safe non-privileged allowlist (ignoring security-sensitive keys such as `approve_cmd`, `safety_disable`, `api_key_cmd`, `shell`, and `base_dir`).
  - Resolve named model profiles (`default_profile`, `profiles.<name>.{provider, model, base_url, api_key_env, api_key_cmd, max_tokens, thinking, cache}`) and role routing (`roles.<role>.{profile, mode, max_steps}` for `plan`, `design`, `work`, `review`, `law`) from `config.json` / `models.json`, environment variables (`RUN_BLOCK_MODEL`, `RUN_BLOCK_MODEL_<ROLE>`, `RUN_BLOCK_CACHE=auto|system|off`, `RUN_BLOCK_COMPACT_TOKENS`, `RUN_BLOCK_MAX_STEPS`), and explicit CLI `--profile <name>` / `-P` override (persisting the resolved `"profile"` in `<session>/meta.json`).
  - Add `run --config [KEY[=VALUE] | --edit | --path]` in `src/cli.py` and `src/header.py` (`--help`) to inspect active settings with their resolution sources and configured profiles/roles (redacting any secrets), get or set a persistent key in `config.json` (written with `0600` permissions), or open `config.json` in the configured editor.
  - Resolve provider API keys in parent memory (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `RUN_BLOCK_API_KEY`, profile `api_key_env`, or `api_key_cmd`) and unconditionally strip all provider API key environment variables from `child_env` in `scrub_child_env()` across all sandbox modes (`off`, `nonet`, `strict`).
  - Document `config.json` / `--config` and `--profile` / `-P` in `README.md` and `AGENTS.md`, and add unit tests in `tests/test_cli.py` and `tests/test_runner.py` covering config precedence, project allowlist filtering, `--config` CLI operations, profile/role resolution, and unconditional secret scrubbing.

# 🎯 [NEXT] F104: Inject protocol reminder into step output when reply contains multiple blocks or trailing prose

- Depends on: B16
- Bump: `PATCH`
- Detect multi-block / malformed reply violations across both `extract_reply_block()` (`run -r` / `--run`) and `_reassemble_split_payload()` (direct `stdin` paste) in `src/runner.py`:
  - Record discarded trailing block references (e.g. `s479/5..s479/7`) and count (`ignored_trailing_blocks`), consecutive duplicate blocks (`duplicate_count`), non-empty trailing prose after the closing fence of the executed block (`trailing_prose`), and fence lines glued to prose on the same line (e.g. closing fence followed immediately by text without a newline, violating column-0 standalone fence rules).
  - When any violation is detected, inject a compact warning and rule reminder immediately after `[<session>/<step>] START` in `<session>/<step>/out` (alongside any `Note: renumbered from ...` line) and persist the violation summary in `<session>/<step>/meta.json`:
    - `[<label>] WARNING: discarded <N> trailing run block(s) (<refs>) and trailing prose after <label> — they were NOT executed.`
    - `[<label>] Rule reminder: emit at most ONE run block per reply at the very end, batch all related commands inside that single block, place opening/closing markdown fences alone on their own lines at column 0, and stop immediately after the closing fence.`
  - Keep `<session>/<step>/out` completely unchanged (zero extra tokens) when the model reply contains a single clean block at the end.
- Tighten `agents/run.md` rule 1 and rule 2 to state explicitly that prose glued to the same line as a closing fence or emitted after the block causes trailing blocks to be discarded with a protocol warning.
- Add unit tests in `tests/test_runner.py` covering multi-block replies, prose glued to closing fences, trailing prose after a block, and direct `stdin` paste truncation warnings.

# 🎯 [NEXT] F102: Add Bundle-Protocol v1 cache-prefix splitter, stdlib HTTP/SSE clients, and chat.json transcript

- Depends on: F101
- Bump: `MINOR`
- Create `src/agent.py` (registered in `build.py` `MODULE_ORDER`) and `agents/run-api.md` (`EMBEDDED_RULE_API` in `src/header.py`) implementing the API transport and prompt caching layer per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Split `<session>/0` losslessly using `bundle_plan["parts"]` (`src/bundle_plan.py`) into an immutable cross-session `system` prefix (all `kind == "rule"` parts with the `vitalio/run-block:run` fragment swapped once to `EMBEDDED_RULE_API` at `chat.json` creation + root `AGENTS.md` `kind == "file"`, excluding per-session headers) and the initial `user[0]` message (`kind == "header"` with `Session:` and `Next-Block:` + dynamic `cmd`, remaining `file`, and `prompt` parts).
  - Register the minimal single `run` tool schema (`script` required, nullable `fix_target` optional normalized from `null`/`""` to omitted; `disable_parallel_tool_use: true` / `parallel_tool_calls: false`) without separate `edits` or `done` JSON fields, and guard against OpenAI-compatible backends that emit multiple parallel `tool_calls` by accepting only `tool_calls[0]` and appending synthetic `tool_result` error responses for `tool_calls[1:]`.
  - Implement stdlib `urllib.request` streaming SSE clients for Anthropic Messages (`/v1/messages` with `cache_control: {"type": "ephemeral"}` breakpoints on `>= 1024`-token blocks under `RUN_BLOCK_CACHE=auto|system|off`) and OpenAI-compatible Chat Completions (`/v1/chat/completions` with `stream_options: {"include_usage": true}` for OpenAI, Gemini, OpenRouter, DeepSeek, and local servers).
  - Persist append-only conversation turns, threshold context compaction (`RUN_BLOCK_COMPACT_TOKENS`), and exact provider usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`, `response_at`) in `<session>/chat.json`, `<session>/<step>/meta.json`, and `<session>/meta.json`.
  - Add offline unit tests in `tests/test_agent.py` using mocked HTTP/SSE streams to verify prefix splitting, one-time `EMBEDDED_RULE_API` replacement, multi-call guard, `cache_control` breakpoint placement, usage accounting, and threshold compaction.

# 🎯 [NEXT] F103: Add proposed step state machine, safe autopilot, and supervisor-session CLI (run --step)

- Depends on: F93
- Depends on: F101 -> F102
- Depends on: F104
- Bump: `MINOR`
- Implement the step proposal state machine (`outcome: "proposed"`), strict `awaiting_reply` handling, session continuation (`--continue`), safe autopilot, and supervisor-session CLI in `src/agent.py`, `src/runner.py`, and `src/cli.py` per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Normalize tool-call `run(script, fix_target?)` and plain-text fallback replies via `extract_reply_block()` (stripping accidental fence/heredoc wrappers and converting misplaced shell scripts in `fix_target` to sequential steps). When the model returns plain prose without a `run` tool call or runnable block, record `outcome: "awaiting_reply"` rather than auto-closing the session via heuristics.
  - Persist all valid candidate steps under `<session>/<step>/` (`block.sh` or `fix.py`, `plan.md` reasoning, and `meta.json` with `"outcome": "proposed"`, keeping declined `aborted` / `not-run` steps materialized on disk so filesystem artifacts stay 1:1 synchronized with `tool_use` / `tool_result` turns in `<session>/chat.json`).
  - Add `run --continue [session]` / `-c` to resume an open API session directly from `<session>/chat.json` (opening `START STEP` if a step is `proposed`, sending pending `<step>/out` `tool_result` if completed but unsent, or prompting on `awaiting_reply`).
  - Add `run --step <target_session> --propose | --approve [--propose] | --reject "<reason>" [--propose] | --reply "<message>" [--propose] | --autopilot` (and `--profile <name>` / `-P`, `--autopilot` CLI flags) allowing a parent/supervisor session (`IN_RUN_BLOCK=1`, when `<target_session>` is not the current session or an ancestor) to inspect, approve, reject, reply to, or autopilot a worker session (surfacing `awaiting_reply` distinctly from `completed`).
  - Implement safe autopilot pausing automatically whenever `src/safety.py` reports risk findings, `RUN_BLOCK_APPROVE_CMD` prompts/rejects, the model enters `awaiting_reply`, or `max_steps` / consecutive failure limits are reached.
  - Add unit tests in `tests/test_agent.py` and `tests/test_runner.py` covering `proposed` and `awaiting_reply` lifecycle, 1:1 `chat.json` step materialization, `--continue`, supervisor `--step` commands, ancestor-recursion guards, and safe autopilot pause triggers.

# 🎯 [NEXT] F88: Integrate interactive TUI agent loop, model reply prompts, and provider cache stats in cards

- Depends on: F103
- Bump: `MINOR`
- Integrate the built-in API agent loop and token/cache telemetry into the interactive TUI (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`, `src/header.py`, `README.md`) per `docs/adr/0001-built-in-api-agent-mode.md`:
  - When a model profile is active, set the default `Enter`/`y` action in `START SESSION` and `END STEP` to `Send to model (<profile>)? [Y/n/a(uto)/c(opy)/e(dit)/i(nfo)]` while preserving `c(opy)` for clipboard mode and `run -r` full-reply mode.
  - Stream model reasoning and tool-call progress cleanly in the terminal, transition into `START STEP` (`BLOCK PLAN` showing `Reasoning:`, operation table, and safety warnings), and when the model replies with prose only (`outcome: "awaiting_reply"`), present `[r(eply)/d(one)/q(uit)/i(nfo)]` so the user can answer (`r`), manually confirm completion (`d`, promoting the model's summary to `completed_note`), or exit to shell (`q`/`n`).
  - Display provider token usage, cache hit percentage, and remaining Anthropic cache TTL in `Stats:` across `END STEP` and `END SESSION` while keeping fast offline `count_tokens()` estimation for pre-flight cards.
  - Document `--profile` / `-P`, `--continue` / `-c`, `--autopilot`, `--step`, `config.json` / `models.json`, and `RUN_BLOCK_MODEL*` / `RUN_BLOCK_CACHE` in `src/header.py` (`--help`), `agents/run.md`, and `README.md`, and add unit tests in `tests/test_ui.py` and `tests/test_cli.py`.

# ⚪ [NEW] F93: Split src/runner.py by responsibility

- Depends on: F94, B15, B16, D11
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

# ⏸️ [HOLD] D9: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Defer external machine-readable runner contract until an external client is needed; built-in API agent mode (D10) runs in-process*

- Depends on: F79, F83, F88
- Design contract to let an external API/TUI/IDE client drive `run` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and `D10`/`F88` in-process step structures to evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload) and a two-phase `plan -> approve -> execute` CLI handshake for external clients.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).
