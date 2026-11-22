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


def _part_extras_suffix(p: dict[str, object]) -> str:
    extras: list[str] = []
    rc_val = p.get("rc")
    if isinstance(rc_val, int):
        extras.append(f"rc={rc_val}")
    if "ms" in p:
        extras.append(f"{p['ms']}ms")
    return f" ({', '.join(extras)})" if extras else ""


def _collect_hierarchy_rows(plan: dict[str, object], *, edited: bool = False) -> list[dict[str, object]]:
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
        lbl += _part_extras_suffix(p)
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
            lbl = _join_chain_label([str(node["name"])], _part_label(p)) + _part_extras_suffix(p)
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


def format_bundle_parts_lines(plan: dict[str, object], max_width: int = 120, *, edited: bool = False) -> list[str]:
    return _render_bundle_table(_collect_hierarchy_rows(plan, edited=edited), max_width=max_width)


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

def format_bundle_plan_text(plan: dict[str, object], *, session: str | None = None) -> str:
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
    usage = f"{prog} --bundle-plan [<session>] [--json] [--part N]"
    argv, part_no = parse_part_option(argv, usage)
    as_json = False
    session_arg: str | None = None
    for a in argv:
        if a == "--json":
            as_json = True
        elif a.startswith("-"):
            raise SystemExit(f"{prog}: usage: {usage}")
        elif session_arg is None:
            session_arg = a
        else:
            raise SystemExit(f"{prog}: usage: {usage}")
    if part_no is not None and as_json:
        raise SystemExit(f"{prog}: --part cannot be combined with --json")

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
        sys.stdout.write(format_bundle_plan_text(plan, session=session_arg))
    sys.stdout.flush()
    return 0
