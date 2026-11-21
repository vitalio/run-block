BUNDLE_BOUNDARY_HEADER = "bundle-boundary"
BUNDLE_EXPOSE_HEADER = "bundle-expose"
BUNDLE_HIDE_HEADER = "bundle-hide"
DEFAULT_BUNDLE_TOKEN_BUDGET = 100000
DEFAULT_FRAGMENT_MAX_TOKENS = 20000

SECTION_HEADER_RE = re.compile(r"^={5,}\s*(.+?)\s*={5,}$")
TERMINAL_BLOCK_HEADING_RE = re.compile(r"(?m)^## Terminal blocks \(")
EMBEDDED_RULE_ID_RE = re.compile(r"(?:^|:)blocks/(?:bash|pwsh)$")


def _strip_rule_description(raw_text: str) -> str:
    lines = raw_text.replace("\r\n", "\n").splitlines()
    while lines and lines[0].startswith("# Description:"):
        lines.pop(0)
    return "\n".join(lines).strip("\n")


def get_embedded_block_rule(shell_bin: str | None = None) -> tuple[str, str]:
    is_ps = _is_powershell(shell_bin)
    rule_id = "run_block:blocks/pwsh" if is_ps else "run_block:blocks/bash"
    raw = EMBEDDED_RULE_PWSH if is_ps else EMBEDDED_RULE_BASH
    placeholder = "__EMBEDDED_RULE_PWSH__" if is_ps else "__EMBEDDED_RULE_BASH__"
    if raw == placeholder:
        rel = Path("rules/blocks/pwsh.md" if is_ps else "rules/blocks/bash.md")
        src_path = Path(__file__).resolve().parent / rel
        if src_path.is_file():
            raw = _strip_rule_description(src_path.read_text(encoding="utf-8"))
        else:
            raw = ""
    else:
        raw = _strip_rule_description(raw)
    rendered = raw.replace("{cmd:run_block}", prog_name())
    return rule_id, rendered


def _has_embedded_block_rule(body_text: str, boundary: str | None = None) -> bool:
    if not body_text:
        return False
    boundary_val = (boundary or "").strip()
    if boundary_val:
        esc = re.escape(boundary_val)
        part_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:part(?:\s+(\{{.*\}}))?\s*-->\s*$")
        end_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:end\s*-->\s*$")
        in_part = False
        is_rule_part = False
        for line in body_text.replace("\r\n", "\n").splitlines():
            m = part_re.match(line)
            if m:
                in_part = True
                is_rule_part = False
                if m.group(1):
                    try:
                        meta = json.loads(m.group(1))
                    except ValueError:
                        meta = None
                    if isinstance(meta, dict):
                        kind = str(meta.get("kind") or "")
                        is_rule_part = kind in ("", "rule", "rules")
                        ident = str(meta.get("id") or meta.get("name") or "")
                        if is_rule_part and EMBEDDED_RULE_ID_RE.search(ident):
                            return True
                continue
            if end_re.match(line):
                in_part = False
                is_rule_part = False
                continue
            if (not in_part or is_rule_part) and TERMINAL_BLOCK_HEADING_RE.match(line):
                return True
        return False
    return bool(TERMINAL_BLOCK_HEADING_RE.search(body_text))


def inject_embedded_block_rule(
    raw_body: str,
    boundary: str | None = None,
    shell_bin: str | None = None,
) -> str:
    norm_body = (raw_body or "").replace("\r\n", "\n")
    boundary_val = (boundary or "").strip() or None
    if _has_embedded_block_rule(norm_body, boundary=boundary_val):
        return norm_body
    rule_id, rule_text = get_embedded_block_rule(shell_bin=shell_bin)
    if not rule_text.strip():
        return norm_body

    if boundary_val:
        part_meta = json.dumps(
            {"kind": "rule", "id": rule_id, "chain": ["run_block"]},
            ensure_ascii=False,
        )
        part_block = [
            f"<!-- bundle:{boundary_val}:part {part_meta} -->",
            *rule_text.splitlines(),
            f"<!-- bundle:{boundary_val}:end -->",
        ]
        esc = re.escape(boundary_val)
        part_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:part(?:\s+(\{{.*\}}))?\s*-->\s*$")
        end_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:end\s*-->\s*$")
        lines = norm_body.splitlines()
        in_part = False
        rules_idx: int | None = None
        first_part_idx: int | None = None
        for idx, line in enumerate(lines):
            if part_re.match(line):
                if first_part_idx is None:
                    first_part_idx = idx
                in_part = True
                continue
            if end_re.match(line):
                in_part = False
                continue
            if not in_part and rules_idx is None:
                m_sec = SECTION_HEADER_RE.match(line.strip())
                if m_sec and m_sec.group(1).strip().lower() == "rules":
                    rules_idx = idx
        if rules_idx is not None:
            after = lines[rules_idx + 1 :]
            while after and not after[0].strip():
                after.pop(0)
            merged = [*lines[: rules_idx + 1], *part_block]
            if after:
                merged.extend(["", *after])
            return "\n".join(merged)
        if first_part_idx is not None:
            before = lines[:first_part_idx]
            while before and not before[-1].strip():
                before.pop()
            after = lines[first_part_idx:]
            if before and SECTION_HEADER_RE.match(before[0].strip()):
                return "\n".join(["===== Rules =====", *part_block, "", *before, *after])
            merged: list[str] = []
            if before:
                merged.extend([*before, ""])
            merged.extend(["===== Rules =====", *part_block, "", *after])
            return "\n".join(merged)
        stripped = norm_body.strip("\n")
        if not stripped.strip():
            return "\n".join(["===== Rules =====", *part_block])
        first_nonempty = next((ln.strip() for ln in stripped.splitlines() if ln.strip()), "")
        if SECTION_HEADER_RE.match(first_nonempty):
            return "\n".join(["===== Rules =====", *part_block, "", stripped])
        return "\n".join(["===== Rules =====", *part_block, "", "===== Prompt =====", stripped])

    stripped = norm_body.strip("\n")
    if not stripped.strip():
        return f"===== Rules =====\n{rule_text}"
    lines = stripped.splitlines()
    first_idx = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    m_first = SECTION_HEADER_RE.match(lines[first_idx].strip())
    if m_first and m_first.group(1).strip().lower() == "rules":
        after = lines[first_idx + 1 :]
        while after and not after[0].strip():
            after.pop(0)
        merged = [lines[first_idx], rule_text]
        if after:
            merged.extend(["", *after])
        return "\n".join(merged)
    if m_first:
        return f"===== Rules =====\n{rule_text}\n\n{stripped}"
    return f"===== Rules =====\n{rule_text}\n\n===== Prompt =====\n{stripped}"


