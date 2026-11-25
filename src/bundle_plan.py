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


def _preamble_prefix_and_offset(full_text: str) -> tuple[str, int]:
    try:
        preamble_headers, body = parse_stdin_preamble(full_text)
    except Exception:
        return "", 0
    if not preamble_headers:
        return "", 0
    norm = full_text.replace("\r\n", "\n")
    if not body.strip():
        return norm, norm.count("\n")
    lines = norm.splitlines(keepends=True)
    sep_idx: int | None = None
    for idx, line in enumerate(lines):
        if not line.strip():
            sep_idx = idx
            break
    if sep_idx is None:
        return "", 0
    body_idx = sep_idx + 1
    while body_idx < len(lines) and not lines[body_idx].strip():
        body_idx += 1
    prefix = "".join(lines[:body_idx])
    return prefix, body_idx


def _body_line_offset(full_text: str) -> int:
    _, offset = _preamble_prefix_and_offset(full_text)
    return offset


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
        preamble_headers, _ = parse_stdin_preamble(full_text)
    except Exception:
        preamble_headers = []
    prefix, offset = _preamble_prefix_and_offset(full_text)
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
                    for ref_key in ("part_index", "overlap_with"):
                        if isinstance(qw.get(ref_key), int):
                            qw[ref_key] = int(qw[ref_key]) + 1
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
            "kind": normalize_fragment_kind(meta.get("kind"), default="part"),
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
        part_spans: list[tuple[int, int] | None] = []
        cur_start = 0
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
                    part_spans.append((cur_start, len(stripped_lines)))
                else:
                    raw_parts.extend(_collect_unframed_parts(unframed_lines, is_first=(len(raw_parts) == 0)))
                    part_spans.extend([None] * (len(raw_parts) - len(part_spans)))
                unframed_lines = []
                in_part = True
                cur_start = len(stripped_lines)
                cur_lines = []
                cur_meta = {}
                raw_json = m_part.group(1)
                if raw_json:
                    try:
                        parsed = json.loads(raw_json)
                        if isinstance(parsed, dict):
                            cur_meta = dict(parsed)
                            if "kind" in cur_meta:
                                cur_meta["kind"] = normalize_fragment_kind(cur_meta.get("kind"), default="part")
                    except ValueError:
                        cur_meta = {"kind": "part"}
                continue

            if end_re.match(line):
                found_markers += 1
                if in_part:
                    raw_parts.append((cur_meta, cur_lines))
                    part_spans.append((cur_start, len(stripped_lines)))
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
            part_spans.append((cur_start, len(stripped_lines)))
        else:
            raw_parts.extend(_collect_unframed_parts(unframed_lines, is_first=(len(raw_parts) == 0)))
            part_spans.extend([None] * (len(raw_parts) - len(part_spans)))

        if found_markers > 0:
            raw_parts, stripped_lines, dedup_warns = _dedupe_fragments(raw_parts, part_spans, stripped_lines)
            clean_body = "\n".join(stripped_lines)
            clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip("\n")
            plan = _build_bundle_plan("boundary", boundary_val, raw_parts)
            plan["warnings"] = dedup_warns + list(plan["warnings"])
            _assign_part_ranges(plan, raw_parts, clean_body, collapse_blanks=True)
            if clean_body:
                plan = reconcile_bundle_plan(plan, clean_body + "\n", track_lines=False)
            return clean_body, plan

    return _split_section_fallback(norm_text, boundary_val)


def _is_trailing_root_prompt_part(entry: dict[str, object]) -> bool:
    return normalize_fragment_kind(entry.get("kind")) == "prompt" and not _resolve_part_chain(entry)


def refresh_bundle_plan_after_edit(
    prev_plan: dict[str, object] | None,
    parsed_plan: dict[str, object],
    text: str,
) -> dict[str, object] | None:
    if not (
        isinstance(prev_plan, dict)
        and prev_plan.get("protocol") == "boundary"
        and parsed_plan.get("protocol") != "boundary"
    ):
        return None
    prev_parts = [dict(p) for p in (prev_plan.get("parts") or []) if isinstance(p, dict)]
    non_hdr = [p for p in prev_parts if str(p.get("kind") or "") != "header"]
    if not non_hdr:
        return None
    has_trailing_root_prompt = _is_trailing_root_prompt_part(non_hdr[-1])
    fixed_parts = non_hdr[:-1] if has_trailing_root_prompt else non_hdr
    lines = text.splitlines()
    last_fixed_end = 0
    for p in fixed_parts:
        ls, le = p.get("line_start"), p.get("line_end")
        if not isinstance(ls, int) or not isinstance(le, int) or ls < 1 or le > len(lines):
            return None
        last_fixed_end = max(last_fixed_end, int(le))
    if last_fixed_end <= 0 or last_fixed_end > len(lines):
        return None
    tail_start = last_fixed_end + 1
    while tail_start <= len(lines) and not lines[tail_start - 1].strip():
        tail_start += 1
    tail_end = len(lines)
    while tail_end >= tail_start and not lines[tail_end - 1].strip():
        tail_end -= 1
    if tail_start > tail_end:
        return None
    tail_lines = lines[tail_start - 1 : tail_end]
    first_tail = tail_lines[0].strip()
    m_sec = SECTION_HEADER_RE.match(first_tail)
    if not (m_sec and m_sec.group(1).strip().lower() == "prompt"):
        return None
    p_text = "\n".join(tail_lines) + "\n"
    tok = count_tokens(p_text.encode("utf-8"))
    if has_trailing_root_prompt:
        p_entry = dict(non_hdr[-1])
        non_hdr[-1] = p_entry
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
    return reconcile_bundle_plan(kept_plan, text, track_lines=False)


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
    reconciled_edit = refresh_bundle_plan_after_edit(prev_plan, parsed_plan, text)
    if reconciled_edit is not None:
        update_session_meta(sdir, bundle_plan=reconciled_edit)
        return
    raw_path.unlink(missing_ok=True)
    plan = reconcile_bundle_plan(parsed_plan, text)
    update_session_meta(sdir, bundle_plan=plan)

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
