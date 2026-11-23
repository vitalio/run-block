# 🎯 [NEXT] F100: Refine README.md progressive disclosure, add Options table, and update producer chain example

- Keep the introduction and `Quick Start` scenario-focused by moving low-level step descriptor/artifact details (`<session>/<step>/out`, `aborted`, `error`, `meta.json`) and `--fix` fuzzy-anchor heuristics (`similarity >= 0.85`, traceback tail extraction) into a dedicated reference section in the second half of `README.md`.
- Add a structured `Options` table under `CLI Reference` matching `run --help` and `agents/stack/cli/docs.md`.
- Update the legacy producer chain example `chain: ["todo_md"]` to `chain: ["vitalio/todo-md"]`.

# 🎯 [NEXT] F101: Add model/role profile resolution and unconditional child env API key scrubbing

- Depends on: D10, F85
- Bump: `MINOR`
- Implement model profile resolution and unconditional secret isolation per `docs/adr/0001-built-in-api-agent-mode.md`:
  - In `src/config.py`, resolve model profiles from `$XDG_CONFIG_HOME/run-block/models.json` (`default_profile`, `profiles.<name>.{provider, model, base_url, api_key_env, api_key_cmd, max_tokens, thinking, cache}`, `roles.<role>.{profile, mode, max_steps}`) and environment variables (`RUN_BLOCK_MODEL`, `RUN_BLOCK_MODEL_<ROLE>`, `RUN_BLOCK_CACHE=auto|system|off`, `RUN_BLOCK_COMPACT_TOKENS`, `RUN_BLOCK_MAX_STEPS`), routing session `Role:` headers (`plan`, `design`, `work`, `review`, `law`) to their configured profile and execution mode.
  - Resolve provider API keys in parent memory (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `RUN_BLOCK_API_KEY`, profile `api_key_env`, or `api_key_cmd` / macOS Keychain / Linux `secret-tool`).
  - In `src/config.py` / `src/runner.py` (`scrub_child_env()`), unconditionally strip all provider API key environment variables (and any profile-configured `api_key_env`) from `child_env` across all sandbox modes (`off`, `nonet`, `strict`).
  - Add unit tests in `tests/test_runner.py` and `tests/test_cli.py` covering profile/role resolution and unconditional secret scrubbing in `scrub_child_env()`.

# 🎯 [NEXT] F102: Add Bundle-Protocol v1 cache-prefix splitter, stdlib HTTP/SSE clients, and chat.json transcript