def normalize_prompt_text(prompt: str | list[str] | tuple[str, ...] | None) -> str:
    if prompt is None:
        return ""
    items = [prompt] if isinstance(prompt, str) else list(prompt)
    cleaned: list[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        norm = item.replace("\r\n", "\n").strip("\n")
        if norm.strip():
            cleaned.append(norm.strip())
    return "\n\n".join(cleaned)


def _append_to_unframed_prompt_tail(
    lines: list[str], start_idx: int, prompt_lines: list[str]
) -> list[str] | None:
    last_sec_idx: int | None = None
    last_sec_title = ""
    for idx in range(start_idx, len(lines)):
        m = SECTION_HEADER_RE.match(lines[idx].strip())
        if m:
            last_sec_idx = idx
            last_sec_title = m.group(1).strip().lower()
    if last_sec_idx is None or last_sec_title != "prompt":
        return None
    trimmed = list(lines)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    has_body = any(ln.strip() for ln in trimmed[last_sec_idx + 1 :])
    if has_body:
        return [*trimmed, "", *prompt_lines]
    return [*trimmed[: last_sec_idx + 1], *prompt_lines]


def inject_embedded_prompt(
    raw_body: str,
    prompt: str | list[str] | tuple[str, ...] | None = None,
    boundary: str | None = None,
) -> str:
    prompt_text = normalize_prompt_text(prompt)
    norm_body = (raw_body or "").replace("\r\n", "\n")
    if not prompt_text:
        return norm_body
    prompt_lines = prompt_text.splitlines()
    boundary_val = (boundary or "").strip() or None
    lines = norm_body.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()

    if boundary_val:
        esc = re.escape(boundary_val)
        part_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:part(?:\s+(\{{.*\}}))?\s*-->\s*$")
        end_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:end\s*-->\s*$")
        last_end_idx: int | None = None
        for idx, line in enumerate(lines):
            if end_re.match(line):
                last_end_idx = idx
        if last_end_idx is not None:
            tail_after_end = lines[last_end_idx + 1 :]
            if any(ln.strip() for ln in tail_after_end):
                updated = _append_to_unframed_prompt_tail(lines, last_end_idx + 1, prompt_lines)
                if updated is not None:
                    return "\n".join(updated)
            else:
                last_part_idx: int | None = None
                last_meta: dict[str, object] = {}
                for idx in range(last_end_idx - 1, -1, -1):
                    m_part = part_re.match(lines[idx])
                    if m_part:
                        last_part_idx = idx
                        if m_part.group(1):
                            try:
                                parsed = json.loads(m_part.group(1))
                                if isinstance(parsed, dict):
                                    last_meta = parsed
                            except ValueError:
                                pass
                        break
                if last_part_idx is not None:
                    part_kind = str(last_meta.get("kind") or "").strip().lower()
                    inner = list(lines[last_part_idx + 1 : last_end_idx])
                    while inner and not inner[-1].strip():
                        inner.pop()
                    first_inner = next((ln.strip() for ln in inner if ln.strip()), "")
                    m_inner_sec = SECTION_HEADER_RE.match(first_inner) if first_inner else None
                    prev_nonempty = next(
                        (lines[j].strip() for j in range(last_part_idx - 1, -1, -1) if lines[j].strip()),
                        "",
                    )
                    m_prev_sec = SECTION_HEADER_RE.match(prev_nonempty) if prev_nonempty else None
                    is_prompt_part = part_kind == "prompt" or (
                        part_kind in ("", "section")
                        and (
                            (m_inner_sec is not None and m_inner_sec.group(1).strip().lower() == "prompt")
                            or (m_prev_sec is not None and m_prev_sec.group(1).strip().lower() == "prompt")
                        )
                    )
                    if is_prompt_part:
                        non_empty_inner = [ln for ln in inner if ln.strip()]
                        only_header = (
                            len(non_empty_inner) == 1
                            and SECTION_HEADER_RE.match(non_empty_inner[0].strip()) is not None
                        )
                        prefix = [*lines[: last_part_idx + 1], *inner]
                        if non_empty_inner and not only_header:
                            prefix.append("")
                        return "\n".join([*prefix, *prompt_lines, lines[last_end_idx]])
            part_meta = json.dumps({"kind": "prompt", "name": "Prompt"}, ensure_ascii=False)
            prompt_block = [
                f"<!-- bundle:{boundary_val}:part {part_meta} -->",
                "===== Prompt =====",
                *prompt_lines,
                f"<!-- bundle:{boundary_val}:end -->",
            ]
            if lines:
                return "\n".join([*lines, "", *prompt_block])
            return "\n".join(prompt_block)

    updated_plain = _append_to_unframed_prompt_tail(lines, 0, prompt_lines)
    if updated_plain is not None:
        return "\n".join(updated_plain)
    if lines:
        return "\n".join([*lines, "", "===== Prompt =====", *prompt_lines])
    return "\n".join(["===== Prompt =====", *prompt_lines])


def _parse_header_filter_tokens(raw: str) -> set[str]:
    tokens: set[str] = set()
    for tok in re.split(r"[\s,]+", raw or ""):
        cleaned = re.sub(r"\s+", "-", tok.strip().lower())
        if cleaned:
            tokens.add(cleaned)
    return tokens


def extract_bundle_transport_headers(headers: list[tuple[str, str]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers:
        if is_bundle_transport_header(k):
            norm = re.sub(r"\s+", "-", k.strip().lower())
            out[norm] = v.strip()
    return out


def get_bundle_boundary(headers: list[tuple[str, str]]) -> str | None:
    transport = extract_bundle_transport_headers(headers)
    val = transport.get(BUNDLE_BOUNDARY_HEADER, "").strip()
    return val or None


def filter_exposed_headers(headers: list[tuple[str, str]]) -> list[tuple[str, str]]:
    transport = extract_bundle_transport_headers(headers)
    raw_expose = transport.get(BUNDLE_EXPOSE_HEADER, "")
    if not raw_expose:
        return []
    expose_set = _parse_header_filter_tokens(raw_expose)
    hide_set = _parse_header_filter_tokens(transport.get(BUNDLE_HIDE_HEADER, ""))
    if "*" in hide_set or "all" in hide_set:
        return []
    expose_all = "*" in expose_set or "all" in expose_set
    if not expose_all and (not expose_set or expose_set == {"none"}):
        return []

    exposed: list[tuple[str, str]] = []
    for k, v in headers:
        norm_k = re.sub(r"\s+", "-", k.strip().lower())
        if is_bundle_transport_header(norm_k):
            continue
        if norm_k in HIDDEN_SESSION_HEADER_KEYS:
            continue
        if norm_k in hide_set:
            continue
        if not expose_all and norm_k not in expose_set:
            continue
        if not v.strip():
            continue
        exposed.append((k, v))
    return exposed


def _infer_section_meta(title: str | None, *, is_sections: bool, is_preamble: bool = False) -> dict[str, object]:
    if title is None:
        if is_sections:
            return {"kind": "text", "name": "Preamble" if is_preamble else "Text"}
        return {"kind": "body", "name": "Body"}
    low = title.lower()
    if low == "rules":
        return {"kind": "rules", "name": "Rules"}
    if low == "prompt":
        return {"kind": "prompt", "name": "Prompt"}
    if title.startswith(chr(36) + " "):
        return {"kind": "cmd", "name": title[2:].strip()}
    if low.startswith("file:"):
        return {"kind": "file", "name": title.split(":", 1)[1].strip()}
    return {"kind": "section", "name": title}


def _bundle_thresholds() -> tuple[int, int]:
    try:
        bundle_max = int(get_setting("bundle_max_tokens")[0])
    except Exception:
        bundle_max = DEFAULT_BUNDLE_TOKEN_BUDGET
    try:
        frag_max = int(get_setting("fragment_max_tokens")[0])
    except Exception:
        frag_max = DEFAULT_FRAGMENT_MAX_TOKENS
    return max(0, bundle_max), max(0, frag_max)


def _part_label(entry: dict[str, object]) -> str:
    name = str(entry.get("name") or entry.get("id") or "")
    if name:
        return name
    grp = str(entry.get("group") or "")
    if grp:
        return grp
    kind = str(entry.get("kind") or "part")
    idx = entry.get("index")
    return f"{kind} #{idx}" if idx is not None else kind


def _is_cmd_output_empty(part_lines: list[str]) -> bool:
    non_empty = [ln for ln in part_lines if ln.strip()]
    if not non_empty:
        return True
    if SECTION_HEADER_RE.match(non_empty[0].strip()):
        return len(non_empty) == 1
    return False


def analyze_bundle_warnings(
    parts: list[dict[str, object]],
    part_texts: list[str] | None = None,
    part_lines_list: list[list[str]] | None = None,
    total_gpt: int | None = None,
) -> list[dict[str, object]]:
    bundle_budget, frag_limit = _bundle_thresholds()
    warnings: list[dict[str, object]] = []
    computed_gpt = 0
    for idx_0, entry in enumerate(parts):
        idx = int(entry.get("index") or (idx_0 + 1))
        kind = str(entry.get("kind") or "part").lower()
        label = _part_label(entry)
        gpt_cnt = int(entry.get("gpt") or 0)
        computed_gpt += gpt_cnt
        rc_val = entry.get("rc")
        if isinstance(rc_val, int) and rc_val != 0:
            warnings.append(
                {
                    "code": "cmd_rc",
                    "severity": "warn",
                    "part_index": idx,
                    "part_name": label,
                    "message": f"command {label!r} exited with rc={rc_val}",
                }
            )
        if kind == "cmd" and part_lines_list is not None and idx_0 < len(part_lines_list):
            if _is_cmd_output_empty(part_lines_list[idx_0]):
                warnings.append(
                    {
                        "code": "cmd_empty",
                        "severity": "warn",
                        "part_index": idx,
                        "part_name": label,
                        "message": f"command {label!r} produced empty output",
                    }
                )
        if frag_limit > 0 and gpt_cnt > frag_limit:
            warnings.append(
                {
                    "code": "fragment_oversized",
                    "severity": "warn",
                    "part_index": idx,
                    "part_name": label,
                    "message": f"fragment {label!r} is oversized (~{_human_tok(gpt_cnt)} > {_human_tok(frag_limit)} tokens)",
                }
            )
        if kind not in ("rule", "rules") and part_texts is not None and idx_0 < len(part_texts):
            sec_hits = scan_content_secrets(part_texts[idx_0])
            if sec_hits:
                labels: list[str] = []
                for h in sec_hits:
                    lbl = str(h.get("label") or h.get("category") or "secret")
                    if lbl not in labels:
                        labels.append(lbl)
                cat_str = ", ".join(labels)
                warnings.append(
                    {
                        "code": "secret_detected",
                        "severity": "warn",
                        "part_index": idx,
                        "part_name": label,
                        "message": f"potential secret in {label!r} ({cat_str})",
                    }
                )
    eff_total_gpt = total_gpt if total_gpt is not None else computed_gpt
    if bundle_budget > 0 and eff_total_gpt > bundle_budget:
        warnings.append(
            {
                "code": "token_budget",
                "severity": "warn",
                "message": f"total bundle (~{_human_tok(eff_total_gpt)} tokens) exceeds {_human_tok(bundle_budget)} token budget",
            }
        )
    return warnings


def _part_chars(entry: dict[str, object]) -> int:
    raw = entry.get("chars")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw)
    return int(entry.get("bytes") or 0)


def _resolve_part_chain(entry: dict[str, object]) -> list[str]:
    if "chain" in entry and isinstance(entry.get("chain"), (list, tuple)):
        return [str(x).strip() for x in entry["chain"] if str(x).strip()]
    grp = str(entry.get("group") or "").strip()
    if not grp:
        return []
    via = str(entry.get("via") or "").strip()
    if via and via != grp:
        return [via, grp]
    return [grp]


def _join_chain_label(chain: list[str], name: str) -> str:
    if not chain:
        return name
    if not name:
        return " -> ".join(chain) if len(chain) > 1 else chain[0]
    cur = name
    for seg in reversed(chain):
        if cur == seg or cur.startswith(seg + ":") or cur.startswith(seg + "/"):
            continue
        cur = f"{seg}: {cur}"
    return cur


def _child_rel_label(prefix: str, name: str) -> str:
    if not prefix or not name or name == prefix:
        return name
    for sep in (":", "/"):
        if name.startswith(prefix + sep):
            return name[len(prefix) + 1 :].lstrip() or name
    return name


def _recompute_share_pct(plan: dict[str, object]) -> None:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    total_chars = int(plan.get("chars") if plan.get("chars") is not None else (plan.get("bytes") or 0))
    total_bytes = int(plan.get("bytes") or 0)
    denom = total_chars if total_chars > 0 else total_bytes
    use_chars = total_chars > 0
    for entry in parts:
        val = _part_chars(entry) if use_chars else int(entry.get("bytes") or 0)
        entry["share_pct"] = round(val * 100.0 / denom, 1) if denom > 0 else 0.0


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        if ln == "" and out and out[-1] == "":
            continue
        out.append(ln)
    return out


def _assign_part_ranges(
    plan: dict[str, object],
    raw_parts: list[tuple[dict[str, object], list[str]]],
    body_text: str,
    *,
    collapse_blanks: bool,
) -> None:
    # Locate each part inside the cleaned body (1-based, body-relative); parts
    # that cannot be matched contiguously simply carry no range.
    body_lines = body_text.splitlines()
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    cursor = 0
    for entry, (_, part_lines) in zip(parts, raw_parts):
        seq = _collapse_blank_runs(part_lines) if collapse_blanks else list(part_lines)
        while seq and not seq[0].strip():
            seq.pop(0)
        while seq and not seq[-1].strip():
            seq.pop()
        if not seq:
            continue
        span = len(seq)
        for pos in range(cursor, len(body_lines) - span + 1):
            if body_lines[pos] == seq[0] and body_lines[pos:pos + span] == seq:
                entry["line_start"] = pos + 1
                entry["line_end"] = pos + span
                cursor = pos + span
                break
    plan["line_offset"] = 0


def _body_line_offset(full_text: str) -> int:
    try:
        _, body = parse_stdin_preamble(full_text)
    except Exception:
        return 0
    if not body.strip():
        return 0
    body_pos = full_text.find(body[:200])
    return full_text.count("\n", 0, body_pos) if body_pos > 0 else 0


def _shift_part_ranges(plan: dict[str, object], offset: int) -> dict[str, object]:
    delta = offset - int(plan.get("line_offset") or 0)
    out = dict(plan)
    out["line_offset"] = offset
    if delta == 0:
        return out
    shifted: list[dict[str, object]] = []
    for p in out.get("parts") or []:
        q = dict(p)
        if str(q.get("kind") or "") != "header" and isinstance(q.get("line_start"), int) and isinstance(q.get("line_end"), int):
            q["line_start"] += delta
            q["line_end"] += delta
        shifted.append(q)
    out["parts"] = shifted
    return out


def parse_part_option(argv: list[str], usage: str) -> tuple[list[str], int | None]:
    prog = prog_name()
    rest: list[str] = []
    part: int | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--part":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --part requires a number (usage: {usage})")
            raw = argv[i + 1]
            i += 2
        elif a.startswith("--part="):
            raw = a.split("=", 1)[1]
            i += 1
        else:
            rest.append(a)
            i += 1
            continue
        if part is not None:
            raise SystemExit(f"{prog}: --part given more than once (usage: {usage})")
        if not re.fullmatch(r"[0-9]+", raw) or int(raw) < 1:
            raise SystemExit(f"{prog}: --part expects a positive integer, got {raw!r}")
        part = int(raw)
    return rest, part


def extract_bundle_part(plan: dict[str, object], text: str, number: int) -> tuple[dict[str, object], str]:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    if number < 1 or number > len(parts):
        raise ValueError(f"part {number} out of range (bundle has {len(parts)} part{'s' if len(parts) != 1 else ''})")
    entry = parts[number - 1]
    start, end = entry.get("line_start"), entry.get("line_end")
    if not isinstance(start, int) or not isinstance(end, int):
        raise ValueError(f"part {number} has no recorded line range (bundle plan predates part ranges)")
    lines = text.splitlines()
    if start < 1 or end < start or end > len(lines):
        raise ValueError(f"part {number} line range {start}-{end} is outside the bundle ({len(lines)} lines)")
    return entry, "\n".join(lines[start - 1:end]) + "\n"


def format_part_header(target: str, entry: dict[str, object], total: int) -> str:
    return (
        f"{target} part {entry.get('index')}/{total}: {_part_label(entry)} "
        f"(lines {entry.get('line_start')}-{entry.get('line_end')})\n"
    )


def reconcile_bundle_plan(plan: dict[str, object], full_text: str, *, track_lines: bool = True) -> dict[str, object]:
    out = dict(plan)
    raw_parts = [dict(p) for p in (out.get("parts") or []) if isinstance(p, dict)]
    had_header_part = bool(raw_parts and str(raw_parts[0].get("kind") or "") == "header")
    non_hdr_parts = raw_parts[1:] if had_header_part else raw_parts
    sum_lines = sum(int(p.get("lines") or 0) for p in non_hdr_parts)
    sum_chars = sum(_part_chars(p) for p in non_hdr_parts)
    sum_bytes = sum(int(p.get("bytes") or 0) for p in non_hdr_parts)
    sum_gpt = sum(int(p.get("gpt") or 0) for p in non_hdr_parts)
    sum_claude = sum(int(p.get("claude") or 0) for p in non_hdr_parts)
    full_tok = count_tokens(full_text.encode("utf-8"))
    try:
        preamble_headers, body = parse_stdin_preamble(full_text)
    except Exception:
        preamble_headers, body = [], full_text
    body_pos = full_text.find(body[:200]) if body.strip() else -1
    prefix = full_text[:body_pos] if body_pos > 0 else (full_text if (preamble_headers and not body.strip()) else "")
    pre_tok = count_tokens(prefix.encode("utf-8")) if prefix else {}

    def _hdr_val(key: str, sum_val: int) -> int:
        return max(0, int(full_tok[key]) - sum_val, int(pre_tok.get(key) or 0))

    has_leading_headers = bool(preamble_headers)
    hdr_lines = _hdr_val("lines", sum_lines) if has_leading_headers else 0
    hdr_chars = _hdr_val("chars", sum_chars) if has_leading_headers else 0
    hdr_bytes = _hdr_val("bytes", sum_bytes) if has_leading_headers else 0
    hdr_gpt = _hdr_val("gpt", sum_gpt) if has_leading_headers else 0
    hdr_claude = _hdr_val("claude", sum_claude) if has_leading_headers else 0
    out.pop("header", None)
    if has_leading_headers and (hdr_lines > 0 or hdr_chars > 0):
        out["lines"] = sum_lines + hdr_lines
        out["chars"] = sum_chars + hdr_chars
        out["bytes"] = sum_bytes + hdr_bytes
        out["gpt"] = sum_gpt + hdr_gpt
        out["claude"] = sum_claude + hdr_claude
        out["gpt_exact"] = bool(full_tok["gpt_exact"])
        offset = _body_line_offset(full_text)
        hdr_end = max(1, offset) if offset > 0 else max(1, len(prefix.splitlines()))
        hdr_part: dict[str, object] = {
            "index": 1,
            "kind": "header",
            "name": "Headers & spacing",
            "chain": [],
            "lines": hdr_lines,
            "chars": hdr_chars,
            "bytes": hdr_bytes,
            "gpt": hdr_gpt,
            "claude": hdr_claude,
            "line_start": 1,
            "line_end": hdr_end,
        }
        shifted_parts: list[dict[str, object]] = [hdr_part]
        for idx_p, p in enumerate(non_hdr_parts, 2):
            qp = dict(p)
            qp["index"] = idx_p
            shifted_parts.append(qp)
        out["parts"] = shifted_parts
        out["part_count"] = len(shifted_parts)
        if not had_header_part and isinstance(out.get("warnings"), list):
            new_warns: list[dict[str, object]] = []
            for w in out["warnings"]:
                if isinstance(w, dict):
                    qw = dict(w)
                    if isinstance(qw.get("part_index"), int):
                        qw["part_index"] = int(qw["part_index"]) + 1
                    new_warns.append(qw)
            out["warnings"] = new_warns
    else:
        renumbered: list[dict[str, object]] = []
        for idx_p, p in enumerate(non_hdr_parts, 1):
            qp = dict(p)
            qp["index"] = idx_p
            renumbered.append(qp)
        out["parts"] = renumbered
        out["part_count"] = len(renumbered)
        out["lines"] = sum_lines
        out["chars"] = sum_chars
        out["bytes"] = sum_bytes
        out["gpt"] = sum_gpt
        out["claude"] = sum_claude
    _recompute_share_pct(out)
    if track_lines:
        out = _shift_part_ranges(out, _body_line_offset(full_text))
    return out


def group_bundle_parts(parts: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, tuple[str, ...]], dict[str, object]] = {}
    order: list[tuple[str, tuple[str, ...]]] = []
    for entry in parts:
        kind = str(entry.get("kind") or "part")
        chain = tuple(_resolve_part_chain(entry))
        group = " / ".join(chain) if chain else ""
        key = (kind, chain)
        if key not in buckets:
            order.append(key)
            buckets[key] = {
                "kind": kind,
                "group": group,
                "chain": list(chain),
                "count": 0,
                "lines": 0,
                "chars": 0,
                "bytes": 0,
                "gpt": 0,
                "claude": 0,
                "share_pct": 0.0,
                "names": [],
                "rc_errors": 0,
            }
        b = buckets[key]
        b["count"] = int(b["count"]) + 1
        b["lines"] = int(b["lines"]) + int(entry.get("lines") or 0)
        b["chars"] = int(b["chars"]) + _part_chars(entry)
        b["bytes"] = int(b["bytes"]) + int(entry.get("bytes") or 0)
        b["gpt"] = int(b["gpt"]) + int(entry.get("gpt") or 0)
        b["claude"] = int(b["claude"]) + int(entry.get("claude") or 0)
        b["share_pct"] = round(float(b["share_pct"]) + float(entry.get("share_pct") or 0.0), 1)
        name = str(entry.get("name") or entry.get("id") or "")
        names_list = b["names"]
        if name and isinstance(names_list, list) and name not in names_list:
            names_list.append(name)
        rc_val = entry.get("rc")
        if isinstance(rc_val, int) and rc_val != 0:
            b["rc_errors"] = int(b["rc_errors"]) + 1
    return [buckets[k] for k in order]


