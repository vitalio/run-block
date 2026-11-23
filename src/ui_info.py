def _parse_pager_line(line: str) -> str:
    if line.startswith("\t"):
        return "tab"
    raw = line.strip()
    if raw == "O":
        return "overwrite"
    ans = raw.lower()
    if ans in ("tab", "parts"):
        return "tab"
    if ans in ("j", "down"):
        return "down"
    if ans in ("k", "up"):
        return "up"
    if ans in ("pgdn", "pagedown", "f", "space"):
        return "pgdn"
    if ans in ("pgup", "pageup", "b"):
        return "pgup"
    if ans in ("g", "top", "home"):
        return "top"
    if ans in ("end", "bottom"):
        return "bottom"
    if ans in ("e", "edit"):
        return "edit"
    if ans in ("p", "prompt"):
        return "prompt"
    if ans in ("s", "script"):
        return "script"
    if ans in ("o", "output"):
        return "output"
    if ans == "overwrite":
        return "overwrite"
    if ans in ("v", "view"):
        return "view"
    if ans in ("m", "meta"):
        return "meta"
    if ans == "n":
        return "next_part"
    if raw == "N":
        return "prev_part"
    if ans in ("", "y", "yes", "enter", "copy"):
        return "copy"
    if ans in ("esc", "\x1b"):
        return "esc"
    return "back"


