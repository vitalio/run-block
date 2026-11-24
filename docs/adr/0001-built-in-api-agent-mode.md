# ADR 0001: Built-in LLM API Agent Mode, Prompt Caching, and Multi-Session Orchestration

- **Status:** Accepted
- **Date:** 2026-11-24
- **Task:** D10

## Context

`run-block` (`run`) initializes reproducible agent context bundles (`todo <ID> | context | run` -> `<session>/0` and `<session>/meta.json` using `Bundle-Protocol: 1`) and executes sequential `<session>/<step>` bash blocks (`block.sh`) or targeted Python `--fix` patches (`fix.py`) inside an isolated shell process with static risk scanning (`src/safety.py`), optional OS sandboxing (`nonet`, `strict`), and interactive TUI cards (`START SESSION`, `START STEP`, `END STEP`, `END SESSION`).

Previously, transporting prompts and replies between `run` and an LLM required either copying `<session>/0` and `<session>/<step>/out` via the system clipboard (`c(opy)`) or pasting full model replies into `run -r` (`F84`). While those workflows remain essential for web-chat interfaces, we also need a built-in API transport mode directly inside `run` that:

1. Preserves the zero-dependency, single-file standalone executable invariant (`build.py` -> `./run`).
2. Keeps 100% behavioral parity between web-chat blocks and API tool calls without introducing duplicate file-editing or session-lifecycle schemas.
3. Maximizes cross-session and intra-session prompt cache hit rates across providers (Anthropic explicit ephemeral breakpoints and OpenAI / Gemini / DeepSeek / local implicit prefix caches).
4. Prevents child step scripts from reading or leaking LLM provider API keys.
5. Enables multi-model, multi-role orchestration (`plan` -> `work` -> `review`) and supervisor-session control where one `run` session can inspect, approve, reject, or answer another `run` session step by step.

## Decision

### 1. Stdlib-Only HTTP/SSE Client and Cohesive `src/agent.py` Module

- Keep `run` strictly free of third-party Python dependencies. Implement the HTTP/SSE streaming client in `src/agent.py` on top of Python's standard library (`urllib.request`, `http.client`, `ssl`, `json`) supporting two canonical wire protocols:
  - **Anthropic Messages API** (`/v1/messages`, `anthropic-version: 2023-06-01`, SSE events `message_start`, `content_block_start`, `content_block_delta`, `message_delta`, `message_stop`).
  - **OpenAI-Compatible Chat Completions API** (`/v1/chat/completions` with `stream: true`, `stream_options: {"include_usage": true}` covering OpenAI, Google Gemini OpenAI-compatible endpoints, OpenRouter, DeepSeek, Ollama, vLLM, and llama.cpp).
- Place `src/agent.py` in `MODULE_ORDER` (`build.py`) between `runner.py` and `bundle.py`, keeping `src/runner.py` focused on local step execution (`F93`).

### 2. Minimal Single `run` Tool Schema (No Separate `edits` or `done` JSON Fields)

- Register a single tool named `run` with parallel tool calls disabled (`disable_parallel_tool_use: true` on Anthropic, `parallel_tool_calls: false` on OpenAI-compatible APIs):

```json
{
  "name": "run",
  "description": "Execute the next bash step in the active run-block session (or apply a Python --fix patch when fix_target is specified).",
  "input_schema": {
    "type": "object",
    "properties": {
      "script": {
        "type": "string",
        "description": "Batched bash commands to execute in Workdir (or Python text patch when fix_target is set). Do not wrap in markdown fences or heredocs."
      },
      "fix_target": {
        "type": "string",
        "description": "Optional target step (<session>/<step>) to patch via run --fix."
      }
    },
    "required": ["script"],
    "additionalProperties": false
  }
}
```

