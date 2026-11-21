def open_tty():
    tty_in_name = "CONIN$" if os.name == "nt" else "/dev/tty"
    tty_out_name = "CONOUT$" if os.name == "nt" else "/dev/tty"
    return (
        open(tty_out_name, "w", encoding="utf-8", errors="replace"),
        open(tty_in_name, "r", encoding="utf-8", errors="replace"),
    )


def flush_tty_input(tty_r) -> None:
    if HAS_PTY and termios is not None:
        try:
            termios.tcflush(tty_r.fileno(), termios.TCIFLUSH)
        except Exception:
            pass


def _drain_fd_nonblock(fd: int) -> None:
    while True:
        try:
            chunk = os.read(fd, 256)
            if not chunk:
                break
        except OSError:
            break


def _drain_and_debounce_sigwinch(
    win_fd: int,
    debounce_s: float = 0.025,
    max_wait_s: float = 0.10,
) -> None:
    _drain_fd_nonblock(win_fd)
    start = time.monotonic()
    deadline = start + debounce_s
    max_deadline = start + max_wait_s
    while True:
        rem = deadline - time.monotonic()
        if rem <= 0:
            break
        try:
            rlist, _, _ = select.select([win_fd], [], [], rem)
        except (InterruptedError, OSError):
            continue
        if not rlist:
            break
        _drain_fd_nonblock(win_fd)
        now = time.monotonic()
        if now >= max_deadline:
            break
        deadline = min(max_deadline, now + debounce_s)


class _SigwinchWatcher:
    """Monitors POSIX SIGWINCH via a self-pipe and restores the prior handler on exit."""

    def __init__(self) -> None:
        self._r_fd = -1
        self._w_fd = -1
        self._prev_handler = None
        self._installed = False

    def __enter__(self) -> int | None:
        if not hasattr(signal, "SIGWINCH") or not hasattr(os, "pipe"):
            return None
        try:
            r_fd, w_fd = os.pipe()
            os.set_blocking(r_fd, False)
            os.set_blocking(w_fd, False)
            self._r_fd = r_fd
            self._w_fd = w_fd
            prev = signal.getsignal(signal.SIGWINCH)

            def _on_sigwinch(signum, frame) -> None:
                try:
                    os.write(w_fd, b"1")
                except OSError:
                    pass
                if callable(prev):
                    try:
                        prev(signum, frame)
                    except Exception:
                        pass

            self._prev_handler = signal.signal(signal.SIGWINCH, _on_sigwinch)
            self._installed = True
            return self._r_fd
        except (ValueError, OSError, AttributeError):
            self._cleanup()
            return None

    def _cleanup(self) -> None:
        if self._installed:
            try:
                signal.signal(signal.SIGWINCH, self._prev_handler)
            except (ValueError, OSError, AttributeError):
                pass
            self._installed = False
        for fd_to_close in (self._r_fd, self._w_fd):
            if fd_to_close >= 0:
                try:
                    os.close(fd_to_close)
                except OSError:
                    pass
        self._r_fd = -1
        self._w_fd = -1

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self._cleanup()


def read_clipboard_key(tty_r, *, flush: bool = True) -> str:
    """Wait for a single key: returns 'copy', 'skip', 'view', 'edit', 'prompt', 'info', or 'resize'."""
    if flush:
        flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        ans = tty_r.readline().strip().lower()
        if ans in ("i", "info", "inspect", "d", "details"):
            return "info"
        if ans in ("e", "edit"):
            return "edit"
        if ans in ("p", "prompt"):
            return "prompt"
        if ans in ("v", "view"):
            return "view"
        return "skip" if ans in ("n", "no", "q", "quit", "esc", "\x1b") else "copy"
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        ans = tty_r.readline().strip().lower()
        if ans in ("i", "info", "inspect", "d", "details"):
            return "info"
        if ans in ("e", "edit"):
            return "edit"
        if ans in ("p", "prompt"):
            return "prompt"
        return "view" if ans in ("v", "view") else ("skip" if ans in ("n", "no", "q", "quit", "esc", "\x1b") else "copy")
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
                    return "skip"
                if ch in (b"i", b"I", b"d", b"D"):
                    return "info"
                if ch in (b"e", b"E"):
                    return "edit"
                if ch in (b"p", b"P"):
                    return "prompt"
                if ch in (b"v", b"V"):
                    return "view"
                if ch in (b"\r", b"\n", b"y", b"Y"):
                    return "copy"
                if ch in (b"n", b"N", b"q", b"Q", b"\x03", b"\x04"):
                    return "skip"
                if ch == b"\x1b":
                    # Distinguish standalone Esc from multi-byte escape sequences (like arrow keys)
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                    if rlist:
                        os.read(fd, 32)
                        continue
                    return "skip"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def _step_matches_group_item(
    st: dict[str, object],
    tag: str,
    desc: str,
    group_dir: str,
) -> bool:
    if str(st.get("tag") or "") != tag or str(st.get("dir") or "") != group_dir:
        return False
    st_desc = str(st.get("desc") or "")
    if not st_desc or st_desc == desc:
        return True
    if not group_dir:
        return False
    if st_desc.endswith(" " + desc):
        return True
    if tag == "git" and st_desc.startswith("git -C "):
        m_git_c = re.match(r"^git\s+-C\s+[^\s]+\s+(.+)$", st_desc)
        if m_git_c and f"git {m_git_c.group(1)}" == desc:
            return True
    short_ext = (
        st_desc.replace(f"{group_dir}/", "")
        .replace(f'"{group_dir}"', ".")
        .replace(f"'{group_dir}'", ".")
        .replace(group_dir, ".")
    )
    return short_ext == desc

def _match_operation_step_numbers(
    items: list[tuple[str, str]],
    operation_steps: list[dict[str, object]],
    *,
    group_dir: str | None = None,
    step_cursor: int = 0,
) -> tuple[list[int | None], int]:
    if not operation_steps:
        return [None] * len(items), step_cursor
    result: list[int | None] = []
    idx = step_cursor
    n_steps = len(operation_steps)
    for tag, desc in items:
        if idx < n_steps:
            st = operation_steps[idx]
            st_tag = str(st.get("tag") or "")
            st_desc = str(st.get("desc") or "")
            if group_dir is not None:
                matches = _step_matches_group_item(st, tag, desc, group_dir)
            else:
                matches = st_tag == tag and st_desc == desc
            if matches:
                result.append(int(st.get("step") or (idx + 1)))
                idx += 1
                continue
        result.append(None)
    return result, idx


def _wrap_labeled_items(
    items: list[tuple[str, str]],
    max_width: int,
    indent: str = "  ",
    step_nums: list[int | None] | None = None,
    num_width: int | None = None,
) -> list[str]:
    if not items:
        return []
    tag_w = max(len(f"[{k}]") for k, _ in items)
    nums = step_nums if step_nums is not None else [None] * len(items)
    has_nums = num_width is not None or any(n is not None for n in nums)
    if has_nums:
        nw = num_width if num_width is not None else max(len(f"{n}.") for n in nums if n is not None)
    else:
        nw = 0
    utf8_ok = _supports_utf8()
    out: list[str] = []
    for idx, ((k, v), num) in enumerate(zip(items, nums)):
        num_prefix = ""
        sub_marker = ""
        if has_nums:
            if num is not None:
                num_prefix = f"{num}.".rjust(nw) + " "
            else:
                num_prefix = " " * (nw + 1)
                is_last_sub = idx + 1 >= len(nums) or nums[idx + 1] is not None
                if utf8_ok:
                    sub_marker = "└─ " if is_last_sub else "├─ "
                else:
                    sub_marker = "`- " if is_last_sub else "|- "
        tag = f"[{k}]".ljust(tag_w)
        prefix = f"{indent}{num_prefix}{sub_marker}{tag}  "
        sub_indent = " " * len(prefix)
        avail = max(12, max_width - len(prefix))
        wrapped = textwrap.wrap(v, width=avail, break_long_words=True, break_on_hyphens=False) or [v]
        out.append(prefix + wrapped[0])
        for cont in wrapped[1:]:
            out.append(sub_indent + cont)
    return out


def _group_operations_for_display(
    ops: list[tuple[str, str]],
    op_groups: list[tuple[str, list[tuple[str, str]]]],
    op_steps: list[dict[str, object]],
) -> list[tuple[str | None, list[tuple[str, str]], list[int | None]]]:
    if not op_groups:
        op_nums, _ = _match_operation_step_numbers(ops, op_steps)
        return [(None, list(ops), op_nums)]
    has_step_subdirs = (
        any(bool(s.get("dir")) for s in op_steps)
        if op_steps
        else any(bool(g_dir) for g_dir, _ in op_groups)
    )
    if not has_step_subdirs:
        op_nums, _ = _match_operation_step_numbers(ops, op_steps)
        return [(None, list(ops), op_nums)]
    merged: list[tuple[str, list[tuple[str, str]], list[int | None]]] = []
    step_cursor = 0
    for g_dir, g_items in op_groups:
        g_nums, step_cursor = _match_operation_step_numbers(
            g_items, op_steps, group_dir=g_dir, step_cursor=step_cursor
        )
        if merged and g_nums and all(n is None for n in g_nums):
            parent_dir, parent_items, parent_nums = merged[-1]
            for tag, desc in g_items:
                disp_desc = f"{g_dir}: {desc}" if (g_dir and g_dir != parent_dir) else desc
                parent_items.append((tag, disp_desc))
                parent_nums.append(None)
        elif merged and merged[-1][0] == g_dir:
            merged[-1][1].extend(g_items)
            merged[-1][2].extend(g_nums)
        else:
            merged.append((g_dir, list(g_items), list(g_nums)))
    return [(g_dir, items, nums) for g_dir, items, nums in merged]


def _is_step_meta_file(meta_path: Path) -> bool:
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, dict):
            if "headers" in data or "bundle_plan" in data or "completed" in data:
                return False
            if "duration_ms" in data or "exit_code" in data or "operations" in data:
                return True
    except (OSError, ValueError):
        pass
    return False


def _resolve_session_dir(label: str | None = None, path_hint: Path | None = None) -> Path | None:
    if path_hint is not None:
        ancestors = (path_hint.parent, path_hint.parent.parent)
        for anc in ancestors:
            if (anc / "0").is_file():
                return anc
        for anc in ancestors:
            meta_p = anc / "meta.json"
            if meta_p.is_file():
                if _is_step_meta_file(meta_p):
                    continue
                if re.fullmatch(r"\d+(?:_\d+)?", anc.name) and not (anc / "0").is_file():
                    continue
                return anc
    if label:
        sess = label.split("/", 1)[0].strip()
        if sess and (BASE_DIR / sess).is_dir():
            return BASE_DIR / sess
    if path_hint is not None:
        for anc in (path_hint.parent, path_hint.parent.parent):
            if re.fullmatch(r"s\d+", anc.name):
                return anc
    if label:
        sess = label.split("/", 1)[0].strip()
        if sess:
            return BASE_DIR / sess
    return None


def _truncate_display_width(value: str, max_val_width: int) -> str:
    clean = re.sub(r"\s+", " ", value.strip())
    if max_val_width <= 0:
        return ""
    if display_width(clean) <= max_val_width:
        return clean
    ellipsis = "…" if _supports_utf8() else "..."
    ell_w = display_width(ellipsis)
    if max_val_width <= ell_w:
        return ellipsis[:max_val_width]
    budget = max_val_width - ell_w
    acc: list[str] = []
    cur_w = 0
    for ch in clean:
        ch_w = display_width(ch)
        if cur_w + ch_w > budget:
            break
        acc.append(ch)
        cur_w += ch_w
    trimmed = "".join(acc).rstrip()
    return f"{trimmed}{ellipsis}"


def format_session_header_lines(
    label: str | None = None,
    sdir: Path | None = None,
    work_dir: Path | str | None = None,
    sandbox_mode: str | None = None,
    cd_dirs: list[str] | None = None,
    max_width: int | None = None,
    clamp_width: int | None = None,
) -> list[str]:
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label)
    hdr_items = parse_bundle_header_items(resolved_sdir, include_transport=False)
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
    norm_sb = normalize_sandbox_mode(sb_val)
    if norm_sb and norm_sb != "off":
        lines.append(f"Sandbox: {format_sandbox_header(sb_val)}")

    exposed_indices: set[int] = set()
    for raw_k, val in hdr_items:
        if is_bundle_transport_header(raw_k) or raw_k.lower() in HIDDEN_SESSION_HEADER_KEYS or not val:
            continue
        exposed_indices.add(len(lines))
        lines.append(f"{raw_k}: {val}")

    if exposed_indices:
        eff_width = (
            clamp_width
            if clamp_width is not None
            else (max_width if max_width is not None else max(24, _hr_width() - 2))
        )
        key_widths = []
        for ln in lines:
            m_kv = _KV_LINE_RE.match(ln)
            if m_kv:
                key_widths.append(len(m_kv.group(1)))
        pad_w = (max(key_widths) + 1) if len(key_widths) >= 2 else 0
        for idx in sorted(exposed_indices):
            m_kv = _KV_LINE_RE.match(lines[idx])
            if not m_kv:
                continue
            key_lbl, val_txt = m_kv.group(1), m_kv.group(2).lstrip()
            prefix_w = max(len(key_lbl) + 1, pad_w)
            avail_val = max(12, eff_width - prefix_w)
            clamped = _truncate_display_width(val_txt, avail_val)
            lines[idx] = f"{key_lbl} {clamped}"

    aligned = _align_kv_lines(lines)
    if max_width is None:
        return aligned
    wrapped: list[str] = []
    for idx, line in enumerate(aligned):
        if idx not in exposed_indices and display_width(line) > max_width:
            wrapped.extend(_wrap_box_line(line, max_width))
        else:
            wrapped.append(line)
    return wrapped