def _build_bundle_plan(
    protocol: str,
    boundary: str | None,
    raw_parts: list[tuple[dict[str, object], list[str]]],
) -> dict[str, object]:
    parts: list[dict[str, object]] = []
    part_texts: list[str] = []
    part_lines_list: list[list[str]] = []
    total_lines = 0
    total_chars = 0
    total_bytes = 0
    total_gpt = 0
    total_claude = 0
    gpt_exact = False

    for idx, (meta, part_lines) in enumerate(raw_parts, 1):
        part_text = "\n".join(part_lines) + ("\n" if part_lines else "")
        part_texts.append(part_text)
        part_lines_list.append(part_lines)
        tok = count_tokens(part_text.encode("utf-8"))
        gpt_exact = bool(tok["gpt_exact"])
        lines_cnt = int(tok["lines"])
        chars_cnt = int(tok["chars"])
        bytes_cnt = int(tok["bytes"])
        gpt_cnt = int(tok["gpt"])
        claude_cnt = int(tok["claude"])

        entry: dict[str, object] = {
            "index": idx,
            "kind": str(meta.get("kind") or "part"),
        }
        if meta.get("id"):
            entry["id"] = str(meta["id"])
        name_val = str(meta.get("name") or meta.get("id") or "")
        if name_val:
            entry["name"] = name_val
        if "chain" in meta and isinstance(meta.get("chain"), (list, tuple)):
            entry["chain"] = [str(x).strip() for x in meta["chain"] if str(x).strip()]
        if meta.get("group"):
            entry["group"] = str(meta["group"])
        if meta.get("via"):
            entry["via"] = str(meta["via"])
        rc_val = meta.get("rc")
        if isinstance(rc_val, (int, float)) and not isinstance(rc_val, bool):
            entry["rc"] = int(rc_val)
        ms_val = meta.get("ms")
        if isinstance(ms_val, (int, float)) and not isinstance(ms_val, bool):
            ms_f = float(ms_val)
            entry["ms"] = int(round(ms_f)) if ms_f.is_integer() else ms_f
        entry["lines"] = lines_cnt
        entry["chars"] = chars_cnt
        entry["bytes"] = bytes_cnt
        entry["gpt"] = gpt_cnt
        entry["claude"] = claude_cnt

        total_lines += lines_cnt
        total_chars += chars_cnt
        total_bytes += bytes_cnt
        total_gpt += gpt_cnt
        total_claude += claude_cnt
        parts.append(entry)

    plan: dict[str, object] = {
        "protocol": protocol,
        "boundary": boundary or None,
        "part_count": len(parts),
        "lines": total_lines,
        "chars": total_chars,
        "bytes": total_bytes,
        "gpt": total_gpt,
        "claude": total_claude,
        "gpt_exact": gpt_exact,
        "parts": parts,
        "warnings": analyze_bundle_warnings(
            parts,
            part_texts=part_texts,
            part_lines_list=part_lines_list,
            total_gpt=total_gpt,
        ),
    }
    _recompute_share_pct(plan)
    return plan


