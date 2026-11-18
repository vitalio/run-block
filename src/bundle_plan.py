BUNDLE_BOUNDARY_HEADER = "bundle-boundary"
BUNDLE_EXPOSE_HEADER = "bundle-expose"
BUNDLE_HIDE_HEADER = "bundle-hide"

SECTION_HEADER_RE = re.compile(r"^={5,}\s*(.+?)\s*={5,}$")


def is_bundle_transport_header(key: str) -> bool:
    norm = re.sub(r"\s+", "-", key.strip().lower())
    return norm.startswith("bundle-")


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
        norm = re.sub(r"\s+", "-", k.strip().lower())
        if norm.startswith("bundle-"):
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


def _build_bundle_plan(
    protocol: str,
    boundary: str | None,
    raw_parts: list[tuple[dict[str, object], list[str]]],
) -> dict[str, object]:
    parts: list[dict[str, object]] = []
    total_lines = 0
    total_bytes = 0
    total_gpt = 0
    total_claude = 0
    gpt_exact = gpt_encoder() is not None

    for idx, (meta, part_lines) in enumerate(raw_parts, 1):
        part_text = "\n".join(part_lines) + ("\n" if part_lines else "")
        tok = count_tokens(part_text.encode("utf-8"))
        gpt_exact = bool(tok["gpt_exact"])
        lines_cnt = int(tok["lines"])
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
        entry["bytes"] = bytes_cnt
        entry["gpt"] = gpt_cnt
        entry["claude"] = claude_cnt

        total_lines += lines_cnt
        total_bytes += bytes_cnt
        total_gpt += gpt_cnt
        total_claude += claude_cnt
        parts.append(entry)

    for entry in parts:
        if total_gpt > 0:
            share = round(int(entry["gpt"]) * 100.0 / total_gpt, 1)
        elif total_bytes > 0:
            share = round(int(entry["bytes"]) * 100.0 / total_bytes, 1)
        else:
            share = 0.0
        entry["share_pct"] = share

    return {
        "protocol": protocol,
        "boundary": boundary or None,
        "part_count": len(parts),
        "lines": total_lines,
        "bytes": total_bytes,
        "gpt": total_gpt,
        "claude": total_claude,
        "gpt_exact": gpt_exact,
        "parts": parts,
    }


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
    return clean_body, _build_bundle_plan(protocol, boundary_val, raw_parts)


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
                elif any(x.strip() for x in unframed_lines):
                    raw_parts.append((_infer_section_meta(None, is_sections=True, is_preamble=(found_markers == 1)), unframed_lines))
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
        elif any(x.strip() for x in unframed_lines):
            raw_parts.append((_infer_section_meta(None, is_sections=True, is_preamble=False), unframed_lines))

        if found_markers > 0:
            clean_body = "\n".join(stripped_lines)
            clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip("\n")
            return clean_body, _build_bundle_plan("boundary", boundary_val, raw_parts)

    return _split_section_fallback(norm_text, boundary_val)


def refresh_bundle_plan_meta(sdir: Path, bundle_path: Path) -> None:
    if not bundle_path.is_file():
        return
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    _, body = parse_stdin_preamble(text)
    meta_hdrs = _parse_meta_header_items(sdir)
    boundary = get_bundle_boundary(meta_hdrs)
    _, plan = parse_bundle_fragments(body, boundary=boundary)
    update_session_meta(sdir, bundle_plan=plan)
