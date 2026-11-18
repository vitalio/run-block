BUNDLE_BOUNDARY_HEADER = "bundle-boundary"
BUNDLE_EXPOSE_HEADER = "bundle-expose"
BUNDLE_HIDE_HEADER = "bundle-hide"
DEFAULT_BUNDLE_TOKEN_BUDGET = 100000
DEFAULT_FRAGMENT_MAX_TOKENS = 20000

SECTION_HEADER_RE = re.compile(r"^={5,}\s*(.+?)\s*={5,}$")


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
    hdr = plan.get("header") if isinstance(plan.get("header"), dict) else None
    total_chars = int(plan.get("chars") if plan.get("chars") is not None else (plan.get("bytes") or 0))
    total_bytes = int(plan.get("bytes") or 0)
    denom = total_chars if total_chars > 0 else total_bytes
    use_chars = total_chars > 0
    for entry in parts:
        val = _part_chars(entry) if use_chars else int(entry.get("bytes") or 0)
        entry["share_pct"] = round(val * 100.0 / denom, 1) if denom > 0 else 0.0
    if hdr is not None:
        hval = _part_chars(hdr) if use_chars else int(hdr.get("bytes") or 0)
        hdr["share_pct"] = round(hval * 100.0 / denom, 1) if denom > 0 else 0.0


def reconcile_bundle_plan(plan: dict[str, object], full_text: str) -> dict[str, object]:
    out = dict(plan)
    parts = [p for p in (out.get("parts") or []) if isinstance(p, dict)]
    out["parts"] = parts
    sum_lines = sum(int(p.get("lines") or 0) for p in parts)
    sum_chars = sum(_part_chars(p) for p in parts)
    sum_bytes = sum(int(p.get("bytes") or 0) for p in parts)
    sum_gpt = sum(int(p.get("gpt") or 0) for p in parts)
    sum_claude = sum(int(p.get("claude") or 0) for p in parts)
    full_tok = count_tokens(full_text.encode("utf-8"))
    f_lines = int(full_tok["lines"])
    f_chars = int(full_tok["chars"])
    f_bytes = int(full_tok["bytes"])
    f_gpt = int(full_tok["gpt"])
    f_claude = int(full_tok["claude"])
    rem_lines = f_lines - sum_lines
    rem_chars = f_chars - sum_chars
    rem_bytes = f_bytes - sum_bytes
    if (rem_lines > 0 or rem_chars > 0) and f_chars >= sum_chars and f_lines >= sum_lines:
        out["lines"] = f_lines
        out["chars"] = f_chars
        out["bytes"] = f_bytes
        out["gpt"] = f_gpt
        out["claude"] = f_claude
        out["gpt_exact"] = bool(full_tok["gpt_exact"])
        out["header"] = {
            "kind": "header",
            "name": "Headers & spacing",
            "lines": max(0, rem_lines),
            "chars": max(0, rem_chars),
            "bytes": max(0, rem_bytes),
            "gpt": max(0, f_gpt - sum_gpt),
            "claude": max(0, f_claude - sum_claude),
        }
    else:
        out.pop("header", None)
        out["lines"] = sum_lines
        out["chars"] = sum_chars
        out["bytes"] = sum_bytes
        out["gpt"] = sum_gpt
        out["claude"] = sum_claude
    _recompute_share_pct(out)
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
    gpt_exact = gpt_encoder() is not None

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
    if clean_body:
        plan = reconcile_bundle_plan(plan, clean_body + "\n")
    return clean_body, plan


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
                    real_unframed = [ln for ln in unframed_lines if not SECTION_HEADER_RE.match(ln.strip())]
                    while real_unframed and not real_unframed[0].strip():
                        real_unframed.pop(0)
                    while real_unframed and not real_unframed[-1].strip():
                        real_unframed.pop()
                    if any(x.strip() for x in real_unframed):
                        raw_parts.append((_infer_section_meta(None, is_sections=True, is_preamble=(len(raw_parts) == 0)), real_unframed))
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
            real_unframed = [ln for ln in unframed_lines if not SECTION_HEADER_RE.match(ln.strip())]
            while real_unframed and not real_unframed[0].strip():
                real_unframed.pop(0)
            while real_unframed and not real_unframed[-1].strip():
                real_unframed.pop()
            if any(x.strip() for x in real_unframed):
                raw_parts.append((_infer_section_meta(None, is_sections=True, is_preamble=(len(raw_parts) == 0)), real_unframed))

        if found_markers > 0:
            clean_body = "\n".join(stripped_lines)
            clean_body = re.sub(r"\n{3,}", "\n\n", clean_body).strip("\n")
            plan = _build_bundle_plan("boundary", boundary_val, raw_parts)
            if clean_body:
                plan = reconcile_bundle_plan(plan, clean_body + "\n")
            return clean_body, plan

    return _split_section_fallback(norm_text, boundary_val)