def _split_section_fallback(norm_text: str, boundary_val: str | None) -> tuple[str, dict[str, object]]:
    clean_body = norm_text.strip("\n")
    if not clean_body.strip():
        return "", _build_bundle_plan("empty", boundary_val, [])

    lines = clean_body.splitlines()
    raw_sections: list[tuple[str | None, list[str]]] = []
    cur_title: str | None = None
    cur_lines: list[str] = []
    saw_section = False

    for line in lines:
        m = SECTION_HEADER_RE.match(line.strip())
        if m:
            if saw_section or any(x.strip() for x in cur_lines):
                while cur_lines and not cur_lines[-1].strip():
                    cur_lines.pop()
                raw_sections.append((cur_title, cur_lines))
            saw_section = True
            cur_title = m.group(1).strip()
            cur_lines = [line]
        else:
            cur_lines.append(line)

    if saw_section or any(x.strip() for x in cur_lines):
        while cur_lines and not cur_lines[-1].strip():
            cur_lines.pop()
        raw_sections.append((cur_title, cur_lines))

    protocol = "sections" if saw_section else "body"
    raw_parts: list[tuple[dict[str, object], list[str]]] = []
    for idx, (sec_title, sec_lines) in enumerate(raw_sections):
        meta = _infer_section_meta(sec_title, is_sections=saw_section, is_preamble=(idx == 0))
        raw_parts.append((meta, sec_lines))
    plan = _build_bundle_plan(protocol, boundary_val, raw_parts)
    _assign_part_ranges(plan, raw_parts, clean_body, collapse_blanks=False)
    if clean_body:
        plan = reconcile_bundle_plan(plan, clean_body + "\n", track_lines=False)
    return clean_body, plan