- Depends on: F101
- Bump: `MINOR`
- Create `src/agent.py` (registered in `build.py` `MODULE_ORDER`) implementing the API transport and prompt caching layer per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Split `<session>/0` losslessly using `bundle_plan["parts"]` (`src/bundle_plan.py`) into an immutable cross-session `system` prefix (leading `kind == "rule"` parts + root `AGENTS.md` `kind == "file"`, excluding per-session headers) and the initial `user[0]` message (`kind == "header"` + dynamic `cmd`, `file`, and `prompt` parts).
  - Register the minimal single `run` tool schema (`script` required, `fix_target` optional; `disable_parallel_tool_use: true` / `parallel_tool_calls: false`) without separate `edits` or `done` JSON fields (edits run via batched `bash` + `python3` and completion runs via `run --done` inside `script`).
  - Implement stdlib `urllib.request` streaming SSE clients for Anthropic Messages (`/v1/messages` with `cache_control: {"type": "ephemeral"}` breakpoints on `>= 1024`-token blocks under `RUN_BLOCK_CACHE=auto|system|off`) and OpenAI-compatible Chat Completions (`/v1/chat/completions` with `stream_options: {"include_usage": true}` for OpenAI, Gemini, OpenRouter, DeepSeek, and local servers).
  - Persist append-only conversation turns, threshold context compaction (`RUN_BLOCK_COMPACT_TOKENS`), and exact provider usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`, `response_at`) in `<session>/chat.json`, `<session>/<step>/meta.json`, and `<session>/meta.json`.
  - Add offline unit tests in `tests/test_agent.py` using mocked HTTP/SSE streams to verify prefix splitting, `cache_control` breakpoint placement, usage accounting, and threshold compaction.

# 🎯 [NEXT] F103: Add proposed step state machine, safe autopilot, and supervisor-session CLI (run --step)

- Depends on: F93
- Depends on: F102
- Bump: `MINOR`
- Implement the step proposal state machine (`outcome: "proposed"`), reply recovery, safe autopilot, and supervisor-session CLI in `src/agent.py`, `src/runner.py`, and `src/cli.py` per `docs/adr/0001-built-in-api-agent-mode.md`:
  - Normalize tool-call `run(script, fix_target?)` and plain-text fallback replies via `extract_reply_block()` (stripping accidental fence/heredoc wrappers, converting misplaced shell scripts in `fix_target` to sequential steps, and pausing when the model asks a prose question without a block).
  - Persist candidate steps under `<session>/<step>/` (`block.sh` or `fix.py`, `plan.md` reasoning, and `meta.json` with `"outcome": "proposed"`) before execution.
  - Add `run --step <target_session> --propose | --approve [--propose] | --reject "<reason>" [--propose] | --reply "<message>" [--propose] | --autopilot` (and `-m`/`--model <profile>`, `--autopilot` CLI flags) allowing a parent/supervisor session (`IN_RUN_BLOCK=1`, when `<target_session>` is not the current session or an ancestor) to inspect, approve, reject, reply to, or autopilot a worker session.
  - Implement safe autopilot pausing automatically whenever `src/safety.py` reports risk findings, `RUN_BLOCK_APPROVE_CMD` prompts/rejects, the model asks a clarifying question, or `max_steps` / consecutive failure limits are reached.
  - Add unit tests in `tests/test_agent.py` and `tests/test_runner.py` covering `proposed` step lifecycle, supervisor `--step` commands, ancestor-recursion guards, and safe autopilot pause triggers.

# 🎯 [NEXT] F88: Integrate interactive TUI agent loop, model reply prompts, and provider cache stats in cards

- Depends on: F103
- Bump: `MINOR`
- Integrate the built-in API agent loop and token/cache telemetry into the interactive TUI (`src/ui.py`, `src/ui_info.py`, `src/ui_prompt.py`, `src/cli.py`, `src/header.py`, `README.md`) per `docs/adr/0001-built-in-api-agent-mode.md`:
  - When a model profile is active, set the default `Enter`/`y` action in `START SESSION` and `END STEP` to `Send to model (<profile>)? [Y/n/a(uto)/c(opy)/e(dit)/i(nfo)]` while preserving `c(opy)` for clipboard mode and `run -r` full-reply mode.
  - Stream model reasoning and tool-call progress cleanly in the terminal, transition into `START STEP` (`BLOCK PLAN` showing `Reasoning:`, operation table, and safety warnings), and support interactive `r(eply)` when the model asks a question without emitting a block or `a(uto)` to switch the session into safe autopilot.
  - Display provider token usage, cache hit percentage, and remaining Anthropic cache TTL in `Stats:` across `END STEP` and `END SESSION` while keeping fast offline `count_tokens()` estimation for pre-flight cards.
  - Document `-m`/`--model`, `--autopilot`, `--step`, `models.json`, and `RUN_BLOCK_MODEL*` / `RUN_BLOCK_CACHE` in `src/header.py` (`--help`), `agents/run.md`, and `README.md`, and add unit tests in `tests/test_ui.py` and `tests/test_cli.py`.

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

# ⏸️ [HOLD] D9: Design machine-readable runner contract (--json step output and plan/execute handshake) — *Defer external machine-readable runner contract until an external client is needed; built-in API agent mode (D10) runs in-process*

- Depends on: F79, F83, F88
- Design contract to let an external API/TUI/IDE client drive `run` cleanly without parsing TUI frames or overloading `-y`/`--yes`.
- Align with `F83` step outcome metadata in `<session>/<step>/meta.json` (`outcome`: `ok`/`failed`/`syntax-error`/`not-run`/`aborted`/`saved`, `exit_code`, `duration_ms`, `reason`, `fix_target`) and `D10`/`F88` in-process step structures to evaluate structured `--json` execution output for `<session>/<step>` (including safety findings, auto-repair/renumber notes, and clean `[sN/k]` LLM payload) and a two-phase `plan -> approve -> execute` CLI handshake for external clients.
- Coordinate with `F42` (`--done` completion state) and `F46` (`bundle_plan` metadata).