def refresh_bundle_plan_meta(sdir: Path, bundle_path: Path) -> None:
    if not bundle_path.is_file():
        return
    text = bundle_path.read_text(encoding="utf-8", errors="replace")
    _, body = parse_stdin_preamble(text)
    meta_hdrs = _parse_meta_header_items(sdir)
    boundary = get_bundle_boundary(meta_hdrs)
    _, plan = parse_bundle_fragments(body, boundary=boundary)
    plan = reconcile_bundle_plan(plan, text)
    update_session_meta(sdir, bundle_plan=plan)


def _format_tok_pair(gpt_cnt: int, claude_cnt: int) -> str:
    lo = min(gpt_cnt, claude_cnt)
    hi = max(gpt_cnt, claude_cnt)
    return f"~{_human_tok(lo)}–{_human_tok(hi)} tok" if lo != hi else f"~{_human_tok(lo)} tok"


def _new_tree_node(name: str, chain: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "chain": list(chain),
        "items": [],
        "children_by_name": {},
        "direct_parts": [],
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


def _node_display_kind(node: dict[str, object]) -> str:
    kinds = node.get("kinds") or []
    return str(kinds[0]) if isinstance(kinds, list) and len(kinds) == 1 else "bundle"


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
    num: int | None = None,
) -> dict[str, object]:
    return {
        "pct_str": f"{share_pct:.1f}%",
        "chars_str": _human_chars(chars_cnt, short=True),
        "lines_str": f"{lines_cnt}L",
        "tok_str": _format_tok_pair(gpt_cnt, claude_cnt),
        "kind": kind,
        "tree_prefix": tree_prefix,
        "num": num,
        "desc": desc,
    }


def _part_extras_suffix(p: dict[str, object], *, include_ms: bool = True) -> str:
    extras: list[str] = []
    rc_val = p.get("rc")
    if isinstance(rc_val, int) and (include_ms or rc_val != 0):
        extras.append(f"rc={rc_val}")
    if include_ms and "ms" in p:
        extras.append(f"{p['ms']}ms")
    return f" ({', '.join(extras)})" if extras else ""


def _collect_hierarchy_rows(plan: dict[str, object], *, details: bool) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    hdr = plan.get("header")
    if isinstance(hdr, dict) and (_part_chars(hdr) > 0 or int(hdr.get("lines") or 0) > 0):
        rows.append(
            _make_table_row(
                kind="header",
                desc=str(hdr.get("name") or "Headers & spacing"),
                lines_cnt=int(hdr.get("lines") or 0),
                chars_cnt=_part_chars(hdr),
                gpt_cnt=int(hdr.get("gpt") or 0),
                claude_cnt=int(hdr.get("claude") or 0),
                share_pct=float(hdr.get("share_pct") or 0.0),
            )
        )
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    root_items = _build_bundle_tree(parts)

    def _emit_part(p: dict[str, object], parent_name: str, ancestors_more: list[bool], is_last: bool | None) -> None:
        t_pfx = _tree_connector(ancestors_more, is_last) if is_last is not None else ""
        raw_lbl = _part_label(p)
        lbl = _child_rel_label(parent_name, raw_lbl) if parent_name else raw_lbl
        lbl += _part_extras_suffix(p, include_ms=details)
        p_idx = int(p["index"]) if (details and isinstance(p.get("index"), int)) else None
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
                num=p_idx,
            )
        )

    def _emit_node(node: dict[str, object], ancestors_more: list[bool], is_last: bool | None) -> None:
        t_pfx = _tree_connector(ancestors_more, is_last) if is_last is not None else ""
        has_children = bool(node.get("children_by_name"))
        direct_parts: list[dict[str, object]] = list(node.get("direct_parts") or [])  # type: ignore[arg-type]
        if not has_children and len(direct_parts) == 1:
            p = direct_parts[0]
            lbl = _join_chain_label([str(node["name"])], _part_label(p)) + _part_extras_suffix(p, include_ms=details)
            p_idx = int(p["index"]) if (details and isinstance(p.get("index"), int)) else None
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
                    num=p_idx,
                )
            )
            return
        cnt = int(node.get("total_count") or 0)
        rc_errs = int(node.get("rc_errors") or 0)
        lbl = f"{node['name']} ({cnt})" + (f" ({rc_errs} rc!=0)" if rc_errs else "")
        rows.append(
            _make_table_row(
                kind=_node_display_kind(node),
                desc=lbl,
                lines_cnt=int(node.get("lines") or 0),
                chars_cnt=int(node.get("chars") or 0),
                gpt_cnt=int(node.get("gpt") or 0),
                claude_cnt=int(node.get("claude") or 0),
                share_pct=float(node.get("share_pct") or 0.0),
                tree_prefix=t_pfx,
            )
        )
        if details or has_children:
            child_items: list[tuple[str, dict[str, object]]] = list(node.get("items") or [])  # type: ignore[arg-type]
            next_anc = ([*ancestors_more, not is_last] if is_last is not None else [])
            for c_idx, (c_type, c_obj) in enumerate(child_items):
                c_last = c_idx == len(child_items) - 1
                if c_type == "node":
                    _emit_node(c_obj, next_anc, c_last)
                else:
                    _emit_part(c_obj, str(node["name"]), next_anc, c_last)

    for it_type, it_obj in root_items:
        if it_type == "node":
            _emit_node(it_obj, [], None)
        else:
            _emit_part(it_obj, "", [], None)
    return rows


