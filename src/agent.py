ANTHROPIC_API_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_PROVIDER_BASE_URLS: dict[str, str] = {
    "anthropic": DEFAULT_ANTHROPIC_BASE_URL,
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com/v1",
}
DEFAULT_MAX_OUTPUT_TOKENS = 8192
MIN_CACHE_CONTROL_TOKENS = 1024
MAX_ANTHROPIC_CACHE_BREAKPOINTS = 4
CACHE_EPHEMERAL: dict[str, str] = {"type": "ephemeral"}

RUN_TOOL_NAME = "run"
RUN_TOOL_DESCRIPTION = (
    "Execute the next bash step in the active run-block session "
    "(or apply a Python --fix patch when fix_target is specified)."
)
RUN_TOOL_SCRIPT_DESCRIPTION = (
    "Batched bash commands to execute in Workdir (or Python text patch when fix_target is set). "
    "Do not wrap in markdown fences or heredocs."
)
RUN_TOOL_FIX_TARGET_DESCRIPTION = "Optional target step (<session>/<step>) to patch via run --fix."
PARALLEL_TOOL_CALL_ERROR = "Parallel tool calls are disabled; execute one sequential step at a time."

RUN_TOOL_INPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "script": {
            "type": "string",
            "description": RUN_TOOL_SCRIPT_DESCRIPTION,
        },
        "fix_target": {
            "type": "string",
            "description": RUN_TOOL_FIX_TARGET_DESCRIPTION,
        },
    },
    "required": ["script"],
    "additionalProperties": False,
}

_ROOT_AGENTS_MD_CHAINS = frozenset({"", ".context.bundle", ".agents_bundle", "local", "root"})
_USAGE_COUNTER_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "cached_tokens",
)


class AgentAPIError(RuntimeError):
    """Raised when an LLM provider HTTP/SSE request fails."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status_code: int | None = None,
        body: str = "",
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code
        self.body = body


def get_embedded_api_rule() -> tuple[str, str]:
    """Return the canonical rule ID and rendered EMBEDDED_RULE_API text."""
    rule_id = "vitalio/run-block:run"
    raw = EMBEDDED_RULE_API if EMBEDDED_RULE_API != "__EMBEDDED_RULE_API__" else ""
    prog = prog_name()
    rendered = raw.replace("{cmd:run}", prog).replace("{cmd:run_block}", prog)
    return rule_id, rendered


def build_run_tool_schema(provider: str = "anthropic") -> dict[str, object]:
    """Return the minimal single 'run' tool definition for Anthropic or OpenAI-compatible APIs."""
    prov = (provider or "anthropic").strip().lower()
    if prov == "anthropic":
        return {
            "name": RUN_TOOL_NAME,
            "description": RUN_TOOL_DESCRIPTION,
            "input_schema": json.loads(json.dumps(RUN_TOOL_INPUT_SCHEMA)),
        }
    return {
        "type": "function",
        "function": {
            "name": RUN_TOOL_NAME,
            "description": RUN_TOOL_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "script": {
                        "type": "string",
                        "description": RUN_TOOL_SCRIPT_DESCRIPTION,
                    },
                    "fix_target": {
                        "type": ["string", "null"],
                        "description": RUN_TOOL_FIX_TARGET_DESCRIPTION,
                    },
                },
                "required": ["script"],
                "additionalProperties": False,
            },
        },
    }


def _clean_fix_target_arg(raw_fix_target: object) -> str | None:
    if raw_fix_target is None or isinstance(raw_fix_target, bool):
        return None
    val = str(raw_fix_target).strip()
    if not val or val.lower() == "null":
        return None
    return val


def normalize_run_tool_call(
    raw_args: dict[str, object] | str | None,
    *,
    session: str | None = None,
) -> dict[str, object]:
    """Normalize a run(script, fix_target?) tool call argument payload.

    Strips null/empty fix_target to omitted/None and unwraps accidental Markdown
    fences or heredocs via normalize_api_tool_script().
    """
    parsed: dict[str, object] = {}
    if isinstance(raw_args, dict):
        parsed = dict(raw_args)
    elif isinstance(raw_args, str):
        text = raw_args.strip()
        if text:
            try:
                loaded = json.loads(text)
            except ValueError as exc:
                raise ValueError(f"invalid tool call JSON arguments: {exc}") from None
            if not isinstance(loaded, dict):
                raise ValueError("tool call arguments must be a JSON object")
            parsed = loaded
    elif raw_args is not None:
        raise ValueError("tool call arguments must be a dict or JSON object string")

    raw_script = parsed.get("script")
    if not isinstance(raw_script, str) or not raw_script.strip():
        raise ValueError("tool call 'run' requires a non-empty 'script' string")

    fix_target = _clean_fix_target_arg(parsed.get("fix_target"))
    norm = normalize_api_tool_script(raw_script, session=session, fix_target=fix_target)
    eff_fix_target = _clean_fix_target_arg(norm.get("fix_target"))
    clean_input: dict[str, object] = {"script": str(norm["payload"])}
    if eff_fix_target is not None:
        clean_input["fix_target"] = eff_fix_target
    return {
        "name": RUN_TOOL_NAME,
        "input": clean_input,
        "script": str(norm["payload"]),
        "fix_target": eff_fix_target,
        "kind": str(norm["kind"]),
        "had_wrapper": bool(norm.get("had_wrapper")),
        "glued_fence": bool(norm.get("glued_fence")),
        "protocol_violations": norm.get("protocol_violations"),
        "reply_transport": "api_tool",
    }


def process_assistant_tool_calls(
    tool_calls: list[dict[str, object]],
    *,
    session: str | None = None,
) -> dict[str, object]:
    """Enforce the single-tool-call guard on assistant tool_calls.

    Accepts only tool_calls[0] (normalized via normalize_run_tool_call) and
    generates synthetic tool_result error responses for tool_calls[1:].
    """
    if not tool_calls:
        return {
            "primary_call": None,
            "normalized_calls": [],
            "rejected_calls": [],
            "synthetic_tool_results": [],
        }

    normalized_calls: list[dict[str, object]] = []
    primary_raw = dict(tool_calls[0])
    primary_id = str(primary_raw.get("id") or "call_0")
    primary_name = str(primary_raw.get("name") or RUN_TOOL_NAME)
    raw_input = primary_raw.get("input")
    if raw_input is None and "arguments" in primary_raw:
        raw_input = primary_raw.get("arguments")

    primary_norm = normalize_run_tool_call(
        raw_input if isinstance(raw_input, (dict, str)) else None,
        session=session,
    )
    primary_entry: dict[str, object] = {
        "id": primary_id,
        "name": primary_name,
        "input": dict(primary_norm["input"]),
    }
    normalized_calls.append(primary_entry)

    rejected_calls: list[dict[str, object]] = []
    synthetic_results: list[dict[str, object]] = []
    for idx, extra in enumerate(tool_calls[1:], 1):
        extra_d = dict(extra)
        extra_id = str(extra_d.get("id") or f"call_{idx}")
        extra_name = str(extra_d.get("name") or RUN_TOOL_NAME)
        extra_input = extra_d.get("input")
        if extra_input is None and "arguments" in extra_d:
            extra_input = extra_d.get("arguments")
        if isinstance(extra_input, str):
            try:
                parsed_extra = json.loads(extra_input)
                extra_input = parsed_extra if isinstance(parsed_extra, dict) else {"raw": extra_input}
            except ValueError:
                extra_input = {"raw": extra_input}
        elif not isinstance(extra_input, dict):
            extra_input = {}
        clean_extra = dict(extra_input)
        if _clean_fix_target_arg(clean_extra.get("fix_target")) is None:
            clean_extra.pop("fix_target", None)
        extra_entry: dict[str, object] = {
            "id": extra_id,
            "name": extra_name,
            "input": clean_extra,
        }
        normalized_calls.append(extra_entry)
        rejected_calls.append(extra_entry)
        synthetic_results.append({
            "type": "tool_result",
            "tool_use_id": extra_id,
            "content": PARALLEL_TOOL_CALL_ERROR,
            "is_error": True,
        })

    return {
        "primary_call": {**primary_norm, "id": primary_id, "name": primary_name},
        "normalized_calls": normalized_calls,
        "rejected_calls": rejected_calls,
        "synthetic_tool_results": synthetic_results,
    }


def is_root_agents_md_part(entry: dict[str, object]) -> bool:
    """Return True when a bundle_plan part is the root project AGENTS.md file."""
    kind = normalize_fragment_kind(entry.get("kind"))
    if kind != "file":
        return False
    name = str(entry.get("name") or "").strip()
    if name != "AGENTS.md":
        return False
    chain = _resolve_part_chain(entry)
    return all(seg in _ROOT_AGENTS_MD_CHAINS for seg in chain)


def classify_bundle_parts_for_api(
    plan: dict[str, object],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Partition bundle_plan['parts'] into ([system] parts, [user] parts) in delivery order.

    [system]: all kind == 'rule'/'rules' parts in exact plan order + root AGENTS.md part.
    [user]: kind == 'header' preamble + dynamic cmd, remaining file, and prompt parts.
    """
    raw_parts = [dict(p) for p in (plan.get("parts") or []) if isinstance(p, dict)]
    rule_parts: list[dict[str, object]] = []
    agents_md_part: dict[str, object] | None = None
    user_parts: list[dict[str, object]] = []

    for part in raw_parts:
        kind = normalize_fragment_kind(part.get("kind"), default="part")
        if kind in ("rule", "rules"):
            rule_parts.append(part)
        elif agents_md_part is None and is_root_agents_md_part(part):
            agents_md_part = part
        else:
            user_parts.append(part)

    system_parts = list(rule_parts)
    if agents_md_part is not None:
        system_parts.append(agents_md_part)
    return system_parts, user_parts