def _collect_unframed_parts(
    unframed_lines: list[str],
    *,
    is_first: bool,
) -> list[tuple[dict[str, object], list[str]]]:
    real_unframed = [ln for ln in unframed_lines if not SECTION_HEADER_RE.match(ln.strip())]
    while real_unframed and not real_unframed[0].strip():
        real_unframed.pop(0)
    while real_unframed and not real_unframed[-1].strip():
        real_unframed.pop()
    if any(x.strip() for x in real_unframed):
        return [(_infer_section_meta(None, is_sections=True, is_preamble=is_first), real_unframed)]
    return []


def parse_bundle_fragments(body_text: str, boundary: str | None = None) -> tuple[str, dict[str, object]]:
    if not body_text:
        return "", _build_bundle_plan("empty", boundary, [])

    norm_text = body_text.replace("\r\n", "\n")
    boundary_val = (boundary or "").strip() or None

    if boundary_val:
        esc = re.escape(boundary_val)
        part_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:part(?:\s+(\{{.*\}}))?\s*-->\s*$")
        end_re = re.compile(rf"^\s*<!--\s*bundle:{esc}:end\s*-->\s*$")

        raw_parts: list[tuple[dict[str, object], list[str]]] = []
        stripped_lines: list[str] = []
        in_part = False
        cur_meta: dict[str, object] = {}
        cur_lines: list[str] = []
        unframed_lines: list[str] = []
        found_markers = 0

        for line in norm_text.splitlines():
            m_part = part_re.match(line)
            if m_part:
                found_markers += 1
                if in_part:
                    raw_parts.append((cur_meta, cur_lines))
                else:
                    raw_parts.extend(_collect_unframed_parts(unframed_lines, is_first=(len(raw_parts) == 0)))
                unframed_lines = []
                in_part = True
                cur_lines = []
                cur_meta = {}
                raw_json = m_part.group(1)
                if raw_json:
                    try:
                        parsed = json.loads(raw_json)
                        if isinstance(parsed, dict):
                            cur_meta = parsed
                    except ValueError:
                        cur_meta = {"kind": "part"}
                continue

            if end_re.match(line):
                found_markers += 1
                if in_part:
                    raw_parts.append((cur_meta, cur_lines))
                    in_part = False
                    cur_meta = {}
                    cur_lines = []
                continue

            stripped_lines.append(line)
            if in_part:
                cur_lines.append(line)
            else:
                unframed_lines.append(line)

        if in_part:
            raw_parts.append((cur_meta, cur_lines))
        else:
            raw_parts.extend(_collect_unframed_parts(unframed_lines, is_first=(len(raw_parts) == 0)))

        if found_markers > 0:
            clean_body = "\n".join(stripped_lines)
            clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip("\n")
            plan = _build_bundle_plan("boundary", boundary_val, raw_parts)
            _assign_part_ranges(plan, raw_parts, clean_body, collapse_blanks=True)
            if clean_body:
                plan = reconcile_bundle_plan(plan, clean_body + "\n", track_lines=False)
            return clean_body, plan

    return _split_section_fallback(norm_text, boundary_val)


def refresh_bundle_plan_meta(sdir: Path, bundle_path: Path) -> None:
    if not bundle_path.is_file():
        return
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    preamble_hdrs, body = parse_stdin_preamble(text)
    meta = read_session_meta(sdir)
    prev_plan = meta.get("bundle_plan") if isinstance(meta.get("bundle_plan"), dict) else None
    meta_hdrs = _parse_meta_header_items(sdir)
    boundary = get_bundle_boundary(meta_hdrs)
    clean_body, parsed_plan = parse_bundle_fragments(body, boundary=boundary)
    raw_path = sdir / "0.raw"
    if boundary and parsed_plan.get("protocol") == "boundary":
        write_private(raw_path, text, overwrite=True)
        hdr_block = "\n".join(f"{k}: {v}" for k, v in preamble_hdrs) + "\n" if preamble_hdrs else ""
        text = hdr_block + ("\n" + clean_body + "\n" if (hdr_block and clean_body) else (clean_body + "\n" if clean_body else ""))
        write_private(bundle_path, text, overwrite=True)
        plan = reconcile_bundle_plan(parsed_plan, text)
        update_session_meta(sdir, bundle_plan=plan)
        return
    if raw_path.is_file() and boundary:
        raw_text = raw_path.read_text(encoding="utf-8", errors="replace")
        _, raw_body = parse_stdin_preamble(raw_text)
        raw_clean_body, raw_plan = parse_bundle_fragments(raw_body, boundary=boundary)
        if raw_plan.get("protocol") == "boundary" and raw_clean_body == body:
            hdr_block = "\n".join(f"{k}: {v}" for k, v in preamble_hdrs) + "\n" if preamble_hdrs else ""
            new_raw = hdr_block + ("\n" + raw_body.strip("\n") + "\n" if (hdr_block and raw_body.strip()) else (raw_body.strip("\n") + "\n" if raw_body.strip() else ""))
            write_private(raw_path, new_raw, overwrite=True)
            plan = reconcile_bundle_plan(raw_plan, text)
            update_session_meta(sdir, bundle_plan=plan)
            return
    if (
        isinstance(prev_plan, dict)
        and prev_plan.get("protocol") == "boundary"
        and parsed_plan.get("protocol") != "boundary"
    ):
        prev_parts = [dict(p) for p in (prev_plan.get("parts") or []) if isinstance(p, dict)]
        non_hdr = [p for p in prev_parts if str(p.get("kind") or "") != "header"]
        lines = text.splitlines()
        last_non_prompt_end = 0
        for p in non_hdr:
            if str(p.get("kind") or "") != "prompt" and isinstance(p.get("line_end"), int):
                last_non_prompt_end = max(last_non_prompt_end, int(p["line_end"]))
        if non_hdr and last_non_prompt_end > 0 and last_non_prompt_end <= len(lines):
            prefix_match = True
            for p in non_hdr:
                if str(p.get("kind") or "") == "prompt":
                    continue
                ls, le = p.get("line_start"), p.get("line_end")
                if not isinstance(ls, int) or not isinstance(le, int) or ls < 1 or le > len(lines):
                    prefix_match = False
                    break
            if prefix_match:
                tail_start = last_non_prompt_end + 1
                while tail_start <= len(lines) and not lines[tail_start - 1].strip():
                    tail_start += 1
                tail_end = len(lines)
                while tail_end >= tail_start and not lines[tail_end - 1].strip():
                    tail_end -= 1
                if tail_start <= tail_end:
                    tail_lines = lines[tail_start - 1 : tail_end]
                    first_tail = tail_lines[0].strip()
                    m_sec = SECTION_HEADER_RE.match(first_tail)
                    if m_sec and m_sec.group(1).strip().lower() == "prompt":
                        p_text = "\n".join(tail_lines) + "\n"
                        tok = count_tokens(p_text.encode("utf-8"))
                        if str(non_hdr[-1].get("kind") or "") == "prompt":
                            p_entry = dict(non_hdr[-1])
                        else:
                            p_entry = {"kind": "prompt", "name": "Prompt", "chain": []}
                            non_hdr.append(p_entry)
                        p_entry["lines"] = int(tok["lines"])
                        p_entry["chars"] = int(tok["chars"])
                        p_entry["bytes"] = int(tok["bytes"])
                        p_entry["gpt"] = int(tok["gpt"])
                        p_entry["claude"] = int(tok["claude"])
                        p_entry["line_start"] = tail_start
                        p_entry["line_end"] = tail_end
                        kept_plan = dict(prev_plan)
                        kept_plan["parts"] = non_hdr
                        kept_plan["line_offset"] = _body_line_offset(text)
                        plan = reconcile_bundle_plan(kept_plan, text, track_lines=False)
                        update_session_meta(sdir, bundle_plan=plan)
                        return
    raw_path.unlink(missing_ok=True)
    plan = reconcile_bundle_plan(parsed_plan, text)
    update_session_meta(sdir, bundle_plan=plan)


