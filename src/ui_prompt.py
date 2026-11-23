def open_tty():
    return (
        open("/dev/tty", "w", encoding="utf-8", errors="replace"),
        open("/dev/tty", "r", encoding="utf-8", errors="replace"),
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
    reasoning: str | None = None,
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
        reasoning=reasoning,
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
                            reasoning=reasoning,
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
                            reasoning=reasoning,
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


def prompt_reply_in_editor(tty_streams: tuple[object, object] | None = None) -> str:
    fd, name = tempfile.mkstemp(prefix="run_block_reply_", suffix=".md")
    os.close(fd)
    tmp_path = Path(name)
    close_after = False
    tty_w = None
    tty_r = None
    try:
        if tty_streams is not None:
            tty_w, tty_r = tty_streams
        else:
            tty_w, tty_r = open_tty()
            close_after = True
        open_script_in_editor(tmp_path, tty_r, tty_w)
        return tmp_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    finally:
        if close_after:
            for stream in (tty_w, tty_r):
                if stream is not None:
                    try:
                        stream.close()
                    except Exception:
                        pass
        try:
            tmp_path.unlink()
        except OSError:
            pass


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
                new_raw_body = append_note_to_raw_bundle(raw_body, note=text, boundary=boundary)
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