def _is_embedded_run_rule_part(part: dict[str, object]) -> bool:
    kind = normalize_fragment_kind(part.get("kind"))
    if kind not in ("rule", "rules"):
        return False
    ident = str(part.get("id") or part.get("name") or "").strip()
    return bool(ident and EMBEDDED_RULE_ID_RE.search(ident))


def _slice_bundle_parts_with_gaps(
    bundle_text: str,
    parts: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Extract each part's lines from <session>/0 along with any unframed section header in its leading gap."""
    lines = bundle_text.replace("\r\n", "\n").splitlines()
    n_lines = len(lines)
    sliced: list[dict[str, object]] = []
    prev_end = 0

    for part in parts:
        ls = part.get("line_start")
        le = part.get("line_end")
        if not isinstance(ls, int) or not isinstance(le, int) or ls < 1 or le < ls or le > n_lines:
            continue
        gap_lines = lines[prev_end : ls - 1]
        prefix_lines = [ln for ln in gap_lines if ln.strip()]
        had_blank_before = (prev_end == 0) or any(not ln.strip() for ln in gap_lines)
        body_lines = list(lines[ls - 1 : le])
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        sliced.append({
            "part": dict(part),
            "prefix_lines": prefix_lines,
            "body_lines": body_lines,
            "had_blank_before": had_blank_before,
        })
        prev_end = le

    return sliced


def split_bundle_for_api(
    sdir: Path | None = None,
    *,
    bundle_text: str | None = None,
    bundle_plan: dict[str, object] | None = None,
) -> dict[str, object]:
    """Losslessly split <session>/0 using bundle_plan['parts'] into immutable system and initial user[0].

    Swaps the vitalio/run-block:run rule fragment once to EMBEDDED_RULE_API in system
    while keeping <session>/0 on disk intact and excluding per-session headers from system.
    """
    if bundle_text is None:
        if sdir is None:
            raise ValueError("split_bundle_for_api requires either sdir or bundle_text")
        bundle_path = sdir / "0"
        if not bundle_path.is_file():
            raise FileNotFoundError(f"session bundle not found: {bundle_path}")
        bundle_text = bundle_path.read_text(encoding="utf-8", errors="replace")

    if bundle_plan is None:
        if sdir is not None:
            bundle_plan = load_session_bundle_plan(sdir)
        if bundle_plan is None:
            _, body = parse_stdin_preamble(bundle_text)
            _, parsed_plan = parse_bundle_fragments(body, boundary=None)
            bundle_plan = reconcile_bundle_plan(parsed_plan, bundle_text)

    parts = [dict(p) for p in (bundle_plan.get("parts") or []) if isinstance(p, dict)]
    sliced = _slice_bundle_parts_with_gaps(bundle_text, parts)

    _, api_rule_text = get_embedded_api_rule()
    _, bash_rule_text = get_embedded_block_rule()
    swapped_rule = False

    rule_items: list[tuple[list[str], bool]] = []
    agents_md_lines: list[str] | None = None
    user_chunks: list[str] = []

    system_parts: list[dict[str, object]] = []
    user_parts: list[dict[str, object]] = []

    for item in sliced:
        part = item["part"]
        assert isinstance(part, dict)
        prefix_lines = list(item["prefix_lines"])
        body_lines = list(item["body_lines"])
        had_blank = bool(item["had_blank_before"])
        kind = normalize_fragment_kind(part.get("kind"), default="part")

        if kind in ("rule", "rules"):
            system_parts.append(part)
            if not swapped_rule and _is_embedded_run_rule_part(part):
                if body_lines and SECTION_HEADER_RE.match(body_lines[0].strip()):
                    prefix_lines.append(body_lines[0])
                replacement = api_rule_text.splitlines() if api_rule_text.strip() else body_lines
                full_rule_lines = [*prefix_lines, *replacement]
                swapped_rule = True
            else:
                full_rule_lines = [*prefix_lines, *body_lines]
                if not swapped_rule and bash_rule_text.strip() and api_rule_text.strip():
                    joined_rule = "\n".join(full_rule_lines)
                    if bash_rule_text in joined_rule:
                        joined_rule = joined_rule.replace(bash_rule_text, api_rule_text, 1)
                        full_rule_lines = joined_rule.splitlines()
                        swapped_rule = True
            if full_rule_lines:
                rule_items.append((full_rule_lines, had_blank))
        elif agents_md_lines is None and is_root_agents_md_part(part):
            system_parts.append(part)
            agents_md_lines = [*prefix_lines, *body_lines]
        else:
            user_parts.append(part)
            chunk_lines = [*prefix_lines, *body_lines]
            if chunk_lines:
                user_chunks.append("\n".join(chunk_lines))

    rules_pieces: list[str] = []
    for idx, (r_lines, had_blank) in enumerate(rule_items):
        r_text = "\n".join(r_lines)
        if idx == 0:
            rules_pieces.append(r_text)
        else:
            sep = "\n\n" if had_blank else "\n"
            rules_pieces.append(sep + r_text)
    rules_text = "".join(rules_pieces).strip("\n")
    agents_md_text = "\n".join(agents_md_lines).strip("\n") if agents_md_lines else ""

    system_blocks: list[dict[str, str]] = []
    if rules_text:
        system_blocks.append({"kind": "rule", "type": "text", "text": rules_text})
    if agents_md_text:
        system_blocks.append({"kind": "agents_md", "type": "text", "text": agents_md_text})

    system_text = "\n\n".join(b["text"] for b in system_blocks if b.get("text"))
    user_text = "\n\n".join(user_chunks).strip("\n")

    return {
        "system": system_text,
        "system_blocks": system_blocks,
        "rules_text": rules_text,
        "agents_md_text": agents_md_text,
        "user": user_text,
        "system_parts": system_parts,
        "user_parts": user_parts,
        "swapped_embedded_rule": swapped_rule,
    }


def _estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    return int(count_tokens(text.encode("utf-8"))["gpt"])


def _estimate_message_tokens(msg: dict[str, object]) -> int:
    content = msg.get("content")
    if isinstance(content, str):
        return _estimate_text_tokens(content)
    if isinstance(content, list):
        total = 0
        for item in content:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    total += _estimate_text_tokens(str(item["text"]))
                elif isinstance(item.get("content"), str):
                    total += _estimate_text_tokens(str(item["content"]))
                elif isinstance(item.get("input"), dict):
                    total += _estimate_text_tokens(json.dumps(item["input"], ensure_ascii=False))
        return total
    tool_results = msg.get("tool_results")
    if isinstance(tool_results, list):
        return sum(
            _estimate_text_tokens(str(tr.get("content") or ""))
            for tr in tool_results
            if isinstance(tr, dict)
        )
    tool_calls = msg.get("tool_calls")
    total_tc = 0
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            if isinstance(tc, dict):
                total_tc += _estimate_text_tokens(json.dumps(tc.get("input") or {}, ensure_ascii=False))
    return total_tc


def estimate_chat_tokens(chat_data: dict[str, object]) -> int:
    """Estimate total tokens across system + messages in chat_data."""
    total = _estimate_text_tokens(str(chat_data.get("system") or ""))
    messages = chat_data.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                total += _estimate_message_tokens(msg)
    return total


def normalize_usage_dict(
    raw_usage: dict[str, object] | None,
    *,
    response_at: str | None = None,
) -> dict[str, object]:
    """Normalize provider token usage fields into the canonical 6-key usage dictionary."""
    u = dict(raw_usage or {})
    prompt_details = u.get("prompt_tokens_details")
    details_cached = (
        prompt_details.get("cached_tokens")
        if isinstance(prompt_details, dict)
        else None
    )
    input_tok = int(u.get("input_tokens") or u.get("prompt_tokens") or 0)
    output_tok = int(u.get("output_tokens") or u.get("completion_tokens") or 0)
    cache_read_raw = u.get("cache_read_input_tokens")
    cached_raw = (
        u.get("cached_tokens")
        if u.get("cached_tokens") is not None
        else (details_cached if details_cached is not None else u.get("prompt_cache_hit_tokens"))
    )
    cache_read = int(cache_read_raw if cache_read_raw is not None else (cached_raw or 0))
    cache_creation = int(u.get("cache_creation_input_tokens") or 0)
    cached_tok = int(cached_raw if cached_raw is not None else cache_read)
    ts = str(response_at or u.get("response_at") or _utc_now_iso())
    return {
        "input_tokens": max(0, input_tok),
        "output_tokens": max(0, output_tok),
        "cache_read_input_tokens": max(0, cache_read),
        "cache_creation_input_tokens": max(0, cache_creation),
        "cached_tokens": max(0, cached_tok),
        "response_at": ts,
    }


def _empty_usage_totals() -> dict[str, object]:
    return {
        "turns": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cached_tokens": 0,
        "response_at": None,
    }


def _accumulate_usage(
    totals: dict[str, object] | None,
    turn_usage: dict[str, object],
) -> dict[str, object]:
    acc = dict(totals) if isinstance(totals, dict) else _empty_usage_totals()
    norm = normalize_usage_dict(turn_usage)
    acc["turns"] = int(acc.get("turns") or 0) + 1
    for key in _USAGE_COUNTER_KEYS:
        acc[key] = int(acc.get(key) or 0) + int(norm.get(key) or 0)
    acc["last_input_tokens"] = int(norm["input_tokens"])
    acc["last_output_tokens"] = int(norm["output_tokens"])
    acc["response_at"] = norm["response_at"]
    return acc


def chat_file_path(sdir: Path) -> Path:
    return sdir / "chat.json"


def read_session_chat(sdir: Path | None) -> dict[str, object]:
    if sdir is None:
        return {}
    cpath = chat_file_path(sdir)
    if not cpath.is_file():
        return {}
    try:
        data = json.loads(cpath.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_session_chat(sdir: Path, chat_data: dict[str, object]) -> Path:
    cpath = chat_file_path(sdir)
    sdir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(chat_data, indent=2, ensure_ascii=False) + "\n"
    write_private(cpath, payload, overwrite=True)
    return cpath


def init_session_chat(
    sdir: Path,
    *,
    profile: dict[str, object] | None = None,
    force: bool = False,
) -> dict[str, object]:
    """Initialize <session>/chat.json once from <session>/0 and bundle_plan.

    Swaps vitalio/run-block:run to EMBEDDED_RULE_API once on creation and never
    re-splits or mutates system / user[0] on subsequent calls unless force=True.
    """
    existing = read_session_chat(sdir)
    if existing and not force and isinstance(existing.get("messages"), list) and existing.get("messages"):
        return existing

    ensure_session_bundle(sdir)
    split = split_bundle_for_api(sdir)
    chat_data: dict[str, object] = {
        "version": 1,
        "session": sdir.name,
        "created_at": _utc_now_iso(),
        "system": split["system"],
        "system_blocks": split["system_blocks"],
        "messages": [
            {
                "role": "user",
                "content": split["user"],
            }
        ],
        "usage": _empty_usage_totals(),
    }
    if isinstance(profile, dict):
        if profile.get("name"):
            chat_data["profile"] = str(profile["name"])
        if profile.get("provider"):
            chat_data["provider"] = str(profile["provider"])
        if profile.get("model"):
            chat_data["model"] = str(profile["model"])
    write_session_chat(sdir, chat_data)
    return chat_data


def ensure_session_chat(
    sdir: Path,
    *,
    profile: dict[str, object] | None = None,
) -> dict[str, object]:
    return init_session_chat(sdir, profile=profile, force=False)


def record_step_usage(step_dir: Path, usage: dict[str, object]) -> dict[str, object]:
    """Persist exact provider turn usage in <session>/<step>/meta.json."""
    norm = normalize_usage_dict(usage)
    step_dir.mkdir(parents=True, exist_ok=True)
    meta_file = step_dir / "meta.json"
    data = read_step_meta(step_dir)
    data["usage"] = norm
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    write_private(meta_file, payload, overwrite=True)
    return norm


def record_session_usage(session_dir: Path, usage: dict[str, object]) -> dict[str, object]:
    """Accumulate exact provider turn usage into <session>/meta.json ('usage' and 'stats')."""
    norm = normalize_usage_dict(usage)
    meta = read_session_meta(session_dir)
    prev_usage = meta.get("usage") if isinstance(meta.get("usage"), dict) else None
    acc_usage = _accumulate_usage(prev_usage, norm)
    stats = _session_stats(meta)
    stats["api_turns"] = int(acc_usage["turns"])
    for key in _USAGE_COUNTER_KEYS:
        stats[key] = int(acc_usage[key])
    stats["response_at"] = norm["response_at"]
    update_session_meta(session_dir, usage=acc_usage, stats=stats)
    return acc_usage


def record_turn_usage(
    sdir: Path,
    usage: dict[str, object],
    *,
    step: str | None = None,
    chat_data: dict[str, object] | None = None,
) -> dict[str, object]:
    """Persist provider turn usage across <session>/chat.json, <session>/<step>/meta.json, and <session>/meta.json."""
    norm = normalize_usage_dict(usage)
    if chat_data is None:
        chat_data = ensure_session_chat(sdir)
    chat_data["usage"] = _accumulate_usage(
        chat_data.get("usage") if isinstance(chat_data.get("usage"), dict) else None,
        norm,
    )
    write_session_chat(sdir, chat_data)
    if step:
        record_step_usage(_step_dir(sdir, step), norm)
    record_session_usage(sdir, norm)
    return norm


def _compact_tool_result_text(content: str) -> str:
    lines = content.replace("\r\n", "\n").splitlines()
    if len(lines) <= 4 and len(content) <= 240:
        return content
    first = lines[0] if lines else ""
    last = next((ln for ln in reversed(lines) if ln.strip()), "")
    has_start = first.startswith("[") and "] START" in first
    has_end = last.startswith("[") and "] END" in last
    omitted_lines = max(1, len(lines) - (1 if has_start else 0) - (1 if has_end else 0))
    marker = f"[... compacted {omitted_lines} lines ({len(content)} chars) of step output ...]"
    out_lines: list[str] = []
    if has_start:
        out_lines.append(first)
    out_lines.append(marker)
    if has_end and last != first:
        out_lines.append(last)
    return "\n".join(out_lines) + "\n"


def _effective_compact_threshold(compact_tokens: int | None = None) -> int:
    if compact_tokens is not None:
        return max(0, int(compact_tokens))
    try:
        return max(0, int(get_setting("compact_tokens")[0]))
    except (KeyError, TypeError, ValueError):
        return 120000


def _reported_prompt_tokens(chat_data: dict[str, object]) -> int:
    messages = chat_data.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if isinstance(msg, dict) and isinstance(msg.get("usage"), dict):
                u = msg["usage"]
                inp = int(u.get("input_tokens") or 0)
                c_read = int(u.get("cache_read_input_tokens") or 0)
                c_create = int(u.get("cache_creation_input_tokens") or 0)
                return max(inp, inp + c_read + c_create)
    usage = chat_data.get("usage")
    if isinstance(usage, dict):
        return int(usage.get("last_input_tokens") or 0)
    return 0


def compact_chat_history(
    chat_data: dict[str, object],
    *,
    compact_tokens: int | None = None,
    current_input_tokens: int | None = None,
    keep_recent_results: int = 1,
) -> bool:
    """Compact older intermediate tool_result payloads in a single batch when input tokens exceed RUN_BLOCK_COMPACT_TOKENS."""
    threshold = _effective_compact_threshold(compact_tokens)
    if threshold <= 0:
        return False

    estimated = estimate_chat_tokens(chat_data)
    reported = int(current_input_tokens) if current_input_tokens is not None else _reported_prompt_tokens(chat_data)
    active_tokens = max(estimated, reported)
    if active_tokens <= threshold:
        return False

    messages = chat_data.get("messages")
    if not isinstance(messages, list):
        return False

    result_turn_indices = [
        idx
        for idx, msg in enumerate(messages)
        if idx > 0
        and isinstance(msg, dict)
        and msg.get("role") == "user"
        and isinstance(msg.get("tool_results"), list)
        and msg.get("tool_results")
    ]
    keep_n = max(0, int(keep_recent_results))
    eligible_indices = (
        result_turn_indices[:-keep_n]
        if keep_n > 0 and len(result_turn_indices) > keep_n
        else (result_turn_indices if keep_n == 0 else [])
    )
    if not eligible_indices:
        return False

    compacted_any = False
    for idx in eligible_indices:
        msg = messages[idx]
        if not isinstance(msg, dict):
            continue
        t_results = msg.get("tool_results")
        if not isinstance(t_results, list):
            continue
        for tr in t_results:
            if not isinstance(tr, dict) or tr.get("compacted"):
                continue
            raw_content = str(tr.get("content") or "")
            new_content = _compact_tool_result_text(raw_content)
            if new_content != raw_content:
                tr["original_chars"] = len(raw_content)
                tr["original_lines"] = len(raw_content.splitlines())
                tr["content"] = new_content
                tr["compacted"] = True
                compacted_any = True

    if compacted_any:
        chat_data["compactions"] = int(chat_data.get("compactions") or 0) + 1
    return compacted_any


def append_assistant_turn(
    sdir: Path,
    response: dict[str, object],
    *,
    step: str | None = None,
    compact_tokens: int | None = None,
) -> dict[str, object]:
    """Append an assistant turn (and any synthetic multi-call error tool_results) to <session>/chat.json."""
    chat_data = ensure_session_chat(sdir)
    messages = chat_data.setdefault("messages", [])
    assert isinstance(messages, list)

    raw_tool_calls = response.get("tool_calls")
    tc_list = [tc for tc in raw_tool_calls if isinstance(tc, dict)] if isinstance(raw_tool_calls, list) else []
    processed = process_assistant_tool_calls(tc_list, session=sdir.name)

    usage = normalize_usage_dict(
        response.get("usage") if isinstance(response.get("usage"), dict) else None,
        response_at=str(response.get("response_at") or "") or None,
    )
    assistant_msg: dict[str, object] = {
        "role": "assistant",
        "content": str(response.get("content") or ""),
        "usage": usage,
    }
    if response.get("thinking"):
        assistant_msg["thinking"] = response["thinking"]
    if processed["normalized_calls"]:
        assistant_msg["tool_calls"] = processed["normalized_calls"]
    if step:
        assistant_msg["step"] = str(step)
    if response.get("stop_reason"):
        assistant_msg["stop_reason"] = str(response["stop_reason"])
    messages.append(assistant_msg)

    synthetic_results = list(processed["synthetic_tool_results"])
    if synthetic_results:
        messages.append({
            "role": "user",
            "tool_results": synthetic_results,
            "pending_primary_tool_use_id": (
                processed["primary_call"]["id"]
                if isinstance(processed.get("primary_call"), dict)
                else None
            ),
        })

    prompt_tok = int(usage["input_tokens"]) + int(usage["cache_read_input_tokens"]) + int(usage["cache_creation_input_tokens"])
    compact_chat_history(chat_data, compact_tokens=compact_tokens, current_input_tokens=prompt_tok)
    record_turn_usage(sdir, usage, step=step, chat_data=chat_data)
    return {
        "chat": chat_data,
        "assistant_message": assistant_msg,
        "primary_call": processed["primary_call"],
        "rejected_calls": processed["rejected_calls"],
        "synthetic_tool_results": synthetic_results,
        "usage": usage,
    }


def append_tool_result_turn(
    sdir: Path,
    *,
    tool_use_id: str,
    content: str,
    step: str | None = None,
    is_error: bool = False,
    compact_tokens: int | None = None,
) -> dict[str, object]:
    """Append a completed step tool_result turn to <session>/chat.json (merging with pending multi-call error results if present)."""
    chat_data = ensure_session_chat(sdir)
    messages = chat_data.setdefault("messages", [])
    assert isinstance(messages, list)

    entry: dict[str, object] = {
        "type": "tool_result",
        "tool_use_id": str(tool_use_id),
        "content": str(content),
    }
    if step:
        entry["step"] = str(step)
    if is_error:
        entry["is_error"] = True

    if (
        messages
        and isinstance(messages[-1], dict)
        and messages[-1].get("role") == "user"
        and isinstance(messages[-1].get("tool_results"), list)
        and messages[-1].get("pending_primary_tool_use_id") == str(tool_use_id)
    ):
        existing_results = list(messages[-1]["tool_results"])
        messages[-1]["tool_results"] = [entry, *existing_results]
        messages[-1].pop("pending_primary_tool_use_id", None)
    else:
        messages.append({
            "role": "user",
            "tool_results": [entry],
        })

    compact_chat_history(chat_data, compact_tokens=compact_tokens)
    write_session_chat(sdir, chat_data)
    return chat_data


def append_user_reply_turn(
    sdir: Path,
    content: str,
    *,
    compact_tokens: int | None = None,
) -> dict[str, object]:
    """Append a plain-text user reply turn to <session>/chat.json."""
    chat_data = ensure_session_chat(sdir)
    messages = chat_data.setdefault("messages", [])
    assert isinstance(messages, list)
    messages.append({
        "role": "user",
        "content": str(content),
    })
    compact_chat_history(chat_data, compact_tokens=compact_tokens)
    write_session_chat(sdir, chat_data)
    return chat_data


def _resolve_effective_cache_mode(
    profile: dict[str, object] | None = None,
    override: str | None = None,
) -> str:
    if override is not None:
        norm = _norm_cache(override)
        if norm is not None:
            return norm
    env_val, env_src = get_setting("cache")
    if env_src == "env":
        return env_val
    if isinstance(profile, dict) and isinstance(profile.get("cache"), str):
        prof_norm = _norm_cache(str(profile["cache"]))
        if prof_norm is not None:
            return prof_norm
    return env_val


def build_anthropic_request(
    chat_data: dict[str, object],
    profile: dict[str, object],
    *,
    cache_mode: str | None = None,
) -> dict[str, object]:
    """Build an Anthropic /v1/messages request payload with ephemeral cache_control breakpoints."""
    mode = _resolve_effective_cache_mode(profile, override=cache_mode)
    breakpoints_used = 0

    raw_sys_blocks = chat_data.get("system_blocks")
    sys_blocks_in: list[dict[str, object]] = []
    if isinstance(raw_sys_blocks, list) and raw_sys_blocks:
        for b in raw_sys_blocks:
            if isinstance(b, dict) and str(b.get("text") or "").strip():
                sys_blocks_in.append({"type": "text", "text": str(b["text"])})
    elif str(chat_data.get("system") or "").strip():
        sys_blocks_in.append({"type": "text", "text": str(chat_data["system"])})

    anthropic_system: list[dict[str, object]] = []
    for blk in sys_blocks_in:
        blk_copy = dict(blk)
        if (
            mode in ("auto", "system")
            and breakpoints_used < MAX_ANTHROPIC_CACHE_BREAKPOINTS
            and _estimate_text_tokens(str(blk_copy.get("text") or "")) >= MIN_CACHE_CONTROL_TOKENS
        ):
            blk_copy["cache_control"] = dict(CACHE_EPHEMERAL)
            breakpoints_used += 1
        anthropic_system.append(blk_copy)

    raw_messages = [m for m in (chat_data.get("messages") or []) if isinstance(m, dict)]
    anthropic_messages: list[dict[str, object]] = []
    user_msg_indices: list[int] = []

    for msg in raw_messages:
        role = str(msg.get("role") or "user")
        if role == "assistant":
            blocks: list[dict[str, object]] = []
            thinking = msg.get("thinking")
            if isinstance(thinking, dict) and thinking.get("thinking"):
                tb: dict[str, object] = {
                    "type": "thinking",
                    "thinking": str(thinking["thinking"]),
                }
                if thinking.get("signature"):
                    tb["signature"] = str(thinking["signature"])
                blocks.append(tb)
            text_val = str(msg.get("content") or "")
            if text_val:
                blocks.append({"type": "text", "text": text_val})
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict):
                    tc_input = dict(tc.get("input") or {}) if isinstance(tc.get("input"), dict) else {}
                    if _clean_fix_target_arg(tc_input.get("fix_target")) is None:
                        tc_input.pop("fix_target", None)
                    blocks.append({
                        "type": "tool_use",
                        "id": str(tc.get("id") or "call_0"),
                        "name": str(tc.get("name") or RUN_TOOL_NAME),
                        "input": tc_input,
                    })
            if not blocks:
                blocks.append({"type": "text", "text": ""})
            anthropic_messages.append({"role": "assistant", "content": blocks})
        else:
            u_blocks: list[dict[str, object]] = []
            t_results = msg.get("tool_results")
            if isinstance(t_results, list) and t_results:
                for tr in t_results:
                    if isinstance(tr, dict):
                        tr_blk: dict[str, object] = {
                            "type": "tool_result",
                            "tool_use_id": str(tr.get("tool_use_id") or "call_0"),
                            "content": str(tr.get("content") or ""),
                        }
                        if tr.get("is_error"):
                            tr_blk["is_error"] = True
                        u_blocks.append(tr_blk)
            elif isinstance(msg.get("content"), list):
                for item in msg["content"]:
                    if isinstance(item, dict):
                        u_blocks.append(dict(item))
            else:
                u_blocks.append({"type": "text", "text": str(msg.get("content") or "")})
            user_msg_indices.append(len(anthropic_messages))
            anthropic_messages.append({"role": "user", "content": u_blocks})

    if mode == "auto" and user_msg_indices:
        candidate_user_indices: list[int] = [user_msg_indices[0]]
        if len(user_msg_indices) > 1 and user_msg_indices[-1] != user_msg_indices[0]:
            candidate_user_indices.append(user_msg_indices[-1])
        for u_idx in candidate_user_indices:
            if breakpoints_used >= MAX_ANTHROPIC_CACHE_BREAKPOINTS:
                break
            u_msg = anthropic_messages[u_idx]
            u_content = u_msg.get("content")
            if (
                isinstance(u_content, list)
                and u_content
                and _estimate_message_tokens(u_msg) >= MIN_CACHE_CONTROL_TOKENS
            ):
                last_blk = dict(u_content[-1])
                last_blk["cache_control"] = dict(CACHE_EPHEMERAL)
                u_content[-1] = last_blk
                breakpoints_used += 1

    max_tokens = int(profile.get("max_tokens") or DEFAULT_MAX_OUTPUT_TOKENS)
    payload: dict[str, object] = {
        "model": str(profile.get("model") or ""),
        "max_tokens": max_tokens,
        "stream": True,
        "system": anthropic_system,
        "tools": [build_run_tool_schema("anthropic")],
        "tool_choice": {
            "type": "auto",
            "disable_parallel_tool_use": True,
        },
        "messages": anthropic_messages,
    }
    thinking_cfg = profile.get("thinking")
    if isinstance(thinking_cfg, dict):
        payload["thinking"] = dict(thinking_cfg)
    elif isinstance(thinking_cfg, int) and not isinstance(thinking_cfg, bool) and thinking_cfg > 0:
        payload["thinking"] = {"type": "enabled", "budget_tokens": int(thinking_cfg)}
    return payload


def build_openai_request(
    chat_data: dict[str, object],
    profile: dict[str, object],
) -> dict[str, object]:
    """Build an OpenAI-compatible /v1/chat/completions request payload."""
    oai_messages: list[dict[str, object]] = []
    system_text = str(chat_data.get("system") or "")
    if system_text.strip():
        oai_messages.append({"role": "system", "content": system_text})

    for msg in chat_data.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role") or "user")
        if role == "assistant":
            a_msg: dict[str, object] = {
                "role": "assistant",
                "content": str(msg.get("content") or ""),
            }
            t_calls = msg.get("tool_calls")
            if isinstance(t_calls, list) and t_calls:
                oai_tcs: list[dict[str, object]] = []
                for idx, tc in enumerate(t_calls):
                    if not isinstance(tc, dict):
                        continue
                    tc_input = dict(tc.get("input") or {}) if isinstance(tc.get("input"), dict) else {}
                    if _clean_fix_target_arg(tc_input.get("fix_target")) is None:
                        tc_input.pop("fix_target", None)
                    oai_tcs.append({
                        "id": str(tc.get("id") or f"call_{idx}"),
                        "type": "function",
                        "function": {
                            "name": str(tc.get("name") or RUN_TOOL_NAME),
                            "arguments": json.dumps(tc_input, ensure_ascii=False),
                        },
                    })
                if oai_tcs:
                    a_msg["tool_calls"] = oai_tcs
            oai_messages.append(a_msg)
        else:
            t_results = msg.get("tool_results")
            if isinstance(t_results, list) and t_results:
                for tr in t_results:
                    if isinstance(tr, dict):
                        oai_messages.append({
                            "role": "tool",
                            "tool_call_id": str(tr.get("tool_use_id") or "call_0"),
                            "content": str(tr.get("content") or ""),
                        })
            else:
                oai_messages.append({
                    "role": "user",
                    "content": str(msg.get("content") or ""),
                })

    payload: dict[str, object] = {
        "model": str(profile.get("model") or ""),
        "messages": oai_messages,
        "tools": [build_run_tool_schema("openai")],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if profile.get("max_tokens") is not None:
        payload["max_tokens"] = int(profile["max_tokens"])
    return payload


def resolve_provider_endpoint(profile: dict[str, object]) -> str:
    """Resolve the full HTTP endpoint URL for Anthropic Messages or OpenAI-compatible Chat Completions."""
    provider = str(profile.get("provider") or "openai").strip().lower()
    raw_base = str(profile.get("base_url") or DEFAULT_PROVIDER_BASE_URLS.get(provider) or "").strip().rstrip("/")
    if provider == "anthropic":
        base = raw_base or DEFAULT_ANTHROPIC_BASE_URL
        if base.endswith("/v1/messages") or base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return f"{base}/messages"
        return f"{base}/v1/messages"
    base = raw_base or DEFAULT_PROVIDER_BASE_URLS.get(provider, "http://localhost:11434/v1")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or base.endswith("/openai"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def iter_sse_events(stream: object) -> list[tuple[str, str]]:
    """Parse an HTTP SSE stream (yielding bytes or str lines) into (event_type, data_payload) tuples."""
    events: list[tuple[str, str]] = []
    event_name = "message"
    data_lines: list[str] = []

    if isinstance(stream, (bytes, bytearray)):
        raw_lines = stream.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n")
    elif isinstance(stream, str):
        raw_lines = stream.replace("\r\n", "\n").split("\n")
    else:
        raw_lines = []
        for raw_ln in stream:  # type: ignore[union-attr]
            text_ln = (
                raw_ln.decode("utf-8", errors="replace")
                if isinstance(raw_ln, (bytes, bytearray))
                else str(raw_ln)
            )
            norm_ln = text_ln.replace("\r\n", "\n")
            if "\n" in norm_ln:
                parts_ln = norm_ln.split("\n")
                if parts_ln and parts_ln[-1] == "":
                    parts_ln.pop()
                raw_lines.extend(parts_ln)
            else:
                raw_lines.append(norm_ln)

    for raw_line in raw_lines:
        line = raw_line.rstrip("\r\n")
        if not line:
            if data_lines:
                events.append((event_name, "\n".join(data_lines)))
                event_name = "message"
                data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event_name = value.strip() or "message"
        elif field == "data":
            data_lines.append(value)

    if data_lines:
        events.append((event_name, "\n".join(data_lines)))
    return events


def _open_sse_request(
    url: str,
    headers: dict[str, str],
    payload: dict[str, object],
    *,
    provider: str,
    timeout: float = 300.0,
    urlopen: object = None,
) -> list[tuple[str, str]]:
    import http.client
    import urllib.error
    import urllib.request

    body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    opener = urlopen if callable(urlopen) else urllib.request.urlopen
    try:
        resp_ctx = opener(req, timeout=timeout)
        with contextlib.closing(resp_ctx) if not hasattr(resp_ctx, "__enter__") else resp_ctx as resp:
            return iter_sse_events(resp)
    except urllib.error.HTTPError as exc:
        err_body = ""
        try:
            if exc.fp is not None:
                err_body = exc.fp.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise AgentAPIError(
            f"{provider} API error (HTTP {exc.code}): {err_body or exc.reason}",
            provider=provider,
            status_code=exc.code,
            body=err_body,
        ) from None
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, OSError) as exc:
        raise AgentAPIError(
            f"{provider} request failed: {exc}",
            provider=provider,
        ) from None


def stream_anthropic_messages(
    chat_data: dict[str, object],
    profile: dict[str, object],
    *,
    api_key: str | None = None,
    session: str | None = None,
    cache_mode: str | None = None,
    on_text: object = None,
    timeout: float = 300.0,
    urlopen: object = None,
) -> dict[str, object]:
    """Send a streaming Anthropic Messages API (/v1/messages) request and parse SSE events."""
    key = api_key if api_key is not None else resolve_api_key(profile)
    url = resolve_provider_endpoint({**profile, "provider": "anthropic"})
    payload = build_anthropic_request(chat_data, profile, cache_mode=cache_mode)
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "anthropic-version": ANTHROPIC_API_VERSION,
    }
    if key:
        headers["x-api-key"] = key

    events = _open_sse_request(
        url,
        headers,
        payload,
        provider="anthropic",
        timeout=timeout,
        urlopen=urlopen,
    )

    text_chunks: list[str] = []
    thinking_chunks: list[str] = []
    thinking_signature = ""
    blocks_by_index: dict[int, dict[str, object]] = {}
    tool_order: list[int] = []
    raw_usage: dict[str, object] = {}
    stop_reason: str | None = None

    for event_name, data_str in events:
        if not data_str or data_str.strip() == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        ev_type = str(data.get("type") or event_name)
        if ev_type == "error":
            err_obj = data.get("error")
            err_msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj or data)
            raise AgentAPIError(f"anthropic stream error: {err_msg}", provider="anthropic", body=data_str)
        if ev_type == "message_start":
            msg_obj = data.get("message")
            if isinstance(msg_obj, dict) and isinstance(msg_obj.get("usage"), dict):
                raw_usage.update(msg_obj["usage"])
        elif ev_type == "content_block_start":
            idx = int(data.get("index") or 0)
            cb = data.get("content_block")
            if isinstance(cb, dict):
                cb_type = str(cb.get("type") or "")
                entry: dict[str, object] = {"type": cb_type}
                if cb_type == "text":
                    init_txt = str(cb.get("text") or "")
                    if init_txt:
                        text_chunks.append(init_txt)
                        if callable(on_text):
                            on_text(init_txt)
                elif cb_type == "thinking":
                    init_th = str(cb.get("thinking") or "")
                    if init_th:
                        thinking_chunks.append(init_th)
                    if cb.get("signature"):
                        thinking_signature = str(cb["signature"])
                elif cb_type == "tool_use":
                    entry["id"] = str(cb.get("id") or f"toolu_{idx}")
                    entry["name"] = str(cb.get("name") or RUN_TOOL_NAME)
                    init_input = cb.get("input")
                    entry["initial_input"] = dict(init_input) if isinstance(init_input, dict) and init_input else None
                    entry["json_parts"] = []
                    tool_order.append(idx)
                blocks_by_index[idx] = entry
        elif ev_type == "content_block_delta":
            idx = int(data.get("index") or 0)
            delta = data.get("delta")
            if isinstance(delta, dict):
                d_type = str(delta.get("type") or "")
                if d_type == "text_delta":
                    txt = str(delta.get("text") or "")
                    if txt:
                        text_chunks.append(txt)
                        if callable(on_text):
                            on_text(txt)
                elif d_type == "thinking_delta":
                    th = str(delta.get("thinking") or "")
                    if th:
                        thinking_chunks.append(th)
                elif d_type == "signature_delta":
                    sig = str(delta.get("signature") or "")
                    if sig:
                        thinking_signature += sig
                elif d_type == "input_json_delta":
                    part_json = str(delta.get("partial_json") or "")
                    blk = blocks_by_index.get(idx)
                    if isinstance(blk, dict) and isinstance(blk.get("json_parts"), list):
                        blk["json_parts"].append(part_json)
        elif ev_type == "message_delta":
            delta = data.get("delta")
            if isinstance(delta, dict) and delta.get("stop_reason"):
                stop_reason = str(delta["stop_reason"])
            if isinstance(data.get("usage"), dict):
                raw_usage.update(data["usage"])

    raw_tool_calls: list[dict[str, object]] = []
    for idx in tool_order:
        blk = blocks_by_index.get(idx)
        if not isinstance(blk, dict):
            continue
        json_parts = blk.get("json_parts")
        joined_json = "".join(json_parts).strip() if isinstance(json_parts, list) else ""
        if joined_json:
            try:
                parsed_input = json.loads(joined_json)
            except ValueError as exc:
                raise AgentAPIError(f"anthropic invalid tool_use JSON: {exc}", provider="anthropic", body=joined_json) from None
        elif isinstance(blk.get("initial_input"), dict):
            parsed_input = dict(blk["initial_input"])
        else:
            parsed_input = {}
        raw_tool_calls.append({
            "id": str(blk.get("id") or f"toolu_{idx}"),
            "name": str(blk.get("name") or RUN_TOOL_NAME),
            "input": parsed_input,
        })

    processed = process_assistant_tool_calls(raw_tool_calls, session=session)
    usage = normalize_usage_dict(raw_usage)
    result: dict[str, object] = {
        "provider": "anthropic",
        "model": str(profile.get("model") or ""),
        "content": "".join(text_chunks),
        "tool_calls": processed["normalized_calls"],
        "primary_call": processed["primary_call"],
        "rejected_calls": processed["rejected_calls"],
        "synthetic_tool_results": processed["synthetic_tool_results"],
        "stop_reason": stop_reason,
        "usage": usage,
        "response_at": usage["response_at"],
        "request_payload": payload,
    }
    if thinking_chunks:
        th_obj: dict[str, str] = {"thinking": "".join(thinking_chunks)}
        if thinking_signature:
            th_obj["signature"] = thinking_signature
        result["thinking"] = th_obj
    return result


