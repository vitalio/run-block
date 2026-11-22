BUNDLE_BOUNDARY_HEADER = "bundle-boundary"
BUNDLE_EXPOSE_HEADER = "bundle-expose"
BUNDLE_HIDE_HEADER = "bundle-hide"
BUNDLE_PROTOCOL_HEADER = "bundle-protocol"
SUPPORTED_BUNDLE_PROTOCOLS = ("1",)
TASK_CONTEXT_KINDS = ("task", "context")
DEFAULT_BUNDLE_TOKEN_BUDGET = 100000
DEFAULT_FRAGMENT_MAX_TOKENS = 20000
DEDUP_MIN_LINES = 3
OVERLAP_MIN_LINES = 5
OVERLAP_MIN_CHARS = 200

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
        rel = Path("agents/blocks/pwsh.md" if is_ps else "agents/blocks/bash.md")
        src_path = Path(__file__).resolve().parent.parent / rel
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


def get_bundle_protocol(headers: list[tuple[str, str]]) -> str | None:
    transport = extract_bundle_transport_headers(headers)
    val = transport.get(BUNDLE_PROTOCOL_HEADER, "").strip()
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


def _normalize_part_payload_lines(part_lines: list[str]) -> list[str]:
    lines = list(part_lines)
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and SECTION_HEADER_RE.match(lines[0].strip()):
        lines.pop(0)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines

def _comparable_payload(part_lines: list[str]) -> list[str]:
    return [ln.rstrip() for ln in _normalize_part_payload_lines(part_lines)]

def _is_sub_slice(needle: list[str], hay: list[str]) -> bool:
    span = len(needle)
    if span == 0 or span > len(hay):
        return False
    for pos in range(len(hay) - span + 1):
        if hay[pos] == needle[0] and hay[pos:pos + span] == needle:
            return True
    return False

def _find_dedup_source(
    norm: list[str],
    kept: list[tuple[int, list[str], str]],
) -> tuple[int, str] | None:
    non_empty = sum(1 for ln in norm if ln)
    for idx, kept_norm, label in kept:
        if norm == kept_norm:
            return idx, label
        if non_empty >= DEDUP_MIN_LINES and _is_sub_slice(norm, kept_norm):
            return idx, label
    return None

def _dedupe_fragments(
    raw_parts: list[tuple[dict[str, object], list[str]]],
    spans: list[tuple[int, int] | None],
    stripped_lines: list[str],
) -> tuple[list[tuple[dict[str, object], list[str]]], list[str], list[dict[str, object]]]:
    kept_parts: list[tuple[dict[str, object], list[str]]] = []
    kept_norms: list[tuple[int, list[str], str]] = []
    dropped: set[int] = set()
    warns: list[dict[str, object]] = []
    for (meta, part_lines), span in zip(raw_parts, spans):
        norm = _comparable_payload(part_lines)
        src = None
        if span is not None and any(norm) and str(meta.get("kind") or "").lower() != "prompt":
            src = _find_dedup_source(norm, kept_norms)
        if src is None:
            kept_parts.append((meta, part_lines))
            kept_norms.append((len(kept_parts), norm, _part_label(dict(meta))))
            continue
        kept_idx, kept_label = src
        dropped.update(range(span[0], span[1]))
        dup_label = _part_label(dict(meta))
        saved_gpt = int(count_tokens(("\n".join(part_lines) + "\n").encode("utf-8"))["gpt"])
        warns.append(
            {
                "code": "fragment_deduped",
                "severity": "warn",
                "part_index": kept_idx,
                "part_name": kept_label,
                "removed_name": dup_label,
                "saved_lines": len(part_lines),
                "saved_gpt": saved_gpt,
                "message": (
                    f"dropped duplicate fragment {dup_label!r}: same text as #{kept_idx} "
                    f"({kept_label}); saved {len(part_lines)} lines, ~{_human_tok(saved_gpt)} tokens"
                ),
            }
        )
    if not dropped:
        return kept_parts, stripped_lines, warns
    new_lines = [ln for i, ln in enumerate(stripped_lines) if i not in dropped]
    return kept_parts, new_lines, warns

def _longest_shared_block(a: list[str], b: list[str]) -> tuple[int, int]:
    positions: dict[str, list[int]] = {}
    for i, ln in enumerate(a):
        positions.setdefault(ln, []).append(i)
    best_size, best_a = 0, 0
    prev: dict[int, int] = {}
    for ln in b:
        cur: dict[int, int] = {}
        for i in positions.get(ln, ()):
            run = prev.get(i - 1, 0) + 1
            cur[i] = run
            if run > best_size:
                best_size, best_a = run, i - run + 1
        prev = cur
    return best_size, best_a

def _detect_fragment_overlaps(
    parts: list[dict[str, object]],
    part_lines_list: list[list[str]],
) -> list[dict[str, object]]:
    norms = [[ln for ln in _comparable_payload(pl) if ln] for pl in part_lines_list]
    warns: list[dict[str, object]] = []
    for j in range(min(len(norms), len(parts))):
        later = norms[j]
        if len(later) < OVERLAP_MIN_LINES:
            continue
        later_set = set(later)
        later_chars = len("\n".join(later))
        for i in range(j):
            earlier = norms[i]
            if len(earlier) < OVERLAP_MIN_LINES or len(later_set & set(earlier)) < OVERLAP_MIN_LINES:
                continue
            size, a_start = _longest_shared_block(earlier, later)
            if size < OVERLAP_MIN_LINES or size == len(later):
                continue
            shared_chars = len("\n".join(earlier[a_start:a_start + size]))
            if shared_chars < OVERLAP_MIN_CHARS:
                continue
            pct = round(shared_chars * 100.0 / later_chars) if later_chars else 0
            earlier_idx = int(parts[i].get("index") or (i + 1))
            label = _part_label(parts[j])
            warns.append(
                {
                    "code": "fragment_overlap",
                    "severity": "warn",
                    "part_index": int(parts[j].get("index") or (j + 1)),
                    "part_name": label,
                    "overlap_with": earlier_idx,
                    "shared_lines": size,
                    "shared_chars": shared_chars,
                    "message": (
                        f"fragment {label!r} overlaps #{earlier_idx} ({_part_label(parts[i])}): "
                        f"{size} shared lines, {pct}% of this fragment"
                    ),
                }
            )
    return warns

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
        if kind in TASK_CONTEXT_KINDS and part_lines_list is not None and idx_0 < len(part_lines_list):
            if not any(ln.strip() for ln in part_lines_list[idx_0]):
                warnings.append(
                    {
                        "code": "fragment_empty",
                        "severity": "warn",
                        "part_index": idx,
                        "part_name": label,
                        "message": f"{kind} fragment {label!r} is empty",
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
    if part_lines_list is not None:
        warnings.extend(_detect_fragment_overlaps(parts, part_lines_list))
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