def _safety_prompt_suffix(default_yes: bool) -> str:
    return "[Y/n/i(nfo)]:" if default_yes else "[y/n/i(nfo)]:"


def format_safety_box(
    label: str,
    findings: list[dict[str, object]],
    default_yes: bool = False,
    summary: dict[str, object] | None = None,
    note: str = "",
    script_path: Path | None = None,
    edited: bool = False,
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[str, int, int]:
    meta_str = str(summary.get("meta", "")) if summary else ""
    title = " START STEP "
    prompt_suffix = _safety_prompt_suffix(default_yes)
    prompt_line = f"-> Execute this block? {prompt_suffix}"
    if term_cols is None or term_rows is None:
        det_cols, det_rows = _term_size()
        if term_cols is None:
            term_cols = det_cols
        if term_rows is None:
            term_rows = det_rows
    max_row_len = max(24, term_cols - 2)

    sdir = _resolve_session_dir(label, script_path)
    wdir = str(summary.get("work_dir") or "") if summary else ""
    cd_dirs = list(summary.get("cd_dirs") or []) if summary else []
    sb_mode = str(summary.get("sandbox") or "") if summary else ""
    content_lines: list[str] = format_session_header_lines(
        label=label,
        sdir=sdir,
        work_dir=wdir or None,
        sandbox_mode=sb_mode or None,
        cd_dirs=cd_dirs,
        clamp_width=max_row_len,
    )
    if summary:
        detail_lines: list[str] = []
        if meta_str:
            script_line = f"Script: {meta_str} (edited)" if edited else f"Script: {meta_str}"
            detail_lines.append(script_line)
        elif edited:
            detail_lines.append("Script: (edited)")
        ops = list(summary.get("operations") or [])
        op_groups = list(summary.get("operation_groups") or [])
        op_steps = list(summary.get("operation_steps") or [])
        max_step_num = max((int(s.get("step") or 0) for s in op_steps), default=0)
        step_num_w = len(f"{max_step_num}.") if max_step_num > 0 else None
        if ops:
            if detail_lines:
                detail_lines.append("")
            detail_lines.append(f"{_KEY_COLOR}Operations:{_ANSI_RESET}" if _use_color() else "Operations:")
            op_lines: list[str] = []
            display_groups = _group_operations_for_display(ops, op_groups, op_steps)
            for g_dir, g_items, g_nums in display_groups:
                if g_dir is not None:
                    dir_hdr = g_dir if g_dir else (wdir or ".")
                    op_lines.append(f"  {dir_hdr}:")
                    item_indent = "    "
                else:
                    item_indent = "  "
                op_lines.extend(
                    _wrap_labeled_items(
                        g_items, max_row_len, indent=item_indent, step_nums=g_nums, num_width=step_num_w
                    )
                )
            detail_lines.extend(_colorize_operation_lines(op_lines))
        if detail_lines:
            if content_lines:
                content_lines.append("")
            content_lines.extend(detail_lines)

    if findings:
        if content_lines:
            content_lines.append("")
        warn_hdr = f"Safety warnings ({len(findings)}):"
        content_lines.append(f"{_WARN_COLOR}{warn_hdr}{_ANSI_RESET}" if _use_color() else warn_hdr)
        warn_items = [(str(f["category"]), str(f["snippet"])) for f in findings]
        warn_lines = _wrap_labeled_items(warn_items, max_row_len, indent="  ")
        content_lines.extend(_colorize_warning_lines(warn_lines))

    if note.strip():
        if content_lines:
            content_lines.append("")
        content_lines.append("Analyzer:")
        for nline in note.strip().splitlines():
            content_lines.extend(
                textwrap.wrap(nline, width=max_row_len - 2, initial_indent="  ", subsequent_indent="  ")
                or [f"  {nline}"]
            )

    if findings and _use_color():
        prompt_line = f"{_PROMPT_WARN_COLOR}{prompt_line}{_ANSI_RESET}"
    return _render_block(
        title,
        content_lines,
        prompt_line=prompt_line,
        term_cols=term_cols,
        term_rows=term_rows,
    )


def format_info_box(title: str, content_lines: list[str]) -> str:
    box, _, _ = _render_block(title, content_lines)
    return box


def format_prompt_box(
    title: str,
    content_lines: list[str],
    prompt_line: str,
    status_lines: list[str] | tuple[str, ...] = (),
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[str, int, int]:
    _ = status_lines
    return _render_block(
        title,
        content_lines,
        prompt_line=prompt_line,
        term_cols=term_cols,
        term_rows=term_rows,
    )


def _fit_prompt_content_lines(lines: list[str], max_width: int) -> list[str]:
    aligned = _align_kv_lines(lines)
    if max_width <= 0:
        return aligned
    fitted: list[str] = []
    for line in aligned:
        if display_width(line) <= max_width:
            fitted.append(line)
            continue
        m_kv = _KV_LINE_RE.match(line)
        if m_kv and m_kv.group(1) == "Title:":
            key_lbl = m_kv.group(1)
            val_txt = m_kv.group(2).lstrip()
            gap = len(line) - len(key_lbl) - len(val_txt)
            prefix = key_lbl + (" " * max(1, gap))
            avail = max(8, max_width - len(prefix))
            fitted.append(prefix + _truncate_display_width(val_txt, avail))
        else:
            fitted.append(line)
    return fitted


def _build_prompt_yes_no_suffix(
    default_yes: bool,
    has_script: bool = False,
    has_output: bool = False,
    can_copy: bool = False,
    has_renumber: bool = False,
    renumber_only: bool = False,
    copy_on_yes: bool = False,
    has_info: bool = False,
) -> str:
    _ = has_script, has_output, can_copy
    if renumber_only:
        parts = ["r(enumber)", "n"]
    elif copy_on_yes and has_renumber:
        parts = ["Y", "n", "r(enumber)"]
    else:
        parts = ["Y", "n"] if default_yes else ["y", "N"]
        if has_renumber:
            parts.append("r(enumber)")
    if has_info:
        parts.append("i(nfo)")
    return f"[{'/'.join(parts)}]:"


def prompt_yes_no_box(
    title: str,
    content_lines: list[str],
    question: str,
    default_yes: bool = False,
    yes_status: str = "✓ Confirmed by user.",
    no_status: str = "✗ Canceled by user.",
    tty_streams: tuple[object, object] | None = None,
    script_path: Path | None = None,
    out_path: Path | None = None,
    renumber_label: str | None = None,
    renumber_status: str | None = None,
    content_builder=None,
    renumber_only: bool = False,
    copy_on_yes: bool = False,
    label: str | None = None,
    sdir: Path | None = None,
    sandbox_mode: str | None = None,
    enable_info: bool | None = None,
    allow_overwrite: bool = False,
    overwrite_status: str | None = None,
) -> bool | str:
    has_script = script_path is not None and script_path.is_file()
    has_output = out_path is not None and out_path.is_file()
    can_copy = has_output
    has_renumber = bool(renumber_label)
    has_info = (title.strip() != "CLEAN SESSIONS") if enable_info is None else bool(enable_info)
    eff_default_yes = False if renumber_only else default_yes
    eff_default_no = False if renumber_only else (not eff_default_yes)
    allow_yes = not renumber_only
    renum_msg = renumber_status or (f"✓ Renumbering to {renumber_label}." if has_renumber else "")
    overw_msg = overwrite_status or (f"✓ Overwriting {label}." if label else "✓ Overwriting existing step.")
    suffix = _build_prompt_yes_no_suffix(
        eff_default_yes,
        has_script=has_script,
        has_output=has_output,
        can_copy=can_copy,
        has_renumber=has_renumber,
        renumber_only=renumber_only,
        copy_on_yes=copy_on_yes,
        has_info=has_info,
    )
    prompt_line = f"-> {question} {suffix}"
    status_list: list[str] = [yes_status, no_status]
    if has_renumber:
        status_list.append(renum_msg)
    if allow_overwrite:
        status_list.append(overw_msg)
    clip_target: Path | None = None
    clip: tuple[list[str], str] | None = None

    def _refresh_clip_target() -> None:
        nonlocal clip_target, clip
        if not (can_copy and out_path is not None):
            return
        try:
            full_out = out_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            full_out = ""
        clip_target = resolve_clipboard_target(out_path, full_out)
        clip = clipboard_command(clip_target)

    _refresh_clip_target()
    if can_copy and clip_target is not None:
        status_list.append(f"✓ Copied {clip_target} to clipboard.")
        if clip is not None:
            status_list.append(f"✗ Clipboard copy failed; run: {clip[1]}")
        else:
            status_list.append(f"✗ No clipboard tool found for {clip_target}.")
    extra_keys: dict[str, str] = {}
    if has_renumber:
        extra_keys["r"] = "renumber"
        extra_keys["renumber"] = "renumber"
    if has_info:
        extra_keys["i"] = "info"
        extra_keys["info"] = "info"
        extra_keys["d"] = "info"
        extra_keys["details"] = "info"
    prev_cols, prev_rows = _term_size()
    init_lines = content_builder() if callable(content_builder) else content_lines
    box, rule_width, cursor_offset = format_prompt_box(
        title,
        _fit_prompt_content_lines(init_lines, max(24, prev_cols - 2)),
        prompt_line,
        status_lines=status_list,
        term_cols=prev_cols,
        term_rows=prev_rows,
    )
    _, border_col = _block_colors(title)
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    box_lines_init = box.splitlines()
    prefixed_prompt = (
        box_lines_init[-2] if len(box_lines_init) >= 2 else _prefix_block_line(prompt_line, border_color=border_col)
    )
    try:
        if tty_streams is not None:
            tty_w, tty_r = tty_streams
            close_after = False
        else:
            tty_w, tty_r = open_tty()
            close_after = True
        try:
            tty_w.write(f"{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            status_line: str | None = None
            result: bool | str = False
            first_read = True
            while True:
                action = read_confirm_key(
                    tty_r,
                    default_yes=eff_default_yes,
                    default_no=eff_default_no,
                    extra_keys=extra_keys,
                    allow_yes=allow_yes,
                    flush=first_read,
                )
                first_read = False
                if action == "resize":
                    new_cols, new_rows = _term_size()
                    if (new_cols, new_rows) != (prev_cols, prev_rows):
                        up_rows = _box_rows_above_prompt(box, new_cols)
                        prev_cols, prev_rows = new_cols, new_rows
                        cur_lines = content_builder() if callable(content_builder) else content_lines
                        box, rule_width, cursor_offset = format_prompt_box(
                            title,
                            _fit_prompt_content_lines(cur_lines, max(24, new_cols - 2)),
                            prompt_line,
                            status_lines=status_list,
                            term_cols=new_cols,
                            term_rows=new_rows,
                        )
                        bottom = _format_bottom_rule(rule_width, border_color=border_col)
                        box_lines_res = box.splitlines()
                        prefixed_prompt = (
                            box_lines_res[-2]
                            if len(box_lines_res) >= 2
                            else _prefix_block_line(prompt_line, border_color=border_col)
                        )
                        move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                        tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "info" and has_info:
                    info_edit_target = out_path if (has_output and out_path is not None) else (script_path if has_script else None)
                    info_state = _show_info_fullscreen(
                        title_kind=title.strip(),
                        label=label or title.strip(),
                        sdir=sdir,
                        out_path=out_path if has_output else None,
                        script_path=script_path if has_script else None,
                        edit_target=info_edit_target,
                        sandbox_mode=sandbox_mode,
                        extra_lines=content_builder() if callable(content_builder) else content_lines,
                        tty_r=tty_r,
                        tty_w=tty_w,
                        allow_copy=False,
                        allow_overwrite=allow_overwrite,
                    )
                    if info_state.get("edited"):
                        _refresh_clip_target()
                    if info_state.get("action") == "overwrite" and allow_overwrite:
                        status_line = overw_msg
                        result = "overwrite"
                        break
                    new_cols, new_rows = _term_size()
                    if info_state.get("edited") or (new_cols, new_rows) != (prev_cols, prev_rows):
                        up_rows = _box_rows_above_prompt(box, new_cols)
                        prev_cols, prev_rows = new_cols, new_rows
                        cur_lines = content_builder() if callable(content_builder) else content_lines
                        box, rule_width, cursor_offset = format_prompt_box(
                            title,
                            _fit_prompt_content_lines(cur_lines, max(24, new_cols - 2)),
                            prompt_line,
                            status_lines=status_list,
                            term_cols=new_cols,
                            term_rows=new_rows,
                        )
                        bottom = _format_bottom_rule(rule_width, border_color=border_col)
                        box_lines_res = box.splitlines()
                        prefixed_prompt = (
                            box_lines_res[-2]
                            if len(box_lines_res) >= 2
                            else _prefix_block_line(prompt_line, border_color=border_col)
                        )
                        move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                        tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if (action == "copy" or (copy_on_yes and action == "yes")) and can_copy and clip_target is not None:
                    if clip is not None and copy_file_to_clipboard(clip[0], clip_target):
                        status_line = f"✓ Copied {clip_target} to clipboard."
                        result = "copy" if copy_on_yes else False
                    elif clip is not None:
                        status_line = f"✗ Clipboard copy failed; run: {clip[1]}"
                        result = False
                    else:
                        status_line = f"✗ No clipboard tool found for {clip_target}."
                        result = False
                    break
                if action == "renumber" and has_renumber:
                    status_line = renum_msg
                    result = "renumber"
                    break
                if action == "yes" and allow_yes:
                    result = True
                    break
                if action == "no":
                    result = False
                    break
            if status_line is None:
                status_line = yes_status if result else no_status
            prefixed_status = _prefix_block_line(status_line, border_color=border_col)
            tty_w.write(f"\r\033[K{prefixed_status}\n\r\033[K{bottom}\n")
            tty_w.flush()
            return result
        finally:
            if close_after:
                tty_w.close()
                tty_r.close()
    except OSError:
        return eff_default_yes if (not copy_on_yes and not renumber_only) else False


def resolve_editor_command() -> list[str]:
    cfg_ed, _ = get_setting("editor")
    if cfg_ed and cfg_ed.lower() != "auto":
        return shlex.split(cfg_ed)
    for env_k in ("VISUAL", "EDITOR"):
        val = os.environ.get(env_k, "").strip()
        if val:
            return shlex.split(val)
    for candidate in ("vim", "vi", "less", "nano", "more"):
        if shutil.which(candidate):
            return [candidate]
    return ["vi"]


def open_script_in_editor(script_path: Path, tty_r, tty_w) -> None:
    cmd = resolve_editor_command() + [str(script_path)]
    try:
        subprocess.run(cmd, stdin=tty_r, stdout=tty_w, stderr=tty_w, check=False)
    except Exception as exc:
        tty_w.write(f"\n[editor error: {exc}]\n")
        tty_w.flush()


def _parse_confirm_line(
    line: str,
    default_yes: bool,
    default_no: bool = False,
    extra_keys: dict[str, str] | None = None,
    case_sensitive_keys: dict[str, str] | None = None,
    allow_yes: bool = True,
) -> str:
    if not line:
        return "yes" if default_yes else "no"
    raw_ans = line.strip()
    if case_sensitive_keys and raw_ans in case_sensitive_keys:
        return case_sensitive_keys[raw_ans]
    ans = raw_ans.lower()
    if extra_keys and ans in extra_keys:
        return extra_keys[ans]
    if ans in ("e", "edit"):
        return "edit"
    if ans in ("v", "view"):
        return "view"
    if allow_yes and ans in ("y", "yes"):
        return "yes"
    if default_yes and ans == "":
        return "yes"
    if default_no and ans == "":
        return "no"
    if ans in ("n", "no", "q", "esc", "\x1b"):
        return "no"
    return "invalid"


def read_confirm_key(
    tty_r,
    default_yes: bool,
    default_no: bool = False,
    extra_keys: dict[str, str] | None = None,
    case_sensitive_keys: dict[str, str] | None = None,
    *,
    allow_yes: bool = True,
    flush: bool = True,
) -> str:
    """Reads a single key: returns 'yes', 'no', 'view', 'resize', or an extra_keys action."""
    if flush:
        flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        return _parse_confirm_line(
            tty_r.readline(),
            default_yes,
            default_no=default_no,
            extra_keys=extra_keys,
            case_sensitive_keys=case_sensitive_keys,
            allow_yes=allow_yes,
        )
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        return _parse_confirm_line(
            tty_r.readline(),
            default_yes,
            default_no=default_no,
            extra_keys=extra_keys,
            case_sensitive_keys=case_sensitive_keys,
            allow_yes=allow_yes,
        )
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
                    return "no"
                ch_str = ch.decode("latin1")
                if case_sensitive_keys and ch_str in case_sensitive_keys:
                    return case_sensitive_keys[ch_str]
                ch_low = ch_str.lower()
                if extra_keys and ch_low in extra_keys:
                    return extra_keys[ch_low]
                if ch in (b"e", b"E"):
                    return "edit"
                if ch in (b"v", b"V"):
                    return "view"
                if allow_yes and ch in (b"y", b"Y"):
                    return "yes"
                if ch in (b"\r", b"\n"):
                    if default_yes:
                        return "yes"
                    if default_no:
                        return "no"
                if ch in (b"n", b"N", b"q", b"Q", b"\x03", b"\x04"):
                    return "no"
                if ch == b"\x1b":
                    rlist, _, _ = select.select([fd], [], [], 0.05)
                    if rlist:
                        os.read(fd, 32)
                        continue
                    return "no"
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
        except Exception:
            pass


def _write_orig_backup_once(orig_path: Path, raw_bytes: bytes) -> None:
    if orig_path.exists():
        return
    fd = os.open(orig_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f_orig:
        f_orig.write(raw_bytes)


def _is_file_edited(file_path: Path | None, orig_path: Path | None = None) -> bool:
    if file_path is None:
        return False
    resolved_orig = orig_path if orig_path is not None else _orig_file_backup_path(file_path)
    if not resolved_orig.is_file() or not file_path.is_file():
        return False
    try:
        return file_path.read_bytes() != resolved_orig.read_bytes()
    except OSError:
        return False


def _safety_prompt_prefix(default_yes: bool, has_findings: bool, border_color: str) -> str:
    raw_prompt = f"-> Execute this block? {_safety_prompt_suffix(default_yes)}"
    if has_findings and _use_color():
        raw_prompt = f"{_PROMPT_WARN_COLOR}{raw_prompt}{_ANSI_RESET}"
    return _prefix_block_line(raw_prompt, border_color=border_color)


def confirm_execution(
    label: str,
    script_text: str,
    summary: dict[str, object] | None = None,
    script_path: Path | None = None,
    auto_yes: bool = False,
) -> tuple[bool, str]:
    if in_run_block():
        return True, ""
    findings = scan_script_risks(script_text)
    note = ""
    approve_decision = ""
    approve_cmd, _ = get_setting("approve_cmd")
    wdir = Path(str(summary.get("work_dir"))) if summary and summary.get("work_dir") else get_work_dir()
    orig_sandbox = str(summary.get("sandbox") or "") if summary else ""
    if approve_cmd:
        plan_obj = analyze_script(script_text, work_dir=wdir, label=label, check_syntax=False)
        approve_decision, note = run_approve_cmd(approve_cmd, label, script_text, plan_obj, script_path=script_path)
        if approve_decision == "reject":
            return False, (note or "rejected by RUN_BLOCK_APPROVE_CMD")
        if approve_decision == "approve":
            if findings and (auto_yes or not sys.stdout.isatty() or no_clipboard()):
                for f in findings:
                    sys.stdout.write(f"[{label}] safety warning [{f['category']}]: {f['snippet']}\n")
                sys.stdout.flush()
            return True, note
    if auto_yes or not sys.stdout.isatty() or no_clipboard():
        if findings:
            for f in findings:
                sys.stdout.write(f"[{label}] safety warning [{f['category']}]: {f['snippet']}\n")
            sys.stdout.flush()
        return True, note
    orig_path = _orig_backup_path(script_path) if script_path is not None else None
    is_edited = _is_file_edited(script_path, orig_path)
    default_yes = (len(findings) == 0 and approve_decision != "prompt")
    prev_cols, prev_rows = _term_size()
    box, rule_width, cursor_offset = format_safety_box(
        label,
        findings,
        default_yes=default_yes,
        summary=summary,
        note=note,
        script_path=script_path,
        edited=is_edited,
        term_cols=prev_cols,
        term_rows=prev_rows,
    )
    _, border_col = _block_colors("START STEP")
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    ce_lines = box.splitlines()
    prefixed_prompt = (
        ce_lines[-2] if len(ce_lines) >= 2 else _safety_prompt_prefix(default_yes, bool(findings), border_col)
    )
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            first_read = True
            info_extra_keys = {"i": "info", "info": "info", "d": "info", "details": "info"}
            while True:
                action = read_confirm_key(
                    tty_r,
                    default_yes=default_yes,
                    default_no=False,
                    extra_keys=info_extra_keys,
                    flush=first_read,
                )
                first_read = False
                if action == "resize":
                    new_cols, new_rows = _term_size()
                    if (new_cols, new_rows) != (prev_cols, prev_rows):
                        up_rows = _box_rows_above_prompt(box, new_cols)
                        prev_cols, prev_rows = new_cols, new_rows
                        box, rule_width, cursor_offset = format_safety_box(
                            label,
                            findings,
                            default_yes=default_yes,
                            summary=summary,
                            note=note,
                            script_path=script_path,
                            edited=is_edited,
                            term_cols=new_cols,
                            term_rows=new_rows,
                        )
                        bottom = _format_bottom_rule(rule_width, border_color=border_col)
                        ce_lines = box.splitlines()
                        prefixed_prompt = (
                            ce_lines[-2]
                            if len(ce_lines) >= 2
                            else _safety_prompt_prefix(default_yes, bool(findings), border_col)
                        )
                        move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                        tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "info":
                    ce_sdir = _resolve_session_dir(label, script_path)

                    def _on_start_step_edit(_edited_path: Path) -> dict[str, object]:
                        nonlocal script_text, summary, findings, approve_decision, note, default_yes, is_edited
                        if script_path is None or not script_path.is_file():
                            return {}
                        new_text = script_path.read_text(encoding="utf-8", errors="replace")
                        script_text = new_text
                        summary = summarize_script_actions(script_text, work_dir=wdir)
                        if orig_sandbox:
                            summary["sandbox"] = orig_sandbox
                        findings = scan_script_risks(script_text)
                        if approve_cmd:
                            plan_obj = analyze_script(script_text, work_dir=wdir, label=label, check_syntax=False)
                            approve_decision, note = run_approve_cmd(
                                approve_cmd, label, script_text, plan_obj, script_path=script_path
                            )
                            if approve_decision == "reject":
                                return {"reject_msg": note or "rejected by RUN_BLOCK_APPROVE_CMD"}
                        default_yes = (len(findings) == 0 and approve_decision != "prompt")
                        is_edited = _is_file_edited(script_path, orig_path)
                        return {
                            "summary": summary,
                            "findings": findings,
                            "note": note,
                            "edited": is_edited,
                        }

                    info_state = _show_info_fullscreen(
                        title_kind="START STEP",
                        label=label,
                        sdir=ce_sdir,
                        script_path=script_path,
                        edit_target=script_path,
                        summary=summary,
                        findings=findings,
                        note=note,
                        sandbox_mode=orig_sandbox or None,
                        edited=is_edited,
                        tty_r=tty_r,
                        tty_w=tty_w,
                        allow_copy=False,
                        on_edit_callback=_on_start_step_edit,
                    )
                    if info_state.get("reject_msg"):
                        reject_msg = str(info_state["reject_msg"])
                        prefixed_rej = _prefix_block_line(f"✗ {reject_msg}", border_color=border_col)
                        tty_w.write(f"\r\033[K{prefixed_rej}\n\r\033[K{bottom}\n")
                        tty_w.flush()
                        return False, reject_msg
                    new_cols, new_rows = _term_size()
                    if info_state.get("edited") or (new_cols, new_rows) != (prev_cols, prev_rows):
                        up_rows = _box_rows_above_prompt(box, new_cols)
                        prev_cols, prev_rows = new_cols, new_rows
                        box, rule_width, cursor_offset = format_safety_box(
                            label,
                            findings,
                            default_yes=default_yes,
                            summary=summary,
                            note=note,
                            script_path=script_path,
                            edited=is_edited,
                            term_cols=new_cols,
                            term_rows=new_rows,
                        )
                        bottom = _format_bottom_rule(rule_width, border_color=border_col)
                        ce_lines = box.splitlines()
                        prefixed_prompt = (
                            ce_lines[-2]
                            if len(ce_lines) >= 2
                            else _safety_prompt_prefix(default_yes, bool(findings), border_col)
                        )
                        move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                        tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "yes":
                    approved = True
                    break
                if action == "no":
                    approved = False
                    break
            run_target = str(script_path) if script_path is not None else label
            status_line = f"✓ Running {run_target} ..." if approved else f"✗ Aborted (--retry {label})"
            prefixed_status = _prefix_block_line(status_line, border_color=border_col)
            tty_w.write(f"\r\033[K{prefixed_status}\n\r\033[K{bottom}\n")
            tty_w.flush()
            return approved, ("" if approved else "USER_ABORTED")
    except OSError:
        return True, note


# --- Built-in token and byte statistics ---
def gpt_encoder() -> None:
    return None


def count_tokens(data: bytes) -> dict[str, int | bool]:
    text = data.decode("utf-8", "replace")
    chars = len(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    gpt = math.ceil(chars / 4)
    return {
        "bytes": len(data),
        "chars": chars,
        "lines": lines,
        "claude": math.ceil(chars / 3.5),
        "gpt": gpt,
        "gpt_exact": False,
        "gemini": math.ceil(chars / 4),
    }


def _human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.1f} GB"


def _human_tok(n: int) -> str:
    if n < 1000:
        return f"{n}"
    if n < 1_000_000:
        return f"{n / 1000:.1f}k"
    return f"{n / 1_000_000:.1f}M"


def _human_chars(num_chars: int, *, short: bool = False) -> str:
    n = max(0, int(num_chars))
    if short:
        return f"{_human_tok(n)} ch"
    if n < 1000:
        return f"{n} char{'s' if n != 1 else ''}"
    return f"{_human_tok(n)} chars"


def format_stats(data: bytes) -> str:
    s = count_tokens(data)
    lines = int(s["lines"])
    sz = _human_chars(int(s["chars"]))
    lo = min(int(s["gpt"]), int(s["claude"]))
    hi = max(int(s["gpt"]), int(s["claude"]))
    tok_str = f"~{_human_tok(lo)}–{_human_tok(hi)} tokens" if lo != hi else f"~{_human_tok(lo)} tokens"
    line_lbl = f"{lines} line{'s' if lines != 1 else ''}"
    return f"{line_lbl} · {sz} · {tok_str}"


def stats_line(path: Path) -> str | None:
    enabled, _ = get_setting("token_stats")
    if enabled == "false":
        return None
    try:
        return format_stats(path.read_bytes())
    except Exception:
        return None


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
CR_LINE_RE = re.compile(r"[^\n]*\r(?!\n)")


def resolve_clipboard_target(out_path: Path, full_output: str) -> Path:
    matches = re.findall(
        r"^(?:\[[A-Za-z0-9._-]+\] Attach:|\s*Bundle:)\s*(\S+)\s*$",
        full_output,
        flags=re.MULTILINE,
    )
    if matches:
        candidate = Path(matches[-1])
        if candidate.is_file():
            return candidate
    return out_path


def clipboard_command(out_path: Path) -> tuple[list[str], str] | None:
    if shutil.which("xclip") and os.environ.get("DISPLAY"):
        return ["xclip", "-selection", "clipboard"], f"xclip -selection clipboard < {out_path}"
    if shutil.which("wl-copy") and os.environ.get("WAYLAND_DISPLAY"):
        return ["wl-copy"], f"wl-copy < {out_path}"
    if shutil.which("pbcopy"):
        return ["pbcopy"], f"pbcopy < {out_path}"
    if shutil.which("xsel") and os.environ.get("DISPLAY"):
        return ["xsel", "--clipboard", "--input"], f"xsel --clipboard --input < {out_path}"
    if shutil.which("clip.exe"):
        return ["clip.exe"], f"clip.exe < {out_path}"
    return None


def copy_file_to_clipboard(cmd: list[str], out_path: Path) -> bool:
    try:
        with open(out_path, "rb") as f_in:
            r = subprocess.run(
                cmd,
                stdin=f_in,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            )
        return r.returncode == 0
    except Exception:
        return False


_KV_LINE_RE = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*:)\s+(.*\S.*)$")
_TITLE_COLORS = {
    "START SESSION": "\x1b[1;96m",
    "START STEP": "\x1b[1;93m",
    "END STEP": "\x1b[1;92m",
    "SYNTAX ERROR": "\x1b[1;91m",
    "NOT RUN": "\x1b[1;91m",
    "MISSING PREVIOUS STEP": "\x1b[1;93m",
    "STEP ALREADY EXISTS": "\x1b[1;93m",
    "SESSION COMPLETED": "\x1b[1;93m",
    "END SESSION": "\x1b[1;92m",
}
_BORDER_COLOR = "\x1b[96m"
_KEY_COLOR = "\x1b[2m"
_ERROR_COLOR = "\x1b[1;91m"
_WARN_COLOR = "\x1b[1;31m"
_HIGHLIGHT_COLOR = "\x1b[1;33m"
_PROMPT_WARN_COLOR = "\x1b[1;93m"
_TAG_COLORS = {
    "read": "\x1b[1;94m",
    "write": "\x1b[1;33m",
    "exec": "\x1b[1;35m",
    "git": "\x1b[1;36m",
    "python": "\x1b[1;32m",
}
_BUNDLE_TAG_COLORS = {
    "total": "\x1b[1;97m",
    "header": "\x1b[2m",
    "bundle": "\x1b[1;34m",
    "ruleset": "\x1b[1;36m",
    "group": "\x1b[1;34m",
    "rule": "\x1b[1;36m",
    "rules": "\x1b[1;36m",
    "cmd": "\x1b[1;35m",
    "file": "\x1b[1;94m",
    "include": "\x1b[1;94m",
    "prompt": "\x1b[1;33m",
    "task": "\x1b[1;33m",
    "context": "\x1b[1;94m",
    "section": "\x1b[1;32m",
    "text": "\x1b[1;32m",
    "body": "\x1b[1;32m",
}
_ANSI_RESET = "\x1b[0m"


def _block_colors(title: str, has_exit: bool = False) -> tuple[str, str]:
    clean_title = title.strip()
    if clean_title == "END STEP" and has_exit:
        t_col = "\x1b[1;91m"
    else:
        t_col = _TITLE_COLORS.get(clean_title, "\x1b[1;96m")
    if t_col.startswith("\x1b[1;"):
        b_col = "\x1b[" + t_col[4:]
    else:
        b_col = _BORDER_COLOR
    return t_col, b_col


def _supports_utf8(stream=None) -> bool:
    target = stream if stream is not None else sys.stdout
    enc = getattr(target, "encoding", None)
    if not enc:
        enc = sys.getdefaultencoding()
    return "utf" in str(enc).lower()


def _use_color(stream=None) -> bool:
    if os.environ.get("NO_COLOR", "") != "":
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    target = stream if stream is not None else sys.stdout
    try:
        return bool(target.isatty())
    except Exception:
        return False


def _align_kv_lines(lines: list[str]) -> list[str]:
    out = list(lines)
    i = 0
    n = len(out)
    while i < n:
        m = _KV_LINE_RE.match(out[i])
        if not m:
            i += 1
            continue
        j = i
        parsed: list[tuple[str, str]] = []
        while j < n:
            mj = _KV_LINE_RE.match(out[j])
            if not mj:
                break
            parsed.append((mj.group(1), mj.group(2).lstrip()))
            j += 1
        if len(parsed) >= 2:
            key_w = max(len(k) for k, _ in parsed)
            for idx, (k, v) in enumerate(parsed):
                out[i + idx] = f"{k.ljust(key_w)} {v}"
        i = j
    return out


def _is_same_cwd(wdir_val: str) -> bool:
    wdir_part = wdir_val.split("  (cd ->", 1)[0].strip()
    if not wdir_part:
        return False
    try:
        return Path(wdir_part).resolve() == Path(os.getcwd()).resolve()
    except OSError:
        return os.path.abspath(wdir_part) == os.path.abspath(os.getcwd())


def _colorize_kv_line(line: str, *, bright_stats: bool = False) -> str:
    if not _use_color():
        return line
    m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*:)(\s+)(.*)$", line)
    if m:
        key, spaces, val = m.group(1), m.group(2), m.group(3)
        if key == "Workdir:":
            if _is_same_cwd(val):
                return f"{_KEY_COLOR}{key}{spaces}{val}{_ANSI_RESET}"
            return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}{_HIGHLIGHT_COLOR}{val}{_ANSI_RESET}"
        if key == "Sandbox:" and val.strip() == "off":
            return f"{_KEY_COLOR}{key}{spaces}{val}{_ANSI_RESET}"
        if key == "Exit:" and val.strip() != "0":
            return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}{_WARN_COLOR}{val}{_ANSI_RESET}"
        if key == "Error:":
            return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}{_ERROR_COLOR}{val}{_ANSI_RESET}"
        if key == "Stats:" and bright_stats:
            return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}\x1b[97m{val}{_ANSI_RESET}"
        if key in ("Fix:", "Output:", "Stats:"):
            return f"{_KEY_COLOR}{key}{spaces}{val}{_ANSI_RESET}"
        return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}{val}"
    return line