def stream_openai_chat(
    chat_data: dict[str, object],
    profile: dict[str, object],
    *,
    api_key: str | None = None,
    session: str | None = None,
    on_text: object = None,
    timeout: float = 300.0,
    urlopen: object = None,
) -> dict[str, object]:
    """Send a streaming OpenAI-compatible Chat Completions (/v1/chat/completions) request and parse SSE events."""
    provider = str(profile.get("provider") or "openai").strip().lower()
    key = api_key if api_key is not None else resolve_api_key(profile)
    url = resolve_provider_endpoint(profile)
    payload = build_openai_request(chat_data, profile)
    headers: dict[str, str] = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"

    events = _open_sse_request(
        url,
        headers,
        payload,
        provider=provider,
        timeout=timeout,
        urlopen=urlopen,
    )

    text_chunks: list[str] = []
    reasoning_chunks: list[str] = []
    tool_builders: dict[int, dict[str, object]] = {}
    raw_usage: dict[str, object] = {}
    finish_reason: str | None = None

    for _, data_str in events:
        stripped = data_str.strip()
        if not stripped or stripped == "[DONE]":
            continue
        try:
            chunk = json.loads(stripped)
        except ValueError:
            continue
        if not isinstance(chunk, dict):
            continue
        if isinstance(chunk.get("error"), dict):
            err_msg = chunk["error"].get("message") or str(chunk["error"])
            raise AgentAPIError(f"{provider} stream error: {err_msg}", provider=provider, body=stripped)
        if isinstance(chunk.get("usage"), dict):
            raw_usage.update(chunk["usage"])
        choices = chunk.get("choices")
        if not isinstance(choices, list):
            continue
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            if not isinstance(delta, dict):
                continue
            content_piece = delta.get("content")
            if isinstance(content_piece, str) and content_piece:
                text_chunks.append(content_piece)
                if callable(on_text):
                    on_text(content_piece)
            reasoning_piece = delta.get("reasoning_content") or delta.get("reasoning")
            if isinstance(reasoning_piece, str) and reasoning_piece:
                reasoning_chunks.append(reasoning_piece)
            tc_deltas = delta.get("tool_calls")
            if isinstance(tc_deltas, list):
                for pos, tc_delta in enumerate(tc_deltas):
                    if not isinstance(tc_delta, dict):
                        continue
                    tc_idx = int(tc_delta.get("index") if tc_delta.get("index") is not None else pos)
                    builder = tool_builders.setdefault(
                        tc_idx,
                        {"id": "", "name": "", "arg_parts": []},
                    )
                    if tc_delta.get("id"):
                        builder["id"] = str(tc_delta["id"])
                    fn = tc_delta.get("function")
                    if isinstance(fn, dict):
                        if fn.get("name"):
                            builder["name"] = str(fn["name"])
                        if isinstance(fn.get("arguments"), str):
                            arg_parts = builder["arg_parts"]
                            assert isinstance(arg_parts, list)
                            arg_parts.append(fn["arguments"])

    raw_tool_calls: list[dict[str, object]] = []
    for idx in sorted(tool_builders):
        b = tool_builders[idx]
        arg_parts = b.get("arg_parts")
        raw_args = "".join(arg_parts).strip() if isinstance(arg_parts, list) else ""
        if raw_args:
            try:
                parsed_args = json.loads(raw_args)
            except ValueError as exc:
                raise AgentAPIError(f"{provider} invalid tool_calls arguments JSON: {exc}", provider=provider, body=raw_args) from None
        else:
            parsed_args = {}
        raw_tool_calls.append({
            "id": str(b.get("id") or f"call_{idx}"),
            "name": str(b.get("name") or RUN_TOOL_NAME),
            "input": parsed_args,
        })

    processed = process_assistant_tool_calls(raw_tool_calls, session=session)
    usage = normalize_usage_dict(raw_usage)
    result: dict[str, object] = {
        "provider": provider,
        "model": str(profile.get("model") or ""),
        "content": "".join(text_chunks),
        "tool_calls": processed["normalized_calls"],
        "primary_call": processed["primary_call"],
        "rejected_calls": processed["rejected_calls"],
        "synthetic_tool_results": processed["synthetic_tool_results"],
        "stop_reason": finish_reason,
        "usage": usage,
        "response_at": usage["response_at"],
        "request_payload": payload,
    }
    if reasoning_chunks:
        result["thinking"] = {"thinking": "".join(reasoning_chunks)}
    return result