def _read_pager_key(tty_r, *, flush: bool = False) -> str:
    if flush:
        flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        return _parse_pager_line(tty_r.readline())
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        return _parse_pager_line(tty_r.readline())
    try:
        tty.setraw(fd, termios.TCSANOW)
        with _SigwinchWatcher() as win_fd:
            while True:
                if win_fd is not None:
                    try:
                        rlist, _, _ = select.select([fd, win_fd], [], [])
                    except (InterruptedError, OSError):
                        continue
                    if win_fd in rlist:
                        _drain_and_debounce_sigwinch(win_fd)
                        return "resize"
                    if fd not in rlist:
                        continue
                ch = os.read(fd, 1)
                if not ch:
                    return "back"
                if ch == b"\t":
                    return "tab"
                if ch in (b"j", b"J", b"\x0e"):
                    return "down"
                if ch in (b"k", b"K", b"\x10"):
                    return "up"
                if ch in (b" ", b"\x06"):
                    return "pgdn"
                if ch in (b"b", b"B", b"\x02"):
                    return "pgup"
                if ch == b"\x04":
                    return "half_down"
                if ch == b"\x15":
                    return "half_up"
                if ch == b"g":
                    return "top"
                if ch == b"G":
                    return "bottom"
                if ch in (b"\r", b"\n", b"y", b"Y"):
                    return "copy"
                if ch in (b"e", b"E"):
                    return "edit"
                if ch in (b"p", b"P"):
                    return "prompt"
                if ch in (b"s", b"S"):
                    return "script"
                if ch == b"o":
                    return "output"
                if ch == b"O":
                    return "overwrite"
                if ch in (b"v", b"V"):
                    return "view"
                if ch in (b"m", b"M"):
                    return "meta"
                if ch == b"n":
                    return "next_part"
                if ch == b"N":
                    return "prev_part"
                if ch in (b"q", b"Q", b"d", b"D", b"i", b"I", b"\x03"):
                    return "back"
                if ch == b"\x1b":
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                    if not rlist:
                        return "esc"
                    seq = os.read(fd, 32)
                    if seq in (b"[A", b"OA"):
                        return "up"
                    if seq in (b"[B", b"OB"):
                        return "down"
                    if seq == b"[5~":
                        return "pgup"
                    if seq == b"[6~":
                        return "pgdn"
                    if seq in (b"[H", b"[1~", b"OH"):
                        return "top"
                    if seq in (b"[F", b"[4~", b"OF"):
                        return "bottom"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def _apply_pager_scroll(key: str, scroll_top: int, viewport_rows: int) -> int | None:
    if key == "down":
        return scroll_top + 1
    if key == "up":
        return max(0, scroll_top - 1)
    if key == "pgdn":
        return scroll_top + max(1, viewport_rows - 1)
    if key == "pgup":
        return max(0, scroll_top - max(1, viewport_rows - 1))
    if key == "half_down":
        return scroll_top + max(1, viewport_rows // 2)
    if key == "half_up":
        return max(0, scroll_top - max(1, viewport_rows // 2))
    if key == "top":
        return 0
    if key == "bottom":
        return 10**9
    return None


def _compose_pager_frame(
    header_rows: list[str],
    all_items: list[str],
    cols: int,
    rows: int,
    scroll_top: int,
    footer_tail: list[str],
    *,
    scroll_hint: str = "Up/Down j/k PgUp/PgDn: scroll",
    position_label: str | None = None,
    always_hint: bool = False,
) -> tuple[str, int, int]:
    viewport_rows = max(1, rows - len(header_rows) - 1)
    max_scroll = max(0, len(all_items) - viewport_rows)
    clamped_scroll = max(0, min(scroll_top, max_scroll))
    visible = list(all_items[clamped_scroll : clamped_scroll + viewport_rows])
    while len(visible) < viewport_rows:
        visible.append("")

    total_items = len(all_items)
    overflow = total_items > viewport_rows
    footer_parts: list[str] = []
    if position_label:
        footer_parts.append(position_label)
    elif overflow:
        footer_parts.append(f"Lines {clamped_scroll + 1}-{min(total_items, clamped_scroll + viewport_rows)}/{total_items}")
    if overflow or always_hint:
        footer_parts.append(scroll_hint)
    footer_parts.extend(footer_tail)
    footer_raw = " " + " · ".join(footer_parts)
    footer_txt = _truncate_display_width(footer_raw, cols) if display_width(footer_raw) > cols else footer_raw
    if _use_color():
        footer_bar = f"\x1b[7m{footer_txt.ljust(cols)}\x1b[0m"
    else:
        footer_bar = footer_txt

    frame_lines = [*header_rows, *visible, footer_bar]
    frame = "\033[H" + "\r\n".join(f"{ln}\033[K" for ln in frame_lines)
    return frame, clamped_scroll, viewport_rows


def _info_table_rows(sdir: Path | None, bundle_path: Path | None) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    fn_load = globals().get("load_session_bundle_plan")
    fn_rows = globals().get("_collect_hierarchy_rows")
    if not callable(fn_load) or not callable(fn_rows) or sdir is None or bundle_path is None or not bundle_path.is_file():
        return None, []
    plan = fn_load(sdir, bundle_path)
    if not isinstance(plan, dict):
        return None, []
    all_rows = fn_rows(plan)
    numbered = [r for r in all_rows if isinstance(r, dict) and str(r.get("num_str") or "").isdigit()]
    return plan, numbered


def _info_part_total(sdir: Path | None, bundle_path: Path | None) -> int:
    _, numbered = _info_table_rows(sdir, bundle_path)
    return len(numbered)


_PART_ROW_NUM_RE = re.compile(
    r"^\s*(\d+)\s+\d+(?:\.\d+)?%\s+\S+\s+\d+\s+~\S+\s+" + TABLE_TIME_COL_PATTERN + r"\[[a-z0-9_-]+\]"
)


def _find_selectable_part_rows(items: list[str]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    seen_parts: set[int] = set()
    for row_idx, raw_line in enumerate(items):
        plain = ANSI_RE.sub("", raw_line)
        m = _PART_ROW_NUM_RE.match(plain)
        if m:
            pno = int(m.group(1))
            if pno not in seen_parts:
                seen_parts.add(pno)
                found.append((pno, row_idx))
    return found


_STEP_INFO_KINDS = ("START STEP", "END STEP", "SYNTAX ERROR", "NOT RUN", "STEP ALREADY EXISTS")


def _info_operation_steps(
    script_path: Path | None, sdir: Path | None, label: str | None = None
) -> list[dict[str, object]]:
    if script_path is None or not script_path.is_file():
        return []
    try:
        text = script_path.read_text(encoding="utf-8", errors="replace")
        plan = analyze_script(text, work_dir=get_work_dir(sdir), label=label or "", check_syntax=False)
    except Exception:
        return []
    return [
        s for s in (plan.get("operation_steps") or []) if isinstance(s, dict) and int(s.get("line") or 0) > 0
    ]


def _info_meta_path(
    kind: str, sdir: Path | None, script: Path | None, out_path: Path | None
) -> Path | None:
    if kind == "START SESSION":
        cand = sdir / "meta.json" if sdir is not None else None
    else:
        step_dir = script.parent if script is not None else (out_path.parent if out_path is not None else None)
        cand = step_dir / "meta.json" if step_dir is not None else None
    return cand if cand is not None and cand.is_file() else None


def _step_op_timings(
    op_timings: list[dict[str, object]] | None, script: Path | None
) -> list[dict[str, object]]:
    if op_timings is not None:
        return op_timings
    if script is None:
        return []
    ops_meta = read_step_meta(script.parent).get("operations")
    return [x for x in ops_meta if isinstance(x, dict)] if isinstance(ops_meta, list) else []


def _step_part_total(
    kind: str,
    script: Path | None,
    sdir: Path | None,
    label: str,
    op_timings: list[dict[str, object]] | None,
    *,
    has_output: bool,
) -> int:
    steps = _info_operation_steps(script, sdir, label)
    script_edited = _is_file_edited(script, _orig_backup_path(script)) if script is not None else False
    if kind != "START STEP" and has_output and not (script_edited and steps):
        timed = _step_op_timings(op_timings, script)
        if timed:
            return len(timed)
    return len(steps)


def _build_operation_screen(
    label: str,
    op_no: int,
    total: int,
    step: dict[str, object],
    script_path: Path,
    script_lines: list[str],
    timing: dict[str, object] | None,
    failed: bool,
    cols: int,
    rows: int,
    scroll_top: int,
    *,
    can_edit: bool,
    out_path: Path | None = None,
    out_lines: list[str] | None = None,
    has_meta: bool = False,
) -> tuple[str, int, int]:
    tag = str(step.get("tag") or "exec")
    desc = str(step.get("desc") or "").strip()
    line_no = int(step.get("line") or 0)
    end_no = int(step.get("end_line") or line_no)
    hdr = [f"Command: [{tag}] {desc}" if desc else f"Command: [{tag}]"]
    if step.get("dir"):
        hdr.append(f"Directory: {step['dir']}")
    if timing is not None:
        try:
            dur_ms = max(0, int(timing.get("duration_ms") or 0))
        except (TypeError, ValueError):
            dur_ms = 0
        hdr.append(f"Timing: {format_duration(dur_ms / 1000.0)}" + (" (failed)" if failed else ""))
    elif failed:
        hdr.append("Timing: (failed)")
    hdr.append(f"Script-Range: lines {line_no}-{end_no} of {_shorten_home_path(script_path)}")
    footer = ["n/N: next/prev operation"]
    if out_path is not None:
        body = list(out_lines or [])
        out_start = timing.get("out_line_start") if timing is not None else None
        out_end = timing.get("out_line_end") if timing is not None else None
        if isinstance(out_start, int) and isinstance(out_end, int) and out_end >= out_start:
            hdr.append(f"Range: lines {out_start}-{out_end} of {_shorten_home_path(out_path)}")
            body = body[max(0, out_start - 1) : out_end]
        else:
            hdr.append("Range: (no output)")
            body = ["(no output)"]
        shown_path = out_path
        footer.extend(["e(dit)/o(utput)", "s(cript)"])
    else:
        body = script_lines[max(0, line_no - 1) : end_no]
        shown_path = script_path
        footer.append("e(dit)/s(cript)" if can_edit else "")
    if has_meta:
        footer.append("m(eta)")
    footer.append("Esc: back")
    return _build_part_screen(
        label,
        op_no,
        total,
        None,
        body,
        cols,
        rows,
        scroll_top,
        can_edit=can_edit,
        title=f"PART {op_no}/{total} · {label} · {_shorten_home_path(shown_path)}",
        header_kv=hdr,
        footer_tail=[f for f in footer if f],
    )


def _highlight_selected_part_row(line: str, cols: int) -> str:
    plain = ANSI_RE.sub("", line)
    if _use_color():
        padded = _truncate_display_width(plain, cols) if display_width(plain) > cols else plain.ljust(cols)
        return f"\x1b[7m{padded}\x1b[0m"
    if plain.startswith("  "):
        return "> " + plain[2:]
    return ">" + plain


def _build_part_screen(
    label: str,
    part_no: int,
    total: int,
    entry: dict[str, object] | None,
    body_lines: list[str],
    cols: int,
    rows: int,
    scroll_top: int,
    *,
    can_edit: bool,
    error: str = "",
    folder_row: dict[str, object] | None = None,
    folder_entries: list[dict[str, object]] | None = None,
    title: str | None = None,
    header_kv: list[str] | None = None,
    footer_tail: list[str] | None = None,
    has_meta: bool = False,
) -> tuple[str, int, int]:
    title_col, border_col = _block_colors("START SESSION", has_exit=False)
    is_folder = folder_row is not None and folder_entries is not None and len(folder_entries) > 1
    if is_folder:
        panel_title = f"BUNDLE {part_no}/{total} · {label}" if label else f"BUNDLE {part_no}/{total}"
    else:
        panel_title = f"PART {part_no}/{total} · {label}" if label else f"PART {part_no}/{total}"
    if title is not None:
        panel_title = title
    max_content_w = max(1, cols)
    title_line = f"{title_col}{panel_title}{_ANSI_RESET}" if _use_color() else panel_title

    hdr_kv: list[str] = []
    if header_kv is not None:
        hdr_kv.extend(header_kv)
    elif is_folder and folder_row is not None and folder_entries:
        f_desc = str(folder_row.get("desc") or "bundle")
        f_kind = str(folder_row.get("kind") or "bundle")
        hdr_kv.append(f"Source: {f_desc} ({f_kind})")
        starts = [int(e["line_start"]) for e in folder_entries if isinstance(e.get("line_start"), int)]
        ends = [int(e["line_end"]) for e in folder_entries if isinstance(e.get("line_end"), int)]
        idxs = [int(e["index"]) for e in folder_entries if isinstance(e.get("index"), int)]
        if starts and ends:
            p_span = f"parts {idxs[0]}..{idxs[-1]}, " if len(idxs) >= 2 else ""
            hdr_kv.append(f"Range: {p_span}lines {min(starts)}-{max(ends)} of {label}")
    elif entry is not None:
        hdr_kv.append(f"Source: {_part_label(entry)} ({entry.get('kind') or 'part'})")
        hdr_kv.append(f"Range: lines {entry.get('line_start')}-{entry.get('line_end')} of {label}")
    header_rows: list[str] = [title_line]
    for hline in hdr_kv:
        colored = _colorize_kv_line(_expand_tabs(hline), bright=True)
        for wline in _wrap_box_line(colored, max_content_w):
            header_rows.append(wline)
    div_char = "─" if _supports_utf8() else "-"
    div_line = div_char * max(8, max_content_w)
    header_rows.append(f"{border_col}{div_line}{_ANSI_RESET}" if _use_color() else div_line)

    all_items: list[str] = []
    for bline in ([error] if error else body_lines):
        for wline in _wrap_box_line(_expand_tabs(bline), max_content_w):
            all_items.append(wline)

    tail = list(footer_tail) if footer_tail is not None else ["n/N: next/prev part"]
    if footer_tail is None:
        if can_edit:
            tail.append("e(dit) bundle")
        if has_meta:
            tail.append("m(eta)")
        tail.append("Esc: back")
    return _compose_pager_frame(header_rows, all_items, cols, rows, scroll_top, tail)


def _resolve_info_step_script(
    label: str | None,
    resolved_sdir: Path | None,
    script_path: Path | None,
    out_path: Path | None,
) -> Path | None:
    if script_path is not None:
        return script_path
    if out_path is not None and out_path.name in ("out", "error"):
        cand = out_path.with_name("block.sh")
        if cand.is_file():
            return cand
    if label and "/" in label and resolved_sdir is not None:
        step = label.split("/", 1)[1].strip()
        if step and step != "0":
            cand = _find_step_script(resolved_sdir, step)
            if cand.is_file():
                return cand
    return None


def _format_info_header_lines(
    label: str | None = None,
    sdir: Path | None = None,
    work_dir: Path | str | None = None,
    sandbox_mode: str | None = None,
    cd_dirs: list[str] | None = None,
) -> list[str]:
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label)
    hdr_items = parse_bundle_header_items(resolved_sdir, include_transport=True)
    hdr_map = {k.lower(): v for k, v in hdr_items}

    lines: list[str] = []
    if label:
        if "/" in label:
            sess, step = label.split("/", 1)
            if step == "0":
                lines.append(f"Session: {sess}")
                nxt = hdr_map.get("next-block") or f"{sess}/1"
                lines.append(f"Next-Block: {nxt}")
            else:
                lines.append(f"Step: {label}")
        else:
            lines.append(f"Session: {label}")
    elif resolved_sdir is not None:
        sess = hdr_map.get("session") or resolved_sdir.name
        lines.append(f"Session: {sess}")

    if work_dir is not None and str(work_dir):
        wdir_str = str(work_dir)
    else:
        wdir_str = str(get_work_dir(resolved_sdir).resolve())
    wline = f"Workdir: {wdir_str}" + (f"  (cd -> {', '.join(cd_dirs)})" if cd_dirs else "")
    lines.append(wline)

    sb_val = sandbox_mode if (sandbox_mode is not None and str(sandbox_mode)) else get_sandbox_mode(resolved_sdir)
    lines.append(f"Sandbox: {format_sandbox_header(sb_val)}")

    if hdr_map.get("date"):
        lines.append(f"Date: {hdr_map['date']}")

    for raw_k, val in hdr_items:
        if raw_k.lower() in HIDDEN_SESSION_HEADER_KEYS or raw_k.lower() in FULLSCREEN_HIDDEN_HEADER_KEYS or not val:
            continue
        lines.append(f"{raw_k}: {val}")

    meta = read_session_meta(resolved_sdir)
    if meta.get("completed"):
        comp_at = str(meta.get("completed_at") or "").strip()
        lines.append(f"Completed: {comp_at}" if comp_at else "Completed: true")
        comp_note = str(meta.get("completed_note") or "").strip()
        if comp_note:
            lines.append(f"Completed-Note: {comp_note}")
    return lines


def _format_safety_warning_lines(findings: list[dict[str, object]], max_width: int) -> list[str]:
    if not findings:
        return []
    whdr = f"  Safety warnings ({len(findings)}):"
    out: list[str] = [f"{_WARN_COLOR}{whdr}{_ANSI_RESET}" if _use_color() else whdr]
    warn_items = [(str(f.get("category") or "warn"), str(f.get("snippet") or "")) for f in findings]
    out.extend(_colorize_warning_lines(_wrap_labeled_items(warn_items, max_width, indent="    ")))
    return out


def _format_info_plan_section(
    heading: str,
    plan_obj: dict[str, object],
    max_width: int,
) -> list[str]:
    out: list[str] = [f"{_KEY_COLOR}{heading}{_ANSI_RESET}" if _use_color() else heading]
    meta_str = str(plan_obj.get("meta") or "")
    if meta_str:
        out.append(f"  Script: {meta_str}")
    ops_raw = list(plan_obj.get("operations") or [])
    ops = [(str(op[0]), str(op[1])) for op in ops_raw if isinstance(op, (list, tuple)) and len(op) >= 2]
    op_groups_raw = list(plan_obj.get("operation_groups") or [])
    op_groups: list[tuple[str, list[tuple[str, str]]]] = []
    for grp in op_groups_raw:
        if isinstance(grp, (list, tuple)) and len(grp) >= 2:
            g_items = [
                (str(it[0]), str(it[1]))
                for it in (grp[1] or [])
                if isinstance(it, (list, tuple)) and len(it) >= 2
            ]
            op_groups.append((str(grp[0]), g_items))
    op_steps = [s for s in (plan_obj.get("operation_steps") or []) if isinstance(s, dict)]
    max_step_num = max((int(s.get("step") or 0) for s in op_steps), default=0)
    step_num_w = len(f"{max_step_num}.") if max_step_num > 0 else None
    wdir = str(plan_obj.get("work_dir") or ".")
    if ops:
        op_lines: list[str] = []
        display_groups = _group_operations_for_display(ops, op_groups, op_steps)
        for g_dir, g_items, g_nums in display_groups:
            if g_dir is not None:
                dir_hdr = g_dir if g_dir else wdir
                op_lines.append(f"  {dir_hdr}:")
                item_indent = "    "
            else:
                item_indent = "  "
            op_lines.extend(
                _wrap_labeled_items(
                    g_items, max_width, indent=item_indent, step_nums=g_nums, num_width=step_num_w
                )
            )
        out.extend(_colorize_operation_lines(op_lines))
    else:
        out.append("  (no detected operations)")
    findings = [f for f in (plan_obj.get("findings") or []) if isinstance(f, dict)]
    out.extend(_format_safety_warning_lines(findings, max_width))
    return out


def _total_stats_entry(data: bytes) -> dict[str, object]:
    s = count_tokens(data)
    return {k: int(s[k]) for k in ("lines", "chars", "gpt", "claude")}


def _render_operation_table(
    ops: list[dict[str, object]],
    total: dict[str, object],
    max_width: int,
    *,
    edited: bool,
    failed_step: int | None,
) -> list[str]:
    lines = _colorize_bundle_lines(
        format_operation_table_lines(ops, total, max_width=max_width, edited=edited, failed_step=failed_step)
    )
    if _use_color():
        lines = [ln.replace(" (failed)", f" {_WARN_COLOR}(failed){_ANSI_RESET}") for ln in lines]
    return lines


def _refresh_output_operations(
    op_timings: list[dict[str, object]],
    out_lines: list[str],
    total_chars: int,
    *,
    step_ops: list[dict[str, object]] | None = None,
    out_edited: bool = False,
    script_edited: bool = False,
) -> list[dict[str, object]]:
    raw_ops = [dict(op) for op in op_timings]
    if script_edited and step_ops:
        by_step = {int(op["step"]): op for op in raw_ops if isinstance(op.get("step"), int)}
        merged: list[dict[str, object]] = []
        for idx, st in enumerate(step_ops, 1):
            st_no = int(st.get("step") or idx)
            base = dict(by_step.get(st_no) or {})
            base["step"] = st_no
            base["tag"] = str(st.get("tag") or base.get("tag") or "exec")
            base["desc"] = str(st.get("desc") or base.get("desc") or "")
            base["line"] = int(st.get("line") or base.get("line") or 0)
            base["end_line"] = int(st.get("end_line") or base.get("end_line") or base["line"])
            merged.append(base)
        raw_ops = merged
    elif step_ops:
        st_by_no = {int(st.get("step") or i): st for i, st in enumerate(step_ops, 1)}
        for op in raw_ops:
            st_no = op.get("step")
            if isinstance(st_no, int) and st_no in st_by_no:
                st = st_by_no[st_no]
                if not op.get("line") and st.get("line"):
                    op["line"] = int(st["line"])
                if not op.get("end_line") and st.get("end_line"):
                    op["end_line"] = int(st["end_line"])

    total_lines = len(out_lines)
    refreshed: list[dict[str, object]] = []
    for op in raw_ops:
        out_start = op.get("out_line_start")
        out_end = op.get("out_line_end")
        if isinstance(out_start, int) and isinstance(out_end, int) and out_start >= 1 and out_end >= out_start:
            if out_start <= total_lines:
                clamped_end = min(total_lines, out_end)
                op["out_line_start"] = out_start
                op["out_line_end"] = clamped_end
                if out_edited or "chars" not in op or "lines" not in op:
                    chunk = "\n".join(out_lines[out_start - 1 : clamped_end]) + "\n"
                    s = count_tokens(chunk.encode("utf-8"))
                    op["lines"] = int(s["lines"])
                    op["chars"] = int(s["chars"])
                    op["bytes"] = int(s["bytes"])
                    op["gpt"] = int(s["gpt"])
                    op["claude"] = int(s["claude"])
            elif out_edited:
                op.pop("out_line_start", None)
                op.pop("out_line_end", None)
                op["lines"] = 0
                op["chars"] = 0
                op["bytes"] = 0
                op["gpt"] = 0
                op["claude"] = 0
        chars = max(0, int(op.get("chars") or 0))
        op["share_pct"] = round(100.0 * chars / total_chars, 1) if total_chars > 0 else 0.0
        refreshed.append(op)
    return refreshed


def _format_output_breakdown(
    op_timings: list[dict[str, object]],
    out_path: Path,
    *,
    total_ms: int | None,
    failed_step: int | None,
    edited: bool,
    max_width: int,
    step_ops: list[dict[str, object]] | None = None,
    out_edited: bool | None = None,
    script_edited: bool = False,
) -> list[str]:
    try:
        data = out_path.read_bytes()
    except OSError:
        data = b""
    out_lines = data.decode("utf-8", "replace").splitlines()
    total = _total_stats_entry(data)
    is_out_edited = _is_file_edited(out_path, _orig_file_backup_path(out_path)) if out_edited is None else out_edited
    ops = _refresh_output_operations(
        op_timings,
        out_lines,
        int(total.get("chars") or 0),
        step_ops=step_ops,
        out_edited=is_out_edited,
        script_edited=script_edited,
    )
    total["duration_ms"] = (
        total_ms if total_ms is not None else sum(max(0, int(op.get("duration_ms") or 0)) for op in ops)
    )
    return _render_operation_table(ops, total, max_width, edited=edited, failed_step=failed_step)


def _script_operation_metrics(steps: list[dict[str, object]], script_text: str) -> list[dict[str, object]]:
    script_lines = script_text.splitlines()
    total_chars = max(1, len(script_text))
    ops: list[dict[str, object]] = []
    for st in steps:
        first = int(st.get("line") or 0)
        last = int(st.get("end_line") or first)
        chunk = "\n".join(script_lines[max(0, first - 1) : last]) + "\n"
        s = count_tokens(chunk.encode("utf-8"))
        ops.append(
            {
                **st,
                "lines": int(s["lines"]),
                "chars": int(s["chars"]),
                "gpt": int(s["gpt"]),
                "claude": int(s["claude"]),
                "share_pct": round(100.0 * int(s["chars"]) / total_chars, 1),
            }
        )
    return ops


def _format_script_breakdown(
    steps: list[dict[str, object]], script_path: Path, *, edited: bool, max_width: int
) -> list[str]:
    try:
        data = script_path.read_bytes()
    except OSError:
        return []
    ops = _script_operation_metrics(steps, data.decode("utf-8", "replace"))
    return _render_operation_table(ops, _total_stats_entry(data), max_width, edited=edited, failed_step=None)


def _collect_info_report(
    *,
    title_kind: str,
    label: str,
    max_content_w: int,
    sdir: Path | None = None,
    out_path: Path | None = None,
    script_path: Path | None = None,
    rc: int | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    summary: dict[str, object] | None = None,
    findings: list[dict[str, object]] | None = None,
    note: str = "",
    sandbox_mode: str | None = None,
    extra_lines: list[str] | None = None,
    edited: bool | None = None,
) -> tuple[list[str], list[str]]:
    kind = title_kind.strip()
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, out_path or script_path)
    resolved_script = _resolve_info_step_script(label, resolved_sdir, script_path, out_path)
    step_dir: Path | None = None
    if resolved_script is not None:
        step_dir = resolved_script.parent
    elif out_path is not None and out_path.name in ("out", "error"):
        step_dir = out_path.parent
    elif resolved_sdir is not None and "/" in label:
        st_name = label.split("/", 1)[1].strip()
        if st_name and st_name != "0":
            step_dir = _step_dir(resolved_sdir, st_name)

    step_meta = read_step_meta(step_dir) if step_dir is not None else {}
    if duration_s is None and isinstance(step_meta.get("duration_ms"), (int, float)):
        duration_s = float(step_meta["duration_ms"]) / 1000.0
    if rc is None and isinstance(step_meta.get("exit_code"), int):
        rc = int(step_meta["exit_code"])
    if op_timings is None and isinstance(step_meta.get("operations"), list):
        op_timings = [x for x in step_meta["operations"] if isinstance(x, dict)]
    if failed_step is None and isinstance(step_meta.get("failed_step"), int):
        failed_step = int(step_meta["failed_step"])

    wdir = str(summary.get("work_dir") or "") if summary else ""
    cd_dirs = list(summary.get("cd_dirs") or []) if summary else []
    sb_val = sandbox_mode or (str(summary.get("sandbox") or "") if summary else "") or None
    hdr_lines = _format_info_header_lines(
        label=label,
        sdir=resolved_sdir,
        work_dir=wdir or None,
        sandbox_mode=sb_val,
        cd_dirs=cd_dirs,
    )
    if step_meta.get("renumbered_from"):
        hdr_lines.append(f"Renumbered: from {step_meta['renumbered_from']}")

    meta_kv: list[str] = []
    if extra_lines:
        known_prefixes = ("Session:", "Next-Block:", "Step:", "Workdir:", "Sandbox:", "Date:", "Bundle:", "Script:", "Output:", "Stats:")
        for el in extra_lines:
            stripped = el.strip()
            if not stripped or stripped.startswith(known_prefixes):
                continue
            meta_kv.append(el)

    if kind == "START SESSION":
        bpath = out_path if out_path is not None else (resolved_sdir / "0" if resolved_sdir is not None else None)
        if bpath is not None:
            orig_b = _orig_file_backup_path(bpath)
            b_edited = _is_file_edited(bpath, orig_b) if edited is None else bool(edited)
            plan_obj = None
            fn_load = globals().get("load_session_bundle_plan")
            if callable(fn_load):
                loaded = fn_load(resolved_sdir, bpath)
                if isinstance(loaded, dict):
                    plan_obj = loaded
            body_sections: list[str] = []
            breakdown, warnings_sec = _build_start_bundle_parts(
                resolved_sdir,
                bpath,
                details=True,
                max_width=max_content_w,
                plan=plan_obj,
                include_part_count=True,
                edited=b_edited,
            )
            if breakdown:
                body_sections.extend(breakdown)
            if warnings_sec:
                if body_sections:
                    body_sections.append("")
                body_sections.extend(warnings_sec)
            if not body_sections:
                body_sections = ["(no bundle parts)"]
            meta_kv.append(f"Bundle: {bpath}")
            if orig_b.is_file():
                meta_kv.append(f"Bundle-Orig: {orig_b}")
            if resolved_sdir is not None and (resolved_sdir / "meta.json").is_file():
                meta_kv.append(f"Meta: {resolved_sdir / 'meta.json'}")
            return _align_kv_lines([*hdr_lines, *meta_kv]), body_sections

    orig_script = _orig_backup_path(resolved_script) if resolved_script is not None else None
    script_edited = _is_file_edited(resolved_script, orig_script)
    orig_out = _orig_file_backup_path(out_path) if out_path is not None else None
    out_edited = _is_file_edited(out_path, orig_out)

    if kind != "START STEP" and rc is not None and rc != 0 and not any(ln.startswith("Exit:") for ln in meta_kv):
        meta_kv.append(f"Exit: {rc}")
        if out_path is not None and out_path.is_file():
            last_err = _extract_last_error_line(out_path, label=label, max_width=max_content_w)
            if last_err and not any(ln.startswith("Error:") for ln in meta_kv):
                meta_kv.append(f"Error: {last_err}")
        if kind == "END STEP" and label and not any(ln.startswith("Fix:") for ln in meta_kv):
            fix_st = _format_end_fix_status(label, resolved_sdir)
            if fix_st:
                meta_kv.append(f"Fix: {fix_st}")

    if resolved_script is not None and resolved_script.exists():
        meta_kv.append(f"Script: {resolved_script}")
        if orig_script is not None and orig_script.is_file():
            meta_kv.append(f"Script-Orig: {orig_script}")
    if out_path is not None and out_path.exists():
        meta_kv.append(f"Output: {out_path}")
        if orig_out is not None and orig_out.is_file():
            meta_kv.append(f"Output-Orig: {orig_out}")
    if step_dir is not None:
        smeta_file = step_dir / "meta.json"
        if smeta_file.is_file():
            meta_kv.append(f"Meta: {smeta_file}")
    if resolved_sdir is not None and kind in ("MISSING PREVIOUS STEP", "SESSION COMPLETED"):
        b0 = resolved_sdir / "0"
        if b0.is_file():
            meta_kv.append(f"Bundle: {b0}")
            orig0 = _orig_file_backup_path(b0)
            if orig0.is_file():
                meta_kv.append(f"Original: {orig0}")

    any_edited = bool(edited if edited is not None else (out_edited or script_edited))

    body_sections = []
    step_reasoning = _resolve_step_reasoning(summary=summary, script_path=resolved_script, step_dir=step_dir)
    if step_reasoning:
        body_sections.extend(_format_reasoning_lines(step_reasoning, max_content_w, max_lines=None))
    step_ops = _info_operation_steps(resolved_script, resolved_sdir, label)
    total_ms = int(round(duration_s * 1000.0)) if duration_s is not None else None
    if kind != "START STEP" and op_timings and out_path is not None and out_path.is_file():
        if body_sections:
            body_sections.append("")
        body_sections.extend(
            _format_output_breakdown(
                op_timings,
                out_path,
                total_ms=total_ms,
                failed_step=failed_step if (rc is not None and rc != 0) else None,
                edited=any_edited,
                max_width=max_content_w,
                step_ops=step_ops,
                out_edited=out_edited,
                script_edited=script_edited,
            )
        )
    elif step_ops and resolved_script is not None:
        if body_sections:
            body_sections.append("")
        body_sections.extend(
            _format_script_breakdown(step_ops, resolved_script, edited=any_edited, max_width=max_content_w)
        )

    if kind == "START STEP":
        warn_lines = _format_safety_warning_lines(
            [f for f in (findings or []) if isinstance(f, dict)], max_content_w
        )
        if warn_lines:
            if body_sections:
                body_sections.append("")
            body_sections.extend(warn_lines)
        if note.strip():
            if body_sections:
                body_sections.append("")
            body_sections.append("Analyzer:")
            for nline in note.strip().splitlines():
                body_sections.append(f"  {nline}")
        if orig_script is not None and orig_script.is_file():
            try:
                orig_text = orig_script.read_text(encoding="utf-8", errors="replace")
                w_eff = Path(wdir) if wdir else get_work_dir(resolved_sdir)
                orig_plan = analyze_script(orig_text, work_dir=w_eff, label=label, check_syntax=False)
                if body_sections:
                    body_sections.append("")
                body_sections.extend(
                    _format_info_plan_section(f"Original Plan ({orig_script.name}):", orig_plan, max_content_w)
                )
            except OSError:
                pass

    if not body_sections and resolved_sdir is not None and (resolved_sdir / "0").is_file():
        fn_load = globals().get("load_session_bundle_plan")
        if callable(fn_load):
            s_plan = fn_load(resolved_sdir, resolved_sdir / "0")
            if isinstance(s_plan, dict):
                fn_parts = globals().get("format_bundle_parts_lines")
                part_lines = fn_parts(s_plan, max_width=max_content_w) if callable(fn_parts) else []
                if part_lines:
                    p_cnt = int(s_plan.get("part_count") or 0)
                    shdr = f"Session Bundle Parts ({p_cnt}):"
                    body_sections.append(f"{_KEY_COLOR}{shdr}{_ANSI_RESET}" if _use_color() else shdr)
                    body_sections.extend(_colorize_bundle_lines(part_lines))

    if not body_sections:
        body_sections = ["(no additional details)"]
    return _align_kv_lines([*hdr_lines, *meta_kv]), body_sections


def _build_plain_info_report(**kwargs) -> str:
    max_w = int(kwargs.pop("max_content_w", 100))
    hdr_lines, body_lines = _collect_info_report(max_content_w=max_w, **kwargs)
    plain_lines = [ANSI_RE.sub("", ln) for ln in [*hdr_lines, "", *body_lines]]
    return "\n".join(plain_lines) + "\n"


def _build_info_screen(
    title_kind: str,
    label: str,
    cols: int,
    rows: int,
    scroll_top: int,
    *,
    sdir: Path | None = None,
    out_path: Path | None = None,
    script_path: Path | None = None,
    edit_target: Path | None = None,
    rc: int | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    summary: dict[str, object] | None = None,
    findings: list[dict[str, object]] | None = None,
    note: str = "",
    sandbox_mode: str | None = None,
    extra_lines: list[str] | None = None,
    edited: bool | None = None,
    allow_copy: bool = False,
    allow_overwrite: bool = False,
    part_cursor: int | None = None,
) -> tuple[str, int, int]:
    kind = title_kind.strip()
    title_col, border_col = _block_colors(kind, has_exit=(rc is not None and rc != 0))
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, out_path or script_path or edit_target)
    resolved_script = _resolve_info_step_script(label, resolved_sdir, script_path, out_path)
    if kind == "START SESSION":
        primary_path = out_path if out_path is not None else (edit_target if edit_target is not None else (resolved_sdir / "0" if resolved_sdir is not None else None))
        is_edited = _is_file_edited(primary_path, _orig_file_backup_path(primary_path)) if (edited is None and primary_path is not None) else bool(edited)
    else:
        primary_path = out_path if (out_path is not None and out_path.exists()) else (edit_target if (edit_target is not None and edit_target.exists()) else resolved_script)
        if primary_path is None and resolved_sdir is not None and (resolved_sdir / "0").is_file():
            primary_path = resolved_sdir / "0"
        orig_sc = _orig_backup_path(resolved_script) if resolved_script is not None else None
        orig_o = _orig_file_backup_path(out_path) if out_path is not None else None
        is_edited = bool(edited if edited is not None else (_is_file_edited(out_path, orig_o) or _is_file_edited(resolved_script, orig_sc)))

    base_title = f"{kind} · {label}" if (label and label != kind) else kind
    short_path = _shorten_home_path(primary_path) if primary_path is not None else ""
    panel_title = f"{base_title} · {short_path}" if short_path else base_title
    if is_edited:
        panel_title += " (edited)"
    max_content_w = max(1, cols)
    title_line = f"{title_col}{panel_title}{_ANSI_RESET}" if _use_color() else panel_title

    hdr_kv, raw_body = _collect_info_report(
        title_kind=kind,
        label=label,
        max_content_w=max_content_w,
        sdir=sdir,
        out_path=out_path,
        script_path=script_path,
        rc=rc,
        duration_s=duration_s,
        op_timings=op_timings,
        failed_step=failed_step,
        summary=summary,
        findings=findings,
        note=note,
        sandbox_mode=sandbox_mode,
        extra_lines=extra_lines,
        edited=is_edited,
    )
    header_rows: list[str] = [title_line]
    for hline in hdr_kv:
        colored = _colorize_kv_line(_expand_tabs(hline), bright=True)
        for wline in _wrap_box_line(colored, max_content_w):
            header_rows.append(wline)
    div_char = "─" if _supports_utf8() else "-"
    div_line = div_char * max(8, max_content_w)
    header_rows.append(f"{border_col}{div_line}{_ANSI_RESET}" if _use_color() else div_line)

    all_items: list[str] = []
    for bline in raw_body:
        for wline in _wrap_box_line(_expand_tabs(bline), max_content_w):
            all_items.append(wline)

    is_table_view = kind == "START SESSION" or (
        kind in _STEP_INFO_KINDS and resolved_script is not None and resolved_script.is_file()
    )
    selectable = _find_selectable_part_rows(all_items) if is_table_view else []
    selected_row_idx: int | None = None
    if part_cursor is not None and selectable:
        for pno, r_idx in selectable:
            if pno == part_cursor:
                selected_row_idx = r_idx
                break
        if selected_row_idx is None:
            selected_row_idx = selectable[0][1]
        all_items[selected_row_idx] = _highlight_selected_part_row(all_items[selected_row_idx], max_content_w)

    has_script = resolved_script is not None and resolved_script.is_file()
    has_output = kind != "START SESSION" and out_path is not None and out_path.is_file()
    has_edit = edit_target is not None and edit_target.is_file()

    footer_tail: list[str] = []
    meta_file = _info_meta_path(kind, resolved_sdir, resolved_script, out_path)
    if selected_row_idx is not None:
        scroll_hint = "Up/Down j/k: select part"
        footer_tail.append("Enter: open part")
        footer_tail.append("Tab/Esc: exit parts")
    else:
        scroll_hint = "Up/Down j/k PgUp/PgDn: scroll"
        if has_edit:
            footer_tail.append("e(dit)")
        if allow_copy and has_edit:
            footer_tail.append("p(rompt)")
        if has_script and kind != "START STEP":
            footer_tail.append("s(cript)")
        if has_output:
            footer_tail.append("o(utput)")
        if allow_overwrite:
            footer_tail.append("O(verwrite)" if has_output else "o(verwrite)")
        footer_tail.append("v(iew)")
        if meta_file is not None:
            footer_tail.append("m(eta)")
        if selectable or (kind == "START SESSION" and _info_part_total(resolved_sdir, out_path) > 0):
            footer_tail.append("Tab: parts")
        if allow_copy:
            footer_tail.append("Enter: copy")
        footer_tail.append("Esc: back")

    viewport_rows = max(1, rows - len(header_rows) - 1)
    if selected_row_idx is not None:
        if selected_row_idx < scroll_top:
            scroll_top = selected_row_idx
        elif selected_row_idx >= scroll_top + viewport_rows:
            scroll_top = selected_row_idx - viewport_rows + 1

    return _compose_pager_frame(
        header_rows,
        all_items,
        cols,
        rows,
        scroll_top,
        footer_tail,
        scroll_hint=scroll_hint,
        position_label=f"Part {part_cursor}/{len(selectable)}" if selected_row_idx is not None else None,
        always_hint=selected_row_idx is not None,
    )


def _build_bundle_details_screen(
    label: str,
    bundle_path: Path,
    cols: int,
    rows: int,
    scroll_top: int,
    *,
    sdir: Path | None = None,
    edited: bool = False,
) -> tuple[str, int, int]:
    return _build_info_screen(
        "START SESSION",
        label,
        cols,
        rows,
        scroll_top,
        sdir=sdir,
        out_path=bundle_path,
        edit_target=bundle_path,
        edited=edited,
        allow_copy=True,
    )


def _open_plain_report_in_editor(report_text: str, tty_r, tty_w) -> None:
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(prefix="run_block_info_", suffix=".txt")
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as f_tmp:
            f_tmp.write(report_text)
        open_script_in_editor(tmp_path, tty_r, tty_w)
    except Exception as exc:
        tty_w.write(f"\n[viewer error: {exc}]\n")
        tty_w.flush()
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _show_info_fullscreen(
    *,
    title_kind: str,
    label: str,
    tty_r,
    tty_w,
    sdir: Path | None = None,
    out_path: Path | None = None,
    script_path: Path | None = None,
    edit_target: Path | None = None,
    rc: int | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    summary: dict[str, object] | None = None,
    findings: list[dict[str, object]] | None = None,
    note: str = "",
    sandbox_mode: str | None = None,
    extra_lines: list[str] | None = None,
    edited: bool | None = None,
    allow_copy: bool = False,
    allow_overwrite: bool = False,
    on_edit_callback=None,
) -> dict[str, object]:
    kind = title_kind.strip()
    scroll_top = 0
    any_edited = False
    cur_summary = summary
    cur_findings = findings
    cur_note = note
    cur_edited = edited
    part_cursor: int | None = None
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, out_path or script_path or edit_target)

    def _apply_edit_callbacks(target: Path) -> dict[str, object] | None:
        nonlocal any_edited, cur_summary, cur_findings, cur_note, cur_edited
        any_edited = True
        cur_edited = True
        if callable(on_edit_callback):
            cb_res = on_edit_callback(target)
            if isinstance(cb_res, dict):
                if "summary" in cb_res:
                    cur_summary = cb_res["summary"]
                if "findings" in cb_res:
                    cur_findings = cb_res["findings"]
                if "note" in cb_res:
                    cur_note = str(cb_res["note"] or "")
                if "edited" in cb_res:
                    cur_edited = bool(cb_res["edited"])
                if cb_res.get("reject_msg"):
                    return cb_res
        elif kind == "START SESSION":
            fn_refresh = globals().get("refresh_bundle_meta")
            if callable(fn_refresh):
                fn_refresh(target)
        return None

    def _edit_artifact(target: Path) -> dict[str, object] | None:
        if not target.is_file():
            return None
        try:
            before_clean_bytes: bytes | None = target.read_bytes()
        except OSError:
            before_clean_bytes = None
        if target.name.startswith("block.") and not target.name.startswith("block.orig."):
            orig_p = _orig_backup_path(target)
        else:
            orig_p = _orig_file_backup_path(target)
        raw_bundle = (resolved_sdir / "0.raw") if (kind == "START SESSION" and resolved_sdir is not None and target.name == "0") else None
        raw_stage_bytes: bytes | None = None
        if raw_bundle is not None and raw_bundle.is_file():
            try:
                raw_stage_bytes = raw_bundle.read_bytes()
            except OSError:
                raw_stage_bytes = None
        with tempfile.TemporaryDirectory(prefix="run_block_edit_") as stage_dir:
            edit_path = target
            if raw_stage_bytes is not None:
                edit_path = Path(stage_dir) / target.name
                edit_path.write_bytes(raw_stage_bytes)
            tty_w.write("\033[?25h\033[?1049l")
            tty_w.flush()
            try:
                open_script_in_editor(edit_path, tty_r, tty_w)
            finally:
                tty_w.write("\033[?1049h\033[?25l")
                tty_w.flush()
            try:
                after_edit_bytes: bytes | None = edit_path.read_bytes() if edit_path.is_file() else None
            except OSError:
                after_edit_bytes = None
        before_edit_bytes = raw_stage_bytes if raw_stage_bytes is not None else before_clean_bytes
        if before_edit_bytes is None or after_edit_bytes is None or after_edit_bytes == before_edit_bytes:
            return None
        if before_clean_bytes is not None:
            _write_orig_backup_once(orig_p, before_clean_bytes)
        if raw_stage_bytes is None:
            return _apply_edit_callbacks(target)
        target.write_bytes(after_edit_bytes)
        try:
            return _apply_edit_callbacks(target)
        except BaseException:
            if before_clean_bytes is not None:
                target.write_bytes(before_clean_bytes)
            raise

    def _prompt_artifact(target: Path) -> dict[str, object] | None:
        if not target.is_file():
            return None
        tty_w.write("\033[?25h\033[?1049l")
        tty_w.flush()
        try:
            note_txt = _prompt_append_text(tty_r, tty_w)
        finally:
            tty_w.write("\033[?1049h\033[?25l")
            tty_w.flush()
        if append_note_to_file(target, note_txt, as_prompt=(kind == "START SESSION")):
            return _apply_edit_callbacks(target)
        return None

    def _open_part_viewer(initial_row_no: int) -> tuple[int, dict[str, object] | None]:
        fn_extract = globals().get("extract_bundle_part")
        if not callable(fn_extract) or resolved_sdir is None or out_path is None:
            return initial_row_no, None
        plan, numbered_rows = _info_table_rows(resolved_sdir, out_path)
        total_rows = len(numbered_rows)
        if not isinstance(plan, dict) or total_rows < 1:
            return initial_row_no, None
        total_parts = len([p for p in (plan.get("parts") or []) if isinstance(p, dict)])
        meta_file = _info_meta_path("START SESSION", resolved_sdir, None, out_path)
        row_no = max(1, min(total_rows, initial_row_no))
        part_scroll = 0
        while True:
            cur_row = numbered_rows[row_no - 1]
            p_indices = [int(i) for i in (cur_row.get("part_indices") or []) if isinstance(i, int) and i > 0]
            if not p_indices and row_no <= total_parts:
                p_indices = [row_no]
            entry: dict[str, object] | None = None
            folder_entries: list[dict[str, object]] = []
            body_lines: list[str] = []
            err = ""
            try:
                bundle_txt = out_path.read_text(encoding="utf-8", errors="replace")
                if len(p_indices) == 1:
                    entry, chunk = fn_extract(plan, bundle_txt, p_indices[0])
                    body_lines = chunk.splitlines()
                else:
                    for idx_pos, p_idx in enumerate(p_indices):
                        p_entry, p_chunk = fn_extract(plan, bundle_txt, p_idx)
                        folder_entries.append(p_entry)
                        if idx_pos > 0:
                            body_lines.append("")
                        p_kind = str(p_entry.get("kind") or "part")
                        p_src = _part_label(p_entry)
                        p_ls = p_entry.get("line_start")
                        p_le = p_entry.get("line_end")
                        delim = f"===== [part {p_idx}/{total_parts}] [{p_kind}] {p_src} (lines {p_ls}-{p_le}) ====="
                        body_lines.append(f"{_KEY_COLOR}{delim}{_ANSI_RESET}" if _use_color() else delim)
                        body_lines.extend(p_chunk.splitlines())
            except (ValueError, OSError) as exc:
                err = str(exc)
            cols, rows = _term_size()
            is_single = len(p_indices) == 1
            disp_no = p_indices[0] if is_single else row_no
            disp_total = total_parts if is_single else total_rows
            frame, part_scroll, vp_rows = _build_part_screen(
                label,
                disp_no,
                disp_total,
                entry,
                body_lines,
                cols,
                rows,
                part_scroll,
                can_edit=edit_target is not None and edit_target.is_file(),
                error=err,
                folder_row=None if is_single else cur_row,
                folder_entries=None if is_single else folder_entries,
                has_meta=meta_file is not None,
            )
            tty_w.write(frame)
            tty_w.flush()
            key = _read_pager_key(tty_r)
            if key == "resize":
                continue
            new_scroll = _apply_pager_scroll(key, part_scroll, vp_rows)
            if new_scroll is not None:
                part_scroll = new_scroll
            elif key == "next_part":
                row_no = min(total_rows, row_no + 1)
                part_scroll = 0
            elif key == "prev_part":
                row_no = max(1, row_no - 1)
                part_scroll = 0
            elif key == "meta":
                _open_meta(meta_file)
            elif key == "edit" and edit_target is not None and edit_target.is_file():
                return row_no, _edit_artifact(edit_target)
            elif key in ("back", "esc", "tab"):
                return row_no, None

    def _open_meta(target: Path | None) -> None:
        if target is None or not target.is_file():
            return
        tty_w.write("\033[?25h\033[?1049l")
        tty_w.flush()
        try:
            open_script_in_editor(target, tty_r, tty_w)
        finally:
            tty_w.write("\033[?1049h\033[?25l")
            tty_w.flush()

    def _open_operation_viewer(initial_no: int) -> tuple[int, dict[str, object] | None]:
        script = _resolve_info_step_script(label, resolved_sdir, script_path, out_path)
        if script is None or not script.is_file():
            return initial_no, None
        raw_timings = _step_op_timings(op_timings, script)
        use_out = kind != "START STEP" and out_path is not None and out_path.is_file()
        meta_file = _info_meta_path(kind, resolved_sdir, script, out_path)
        op_no = initial_no
        op_scroll = 0
        while True:
            steps = _info_operation_steps(script, resolved_sdir, label)
            try:
                script_lines = script.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                script_lines = []
            out_lines: list[str] | None = None
            out_total_chars = 0
            if use_out and out_path is not None:
                try:
                    out_text = out_path.read_text(encoding="utf-8", errors="replace")
                    out_total_chars = len(out_text)
                    out_lines = out_text.splitlines()
                except OSError:
                    out_lines = []
            script_edited = _is_file_edited(script, _orig_backup_path(script))
            out_edited = _is_file_edited(out_path, _orig_file_backup_path(out_path)) if out_path is not None else False
            refreshed_timings = (
                _refresh_output_operations(
                    raw_timings,
                    out_lines or [],
                    out_total_chars,
                    step_ops=steps,
                    out_edited=out_edited,
                    script_edited=script_edited,
                )
                if (use_out and raw_timings)
                else raw_timings
            )
            timing_by_step = {
                int(t["step"]): t for t in refreshed_timings if isinstance(t.get("step"), int)
            }
            if use_out and refreshed_timings and not (script_edited and steps):
                st_by_no = {int(st.get("step") or i): st for i, st in enumerate(steps, 1)}
                view_steps = [
                    {**st_by_no.get(int(t.get("step") or i), {}), **t}
                    for i, t in enumerate(refreshed_timings, 1)
                ]
            else:
                view_steps = steps
            if not view_steps:
                return initial_no, None
            total = len(view_steps)
            op_no = max(1, min(total, op_no))
            cur_step = view_steps[op_no - 1]
            cur_step_no = int(cur_step.get("step") or op_no)
            cols, rows = _term_size()
            is_failed = rc is not None and rc != 0 and failed_step == cur_step_no
            frame, op_scroll, vp_rows = _build_operation_screen(
                label,
                op_no,
                total,
                cur_step,
                script,
                script_lines,
                timing_by_step.get(cur_step_no),
                is_failed,
                cols,
                rows,
                op_scroll,
                can_edit=True,
                out_path=out_path if use_out else None,
                out_lines=out_lines,
                has_meta=meta_file is not None,
            )
            tty_w.write(frame)
            tty_w.flush()
            key = _read_pager_key(tty_r)
            if key == "resize":
                continue
            new_scroll = _apply_pager_scroll(key, op_scroll, vp_rows)
            if new_scroll is not None:
                op_scroll = new_scroll
            elif key == "next_part":
                op_no = min(total, op_no + 1)
                op_scroll = 0
            elif key == "prev_part":
                op_no = max(1, op_no - 1)
                op_scroll = 0
            elif key == "meta":
                _open_meta(meta_file)
            elif key in ("edit", "output", "script"):
                target = out_path if (use_out and key in ("edit", "output") and out_path is not None) else script
                cb_edit = _edit_artifact(target)
                op_scroll = 0
                if cb_edit and cb_edit.get("reject_msg"):
                    return op_no, cb_edit
            elif key in ("back", "esc", "tab"):
                return op_no, None

    tty_w.write("\033[?1049h\033[?25l")
    tty_w.flush()
    try:
        first_read = True
        while True:
            cols, rows = _term_size()
            resolved_script = _resolve_info_step_script(label, resolved_sdir, script_path, out_path)
            has_script = resolved_script is not None and resolved_script.is_file()
            has_output = kind != "START SESSION" and out_path is not None and out_path.is_file()
            if kind == "START SESSION":
                part_total = _info_part_total(resolved_sdir, out_path)
            elif kind in _STEP_INFO_KINDS and has_script:
                part_total = _step_part_total(
                    kind, resolved_script, resolved_sdir, label, op_timings, has_output=has_output
                )
            else:
                part_total = 0
            if part_cursor is not None:
                if part_total < 1:
                    part_cursor = None
                else:
                    part_cursor = max(1, min(part_total, part_cursor))
            frame, scroll_top, viewport_rows = _build_info_screen(
                kind,
                label,
                cols,
                rows,
                scroll_top,
                sdir=resolved_sdir,
                out_path=out_path,
                script_path=resolved_script,
                edit_target=edit_target,
                rc=rc,
                duration_s=duration_s,
                op_timings=op_timings,
                failed_step=failed_step,
                summary=cur_summary,
                findings=cur_findings,
                note=cur_note,
                sandbox_mode=sandbox_mode,
                extra_lines=extra_lines,
                edited=cur_edited,
                allow_copy=allow_copy,
                allow_overwrite=allow_overwrite,
                part_cursor=part_cursor,
            )
            tty_w.write(frame)
            tty_w.flush()
            key = _read_pager_key(tty_r, flush=first_read)
            first_read = False
            if key == "resize":
                continue
            if part_cursor is not None:
                if key in ("tab", "esc"):
                    part_cursor = None
                    continue
                if key == "down":
                    part_cursor = min(part_total, part_cursor + 1)
                    continue
                if key == "up":
                    part_cursor = max(1, part_cursor - 1)
                    continue
                if key == "top":
                    part_cursor = 1
                    continue
                if key == "bottom":
                    part_cursor = part_total
                    continue
                if key == "copy":
                    opener = _open_part_viewer if kind == "START SESSION" else _open_operation_viewer
                    part_cursor, cb = opener(part_cursor)
                    if cb and cb.get("reject_msg"):
                        return {"action": "reject", "edited": any_edited, "reject_msg": cb["reject_msg"]}
                    continue
            if key == "tab" and part_total > 0:
                part_cursor = 1
                continue
            new_scroll = _apply_pager_scroll(key, scroll_top, viewport_rows)
            if new_scroll is not None:
                scroll_top = new_scroll
            elif key == "edit" and edit_target is not None and edit_target.is_file():
                cb = _edit_artifact(edit_target)
                if cb and cb.get("reject_msg"):
                    return {"action": "reject", "edited": any_edited, "reject_msg": cb["reject_msg"]}
            elif key == "prompt" and allow_copy and edit_target is not None and edit_target.is_file():
                cb = _prompt_artifact(edit_target)
                if cb and cb.get("reject_msg"):
                    return {"action": "reject", "edited": any_edited, "reject_msg": cb["reject_msg"]}
            elif key == "script" and has_script and resolved_script is not None:
                cb = _edit_artifact(resolved_script)
                if cb and cb.get("reject_msg"):
                    return {"action": "reject", "edited": any_edited, "reject_msg": cb["reject_msg"]}
            elif key == "output":
                if has_output and out_path is not None:
                    _edit_artifact(out_path)
                elif allow_overwrite and not has_output:
                    return {"action": "overwrite", "edited": any_edited}
            elif key == "overwrite" and allow_overwrite:
                return {"action": "overwrite", "edited": any_edited}
            elif key == "meta":
                _open_meta(_info_meta_path(kind, resolved_sdir, resolved_script, out_path))
            elif key == "view":
                report_txt = _build_plain_info_report(
                    title_kind=kind,
                    label=label,
                    max_content_w=max(80, cols),
                    sdir=resolved_sdir,
                    out_path=out_path,
                    script_path=resolved_script,
                    rc=rc,
                    duration_s=duration_s,
                    op_timings=op_timings,
                    failed_step=failed_step,
                    summary=cur_summary,
                    findings=cur_findings,
                    note=cur_note,
                    sandbox_mode=sandbox_mode,
                    extra_lines=extra_lines,
                    edited=cur_edited,
                )
                tty_w.write("\033[?25h\033[?1049l")
                tty_w.flush()
                try:
                    _open_plain_report_in_editor(report_txt, tty_r, tty_w)
                finally:
                    tty_w.write("\033[?1049h\033[?25l")
                    tty_w.flush()
            elif key == "copy" and allow_copy:
                return {"action": "copy", "edited": any_edited}
            elif key in ("back", "esc"):
                return {"action": "back", "edited": any_edited}
    finally:
        tty_w.write("\033[?25h\033[?1049l")
        tty_w.flush()


def _show_bundle_details_fullscreen(
    label: str,
    bundle_path: Path,
    tty_r,
    tty_w,
    *,
    sdir: Path | None = None,
    edited: bool = False,
) -> str:
    res = _show_info_fullscreen(
        title_kind="START SESSION",
        label=label,
        tty_r=tty_r,
        tty_w=tty_w,
        sdir=sdir,
        out_path=bundle_path,
        edit_target=bundle_path,
        edited=edited,
        allow_copy=True,
    )
    return str(res.get("action") or "back")