def _regular_color(ansi_col: str) -> str:
    return ("\x1b[" + ansi_col[4:]) if ansi_col.startswith("\x1b[1;") else ansi_col

def _colorize_python_op_rest(rest: str) -> str:
    py_col = _regular_color(_TAG_COLORS["python"])
    write_col = _regular_color(_TAG_COLORS["write"])
    read_col = _regular_color(_TAG_COLORS["read"])
    parts: list[str] = []
    pos = 0
    for m in re.finditer(r"\b(writes:|reads:)\s+([^;]+)", rest):
        if m.start() > pos:
            parts.append(f"{py_col}{rest[pos:m.start()]}{_ANSI_RESET}")
        kind, body = m.group(1), m.group(2)
        seg_col = read_col if kind == "reads:" else write_col
        parts.append(f"{seg_col}{kind} {body}{_ANSI_RESET}")
        pos = m.end()
    if pos < len(rest):
        parts.append(f"{py_col}{rest[pos:]}{_ANSI_RESET}")
    return "".join(parts)

def _colorize_operation_lines(lines: list[str]) -> list[str]:
    if not _use_color():
        return lines
    out: list[str] = []
    last_tag = ""
    for line in lines:
        m = re.match(r"^(\s*)(\d+\.\s+|(?:├─|└─|\|-|`-)\s+)?(\[([a-z0-9_-]+)\])(\s+)(.*)$", line)
        if m:
            indent, num_part, tag_br, tag, spaces, rest = m.groups()
            num_str = num_part or ""
            if num_str and num_str.lstrip().startswith(("├─", "└─", "|-", "`-")):
                num_str = f"{_KEY_COLOR}{num_str}{_ANSI_RESET}"
            if tag in _TAG_COLORS:
                last_tag = tag
                t_col = _TAG_COLORS[tag]
                if tag == "python":
                    out.append(f"{indent}{num_str}{t_col}{tag_br}{_ANSI_RESET}{spaces}{_colorize_python_op_rest(rest)}")
                else:
                    body_col = _regular_color(t_col)
                    out.append(f"{indent}{num_str}{t_col}{tag_br}{_ANSI_RESET}{spaces}{body_col}{rest}{_ANSI_RESET}")
            else:
                last_tag = ""
                out.append(line)
        elif line.startswith("  ") and not line.lstrip().startswith("[") and not line.rstrip().endswith(":"):
            if last_tag == "python":
                out.append(_colorize_python_op_rest(line))
            elif last_tag in _TAG_COLORS:
                body_col = _regular_color(_TAG_COLORS[last_tag])
                out.append(f"{body_col}{line}{_ANSI_RESET}")
            else:
                out.append(line)
        else:
            last_tag = ""
            out.append(line)
    return out