- **Why no `edits: [{path, old, new}]` field:** Agents already perform atomic, multi-file edits and AST/syntax checks inside batched `bash` + `python3` scripts per `core/edit`. A separate JSON `edits` array would duplicate editing mechanics, increase JSON escaping failures on large multiline patches, and diverge from clipboard / `run -r` workflows.
- **Why no `done` / `done_note` JSON fields:** Session closure and child-session handoff already work uniformly through `run --done [-m "<note>"]` inside `script` (queuing `end_session` and `start_session` events in `<step>/deferred.json`). Reusing `run --done` inside `script` keeps one canonical completion path across all transports.
- **Defensive tool-call normalization & multi-call guard:**
  - Normalize `fix_target: null` or `""` to omitted/unset in `src/agent.py` so the tool schema remains compatible with strict JSON Schema modes (`"type": ["string", "null"]`) across providers.
  - Some OpenAI-compatible `/v1/chat/completions` backends (e.g. local Ollama/llama.cpp or routed providers) ignore `parallel_tool_calls: false` and emit multiple `tool_calls` in a single assistant turn. `src/agent.py` accepts only `tool_calls[0]` as the candidate step and immediately appends synthetic `tool_result` error responses (`"Parallel tool calls are disabled; execute one sequential step at a time."`) for `tool_calls[1:]` so conversation history remains valid for the next provider turn.