def _format_tok_pair(gpt_cnt: int, claude_cnt: int, *, unit: bool = True) -> str:
    lo = min(gpt_cnt, claude_cnt)
    hi = max(gpt_cnt, claude_cnt)
    body = f"~{_human_tok(lo)}–{_human_tok(hi)}" if lo != hi else f"~{_human_tok(lo)}"
    return f"{body} tok" if unit else body


def _new_tree_node(name: str, chain: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "chain": list(chain),
        "items": [],
        "children_by_name": {},
        "direct_parts": [],
        "part_indices": [],
        "total_count": 0,
        "lines": 0,
        "chars": 0,
        "bytes": 0,
        "gpt": 0,
        "claude": 0,
        "share_pct": 0.0,
        "kinds": [],
        "rc_errors": 0,
    }


def _add_part_to_node(node: dict[str, object], entry: dict[str, object]) -> None:
    node["total_count"] = int(node["total_count"]) + 1
    node["lines"] = int(node["lines"]) + int(entry.get("lines") or 0)
    node["chars"] = int(node["chars"]) + _part_chars(entry)
    node["bytes"] = int(node["bytes"]) + int(entry.get("bytes") or 0)
    node["gpt"] = int(node["gpt"]) + int(entry.get("gpt") or 0)
    node["claude"] = int(node["claude"]) + int(entry.get("claude") or 0)
    node["share_pct"] = round(float(node["share_pct"]) + float(entry.get("share_pct") or 0.0), 1)
    p_idx = entry.get("index")
    p_indices = node["part_indices"]
    if isinstance(p_idx, int) and p_idx > 0 and isinstance(p_indices, list):
        p_indices.append(p_idx)
    kind = str(entry.get("kind") or "part")
    kinds = node["kinds"]
    if isinstance(kinds, list) and kind not in kinds:
        kinds.append(kind)
    rc_val = entry.get("rc")
    if isinstance(rc_val, int) and rc_val != 0:
        node["rc_errors"] = int(node["rc_errors"]) + 1


def _build_bundle_tree(parts: list[dict[str, object]]) -> list[tuple[str, dict[str, object]]]:
    root_items: list[tuple[str, dict[str, object]]] = []
    root_nodes: dict[str, dict[str, object]] = {}
    for entry in parts:
        chain = _resolve_part_chain(entry)
        if not chain:
            root_items.append(("part", entry))
            continue
        cur_items = root_items
        cur_map = root_nodes
        cur_node: dict[str, object] | None = None
        for depth_idx, seg in enumerate(chain):
            if seg not in cur_map:
                new_n = _new_tree_node(seg, chain[: depth_idx + 1])
                cur_map[seg] = new_n
                cur_items.append(("node", new_n))
            cur_node = cur_map[seg]
            _add_part_to_node(cur_node, entry)
            cur_items = cur_node["items"]  # type: ignore[assignment]
            cur_map = cur_node["children_by_name"]  # type: ignore[assignment]
        if cur_node is not None:
            cur_node["items"].append(("part", entry))  # type: ignore[union-attr]
            cur_node["direct_parts"].append(entry)  # type: ignore[union-attr]
    return root_items


HEAVY_WARN_SHARE = 25.0
HEAVY_WARN_TOK = 10000
HEAVY_ACCENT_SHARE = 10.0
HEAVY_ACCENT_TOK = 3000
_TABLE_ROW_RE = re.compile(r"^\s*(?:\d+\s+)?(\d+(?:\.\d+)?)%\s+\S+\s+\d+\s+(~\S+)\s+\[([a-z0-9_-]+)\]")
_COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)([kKmM]?)")


def _heavy_level(share_pct: float, tok_hi: float) -> str:
    if share_pct >= HEAVY_WARN_SHARE or tok_hi >= HEAVY_WARN_TOK:
        return "warn"
    if share_pct >= HEAVY_ACCENT_SHARE or tok_hi >= HEAVY_ACCENT_TOK:
        return "accent"
    return ""


def _parse_tok_hi(tok_str: str) -> float:
    scale = {"": 1.0, "k": 1000.0, "m": 1000000.0}
    best = 0.0
    for num, suf in _COUNT_RE.findall(tok_str):
        best = max(best, float(num) * scale[suf.lower()])
    return best


def bundle_row_heavy_level(line: str) -> str:
    m = _TABLE_ROW_RE.match(line)
    if not m:
        return ""
    if m.group(3) == "total":
        return ""
    return _heavy_level(float(m.group(1)), _parse_tok_hi(m.group(2)))


def _tree_connector(ancestors_more: list[bool], is_last: bool) -> str:
    utf8_ok = _supports_utf8()
    bar = "│  " if utf8_ok else "|  "
    branch = ("└─ " if is_last else "├─ ") if utf8_ok else ("`- " if is_last else "|- ")
    return "".join(bar if more else "   " for more in ancestors_more) + branch


def _make_table_row(
    *,
    kind: str,
    desc: str,
    lines_cnt: int,
    chars_cnt: int,
    gpt_cnt: int,
    claude_cnt: int,
    share_pct: float,
    tree_prefix: str = "",
    part_num: str = "",
    depth: int = 0,
    part_indices: list[int] | None = None,
) -> dict[str, object]:
    return {
        "num_str": part_num,
        "depth": depth,
        "pct_str": f"{share_pct:.1f}%",
        "chars_str": re.sub(r"\s*ch$", "", _human_chars(chars_cnt, short=True)),
        "lines_str": str(lines_cnt),
        "tok_str": _format_tok_pair(gpt_cnt, claude_cnt, unit=False),
        "kind": kind,
        "tree_prefix": tree_prefix,
        "desc": desc,
        "part_indices": list(part_indices) if part_indices is not None else [],
    }


def _part_extras_suffix(p: dict[str, object], *, include_ms: bool = True) -> str:
    extras: list[str] = []
    rc_val = p.get("rc")
    if isinstance(rc_val, int) and (include_ms or rc_val != 0):
        extras.append(f"rc={rc_val}")
    if include_ms and "ms" in p:
        extras.append(f"{p['ms']}ms")
    return f" ({', '.join(extras)})" if extras else ""