def _colorize_warning_lines(lines: list[str]) -> list[str]:
    if not _use_color():
        return lines
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(\s*)(\[[^\]]+\])(\s+)(.*)$", line)
        if m:
            indent, tag_br, spaces, rest = m.groups()
            out.append(f"{indent}{_WARN_COLOR}{tag_br}{_ANSI_RESET}{spaces}{rest}")
        else:
            out.append(line)
    return out


def _colorize_bundle_lines(lines: list[str]) -> list[str]:
    if not _use_color():
        return lines
    out: list[str] = []
    tree_re = re.compile(r"^((?:│  |\|  |   )*(?:├─ |└─ |\|- |`- ))(.*)$")
    tab_re = re.compile(r"^(\s*)(\d+\s)?(\s*\S+%\s+\S+\s+\d+\s+~\S+\s+)(\[([a-z0-9_-]+)\])(\s+)(.*)$")
    hdr_re = re.compile(r"^(\s{2})((?:#\s+|\s+)%\s+CHARS\s+LINES\s+~TOK\s+KIND\s+SOURCE)\s*$")
    heavy_colors = {"warn": _WARN_COLOR, "accent": _HIGHLIGHT_COLOR}
    fn_heavy = globals().get("bundle_row_heavy_level")
    for line in lines:
        m_hdr = hdr_re.match(line)
        if m_hdr:
            out.append(f"{m_hdr.group(1)}\x1b[7m{m_hdr.group(2)}{_ANSI_RESET}")
            continue
        m_tab = tab_re.match(line)
        if m_tab:
            lead_sp, row_num_part, metrics_prefix, tag_br, tag, spaces, rest = m_tab.groups()
            num_col_s = f"{lead_sp}{_KEY_COLOR}{row_num_part}{_ANSI_RESET}" if row_num_part else lead_sp
            level = fn_heavy(line) if callable(fn_heavy) else ""
            if level in heavy_colors:
                metrics_prefix = f"{heavy_colors[level]}{metrics_prefix}{_ANSI_RESET}"
            t_col = _BUNDLE_TAG_COLORS.get(tag, _TAG_COLORS.get(tag, _BORDER_COLOR))
            m_tree = tree_re.match(rest)
            if m_tree:
                rest = f"{_KEY_COLOR}{m_tree.group(1)}{_ANSI_RESET}{m_tree.group(2)}"
            out.append(f"{num_col_s}{metrics_prefix}{t_col}{tag_br}{_ANSI_RESET}{spaces}{rest}")
            continue
        m = re.match(r"^(\s*)(\d+\.\s+)?(\[([a-z0-9_-]+)\])(\s+)(.*)$", line)
        if m:
            indent, num_part, tag_br, tag, spaces, rest = m.groups()
            num_str = num_part or ""
            t_col = _BUNDLE_TAG_COLORS.get(tag, _TAG_COLORS.get(tag, _BORDER_COLOR))
            out.append(f"{indent}{num_str}{t_col}{tag_br}{_ANSI_RESET}{spaces}{rest}")
        else:
            out.append(line)
    return out