- **Resilient reply recovery (`extract_reply_block()`) and strict `awaiting_reply` handling:**
  - If the model wraps `script` in Markdown fences or `run sN/k <<'RUN_BLOCK' ... RUN_BLOCK`, strip the wrapper via `extract_reply_block()`.
  - If `fix_target` is set but `script` contains a shell script rather than a Python `text` patch, automatically convert it into the next sequential step `<session>/<next_step>`.
  - If the model replies with plain text containing a fenced block instead of calling the `run` tool, extract the block via `extract_reply_block(allow_fenced_fallback=True)`.
  - **No heuristic auto-closure on prose replies:** Keep `run --done [-m "<note>"]` inside `script` as the sole model-initiated closure mechanism. When the model returns plain prose without a `run` tool call (and `extract_reply_block(allow_fenced_fallback=True)` finds no runnable block), record the turn with `outcome: "awaiting_reply"` rather than auto-closing the session via punctuation heuristics.
  - In the interactive TUI, present `[r(eply)/d(one)/q(uit)/i(nfo)]` so the user can answer the model (`r`), manually confirm completion (`d`, promoting the model's summary to `completed_note` without an extra API round-trip), or exit to the shell (`q`/`n`) and resume later via `run --continue`.
  - In supervisor mode (`run --step <session>`), surface `awaiting_reply` distinctly from `completed` so the supervisor can decide whether to answer a genuine question (`--reply`) or instruct the worker to verify and run `run --done`.

### 3. Model Profiles, Role Routing, and Unconditional API Key Isolation

- **Profiles and role mapping (`$XDG_CONFIG_HOME/run-block/models.json` and `RUN_BLOCK_MODEL*`):**
  - Support named model profiles in `~/.config/run-block/models.json` (`default_profile`, `profiles.<name>.{provider, model, base_url, api_key_env, api_key_cmd, max_tokens, thinking, cache}`) and zero-config environment variables (`RUN_BLOCK_MODEL`, `RUN_BLOCK_MODEL_<ROLE>`, `RUN_BLOCK_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`).
  - Map bundle `Role:` headers (`plan`, `design`, `work`, `review`, `law`) to default model profiles and execution modes (`roles.<role>.{profile, mode, max_steps}`), allowing a `plan` session on a reasoning model to hand off to a `work` session on a fast coding model and then to a `review` session on an independent reviewer model.
  - **Explicit CLI profile override (`--profile <name>` / `-P`):** Override role-based (`roles.<role>.profile`) and default (`default_profile`) model resolution on session start or step execution (`context | run --profile opus-plan`, `run --step s1 --propose --profile local-qwen`), avoiding short-flag collision with `run --done -m "<note>"`. Persist the resolved profile name in `<session>/meta.json` (`"profile"`) so subsequent turns and `run --continue` use the same model unless explicitly overridden.
- **Unconditional secret scrubbing (`scrub_child_env()` in `src/config.py` / `src/runner.py`):**
  - Resolve API keys in parent memory (environment variable, `api_key_cmd` / macOS Keychain / Linux `secret-tool`, or `0600` config file).
  - Always strip provider API key environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPSEEK_API_KEY`, `RUN_BLOCK_API_KEY`, plus any profile-configured `api_key_env`) in `scrub_child_env()` before spawning child step processes, regardless of whether `sandbox` is `off`, `nonet`, or `strict`.

### 4. Prompt Caching and Prefix Stability on Top of `Bundle-Protocol: 1`

- **Lossless `<session>/0` split and transport-aware rule injection via `bundle_plan` (`Bundle-Protocol: 1`):**
  - Per `context-bundle-protocol` v1, `run` is a self-contained tool that owns its execution rule fragment (`id: "vitalio/run-block:run"`, `chain: ["vitalio/run-block"]`), while `context` emits all `kind == "rule"` fragments in deterministic `.context.bundle` declaration order followed by `file AGENTS.md` (kept as `file` rather than `rule` so `#` headings, `{var:default}` literals, and the `===== $ cat AGENTS.md =====` boundary are preserved verbatim for edits), `cmd`, and `prompt` parts.
  - **Transport-aware rule swap (`agents/run.md` vs `agents/run-api.md`):** In web-chat mode (`c(opy)` / `run -r`), models need Markdown fence and `<<'RUN_BLOCK'` / `<<'RUN_FIX'` layout rules (`agents/run.md`, `EMBEDDED_RULE_BASH`). In built-in API mode, `script` is passed directly as a JSON string argument to the `run` tool, making heredoc and Markdown fence rules redundant (~300–500 tokens) and prone to double-escaping. When building `system` for `<session>/chat.json`, `src/agent.py` swaps the `vitalio/run-block:run` rule fragment once for the compact API tool rule (`agents/run-api.md`, `EMBEDDED_RULE_API`) while keeping `<session>/0` on disk intact for clipboard fallback and keeping `Session:` and `Next-Block:` in `user[0]` for `fix_target="<session>/<step>"` and child session handoff.
  - Using the 1-based line ranges in `bundle_plan["parts"]` (`src/bundle_plan.py`), split `<session>/0` into:
    1. **`system` message (immutable across sessions for the same repo & role):** all `kind == "rule"` parts (with `vitalio/run-block:run` swapped to `EMBEDDED_RULE_API` once at `chat.json` creation) plus the root project `AGENTS.md` part (`kind == "file"`, `name == "AGENTS.md"`). Per-session headers (`Session`, `Next-Block`, `Date`, `Role`, `Task`, `Title`) are excluded from `system` so the system prefix remains byte-identical across sessions and turns.
    2. **Initial `user` message (session context):** the `kind == "header"` block (`Session`, `Next-Block`, `Workdir`, `Sandbox`, `Date`, `Role`, `Task`, `Title`) followed by dynamic `cmd`, remaining `file`, and `prompt` parts.
- **Provider cache mechanics and `RUN_BLOCK_CACHE=auto|system|off`:**
  - **Implicit prefix caching (OpenAI, Gemini, DeepSeek, local servers):** free cache writes (`1.0x`) and discounted cache reads (`0.10x–0.50x`, reported in `cached_tokens`). Prefix stability (`system` + append-only turns) automatically maximizes cache hits.
  - **Explicit ephemeral breakpoints (Anthropic `/v1/messages`):** `1.25x` write cost, `0.10x` read cost, 5-minute TTL refreshed on each cache hit (up to 4 `cache_control: {"type": "ephemeral"}` breakpoints per request, applied only to blocks `>= 1024` tokens). In `auto` mode (default), place breakpoints on:
    1. `kind == "rule"` block in `system`,
    2. Root `AGENTS.md` block in `system`,
    3. Initial `user[0]` session bundle,
    4. Latest completed `user` (`tool_result` `<session>/<step>/out`) turn.
  - In `system` mode (`RUN_BLOCK_CACHE=system`), place `cache_control` only on `system` (avoiding `1.25x` history write charges when human pauses between steps regularly exceed the 5-minute TTL); in `off` mode, omit `cache_control`.
- **Append-only step history and threshold compaction:**
  - Persist conversation turns and per-turn provider usage (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `cached_tokens`, `response_at`) in `<session>/chat.json`, `<session>/<step>/meta.json`, and accumulated `<session>/meta.json`.
  - Keep turn history strictly append-only across steps so prior turns stay cache-valid. Compact older intermediate `tool_result` payloads in a single batch only when total input tokens exceed `RUN_BLOCK_COMPACT_TOKENS` (default `120000`).
  - Surface provider token usage, cache hit percentage, and remaining Anthropic cache TTL in `Stats:` across `END STEP` and `END SESSION` while keeping fast offline `count_tokens()` estimation for pre-flight cards.

### 5. Step State Machine, Safe Autopilot, and Supervisor-Session Control (`run --step`)

- **Unified step proposal state (`outcome: "proposed"`) and 1:1 audit-log invariant:**
  - When a model proposes a valid tool call `run(script, fix_target?)` (or fallback block), persist the candidate step under `<session>/<step>/` (`block.sh` or `fix.py`, `plan.md` with model reasoning, and `meta.json` with `"outcome": "proposed"`) before execution.
  - Preserve `<session>/<step>/` materialization for all valid candidate steps (including declined `aborted` / `not-run` steps) so filesystem artifacts stay 1:1 synchronized with `tool_use` / `tool_result` turns in `<session>/chat.json`.
- **Interactive session continuation (`run --continue [session]` / `-c`):**
  - Resume an open API session directly from `<session>/chat.json`:
    - If a step is currently in `outcome: "proposed"`, open `START STEP` immediately.
    - If the latest step has completed (`out` exists) and has not yet been sent to the model, send the pending `tool_result` and await the next proposal.
    - If the session is in `outcome: "awaiting_reply"`, prompt for a reply (`[r(eply)/d(one)/q(uit)/i(nfo)]`).
- **Two frontends over the same step state machine:**
  1. **Interactive Human TUI (`START SESSION`, `START STEP`, `END STEP`):**
     - When a model profile is active, default `Enter`/`y` in `START SESSION` and `END STEP` sends the bundle/output to the model (`Send to model (<profile>)? [Y/n/a(uto)/c(opy)/e(dit)/i(nfo)]`), while keeping `c(opy)` for clipboard mode.
     - `START STEP` renders `Reasoning:` (`<step>/plan.md`), operation breakdown, and `src/safety.py` warnings before running the proposed step.
     - **Safe Autopilot (`--autopilot` / `a(uto)` hotkey):** automatically loops `propose -> approve -> execute -> send output` while `src/safety.py` findings are empty and `RUN_BLOCK_APPROVE_CMD` does not require prompting; immediately pauses and falls back to the interactive TUI prompt if safety warnings are detected, the model asks a text question, `max_steps` or consecutive failure limits are reached, or the user presses `Ctrl+C`.
  2. **Supervisor-Session CLI (`run --step <target_session>`):**
     - Allow a running parent/supervisor session (`IN_RUN_BLOCK=1`) to drive a distinct target session (`<target_session> != RUN_BLOCK_PARENT_SESSION` and not an ancestor session) via non-interactive CLI subcommands:
       - `run --step <session> --propose` — send pending bundle/output to `<session>`'s model, save the resulting proposed step (or model question), and print reasoning, safety summary, and script to `stdout` without executing it.
       - `run --step <session> --approve [--propose]` — execute the pending proposed step in `<session>`, print its `<step>/out`, and optionally request the next proposal in one call.
       - `run --step <session> --reject "<reason>" [--propose]` — reject the pending proposed step (`NOT RUN: rejected by supervisor: <reason>`) and optionally request a revised proposal from `<session>`'s model.
       - `run --step <session> --reply "<message>" [--propose]` — send a user/supervisor text reply to `<session>`'s model when it asked a question or needs review feedback.
       - `run --step <session> --autopilot` — run `<session>` on safe autopilot until completion (`run --done`), pausing and returning control to the supervisor's `stdout` only when `<session>` hits a safety warning, asks a question, or exceeds failure/step limits.

## Rejected Alternatives

- **Third-party SDK dependencies (`anthropic`, `openai`, `httpx`):** Rejected because they break single-file compilation (`build.py`) and zero-dependency installation (`install.sh`) while saving only ~100 lines of standard HTTP/SSE framing.
- **Structured `edits: [{path, old, new}]` and `done: bool` in the `run` tool JSON schema:** Rejected because they duplicate existing Python-in-bash file editing (`core/edit`) and `run --done` session completion mechanics, complicate JSON escaping for multiline code, and break symmetry with web-chat (`c(opy)` / `run -r`) blocks.
- **Per-turn sliding-window history truncation:** Rejected because mutating earlier turns on every step invalidates prefix caches across both Anthropic and OpenAI/Gemini/DeepSeek.

## Consequences

- `run` gains a native zero-dependency API agent loop while remaining a single standalone Python 3.9+ executable.
- Web-chat (`c(opy)`, `run -r`), human interactive API mode, safe autopilot (`--autopilot`), and multi-session supervisor pipelines (`plan` -> `work` -> `review` via `run --step <session>`) all share the exact same `<session>/<step>` artifacts, `src/safety.py` scanner, and `run_script()` execution engine.