def _collect_hierarchy_rows(
    plan: dict[str, object],
    *,
    details: bool,
    edited: bool = False,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    parts = [dict(p) for p in (plan.get("parts") or []) if isinstance(p, dict)]
    hdr = plan.get("header")
    if isinstance(hdr, dict) and (_part_chars(hdr) > 0 or int(hdr.get("lines") or 0) > 0):
        if not (parts and str(parts[0].get("kind") or "") == "header"):
            hdr_part = dict(hdr)
            hdr_part.setdefault("index", 1)
            hdr_part.setdefault("kind", "header")
            hdr_part.setdefault("name", "Headers & spacing")
            hdr_part.setdefault("chain", [])
            shifted: list[dict[str, object]] = [hdr_part]
            for idx_p, ep in enumerate(parts, 2):
                qp = dict(ep)
                qp["index"] = idx_p
                shifted.append(qp)
            parts = shifted

    if not parts:
        return []

    row_counter = 0

    def _next_row_num() -> str:
        nonlocal row_counter
        row_counter += 1
        return str(row_counter)

    def _emit_part(
        p: dict[str, object],
        parent_name: str,
        ancestors_more: list[bool],
        is_last: bool | None,
        depth: int,
    ) -> None:
        t_pfx = _tree_connector(ancestors_more, is_last) if is_last is not None else ""
        raw_lbl = _part_label(p)
        lbl = _child_rel_label(parent_name, raw_lbl) if parent_name else raw_lbl
        lbl += _part_extras_suffix(p, include_ms=details)
        idx_val = p.get("index")
        p_indices = [idx_val] if isinstance(idx_val, int) and idx_val > 0 else []
        rows.append(
            _make_table_row(
                kind=str(p.get("kind") or "part"),
                desc=lbl,
                lines_cnt=int(p.get("lines") or 0),
                chars_cnt=_part_chars(p),
                gpt_cnt=int(p.get("gpt") or 0),
                claude_cnt=int(p.get("claude") or 0),
                share_pct=float(p.get("share_pct") or 0.0),
                tree_prefix=t_pfx,
                part_num=_next_row_num(),
                depth=depth,
                part_indices=p_indices,
            )
        )

    def _emit_node(
        node: dict[str, object],
        ancestors_more: list[bool],
        is_last: bool | None,
        depth: int,
    ) -> None:
        t_pfx = _tree_connector(ancestors_more, is_last) if is_last is not None else ""
        has_children = bool(node.get("children_by_name"))
        direct_parts: list[dict[str, object]] = list(node.get("direct_parts") or [])  # type: ignore[arg-type]
        if not has_children and len(direct_parts) == 1:
            p = direct_parts[0]
            p_kind = str(p.get("kind") or "part")
            if p_kind == "rule":
                p_kind = "bundle"
            lbl = _join_chain_label([str(node["name"])], _part_label(p)) + _part_extras_suffix(p, include_ms=details)
            idx_val = p.get("index")
            p_indices = [idx_val] if isinstance(idx_val, int) and idx_val > 0 else []
            rows.append(
                _make_table_row(
                    kind=p_kind,
                    desc=lbl,
                    lines_cnt=int(p.get("lines") or 0),
                    chars_cnt=_part_chars(p),
                    gpt_cnt=int(p.get("gpt") or 0),
                    claude_cnt=int(p.get("claude") or 0),
                    share_pct=float(p.get("share_pct") or 0.0),
                    tree_prefix=t_pfx,
                    part_num=_next_row_num(),
                    depth=depth,
                    part_indices=p_indices,
                )
            )
            return
        cnt = int(node.get("total_count") or 0)
        rc_errs = int(node.get("rc_errors") or 0)
        lbl = f"{node['name']} ({cnt})" + (f" ({rc_errs} rc!=0)" if rc_errs else "")
        node_indices = [int(i) for i in (node.get("part_indices") or []) if isinstance(i, int) and i > 0]
        rows.append(
            _make_table_row(
                kind="bundle",
                desc=lbl,
                lines_cnt=int(node.get("lines") or 0),
                chars_cnt=int(node.get("chars") or 0),
                gpt_cnt=int(node.get("gpt") or 0),
                claude_cnt=int(node.get("claude") or 0),
                share_pct=float(node.get("share_pct") or 0.0),
                tree_prefix=t_pfx,
                part_num=_next_row_num(),
                depth=depth,
                part_indices=node_indices,
            )
        )
        if details or has_children:
            child_items: list[tuple[str, dict[str, object]]] = list(node.get("items") or [])  # type: ignore[arg-type]
            next_anc = ([*ancestors_more, not is_last] if is_last is not None else [])
            for c_idx, (c_type, c_obj) in enumerate(child_items):
                c_last = c_idx == len(child_items) - 1
                if c_type == "node":
                    _emit_node(c_obj, next_anc, c_last, depth + 1)
                else:
                    _emit_part(c_obj, str(node["name"]), next_anc, c_last, depth + 1)

    for it_type, it_obj in _build_bundle_tree(parts):
        if it_type == "node":
            _emit_node(it_obj, [], None, 0)
        else:
            _emit_part(it_obj, "", [], None, 0)

    part_cnt = len(parts)
    tot_lines = int(plan.get("lines") if plan.get("lines") is not None else sum(int(p.get("lines") or 0) for p in parts))
    tot_chars = int(plan.get("chars") if plan.get("chars") is not None else (plan.get("bytes") or sum(_part_chars(p) for p in parts)))
    tot_gpt = int(plan.get("gpt") if plan.get("gpt") is not None else sum(int(p.get("gpt") or 0) for p in parts))
    tot_claude = int(plan.get("claude") if plan.get("claude") is not None else sum(int(p.get("claude") or 0) for p in parts))
    tot_desc = f"{part_cnt} part{'s' if part_cnt != 1 else ''}" + (" (edited)" if edited else "")
    tot_row = _make_table_row(
        kind="total",
        desc=tot_desc,
        lines_cnt=tot_lines,
        chars_cnt=tot_chars,
        gpt_cnt=tot_gpt,
        claude_cnt=tot_claude,
        share_pct=100.0,
        part_num="",
        depth=0,
    )
    return [dict(tot_row), *rows, dict(tot_row)]


def _render_bundle_table(rows: list[dict[str, object]], max_width: int, indent: str = "  ") -> list[str]:
    if not rows:
        return []
    w_num = max(1, *(len(str(r.get("num_str") or "")) for r in rows))
    w_pct_val = max(len("%"), *(len(str(r["pct_str"])) for r in rows))
    max_depth = max((int(r.get("depth") or 0) for r in rows), default=0)
    w_pct_col = w_pct_val + max_depth * 2
    w_ch = max(len("CHARS"), *(len(str(r["chars_str"])) for r in rows))
    w_ln = max(len("LINES"), *(len(str(r["lines_str"])) for r in rows))
    w_tok = max(len("~TOK"), *(len(str(r["tok_str"])) for r in rows))
    w_kind = max(len("KIND"), *(len(f"[{r['kind']}]") for r in rows))

    pct_hdr = "%".rjust(w_pct_val).ljust(w_pct_col)
    out: list[str] = [
        f"{indent}{' ' * w_num} {pct_hdr} {'CHARS'.rjust(w_ch)} {'LINES'.rjust(w_ln)} "
        f"{'~TOK'.rjust(w_tok)}  {'KIND'.ljust(w_kind)}  SOURCE"
    ]
    for r in rows:
        num_col = str(r.get("num_str") or "").rjust(w_num)
        depth = int(r.get("depth") or 0)
        pct_col = ((" " * (depth * 2)) + str(r["pct_str"]).rjust(w_pct_val)).ljust(w_pct_col)
        kind_col = f"[{r['kind']}]".ljust(w_kind)
        cols_prefix = (
            f"{indent}{num_col} "
            f"{pct_col} "
            f"{str(r['chars_str']).rjust(w_ch)} "
            f"{str(r['lines_str']).rjust(w_ln)} "
            f"{str(r['tok_str']).rjust(w_tok)}  "
            f"{kind_col}  "
        )
        full_pfx = f"{cols_prefix}{r.get('tree_prefix') or ''}"
        sub_indent = " " * display_width(full_pfx)
        avail = max(16, max_width - display_width(full_pfx))
        desc = str(r.get("desc") or "")
        wrapped = textwrap.wrap(desc, width=avail, break_long_words=True, break_on_hyphens=False) or [desc]
        out.append(full_pfx + wrapped[0])
        for cont in wrapped[1:]:
            out.append(sub_indent + cont)
    return out


def format_bundle_summary_lines(plan: dict[str, object], max_width: int = 120, *, edited: bool = False) -> list[str]:
    return _render_bundle_table(_collect_hierarchy_rows(plan, details=False, edited=edited), max_width=max_width)


def format_bundle_parts_lines(plan: dict[str, object], max_width: int = 120, *, edited: bool = False) -> list[str]:
    return _render_bundle_table(_collect_hierarchy_rows(plan, details=True, edited=edited), max_width=max_width)


def format_bundle_group_items(plan: dict[str, object]) -> list[tuple[str, str]]:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    if not parts:
        return []
    groups = group_bundle_parts(parts)
    items: list[tuple[str, str]] = []
    for g in groups:
        kind = str(g.get("kind") or "part")
        chain = [str(x) for x in (g.get("chain") or []) if str(x)]
        grp = str(g.get("group") or "")
        cnt = int(g.get("count") or 0)
        names = list(g.get("names") or [])
        if chain:
            if cnt == 1 and names:
                lbl = _join_chain_label(chain, str(names[0]))
            elif cnt > 1:
                lbl = f"{grp} ({cnt})"
            else:
                lbl = grp
        elif cnt == 1 and names:
            lbl = str(names[0])
        else:
            lbl = f"{cnt} part" + ("s" if cnt != 1 else "")
        lines_cnt = int(g.get("lines") or 0)
        chars_cnt = int(g.get("chars") if g.get("chars") is not None else (g.get("bytes") or 0))
        gpt_cnt = int(g.get("gpt") or 0)
        claude_cnt = int(g.get("claude") or 0)
        share = float(g.get("share_pct") or 0.0)
        err_cnt = int(g.get("rc_errors") or 0)
        meta = f"{lines_cnt}L · {_human_chars(chars_cnt, short=True)} · {_format_tok_pair(gpt_cnt, claude_cnt)} ({share:.1f}%)"
        if err_cnt:
            meta += f" · {err_cnt} rc!=0"
        items.append((kind, f"{lbl}  [{meta}]"))
    return items


def format_bundle_part_items(plan: dict[str, object]) -> list[tuple[str, str]]:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    items: list[tuple[str, str]] = []
    for p in parts:
        kind = str(p.get("kind") or "part")
        chain = _resolve_part_chain(p)
        lbl = _join_chain_label(chain, _part_label(p))
        lines_cnt = int(p.get("lines") or 0)
        chars_cnt = _part_chars(p)
        gpt_cnt = int(p.get("gpt") or 0)
        claude_cnt = int(p.get("claude") or 0)
        share = float(p.get("share_pct") or 0.0)
        extras: list[str] = [f"{lines_cnt}L", _human_chars(chars_cnt, short=True), f"{_format_tok_pair(gpt_cnt, claude_cnt)} ({share:.1f}%)"]
        if "rc" in p:
            extras.append(f"rc={p['rc']}")
        if "ms" in p:
            extras.append(f"{p['ms']}ms")
        items.append((kind, f"{lbl}  [{' · '.join(extras)}]"))
    return items


def format_bundle_warning_items(plan: dict[str, object]) -> list[tuple[str, str]]:
    warns = [w for w in (plan.get("warnings") or []) if isinstance(w, dict)]
    return [
        (str(w.get("code") or "warn"), str(w.get("message") or ""))
        for w in warns
        if w.get("message")
    ]


def _enrich_bundle_plan(plan: dict[str, object], full_text: str | None = None) -> dict[str, object]:
    out = dict(plan)
    parts = [dict(p) for p in (out.get("parts") or []) if isinstance(p, dict)]
    for part in parts:
        if part.get("chars") is None:
            part["chars"] = int(part.get("bytes") or 0)
    out["parts"] = parts
    if out.get("chars") is None:
        out["chars"] = int(out.get("bytes") or sum(_part_chars(p) for p in parts))
    has_hdr_part = bool(parts and str(parts[0].get("kind") or "") == "header")
    if full_text is not None and not has_hdr_part:
        out = reconcile_bundle_plan(out, full_text)
    if "warnings" not in out:
        out["warnings"] = analyze_bundle_warnings(parts, total_gpt=int(out.get("gpt") or 0))
    return out


def load_session_bundle_plan(sdir: Path | None, bundle_path: Path | None = None) -> dict[str, object] | None:
    meta = read_session_meta(sdir) if sdir is not None else {}
    raw_plan = meta.get("bundle_plan")
    bpath = bundle_path if bundle_path is not None else (sdir / "0" if sdir is not None else None)
    btext = bpath.read_text(encoding="utf-8", errors="replace") if (bpath is not None and bpath.is_file()) else None
    if isinstance(raw_plan, dict) and "parts" in raw_plan and "warnings" in raw_plan:
        return _enrich_bundle_plan(raw_plan, full_text=btext)
    if btext is not None:
        _, body = parse_stdin_preamble(btext)
        meta_hdrs = _parse_meta_header_items(sdir) if sdir is not None else []
        boundary = get_bundle_boundary(meta_hdrs)
        _, parsed_plan = parse_bundle_fragments(body, boundary=boundary)
        if isinstance(raw_plan, dict) and raw_plan.get("protocol") == "boundary" and parsed_plan.get("protocol") != "boundary":
            return _enrich_bundle_plan(raw_plan, full_text=btext)
        return reconcile_bundle_plan(parsed_plan, btext)
    if isinstance(raw_plan, dict):
        return _enrich_bundle_plan(raw_plan)
    return None


def format_bundle_plan_text(
    plan: dict[str, object],
    *,
    full: bool = False,
    session: str | None = None,
) -> str:
    protocol = str(plan.get("protocol") or "empty")
    part_cnt = int(plan.get("part_count") or 0)
    lines_cnt = int(plan.get("lines") or 0)
    chars_cnt = int(plan.get("chars") if plan.get("chars") is not None else (plan.get("bytes") or 0))
    gpt_cnt = int(plan.get("gpt") or 0)
    claude_cnt = int(plan.get("claude") or 0)
    hdr_target = session if session else "stdin"
    out_lines: list[str] = [
        f"Bundle Plan ({hdr_target}, protocol: {protocol}):",
        f"Total: {lines_cnt} line{'s' if lines_cnt != 1 else ''} · {_human_chars(chars_cnt)} · {_format_tok_pair(gpt_cnt, claude_cnt)} ({part_cnt} part{'s' if part_cnt != 1 else ''})",
    ]
    sum_lines = format_bundle_summary_lines(plan, max_width=120)
    if sum_lines:
        out_lines.append("")
        out_lines.append(f"Summary ({part_cnt} part{'s' if part_cnt != 1 else ''}):")
        out_lines.extend(sum_lines)
    if full:
        part_lines = format_bundle_parts_lines(plan, max_width=120)
        if part_lines:
            out_lines.append("")
            out_lines.append(f"Parts ({part_cnt}):")
            out_lines.extend(part_lines)
    warn_items = format_bundle_warning_items(plan)
    if warn_items:
        out_lines.append("")
        out_lines.append(f"Warnings ({len(warn_items)}):")
        out_lines.extend(_wrap_labeled_items(warn_items, 120, indent="  "))
    return "\n".join(out_lines) + "\n"


def cmd_bundle_plan(argv: list[str], stdin_text: str | None = None) -> int:
    prog = prog_name()
    usage = f"{prog} --bundle-plan [<session>] [--json] [--full] [--part N]"
    argv, part_no = parse_part_option(argv, usage)
    as_json = False
    full = False
    session_arg: str | None = None
    for a in argv:
        if a == "--json":
            as_json = True
        elif a == "--full":
            full = True
        elif a.startswith("-"):
            raise SystemExit(f"{prog}: usage: {usage}")
        elif session_arg is None:
            session_arg = a
        else:
            raise SystemExit(f"{prog}: usage: {usage}")
    if part_no is not None and (as_json or full):
        raise SystemExit(f"{prog}: --part cannot be combined with --json or --full")

    plan: dict[str, object] | None = None
    plan_text: str | None = None
    if session_arg is not None:
        sess = session_arg.split("/", 1)[0] if session_arg.endswith("/0") else session_arg
        if not re.fullmatch(r"[A-Za-z0-9._-]+", sess):
            raise SystemExit(f"{prog}: invalid session name: {session_arg!r}")
        sdir = BASE_DIR / sess
        if not sdir.is_dir():
            raise SystemExit(f"{prog}: session {sess!r} not found in {BASE_DIR}")
        plan = load_session_bundle_plan(sdir)
        if plan is None:
            raise SystemExit(f"{prog}: no bundle data found for session {sess!r}")
        session_arg = sess
        bundle_file = sdir / "0"
        if bundle_file.is_file():
            plan_text = bundle_file.read_text(encoding="utf-8", errors="replace")
    else:
        if stdin_text is None:
            if sys.stdin.isatty():
                sys.stderr.write(
                    f"{prog}: --bundle-plan expects a session name or a bundle on stdin "
                    f"(e.g. '{prog} --bundle-plan s1' or 'cat bundle.txt | {prog} --bundle-plan')\n"
                )
                return 2
            stdin_text = sys.stdin.read()
        stdin_headers, raw_body = parse_stdin_preamble(stdin_text)
        boundary = get_bundle_boundary(stdin_headers)
        plan_text, plan = parse_bundle_fragments(raw_body, boundary=boundary)

    if part_no is not None:
        target = f"{session_arg}/0" if session_arg is not None else "stdin"
        if plan_text is None:
            raise SystemExit(f"{prog}: bundle text for {target} not found")
        try:
            entry, chunk = extract_bundle_part(plan, plan_text, part_no)
        except ValueError as exc:
            raise SystemExit(f"{prog}: {target}: {exc}")
        sys.stderr.write(format_part_header(target, entry, int(plan.get("part_count") or 0)))
        sys.stdout.write(chunk)
        sys.stdout.flush()
        return 0

    if as_json:
        payload = dict(plan)
        if session_arg is not None:
            payload["session"] = session_arg
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(format_bundle_plan_text(plan, full=full, session=session_arg))
    sys.stdout.flush()
    return 0