def _char_display_width(ch: str) -> int:
    if unicodedata.category(ch) in ("Mn", "Me", "Cf", "Cc"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    clean = ANSI_RE.sub("", text)
    col = 0
    for ch in clean:
        if ch == "\t":
            col += 8 - (col % 8)
        elif ch in ("\n", "\r"):
            continue
        else:
            col += _char_display_width(ch)
    return col


def _expand_tabs(text: str, tabsize: int = 8) -> str:
    if "\t" not in text:
        return text
    out: list[str] = []
    col = 0
    pos = 0
    n = len(text)
    while pos < n:
        m_ansi = ANSI_RE.match(text, pos)
        if m_ansi:
            out.append(m_ansi.group(0))
            pos = m_ansi.end()
            continue
        ch = text[pos]
        if ch == "\t":
            spaces = tabsize - (col % tabsize)
            out.append(" " * spaces)
            col += spaces
        elif ch in ("\n", "\r"):
            out.append(ch)
            col = 0
        else:
            out.append(ch)
            col += _char_display_width(ch)
        pos += 1
    return "".join(out)


def _term_size() -> tuple[int, int]:
    sz = shutil.get_terminal_size((80, 24))
    cols = max(40, sz.columns if sz.columns > 0 else 80)
    rows = max(6, sz.lines if sz.lines > 0 else 24)
    return cols, rows


def _hr_width() -> int:
    return _term_size()[0]


def _term_rows() -> int:
    return _term_size()[1]


def _format_top_rule(
    title: str,
    width: int,
    title_color: str | None = None,
    border_color: str | None = None,
) -> str:
    clean_title = title.strip()
    hdr = clean_title
    right_len = max(4, width - 4 - display_width(hdr))
    if _supports_utf8():
        left = "╭─ "
        fill = "─" * right_len
    else:
        left = "+- "
        fill = "-" * right_len
    if _use_color():
        default_t, default_b = _block_colors(clean_title)
        t_col = title_color or default_t
        b_col = border_color or default_b
        return f"{b_col}{left}{_ANSI_RESET}{t_col}{hdr}{_ANSI_RESET} {b_col}{fill}{_ANSI_RESET}"
    return f"{left}{hdr} {fill}"


def _format_bottom_rule(width: int, border_color: str | None = None) -> str:
    dash_len = max(3, width - 1)
    rule = f"╰{'─' * dash_len}" if _supports_utf8() else f"+{'-' * dash_len}"
    if _use_color():
        b_col = border_color or _BORDER_COLOR
        return f"{b_col}{rule}{_ANSI_RESET}"
    return rule


def _prefix_block_line(line: str, border_color: str | None = None) -> str:
    bar = "│" if _supports_utf8() else "|"
    if _use_color():
        b_col = border_color or _BORDER_COLOR
        bar_str = f"{b_col}{bar}{_ANSI_RESET}"
        return f"{bar_str} {line}" if line else bar_str
    return f"{bar} {line}" if line else bar


_BOX_TAG_ITEM_RE = re.compile(
    r"^(\s*(?:\S+%\s+\S+\s+ch\s+\S+L\s+~\S+\s+tok\s+)?(?:\d+\.\s+)?"
    r"(?:(?:├─|└─|\|-|`-)\s+)?\[[^\]]+\]\s+(?:(?:│  |\|  |   )*(?:├─ |└─ |\|- |`- ))?(?:\d+\.\s+)?)(.*)$"
)
_BOX_TREE_ITEM_RE = re.compile(
    r"^(\s*(?:(?:│  |\|  |   )*(?:├─ |└─ |\|- |`- )|\d+\.\s+|[-*•]\s+))(.*)$"
)
_BOX_PROMPT_ARROW_RE = re.compile(r"^(->\s+)(.*)$")
_BOX_WS_INDENT_RE = re.compile(r"^(\s+)(.*\S.*)$")


def _detect_box_hanging_indent(plain: str, max_width: int) -> tuple[int, str]:
    m_kv = _KV_LINE_RE.match(plain)
    if m_kv:
        m_prefix = re.match(r"^([A-Za-z][A-Za-z0-9_-]*:\s+)(.*)$", plain)
        if m_prefix:
            pfx = m_prefix.group(1)
            indent_w = display_width(pfx)
            sub = (" " * indent_w) if (max_width - indent_w >= 8) else "  "
            return len(pfx), sub
    m_pr = _BOX_PROMPT_ARROW_RE.match(plain)
    if m_pr:
        pfx = m_pr.group(1)
        indent_w = display_width(pfx)
        sub = (" " * indent_w) if (max_width - indent_w >= 8) else "  "
        return len(pfx), sub
    lead_ws = re.match(r"^\s*", plain).group(0)  # type: ignore[union-attr]
    lead_w = display_width(lead_ws)
    for pat in (_BOX_TAG_ITEM_RE, _BOX_TREE_ITEM_RE):
        m_it = pat.match(plain)
        if m_it:
            pfx = m_it.group(1)
            indent_w = display_width(pfx)
            if max_width - indent_w >= 8:
                return len(pfx), " " * indent_w
            if max_width - lead_w >= 8:
                return len(pfx), lead_ws
            return len(pfx), ("  " if max_width >= 10 else "")
    m_ws = _BOX_WS_INDENT_RE.match(plain)
    if m_ws:
        pfx = m_ws.group(1)
        if max_width - lead_w >= 8:
            return len(pfx), pfx
        return len(pfx), ("  " if max_width >= 10 else "")
    return 0, ""


def _split_ansi_prefix(line: str, visible_count: int) -> tuple[str, str, str]:
    if visible_count <= 0:
        return "", line, ""
    pos = 0
    seen = 0
    active_sgr = ""
    n = len(line)
    while pos < n and seen < visible_count:
        m_ansi = ANSI_RE.match(line, pos)
        if m_ansi:
            seq = m_ansi.group(0)
            if seq in ("\x1b[0m", "\x1b[m"):
                active_sgr = ""
            elif seq.endswith("m"):
                active_sgr += seq
            pos = m_ansi.end()
            continue
        seen += 1
        pos += 1
    while pos < n:
        if ANSI_RE.match(line, pos):
            break
        if _char_display_width(line[pos]) == 0:
            pos += 1
            continue
        break
    return line[:pos], line[pos:], active_sgr


def _wrap_box_line(line: str, max_width: int) -> list[str]:
    line = _expand_tabs(line)
    if max_width <= 0 or display_width(line) <= max_width:
        return [line]
    plain = ANSI_RE.sub("", line)
    if not plain.strip():
        return [line]
    prefix_chars, sub_indent = _detect_box_hanging_indent(plain, max_width)
    prefix_raw, body_raw, active_after_prefix = _split_ansi_prefix(line, prefix_chars)
    prefix_w = display_width(prefix_raw)
    if prefix_w >= max_width:
        if not prefix_raw.strip():
            prefix_raw = "  " if max_width >= 10 else ""
            sub_indent = prefix_raw
            prefix_w = display_width(prefix_raw)
        else:
            prefix_raw, body_raw, active_after_prefix = "", line, ""
            sub_indent = ""
            prefix_w = 0

    # Parse body_raw into visible char elements: (ch, width, ansi_before, sgr_after)
    elems: list[tuple[str, int, str, str]] = []
    pos = 0
    n = len(body_raw)
    pending_ansi = ""
    cur_sgr = active_after_prefix
    while pos < n:
        m_ansi = ANSI_RE.match(body_raw, pos)
        if m_ansi:
            seq = m_ansi.group(0)
            pending_ansi += seq
            if seq in ("\x1b[0m", "\x1b[m"):
                cur_sgr = ""
            elif seq.endswith("m"):
                cur_sgr += seq
            pos = m_ansi.end()
            continue
        ch = body_raw[pos]
        cw = display_width(ch)
        elems.append((ch, cw, pending_ansi, cur_sgr))
        pending_ansi = ""
        pos += 1
    tail_ansi = pending_ansi

    if not elems:
        return [line]

    # Group elements into whitespace runs and non-whitespace words
    tokens: list[tuple[bool, list[tuple[str, int, str, str]]]] = []
    cur_tok: list[tuple[str, int, str, str]] = []
    cur_is_ws: bool | None = None
    for el in elems:
        el_ws = el[0].isspace()
        if cur_is_ws is None or el_ws == cur_is_ws:
            cur_tok.append(el)
            cur_is_ws = el_ws
        else:
            tokens.append((cur_is_ws, cur_tok))
            cur_tok = [el]
            cur_is_ws = el_ws
    if cur_tok and cur_is_ws is not None:
        tokens.append((cur_is_ws, cur_tok))

    first_avail = max(1, max_width - prefix_w)
    cont_avail = max(1, max_width - display_width(sub_indent))
    wrapped_lines: list[tuple[list[tuple[str, int, str, str]], str]] = []
    cur_line: list[tuple[str, int, str, str]] = []
    cur_w = 0
    cur_avail = first_avail
    line_start_sgr = active_after_prefix

    def _flush_line(next_start_sgr: str) -> None:
        nonlocal cur_line, cur_w, cur_avail, line_start_sgr
        while cur_line and cur_line[-1][0].isspace():
            cur_line.pop()
        wrapped_lines.append((cur_line, line_start_sgr))
        cur_line = []
        cur_w = 0
        cur_avail = cont_avail
        line_start_sgr = next_start_sgr

    for is_ws, tok in tokens:
        tok_w = sum(e[1] for e in tok)
        if is_ws:
            if not cur_line:
                line_start_sgr = tok[-1][3]
                continue
            if cur_w + tok_w <= cur_avail:
                cur_line.extend(tok)
                cur_w += tok_w
            else:
                _flush_line(tok[-1][3])
            continue

        if cur_w + tok_w <= cur_avail:
            cur_line.extend(tok)
            cur_w += tok_w
        elif cur_line and tok_w <= cont_avail:
            prev_sgr = cur_line[-1][3]
            _flush_line(prev_sgr)
            cur_line.extend(tok)
            cur_w = tok_w
        else:
            for el in tok:
                if cur_line and cur_w + el[1] > cur_avail:
                    prev_sgr = cur_line[-1][3]
                    _flush_line(prev_sgr)
                cur_line.append(el)
                cur_w += el[1]

    if cur_line or not wrapped_lines:
        wrapped_lines.append((cur_line, line_start_sgr))

    out: list[str] = []
    last_idx = len(wrapped_lines) - 1
    for idx, (l_elems, start_sgr) in enumerate(wrapped_lines):
        body_str = "".join(e[2] + e[0] for e in l_elems)
        if idx == 0:
            row = prefix_raw + body_str
            end_sgr = l_elems[-1][3] if l_elems else active_after_prefix
        else:
            reopen = ""
            if start_sgr:
                first_ansi = l_elems[0][2] if l_elems else ""
                if not (first_ansi.startswith("\x1b[0m") or first_ansi.startswith("\x1b[m")):
                    reopen = start_sgr
            row = sub_indent + reopen + body_str
            end_sgr = l_elems[-1][3] if l_elems else start_sgr
        if idx == last_idx:
            row += tail_ansi
        elif end_sgr:
            row += _ANSI_RESET
        out.append(row)
    return out


_SECTION_HDR_RE = re.compile(
    r"^(?:Operations:|Safety warnings(?: \(\d+\))?:|Analyzer:|Bundle warnings(?: \(\d+\))?:|Parts(?: \(\d+\))?:)$"
)


def _format_more_hint_row(hidden_count: int, indent: str = "  ", border_color: str | None = None) -> str:
    hint = f"{indent}... +{hidden_count} more"
    if _use_color():
        hint = f"{_KEY_COLOR}{hint}{_ANSI_RESET}"
    return _prefix_block_line(hint, border_color=border_color)


def _clamp_body_rows(
    body_rows: list[str],
    max_body_rows: int,
    border_color: str | None = None,
) -> list[str]:
    if max_body_rows <= 0:
        return []
    if len(body_rows) <= max_body_rows:
        return body_rows

    sep_row = _prefix_block_line("", border_color=border_color)
    groups: list[list[str]] = []
    cur: list[str] = []
    for row in body_rows:
        plain = ANSI_RE.sub("", row)
        content_part = plain[2:] if plain.startswith(("│ ", "| ")) else ("" if plain.strip() in ("│", "|") else plain)
        if not content_part.strip():
            if cur:
                groups.append(cur)
                cur = []
            continue
        if cur and _SECTION_HDR_RE.match(content_part.strip()):
            groups.append(cur)
            cur = [row]
            continue
        cur.append(row)
    if cur:
        groups.append(cur)

    if not groups:
        return [sep_row]

    n_seps = len(groups) - 1
    if max_body_rows <= n_seps + 1:
        kept = max(0, max_body_rows - 1)
        hidden = len(body_rows) - kept
        return [*body_rows[:kept], _format_more_hint_row(hidden, indent="", border_color=border_color)]

    avail = max_body_rows - n_seps
    n_groups = len(groups)
    alloc = [0] * n_groups
    if n_groups == 1:
        alloc[0] = min(len(groups[0]), avail)
    else:
        alloc[0] = min(len(groups[0]), max(2, avail // 2))
        for idx in range(1, n_groups):
            alloc[idx] = min(len(groups[idx]), 2)
        while sum(alloc) > avail:
            trimmed = False
            for idx in range(n_groups - 1, -1, -1):
                floor = 1 if idx == 0 else 0
                if alloc[idx] > floor:
                    alloc[idx] -= 1
                    trimmed = True
                    if sum(alloc) <= avail:
                        break
            if not trimmed:
                break
        rem = avail - sum(alloc)
        if rem > 0:
            for idx in range(n_groups):
                if rem <= 0:
                    break
                if len(groups[idx]) <= 5 and alloc[idx] < len(groups[idx]):
                    add = min(rem, len(groups[idx]) - alloc[idx])
                    alloc[idx] += add
                    rem -= add
            for idx in range(n_groups):
                if rem <= 0:
                    break
                if alloc[idx] < len(groups[idx]):
                    add = min(rem, len(groups[idx]) - alloc[idx])
                    alloc[idx] += add
                    rem -= add

    out: list[str] = []
    for idx, grp in enumerate(groups):
        take = alloc[idx]
        if take <= 0:
            continue
        if out:
            out.append(sep_row)
        if take >= len(grp):
            out.extend(grp)
        elif take == 1:
            plain_first = ANSI_RE.sub("", grp[0])
            c_first = plain_first[2:] if plain_first.startswith(("│ ", "| ")) else ""
            ind = "  " if c_first.startswith("  ") else ""
            out.append(_format_more_hint_row(len(grp), indent=ind, border_color=border_color))
        else:
            kept = take - 1
            hidden = len(grp) - kept
            plain_hidden = ANSI_RE.sub("", grp[kept])
            c_hidden = plain_hidden[2:] if plain_hidden.startswith(("│ ", "| ")) else ""
            ind = "  " if c_hidden.startswith("  ") else ""
            out.extend(grp[:kept])
            out.append(_format_more_hint_row(hidden, indent=ind, border_color=border_color))

    if len(out) > max_body_rows:
        kept = max(0, max_body_rows - 1)
        hidden = len(body_rows) - kept
        out = [*out[:kept], _format_more_hint_row(hidden, indent="", border_color=border_color)]
    return out


def _render_block(
    title: str,
    content_lines: list[str],
    prompt_line: str | None = None,
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[str, int, int]:
    clean_title = title.strip()
    hdr = clean_title
    cols = term_cols if term_cols is not None else _hr_width()
    rows_limit = term_rows if term_rows is not None else _term_rows()
    if prompt_line is None and term_rows is None:
        rows_limit = max(6, rows_limit - 1)
    width = max(min(cols, 48), display_width(hdr) + 8)
    max_content_w = max(1, cols - 2)
    expanded_content = [_expand_tabs(ln) for ln in content_lines]
    aligned_lines = _align_kv_lines(expanded_content)
    has_exit = any(l.startswith("Exit:") for l in aligned_lines)
    title_color, border_color = _block_colors(clean_title, has_exit=has_exit)
    top = _format_top_rule(title, width, title_color=title_color, border_color=border_color)
    bottom = _format_bottom_rule(width, border_color=border_color)
    body_rows: list[str] = []
    for line in aligned_lines:
        colored = _colorize_kv_line(line)
        for wline in _wrap_box_line(colored, max_content_w):
            body_rows.append(_prefix_block_line(wline, border_color=border_color))
    if not body_rows and prompt_line is None:
        body_rows = [_prefix_block_line("", border_color=border_color)]
    cursor_col_offset = 0
    prompt_rows: list[str] = []
    if prompt_line is not None:
        for wprompt in _wrap_box_line(_expand_tabs(prompt_line), max_content_w):
            prefixed_prompt = _prefix_block_line(wprompt, border_color=border_color)
            prompt_rows.append(prefixed_prompt)
            cursor_col_offset = display_width(prefixed_prompt)
    footer_rows = (1 + (1 if body_rows else 0) + len(prompt_rows)) if prompt_line is not None else 1
    max_body_rows = max(1, rows_limit - 1 - footer_rows)
    if len(body_rows) > max_body_rows:
        body_rows = _clamp_body_rows(body_rows, max_body_rows, border_color=border_color)
    rows: list[str] = list(body_rows)
    if prompt_line is not None:
        if body_rows:
            rows.append(_prefix_block_line("", border_color=border_color))
        rows.extend(prompt_rows)
    box = "\n".join([top, *rows, bottom])
    return box, width, cursor_col_offset


def _last_nonempty_line(path: Path, skip_prefixes: tuple[str, ...], max_len: int) -> str:
    try:
        if not path.is_file():
            return ""
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    for line in reversed(raw.splitlines()):
        s = line.strip()
        if not s:
            continue
        if skip_prefixes and any(s.startswith(p) for p in skip_prefixes):
            continue
        if display_width(s) > max_len:
            budget = max(1, max_len - 3)
            acc: list[str] = []
            cur_w = 0
            for ch in s:
                cw = display_width(ch)
                if cur_w + cw > budget:
                    break
                acc.append(ch)
                cur_w += cw
            return "".join(acc).rstrip() + "..."
        return s
    return ""


def _extract_last_error_line(out_path: Path, label: str | None = None, max_width: int | None = None) -> str:
    skip_prefixes: tuple[str, ...] = ()
    if label:
        skip_prefixes = (
            f"[{label}] START",
            f"[{label}] END",
            f"[{label}] STOP --fix",
            f"[{label}] <stdin> line ",
            f"[{label}] Note:",
            f"[{label}] patched ",
            f"[{label}] SECURITY WARNING:",
        )
    content_w = max_width if max_width is not None else max(24, _hr_width() - 2)
    max_len = max(24, content_w - 6)
    return _last_nonempty_line(out_path, skip_prefixes, max_len)


def _format_end_fix_status(label: str, resolved_sdir: Path | None) -> str:
    if "/" not in label:
        return ""
    sess, step = label.split("/", 1)
    base_step = step.split("_", 1)[0]
    try:
        max_attempts = int(get_setting("max_fix_attempts")[0])
    except Exception:
        max_attempts = 2
    used = 0
    fn_failed = globals().get("_consecutive_failed_fixes")
    if callable(fn_failed) and resolved_sdir is not None:
        try:
            used = int(fn_failed(resolved_sdir, base_step))
        except Exception:
            used = 0
    if used >= max_attempts:
        next_hint = f"; emit a fresh {sess}/{int(base_step) + 1} block instead" if base_step.isdigit() else ""
        return f"STOP --fix ({used}/{max_attempts} failed attempts{next_hint})"
    return f"{prog_name()} --fix {label} ({used}/{max_attempts} failed attempts)"


def _build_start_bundle_parts(
    sdir: Path | None,
    bundle_path: Path,
    *,
    details: bool = False,
    max_width: int | None = None,
    plan: dict[str, object] | None = None,
    include_part_count: bool = True,
    edited: bool = False,
) -> tuple[list[str], list[str]]:
    _ = include_part_count
    if plan is None:
        fn_load = globals().get("load_session_bundle_plan")
        if callable(fn_load):
            loaded = fn_load(sdir, bundle_path)
            if isinstance(loaded, dict):
                plan = loaded
    if not isinstance(plan, dict):
        return [], []
    max_row_len = max_width if max_width is not None else max(24, _hr_width() - 2)
    breakdown: list[str] = []
    if details:
        fn_parts = globals().get("format_bundle_parts_lines")
        part_lines = fn_parts(plan, max_width=max_row_len, edited=edited) if callable(fn_parts) else []
        if part_lines:
            breakdown.extend(_colorize_bundle_lines(part_lines))
    warnings_sec: list[str] = []
    fn_warns = globals().get("format_bundle_warning_items")
    warn_items = fn_warns(plan) if callable(fn_warns) else []
    if warn_items:
        whdr = f"Bundle warnings ({len(warn_items)}):"
        warnings_sec.append(f"{_WARN_COLOR}{whdr}{_ANSI_RESET}" if _use_color() else whdr)
        warnings_sec.extend(_colorize_warning_lines(_wrap_labeled_items(warn_items, max_row_len, indent="  ")))
    return breakdown, warnings_sec

def _build_start_bundle_sections(
    sdir: Path | None,
    bundle_path: Path,
    *,
    details: bool = False,
    max_width: int | None = None,
) -> list[str]:
    b, w = _build_start_bundle_parts(sdir, bundle_path, details=details, max_width=max_width)
    return [*b, "", *w] if (b and w) else [*b, *w]


def build_box_body_lines(
    out_path: Path,
    rc: int | None = None,
    stats: str | None = None,
    extra_lines: list[str] | None = None,
    label: str | None = None,
    sdir: Path | None = None,
    edited: bool | None = None,
    error_source: Path | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    title_kind: str | None = None,
    bundle_details: bool = False,
    max_width: int | None = None,
) -> list[str]:
    err_src = error_source if error_source is not None else out_path
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, err_src)
    is_edited = _is_file_edited(err_src) if edited is None else edited
    is_bundle_box = bool(title_kind and title_kind.strip() == "START SESSION")
    bundle_plan_obj: dict[str, object] | None = None
    if is_bundle_box:
        fn_load = globals().get("load_session_bundle_plan")
        if callable(fn_load):
            loaded_plan = fn_load(resolved_sdir, err_src)
            if isinstance(loaded_plan, dict):
                bundle_plan_obj = loaded_plan
    if (duration_s is None or op_timings is None) and err_src.name == "out":
        step_meta = read_step_meta(err_src.parent)
        if duration_s is None and isinstance(step_meta.get("duration_ms"), (int, float)):
            duration_s = float(step_meta["duration_ms"]) / 1000.0
        if op_timings is None and isinstance(step_meta.get("operations"), list):
            op_timings = [x for x in step_meta["operations"] if isinstance(x, dict)]
        if failed_step is None and isinstance(step_meta.get("failed_step"), int):
            failed_step = int(step_meta["failed_step"])
    _ = op_timings, failed_step
    duration_str = format_duration(duration_s) if duration_s is not None else None
    if extra_lines is not None:
        detail_lines = list(extra_lines)
    else:
        detail_lines = []
        if rc is not None and rc != 0:
            detail_lines.append(f"Exit: {rc}")
            last_err = _extract_last_error_line(err_src, label=label, max_width=max_width)
            if last_err:
                detail_lines.append(f"Error: {last_err}")
            if label:
                fix_status = _format_end_fix_status(label, resolved_sdir)
                if fix_status:
                    detail_lines.append(f"Fix: {fix_status}")
        detail_lines.append(f"Output: {out_path}")
    if not any(line.startswith("Stats:") for line in detail_lines):
        stats_parts: list[str] = []
        if stats:
            stats_parts.append(stats)
        if duration_str:
            stats_parts.append(duration_str)
        if stats_parts:
            joined_stats = " · ".join(stats_parts)
            if is_bundle_box and isinstance(bundle_plan_obj, dict):
                p_cnt = int(bundle_plan_obj.get("part_count") or 0)
                if p_cnt > 0:
                    joined_stats += f" ({p_cnt} part{'s' if p_cnt != 1 else ''})"
            detail_lines.append(f"Stats: {joined_stats} (edited)" if is_edited else f"Stats: {joined_stats}")
        elif is_edited:
            detail_lines.append("Stats: (edited)")
    has_header = any(line.startswith(("Step:", "Block:", "Session:")) for line in detail_lines)
    if has_header or (label is None and sdir is None):
        base_lines = _align_kv_lines(detail_lines)
    else:
        hdr_lines = format_session_header_lines(label=label, sdir=resolved_sdir, clamp_width=max_width)
        if detail_lines:
            base_lines = _align_kv_lines([*hdr_lines, "", *detail_lines])
        else:
            base_lines = hdr_lines
    if is_bundle_box:
        has_stats_line = any(line.startswith("Stats:") for line in base_lines)
        has_stats_count = bool(
            stats and isinstance(bundle_plan_obj, dict) and int(bundle_plan_obj.get("part_count") or 0) > 0
        )
        b_breakdown, b_warnings = _build_start_bundle_parts(
            resolved_sdir,
            err_src,
            details=bundle_details,
            max_width=max_width,
            plan=bundle_plan_obj,
            include_part_count=not has_stats_count,
            edited=is_edited,
        )
        out_lines = list(base_lines)
        if b_breakdown:
            if out_lines and not has_stats_line:
                out_lines.append("")
            out_lines.extend(b_breakdown)
        if b_warnings:
            if out_lines:
                out_lines.append("")
            out_lines.extend(b_warnings)
        return out_lines
    return base_lines


def _clipboard_prompt_line(title_kind: str) -> str:
    _ = title_kind
    return "-> Copy to clipboard? [Y/n/p(rompt)/i(nfo)]:"


def format_clipboard_box(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    stats: str | None = None,
    title_kind: str = "END STEP",
    extra_lines: list[str] | None = None,
    cmd_str: str | None = None,
    edited: bool | None = None,
    error_source: Path | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    bundle_details: bool = False,
    sdir: Path | None = None,
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[str, int, int]:
    _ = ok, cmd_str
    if term_cols is None or term_rows is None:
        det_cols, det_rows = _term_size()
        if term_cols is None:
            term_cols = det_cols
        if term_rows is None:
            term_rows = det_rows
    body_lines = build_box_body_lines(
        out_path,
        rc=rc,
        stats=stats,
        extra_lines=extra_lines,
        label=label,
        sdir=sdir,
        edited=edited,
        error_source=error_source,
        duration_s=duration_s,
        op_timings=op_timings,
        failed_step=failed_step,
        title_kind=title_kind,
        bundle_details=bundle_details,
        max_width=max(24, term_cols - 2),
    )
    prompt_line = _clipboard_prompt_line(title_kind)
    return _render_block(
        title_kind,
        body_lines,
        prompt_line=prompt_line,
        term_cols=term_cols,
        term_rows=term_rows,
    )


def _prompt_append_text(tty_r, tty_w) -> str:
    fd, name = tempfile.mkstemp(prefix="run_block_append_", suffix=".md")
    os.close(fd)
    tmp_path = Path(name)
    try:
        open_script_in_editor(tmp_path, tty_r, tty_w)
        return tmp_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def append_note_to_file(target: Path, note: str, *, as_prompt: bool) -> bool:
    text = note.strip()
    if not text or not target.is_file():
        return False
    raw = target.read_bytes()
    _write_orig_backup_once(_orig_file_backup_path(target), raw)
    current = raw.decode("utf-8", errors="replace")
    if as_prompt:
        sdir = _resolve_session_dir(path_hint=target)
        raw_path = (sdir / "0.raw") if (sdir is not None and target.name == "0") else None
        if raw_path is not None and raw_path.is_file() and sdir is not None:
            meta_hdrs = _parse_meta_header_items(sdir)
            boundary = get_bundle_boundary(meta_hdrs)
            if boundary:
                raw_txt = raw_path.read_text(encoding="utf-8", errors="replace")
                pre_hdrs, raw_body = parse_stdin_preamble(raw_txt)
                new_raw_body = inject_embedded_prompt(raw_body, prompt=text, boundary=boundary)
                hdr_block = "\n".join(f"{k}: {v}" for k, v in pre_hdrs) + "\n" if pre_hdrs else ""
                new_raw_full = hdr_block + ("\n" + new_raw_body.strip("\n") + "\n" if (hdr_block and new_raw_body.strip()) else (new_raw_body.strip("\n") + "\n" if new_raw_body.strip() else ""))
                write_private(raw_path, new_raw_full, overwrite=True)
        updated = inject_embedded_prompt(current, prompt=text) + "\n"
    else:
        updated = current.rstrip("\n") + "\n\n" + text + "\n"
    target.write_text(updated, encoding="utf-8")
    return True


def _box_rows_above_prompt(box_text: str, term_cols: int) -> int:
    lines = box_text.splitlines()
    if len(lines) <= 2:
        return 0
    cols = max(1, term_cols)
    above = sum(max(1, (display_width(ln) + cols - 1) // cols) for ln in lines[:-2])
    prompt_w = display_width(lines[-2])
    if prompt_w > cols:
        above += (prompt_w - 1) // cols
    return above


def _shorten_home_path(path: Path | str | None) -> str:
    if path is None:
        return ""
    s = str(path)
    if not s:
        return ""
    try:
        home = str(Path.home())
    except Exception:
        home = os.path.expanduser("~")
    if home and home != "~":
        norm_home = home.rstrip("/\\")
        if s == norm_home:
            return "~"
        if s.startswith(norm_home + "/") or s.startswith(norm_home + "\\"):
            return "~" + s[len(norm_home) :]
    return s


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
) -> tuple[str, int, int]:
    viewport_rows = max(1, rows - len(header_rows) - 1)
    max_scroll = max(0, len(all_items) - viewport_rows)
    clamped_scroll = max(0, min(scroll_top, max_scroll))
    visible = list(all_items[clamped_scroll : clamped_scroll + viewport_rows])
    while len(visible) < viewport_rows:
        visible.append("")

    total_items = len(all_items)
    start_idx = clamped_scroll + 1 if total_items > 0 else 0
    end_idx = min(total_items, clamped_scroll + viewport_rows)
    pos_txt = f"Lines {start_idx}-{end_idx}/{total_items}" if total_items > 0 else "0 lines"

    footer_parts: list[str] = [pos_txt, scroll_hint, *footer_tail]
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
    all_rows = fn_rows(plan, details=True)
    numbered = [r for r in all_rows if isinstance(r, dict) and str(r.get("num_str") or "").isdigit()]
    return plan, numbered


def _info_part_total(sdir: Path | None, bundle_path: Path | None) -> int:
    _, numbered = _info_table_rows(sdir, bundle_path)
    return len(numbered)


_PART_ROW_NUM_RE = re.compile(r"^\s*(\d+)\s+\d+(?:\.\d+)?%\s+\S+\s+\d+\s+~\S+\s+\[[a-z0-9_-]+\]")


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
_OP_ROW_NUM_RE = re.compile(r"^\s*(\d+)\.\s+\[[a-z0-9_-]+\]")
_OP_SECTION_HEADING_RE = re.compile(r"^(?:Operations(?: \(\d+ timed\))?:|Pre-execution Plan \(.*\):)$")


def _find_selectable_operation_rows(items: list[str]) -> list[tuple[int, int]]:
    found: list[tuple[int, int]] = []
    seen_ops: set[int] = set()
    in_section = False
    for row_idx, raw_line in enumerate(items):
        plain = ANSI_RE.sub("", raw_line)
        if not in_section:
            in_section = bool(_OP_SECTION_HEADING_RE.match(plain.strip()))
            continue
        if not plain.strip():
            break
        m = _OP_ROW_NUM_RE.match(plain)
        if m:
            ono = int(m.group(1))
            if ono not in seen_ops:
                seen_ops.add(ono)
                found.append((ono, row_idx))
    return found


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
) -> tuple[str, int, int]:
    tag = str(step.get("tag") or "exec")
    desc = str(step.get("desc") or "").strip()
    line_no = int(step.get("line") or 0)
    end_no = int(step.get("end_line") or line_no)
    hdr = [f"Source: [{tag}] {desc}" if desc else f"Source: [{tag}]"]
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
    hdr.append(f"Range: lines {line_no}-{end_no} of {_shorten_home_path(script_path)}")
    footer = ["n/N: next/prev operation"]
    if can_edit:
        footer.append("e(dit) script")
    footer.append("Esc/q/i/Tab: back")
    return _build_part_screen(
        label,
        op_no,
        total,
        None,
        script_lines[max(0, line_no - 1) : end_no],
        cols,
        rows,
        scroll_top,
        can_edit=can_edit,
        title=f"PART {op_no}/{total} · {label}",
        header_kv=hdr,
        footer_tail=footer,
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
        colored = _colorize_kv_line(_expand_tabs(hline), bright_stats=True)
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
        tail.append("Esc/q/i: back")
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
        for ext in (".sh", ".ps1"):
            cand = out_path.with_name(f"block{ext}")
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
        if raw_k.lower() in HIDDEN_SESSION_HEADER_KEYS or not val:
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


def _format_info_operation_timings(
    op_timings: list[dict[str, object]],
    *,
    total_duration_ms: int | None = None,
    failed_step: int | None = None,
    rc: int | None = None,
) -> list[str]:
    if not op_timings:
        return []
    sum_ms = sum(max(0, int(item.get("duration_ms") or 0)) for item in op_timings)
    denom_ms = total_duration_ms if (total_duration_ms is not None and total_duration_ms > 0) else sum_ms
    raw_lines: list[str] = []
    for item in op_timings:
        step_num = item.get("step")
        tag = str(item.get("tag") or "exec")
        desc = str(item.get("desc") or "").strip()
        try:
            dur_ms = max(0, int(item.get("duration_ms") or 0))
        except (TypeError, ValueError):
            dur_ms = 0
        pct = (100.0 * dur_ms / denom_ms) if denom_ms > 0 else 0.0
        dur_str = format_duration(dur_ms / 1000.0)
        is_failed = rc is not None and rc != 0 and failed_step is not None and step_num == failed_step
        fail_lbl = " (failed)" if is_failed else ""
        desc_part = f"  {desc}" if desc else ""
        raw_lines.append(f"  {step_num}. [{tag}]  {dur_str} ({pct:.1f}%){fail_lbl}{desc_part}")
    colored = _colorize_operation_lines(raw_lines)
    if _use_color():
        colored = [ln.replace(" (failed)", f" {_WARN_COLOR}(failed){_ANSI_RESET}") for ln in colored]
    return colored


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
    if findings:
        whdr = f"  Safety warnings ({len(findings)}):"
        out.append(f"{_WARN_COLOR}{whdr}{_ANSI_RESET}" if _use_color() else whdr)
        warn_items = [(str(f.get("category") or "warn"), str(f.get("snippet") or "")) for f in findings]
        out.extend(_colorize_warning_lines(_wrap_labeled_items(warn_items, max_width, indent="    ")))
    return out


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

    primary_path = out_path if (out_path is not None and out_path.is_file()) else resolved_script
    if primary_path is None and resolved_sdir is not None and (resolved_sdir / "0").is_file():
        primary_path = resolved_sdir / "0"
    primary_stats = stats_line(primary_path) if primary_path is not None else None
    dur_str = format_duration(duration_s) if duration_s is not None else None
    stat_parts: list[str] = []
    if primary_stats:
        stat_parts.append(primary_stats)
    elif kind == "START STEP" and summary and summary.get("meta"):
        stat_parts.append(str(summary["meta"]))
    if dur_str:
        stat_parts.append(dur_str)
    any_edited = bool(edited if edited is not None else (out_edited or script_edited))
    if stat_parts:
        joined = " · ".join(stat_parts)
        meta_kv.append(f"Stats: {joined} (edited)" if any_edited else f"Stats: {joined}")
    elif any_edited:
        meta_kv.append("Stats: (edited)")

    if resolved_script is not None and out_path is not None and resolved_script.is_file() and out_path.is_file():
        sc_st = stats_line(resolved_script)
        if sc_st:
            meta_kv.append(f"Script-Stats: {sc_st}{' (edited)' if script_edited else ''}")

    body_sections = []
    if op_timings:
        total_ms = int(step_meta["duration_ms"]) if isinstance(step_meta.get("duration_ms"), (int, float)) else None
        thdr = f"Operations ({len(op_timings)} timed):"
        body_sections.append(f"{_KEY_COLOR}{thdr}{_ANSI_RESET}" if _use_color() else thdr)
        body_sections.extend(
            _format_info_operation_timings(
                op_timings, total_duration_ms=total_ms, failed_step=failed_step, rc=rc
            )
        )

    if kind == "START STEP":
        if summary:
            if body_sections:
                body_sections.append("")
            cur_plan = {
                "meta": summary.get("meta", ""),
                "work_dir": summary.get("work_dir", str(get_work_dir(resolved_sdir))),
                "operations": summary.get("operations") or [],
                "operation_groups": summary.get("operation_groups") or [],
                "operation_steps": summary.get("operation_steps") or [],
                "findings": findings or [],
            }
            body_sections.extend(_format_info_plan_section("Operations:", cur_plan, max_content_w))
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
    elif resolved_script is not None and (
        (orig_script is not None and orig_script.is_file()) or resolved_script.is_file()
    ):
        plan_src = orig_script if (orig_script is not None and orig_script.is_file()) else resolved_script
        try:
            plan_text = plan_src.read_text(encoding="utf-8", errors="replace")
            w_eff = Path(wdir) if wdir else get_work_dir(resolved_sdir)
            pre_plan = analyze_script(plan_text, work_dir=w_eff, label=label, check_syntax=False)
            if body_sections:
                body_sections.append("")
            body_sections.extend(
                _format_info_plan_section(f"Pre-execution Plan ({plan_src.name}):", pre_plan, max_content_w)
            )
        except OSError:
            pass

    if not body_sections and resolved_sdir is not None and (resolved_sdir / "0").is_file():
        fn_load = globals().get("load_session_bundle_plan")
        if callable(fn_load):
            s_plan = fn_load(resolved_sdir, resolved_sdir / "0")
            if isinstance(s_plan, dict):
                fn_sum = globals().get("format_bundle_summary_lines")
                sum_lines = fn_sum(s_plan, max_width=max_content_w) if callable(fn_sum) else []
                if sum_lines:
                    p_cnt = int(s_plan.get("part_count") or 0)
                    shdr = f"Session Bundle Summary ({p_cnt} part{'s' if p_cnt != 1 else ''}):"
                    body_sections.append(f"{_KEY_COLOR}{shdr}{_ANSI_RESET}" if _use_color() else shdr)
                    body_sections.extend(_colorize_bundle_lines(sum_lines))

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

    base_title = f"INFO · {label}" if label else f"INFO · {kind}"
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
        colored = _colorize_kv_line(_expand_tabs(hline), bright_stats=True)
        for wline in _wrap_box_line(colored, max_content_w):
            header_rows.append(wline)
    div_char = "─" if _supports_utf8() else "-"
    div_line = div_char * max(8, max_content_w)
    header_rows.append(f"{border_col}{div_line}{_ANSI_RESET}" if _use_color() else div_line)

    all_items: list[str] = []
    for bline in raw_body:
        for wline in _wrap_box_line(_expand_tabs(bline), max_content_w):
            all_items.append(wline)

    if kind == "START SESSION":
        selectable = _find_selectable_part_rows(all_items)
    elif kind in _STEP_INFO_KINDS:
        selectable = _find_selectable_operation_rows(all_items)
    else:
        selectable = []
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
        if selectable or (kind == "START SESSION" and _info_part_total(resolved_sdir, out_path) > 0):
            footer_tail.append("Tab: parts")
        if allow_copy:
            footer_tail.append("Enter: copy")
        footer_tail.append("Esc/q/i: back")

    viewport_rows = max(1, rows - len(header_rows) - 1)
    if selected_row_idx is not None:
        if selected_row_idx < scroll_top:
            scroll_top = selected_row_idx
        elif selected_row_idx >= scroll_top + viewport_rows:
            scroll_top = selected_row_idx - viewport_rows + 1

    return _compose_pager_frame(
        header_rows, all_items, cols, rows, scroll_top, footer_tail, scroll_hint=scroll_hint
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
        use_raw_stage = raw_bundle is not None and raw_bundle.is_file()
        before_raw_bytes: bytes | None = None
        if use_raw_stage and raw_bundle is not None:
            try:
                before_raw_bytes = raw_bundle.read_bytes()
                target.write_bytes(before_raw_bytes)
            except OSError:
                use_raw_stage = False
        tty_w.write("\033[?25h\033[?1049l")
        tty_w.flush()
        try:
            open_script_in_editor(target, tty_r, tty_w)
        finally:
            tty_w.write("\033[?1049h\033[?25l")
            tty_w.flush()
        try:
            after_edit_bytes: bytes | None = target.read_bytes() if target.is_file() else None
        except OSError:
            after_edit_bytes = None
        if use_raw_stage and raw_bundle is not None and before_raw_bytes is not None:
            if after_edit_bytes is None or after_edit_bytes == before_raw_bytes:
                if before_clean_bytes is not None:
                    target.write_bytes(before_clean_bytes)
                return None
            if before_clean_bytes is not None:
                _write_orig_backup_once(orig_p, before_clean_bytes)
            return _apply_edit_callbacks(target)
        if before_clean_bytes is not None and after_edit_bytes is not None and after_edit_bytes != before_clean_bytes:
            _write_orig_backup_once(orig_p, before_clean_bytes)
            return _apply_edit_callbacks(target)
        return None

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
            elif key == "edit" and edit_target is not None and edit_target.is_file():
                return row_no, _edit_artifact(edit_target)
            elif key in ("back", "esc", "tab"):
                return row_no, None

    def _open_operation_viewer(initial_no: int) -> tuple[int, dict[str, object] | None]:
        script = _resolve_info_step_script(label, resolved_sdir, script_path, out_path)
        if script is None or not script.is_file():
            return initial_no, None
        timings = op_timings
        if timings is None:
            ops_meta = read_step_meta(script.parent).get("operations")
            timings = [x for x in ops_meta if isinstance(x, dict)] if isinstance(ops_meta, list) else []
        timing_by_step = {int(t["step"]): t for t in timings if isinstance(t.get("step"), int)}
        op_no = initial_no
        op_scroll = 0
        while True:
            steps = _info_operation_steps(script, resolved_sdir, label)
            if not steps:
                return initial_no, None
            total = len(steps)
            op_no = max(1, min(total, op_no))
            try:
                script_lines = script.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                script_lines = []
            cols, rows = _term_size()
            is_failed = rc is not None and rc != 0 and failed_step == op_no
            frame, op_scroll, vp_rows = _build_operation_screen(
                label,
                op_no,
                total,
                steps[op_no - 1],
                script,
                script_lines,
                timing_by_step.get(op_no),
                is_failed,
                cols,
                rows,
                op_scroll,
                can_edit=True,
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
            elif key in ("edit", "script"):
                cb_edit = _edit_artifact(script)
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
                part_total = len(_info_operation_steps(resolved_script, resolved_sdir, label))
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


def offer_clipboard_copy(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    title_kind: str = "END STEP",
    extra_lines: list[str] | None = None,
    duration_s: float | None = None,
    op_timings: list[dict[str, object]] | None = None,
    failed_step: int | None = None,
    sdir: Path | None = None,
) -> None:
    if in_run_block():
        return
    mode = clipboard_mode()
    if mode == "never":
        return
    is_start_bundle = title_kind.strip() == "START SESSION"
    is_end_box = title_kind.strip() == "END STEP"
    edit_target = out_path
    copy_target = edit_target
    if is_end_box and edit_target.is_file():
        try:
            copy_target = resolve_clipboard_target(
                edit_target, edit_target.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            copy_target = edit_target
    clip = clipboard_command(copy_target)
    if clip is None:
        return
    cmd, cmd_str = clip
    if mode == "auto":
        if copy_file_to_clipboard(cmd, copy_target):
            sys.stdout.write(f"✓ Copied {copy_target} to clipboard.\n")
        else:
            sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    if not sys.stdout.isatty():
        sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    orig_path = _orig_file_backup_path(edit_target)
    is_edited = _is_file_edited(edit_target, orig_path)
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, edit_target)
    step_script = None if is_start_bundle else _resolve_info_step_script(label, resolved_sdir, None, edit_target)
    prev_cols, prev_rows = _term_size()
    box, rule_width, cursor_offset = format_clipboard_box(
        label,
        copy_target,
        ok=ok,
        rc=rc,
        stats=stats_line(copy_target),
        title_kind=title_kind,
        extra_lines=extra_lines,
        cmd_str=cmd_str,
        edited=is_edited,
        error_source=edit_target,
        duration_s=duration_s,
        op_timings=op_timings,
        failed_step=failed_step,
        bundle_details=False,
        sdir=sdir,
        term_cols=prev_cols,
        term_rows=max(6, prev_rows - 1),
    )
    _, border_col = _block_colors(title_kind, has_exit=(rc is not None and rc != 0))
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    occ_lines = box.splitlines()
    prefixed_line2 = (
        occ_lines[-2] if len(occ_lines) >= 2 else _prefix_block_line(_clipboard_prompt_line(title_kind), border_color=border_col)
    )
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"\n{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()

            def _on_clip_edit(edited_path: Path) -> dict[str, object]:
                nonlocal copy_target, cmd, cmd_str, is_edited
                if is_start_bundle:
                    fn_refresh = globals().get("refresh_bundle_meta")
                    if callable(fn_refresh):
                        fn_refresh(edited_path)
                elif edited_path == edit_target:
                    try:
                        after_text = edited_path.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        after_text = ""
                    if is_end_box:
                        copy_target = resolve_clipboard_target(edit_target, after_text)
                    else:
                        copy_target = edit_target
                    new_clip = clipboard_command(copy_target)
                    if new_clip is not None:
                        cmd, cmd_str = new_clip
                is_edited = _is_file_edited(edit_target, orig_path)
                return {"edited": is_edited}

            def _redraw_box() -> None:
                nonlocal box, rule_width, cursor_offset, bottom, prev_cols, prev_rows
                new_cols, new_rows = _term_size()
                up_rows = _box_rows_above_prompt(box, new_cols)
                prev_cols, prev_rows = new_cols, new_rows
                box, rule_width, cursor_offset = format_clipboard_box(
                    label,
                    copy_target,
                    ok=ok,
                    rc=rc,
                    stats=stats_line(copy_target),
                    title_kind=title_kind,
                    extra_lines=extra_lines,
                    cmd_str=cmd_str,
                    edited=is_edited,
                    error_source=edit_target,
                    duration_s=duration_s,
                    op_timings=op_timings,
                    failed_step=failed_step,
                    bundle_details=False,
                    sdir=sdir,
                    term_cols=new_cols,
                    term_rows=max(6, new_rows - 1),
                )
                bottom = _format_bottom_rule(rule_width, border_color=border_col)
                move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                tty_w.flush()

            first_read = True
            while True:
                action = read_clipboard_key(tty_r, flush=first_read)
                first_read = False
                if action == "resize":
                    new_cols, new_rows = _term_size()
                    if (new_cols, new_rows) != (prev_cols, prev_rows):
                        up_rows = _box_rows_above_prompt(box, new_cols)
                        prev_cols, prev_rows = new_cols, new_rows
                        box, rule_width, cursor_offset = format_clipboard_box(
                            label,
                            copy_target,
                            ok=ok,
                            rc=rc,
                            stats=stats_line(copy_target),
                            title_kind=title_kind,
                            extra_lines=extra_lines,
                            cmd_str=cmd_str,
                            edited=is_edited,
                            error_source=edit_target,
                            duration_s=duration_s,
                            op_timings=op_timings,
                            failed_step=failed_step,
                            bundle_details=False,
                            sdir=sdir,
                            term_cols=new_cols,
                            term_rows=max(6, new_rows - 1),
                        )
                        bottom = _format_bottom_rule(rule_width, border_color=border_col)
                        occ_lines = box.splitlines()
                        prefixed_line2 = (
                            occ_lines[-2]
                            if len(occ_lines) >= 2
                            else _prefix_block_line(_clipboard_prompt_line(title_kind), border_color=border_col)
                        )
                        move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                        tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "info":
                    info_state = _show_info_fullscreen(
                        title_kind=title_kind,
                        label=label,
                        tty_r=tty_r,
                        tty_w=tty_w,
                        sdir=resolved_sdir,
                        out_path=copy_target if is_start_bundle else edit_target,
                        script_path=step_script,
                        edit_target=edit_target,
                        rc=rc,
                        duration_s=duration_s,
                        op_timings=op_timings,
                        failed_step=failed_step,
                        extra_lines=extra_lines,
                        edited=is_edited,
                        allow_copy=True,
                        on_edit_callback=_on_clip_edit,
                    )
                    if info_state.get("action") == "copy":
                        action = "copy"
                    else:
                        new_cols, new_rows = _term_size()
                        if info_state.get("edited") or (new_cols, new_rows) != (prev_cols, prev_rows):
                            is_edited = _is_file_edited(edit_target, orig_path)
                            up_rows = _box_rows_above_prompt(box, new_cols)
                            prev_cols, prev_rows = new_cols, new_rows
                            box, rule_width, cursor_offset = format_clipboard_box(
                                label,
                                copy_target,
                                ok=ok,
                                rc=rc,
                                stats=stats_line(copy_target),
                                title_kind=title_kind,
                                extra_lines=extra_lines,
                                cmd_str=cmd_str,
                                edited=is_edited,
                                error_source=edit_target,
                                duration_s=duration_s,
                                op_timings=op_timings,
                                failed_step=failed_step,
                                bundle_details=False,
                                sdir=sdir,
                                term_cols=new_cols,
                                term_rows=max(6, new_rows - 1),
                            )
                            bottom = _format_bottom_rule(rule_width, border_color=border_col)
                            occ_lines = box.splitlines()
                            prefixed_line2 = (
                                occ_lines[-2]
                                if len(occ_lines) >= 2
                                else _prefix_block_line(_clipboard_prompt_line(title_kind), border_color=border_col)
                            )
                            move_up = f"\033[{up_rows}A" if up_rows > 0 else ""
                            tty_w.write(f"\r{move_up}\033[J{box}\r\033[1A\033[{cursor_offset}C")
                            tty_w.flush()
                        continue
                if action == "prompt":
                    note = _prompt_append_text(tty_r, tty_w)
                    if append_note_to_file(edit_target, note, as_prompt=is_start_bundle):
                        _on_clip_edit(edit_target)
                    _redraw_box()
                    continue
                if action in ("view", "edit"):
                    continue
                if action == "copy":
                    if copy_file_to_clipboard(cmd, copy_target):
                        status_line = f"✓ Copied {copy_target} to clipboard."
                    else:
                        status_line = f"✗ Clipboard copy failed; run: {cmd_str}"
                else:
                    status_line = "Skipped clipboard copy."
                break
            prefixed_status = _prefix_block_line(status_line, border_color=border_col)
            tty_w.write(f"\r\033[K{prefixed_status}\n\r\033[K{bottom}\n")
            tty_w.flush()
    except OSError:
        sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