def _render_bundle_table(rows: list[dict[str, object]], max_width: int, indent: str = "  ") -> list[str]:
    if not rows:
        return []
    w_pct = max(len(str(r["pct_str"])) for r in rows)
    w_ch = max(len(str(r["chars_str"])) for r in rows)
    w_ln = max(len(str(r["lines_str"])) for r in rows)
    w_tok = max(len(str(r["tok_str"])) for r in rows)
    w_kind = max(len(f"[{r['kind']}]") for r in rows)
    nums = [r["num"] for r in rows if r.get("num") is not None]
    num_w = max((len(f"{n}.") for n in nums), default=0)

    out: list[str] = []
    for r in rows:
        kind_col = f"[{r['kind']}]".ljust(w_kind)
        cols_prefix = (
            f"{indent}{str(r['pct_str']).rjust(w_pct)} "
            f"{str(r['chars_str']).rjust(w_ch)} "
            f"{str(r['lines_str']).rjust(w_ln)} "
            f"{str(r['tok_str']).rjust(w_tok)}  "
            f"{kind_col}  "
        )
        t_pfx = str(r.get("tree_prefix") or "")
        n_val = r.get("num")
        n_pfx = (f"{n_val}.".rjust(num_w) + " ") if n_val is not None else ""
        full_pfx = f"{cols_prefix}{t_pfx}{n_pfx}"
        sub_indent = " " * display_width(full_pfx)
        avail = max(16, max_width - display_width(full_pfx))
        desc = str(r.get("desc") or "")
        wrapped = textwrap.wrap(desc, width=avail, break_long_words=True, break_on_hyphens=False) or [desc]
        out.append(full_pfx + wrapped[0])
        for cont in wrapped[1:]:
            out.append(sub_indent + cont)
    return out


def format_bundle_summary_lines(plan: dict[str, object], max_width: int = 120) -> list[str]:
    return _render_bundle_table(_collect_hierarchy_rows(plan, details=False), max_width=max_width)


def format_bundle_parts_lines(plan: dict[str, object], max_width: int = 120) -> list[str]:
    return _render_bundle_table(_collect_hierarchy_rows(plan, details=True), max_width=max_width)


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
    if full_text is not None and "header" not in out:
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
    as_json = False
    full = False
    session_arg: str | None = None
    for a in argv:
        if a == "--json":
            as_json = True
        elif a == "--full":
            full = True
        elif a.startswith("-"):
            raise SystemExit(f"{prog}: usage: {prog} --bundle-plan [<session>] [--json] [--full]")
        elif session_arg is None:
            session_arg = a
        else:
            raise SystemExit(f"{prog}: usage: {prog} --bundle-plan [<session>] [--json] [--full]")

    plan: dict[str, object] | None = None
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
        _, plan = parse_bundle_fragments(raw_body, boundary=boundary)

    if as_json:
        payload = dict(plan)
        if session_arg is not None:
            payload["session"] = session_arg
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(format_bundle_plan_text(plan, full=full, session=session_arg))
    sys.stdout.flush()
    return 0