def resolve_session_profile(
    sdir: Path | None = None,
    *,
    override: str | None = None,
) -> dict[str, object] | None:
    """Resolve the model profile for a session (CLI override > persisted meta.json 'profile' > role/default)."""
    role = parse_bundle_headers(sdir).get("role") if sdir is not None else None
    if override is not None and override.strip():
        return resolve_profile(role, override=override)
    persisted = read_session_meta(sdir).get("profile") if sdir is not None else None
    if isinstance(persisted, str) and persisted.strip():
        return resolve_profile(role, override=persisted.strip())
    return resolve_profile(role)


def request_model_turn(
    sdir: Path,
    *,
    profile: dict[str, object] | None = None,
    profile_override: str | None = None,
    step: str | None = None,
    cache_mode: str | None = None,
    compact_tokens: int | None = None,
    on_text: object = None,
    timeout: float = 300.0,
    urlopen: object = None,
) -> dict[str, object]:
    """Execute one streaming LLM API turn for <session>, persist chat.json and usage metadata, and return the turn."""
    active_profile = profile if isinstance(profile, dict) else resolve_session_profile(sdir, override=profile_override)
    if not isinstance(active_profile, dict):
        raise ValueError(f"no model profile configured for session {sdir.name}")

    chat_data = ensure_session_chat(sdir, profile=active_profile)
    compact_chat_history(chat_data, compact_tokens=compact_tokens)
    provider = str(active_profile.get("provider") or "openai").strip().lower()
    api_key = resolve_api_key(active_profile)

    if provider == "anthropic":
        response = stream_anthropic_messages(
            chat_data,
            active_profile,
            api_key=api_key,
            session=sdir.name,
            cache_mode=cache_mode,
            on_text=on_text,
            timeout=timeout,
            urlopen=urlopen,
        )
    else:
        response = stream_openai_chat(
            chat_data,
            active_profile,
            api_key=api_key,
            session=sdir.name,
            on_text=on_text,
            timeout=timeout,
            urlopen=urlopen,
        )

    recorded = append_assistant_turn(
        sdir,
        response,
        step=step,
        compact_tokens=compact_tokens,
    )
    return {
        **response,
        "chat": recorded["chat"],
        "assistant_message": recorded["assistant_message"],
    }
