BUNDLE_BOUNDARY_HEADER = "bundle-boundary"
BUNDLE_EXPOSE_HEADER = "bundle-expose"
BUNDLE_HIDE_HEADER = "bundle-hide"
DEFAULT_BUNDLE_TOKEN_BUDGET = 100000
DEFAULT_FRAGMENT_MAX_TOKENS = 20000

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


def group_bundle_parts(parts: list[dict[str, object]]) -> list[dict[str, object]]:
    buckets: dict[tuple[str, str], dict[str, object]] = {}
    order: list[tuple[str, str]] = []
    for entry in parts:
        kind = str(entry.get("kind") or "part")
        group = str(entry.get("group") or "")
        key = (kind, group)
        if key not in buckets:
            order.append(key)
            buckets[key] = {
                "kind": kind,
                "group": group,
                "count": 0,
                "lines": 0,
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

    warnings = analyze_bundle_warnings(
        parts,
        part_texts=part_texts,
        part_lines_list=part_lines_list,
        total_gpt=total_gpt,
    )

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
        "warnings": warnings,
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


def _format_tok_pair(gpt_cnt: int, claude_cnt: int) -> str:
    lo = min(gpt_cnt, claude_cnt)
    hi = max(gpt_cnt, claude_cnt)
    return f"~{_human_tok(lo)}–{_human_tok(hi)} tok" if lo != hi else f"~{_human_tok(lo)} tok"


def format_bundle_group_items(plan: dict[str, object]) -> list[tuple[str, str]]:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    if not parts:
        return []
    groups = group_bundle_parts(parts)
    items: list[tuple[str, str]] = []
    for g in groups:
        kind = str(g.get("kind") or "part")
        grp = str(g.get("group") or "")
        cnt = int(g.get("count") or 0)
        names = list(g.get("names") or [])
        if grp:
            if cnt == 1 and names and names[0] != grp:
                lbl = f"{grp}: {names[0]}"
            elif cnt > 1:
                lbl = f"{grp} ({cnt})"
            else:
                lbl = grp
        elif cnt == 1 and names:
            lbl = str(names[0])
        else:
            lbl = f"{cnt} part" + ("s" if cnt != 1 else "")
        lines_cnt = int(g.get("lines") or 0)
        gpt_cnt = int(g.get("gpt") or 0)
        claude_cnt = int(g.get("claude") or 0)
        share = float(g.get("share_pct") or 0.0)
        err_cnt = int(g.get("rc_errors") or 0)
        meta = f"{lines_cnt}L · {_format_tok_pair(gpt_cnt, claude_cnt)} ({share:.1f}%)"
        if err_cnt:
            meta += f" · {err_cnt} rc!=0"
        items.append((kind, f"{lbl}  [{meta}]"))
    return items


def format_bundle_part_items(plan: dict[str, object]) -> list[tuple[str, str]]:
    parts = [p for p in (plan.get("parts") or []) if isinstance(p, dict)]
    items: list[tuple[str, str]] = []
    for p in parts:
        kind = str(p.get("kind") or "part")
        lbl = _part_label(p)
        grp = str(p.get("group") or "")
        if grp and grp != lbl:
            lbl = f"{grp}: {lbl}"
        lines_cnt = int(p.get("lines") or 0)
        bytes_cnt = int(p.get("bytes") or 0)
        gpt_cnt = int(p.get("gpt") or 0)
        claude_cnt = int(p.get("claude") or 0)
        share = float(p.get("share_pct") or 0.0)
        extras: list[str] = [f"{lines_cnt}L", _human_size(bytes_cnt), f"{_format_tok_pair(gpt_cnt, claude_cnt)} ({share:.1f}%)"]
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


def _enrich_bundle_plan(plan: dict[str, object]) -> dict[str, object]:
    out = dict(plan)
    parts = [p for p in (out.get("parts") or []) if isinstance(p, dict)]
    if "warnings" not in out:
        out["warnings"] = analyze_bundle_warnings(parts, total_gpt=int(out.get("gpt") or 0))
    return out


def load_session_bundle_plan(sdir: Path | None, bundle_path: Path | None = None) -> dict[str, object] | None:
    meta = read_session_meta(sdir) if sdir is not None else {}
    raw_plan = meta.get("bundle_plan")
    bpath = bundle_path if bundle_path is not None else (sdir / "0" if sdir is not None else None)
    if isinstance(raw_plan, dict) and "parts" in raw_plan and "warnings" in raw_plan:
        return _enrich_bundle_plan(raw_plan)
    if bpath is not None and bpath.is_file():
        text = bpath.read_text(encoding="utf-8", errors="replace")
        _, body = parse_stdin_preamble(text)
        meta_hdrs = _parse_meta_header_items(sdir) if sdir is not None else []
        boundary = get_bundle_boundary(meta_hdrs)
        _, parsed_plan = parse_bundle_fragments(body, boundary=boundary)
        if isinstance(raw_plan, dict) and raw_plan.get("protocol") == "boundary" and parsed_plan.get("protocol") != "boundary":
            return _enrich_bundle_plan(raw_plan)
        return parsed_plan
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
    bytes_cnt = int(plan.get("bytes") or 0)
    gpt_cnt = int(plan.get("gpt") or 0)
    claude_cnt = int(plan.get("claude") or 0)
    hdr_target = session if session else "stdin"
    out_lines: list[str] = [
        f"Bundle Plan ({hdr_target}, protocol: {protocol}):",
        f"Total: {lines_cnt} line{'s' if lines_cnt != 1 else ''} · {_human_size(bytes_cnt)} · {_format_tok_pair(gpt_cnt, claude_cnt)} ({part_cnt} part{'s' if part_cnt != 1 else ''})",
    ]
    grp_items = format_bundle_group_items(plan)
    if grp_items:
        out_lines.append("")
        out_lines.append(f"Summary ({part_cnt} part{'s' if part_cnt != 1 else ''}):")
        out_lines.extend(_wrap_labeled_items(grp_items, 120, indent="  "))
    if full:
        part_items = format_bundle_part_items(plan)
        if part_items:
            out_lines.append("")
            out_lines.append(f"Parts ({part_cnt}):")
            step_nums = [int(p.get("index") or i) for i, p in enumerate(plan.get("parts") or [], 1) if isinstance(p, dict)]
            out_lines.extend(_wrap_labeled_items(part_items, 120, indent="  ", step_nums=step_nums))
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
