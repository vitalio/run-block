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


def read_clipboard_key(tty_r) -> str:
    """Wait for a single key: returns 'copy', 'skip', or 'view'."""
    flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        ans = tty_r.readline().strip().lower()
        if ans in ("v", "view", "e", "edit"):
            return "view"
        return "skip" if ans in ("n", "no", "esc", "\x1b") else "copy"
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        ans = tty_r.readline().strip().lower()
        return "view" if ans in ("v", "view", "e", "edit") else ("skip" if ans in ("n", "no", "esc", "\x1b") else "copy")
    try:
        tty.setraw(fd, termios.TCSANOW)
        while True:
            ch = os.read(fd, 1)
            if not ch:
                return "skip"
            if ch in (b"v", b"V", b"e", b"E"):
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


def _wrap_labeled_items(items: list[tuple[str, str]], max_width: int, indent: str = "  ") -> list[str]:
    if not items:
        return []
    tag_w = max(len(f"[{k}]") for k, _ in items)
    out: list[str] = []
    for k, v in items:
        tag = f"[{k}]".ljust(tag_w)
        prefix = f"{indent}{tag}  "
        sub_indent = " " * len(prefix)
        avail = max(24, max_width - len(prefix))
        wrapped = textwrap.wrap(v, width=avail, break_long_words=True, break_on_hyphens=False) or [v]
        out.append(prefix + wrapped[0])
        for cont in wrapped[1:]:
            out.append(sub_indent + cont)
    return out


def _resolve_session_dir(label: str | None = None, path_hint: Path | None = None) -> Path | None:
    if path_hint is not None:
        for anc in (path_hint.parent, path_hint.parent.parent):
            if (anc / "0").is_file() or (anc / "meta.json").is_file():
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


def format_session_header_lines(
    label: str | None = None,
    sdir: Path | None = None,
    work_dir: Path | str | None = None,
    sandbox_mode: str | None = None,
    cd_dirs: list[str] | None = None,
    max_width: int | None = None,
) -> list[str]:
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label)
    hdr_items = parse_bundle_header_items(resolved_sdir)
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
                lines.append(f"Block: {label}")
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
    sb_line = f"Sandbox: {format_sandbox_header(sb_val)}"
    lines.append(sb_line)

    for raw_k, val in hdr_items:
        if raw_k.lower() in HIDDEN_SESSION_HEADER_KEYS or not val:
            continue
        lines.append(f"{raw_k}: {val}")
    aligned = _align_kv_lines(lines)
    if max_width is None:
        return aligned
    wrapped: list[str] = []
    for line in aligned:
        if display_width(line) > max_width:
            wrapped.extend(textwrap.wrap(line, width=max_width, subsequent_indent="  ") or [line])
        else:
            wrapped.append(line)
    return wrapped


def format_safety_box(
    label: str,
    findings: list[dict[str, object]],
    default_yes: bool = False,
    summary: dict[str, object] | None = None,
    note: str = "",
    script_path: Path | None = None,
) -> tuple[str, int, int]:
    meta_str = str(summary.get("meta", "")) if summary else ""
    title = " BLOCK PLAN "
    prompt_suffix = "[Y/n/v(iew)]:" if default_yes else "[y/n/v(iew)]:"
    prompt_line = f"-> Execute this block? {prompt_suffix}"
    term_cols = _hr_width()
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
        max_width=max_row_len,
    )
    if summary:
        detail_lines: list[str] = []
        if meta_str:
            detail_lines.append(f"Script: {meta_str}")
        ops = list(summary.get("operations") or [])
        op_groups = list(summary.get("operation_groups") or [])
        has_subdirs = any(bool(g_dir) for g_dir, _ in op_groups)
        if ops:
            if detail_lines:
                detail_lines.append("")
            detail_lines.append(f"{_KEY_COLOR}Operations:{_ANSI_RESET}" if _use_color() else "Operations:")
            op_lines: list[str] = []
            if has_subdirs and op_groups:
                for g_dir, g_items in op_groups:
                    dir_hdr = g_dir if g_dir else (wdir or ".")
                    op_lines.append(f"  {dir_hdr}:")
                    op_lines.extend(_wrap_labeled_items(g_items, max_row_len, indent="    "))
            else:
                op_lines.extend(_wrap_labeled_items(ops, max_row_len, indent="  "))
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
        prompt_line = f"{_WARN_COLOR}{prompt_line}{_ANSI_RESET}"
    return _render_block(title, content_lines, prompt_line=prompt_line)


def format_info_box(title: str, content_lines: list[str]) -> str:
    box, _, _ = _render_block(title, content_lines)
    return box


def format_prompt_box(
    title: str,
    content_lines: list[str],
    prompt_line: str,
    status_lines: list[str] | tuple[str, ...] = (),
) -> tuple[str, int, int]:
    _ = status_lines
    return _render_block(title, content_lines, prompt_line=prompt_line)


def _build_prompt_yes_no_suffix(
    default_yes: bool,
    has_script: bool = False,
    has_output: bool = False,
    can_copy: bool = False,
) -> str:
    parts = ["Y", "n"] if default_yes else ["y", "N"]
    if has_script:
        parts.append("s(cript)")
    if has_output:
        parts.append("o(utput)")
    if can_copy:
        parts.append("c(opy)")
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
) -> bool:
    has_script = script_path is not None and script_path.is_file()
    has_output = out_path is not None and out_path.is_file()
    can_copy = has_output
    suffix = _build_prompt_yes_no_suffix(
        default_yes,
        has_script=has_script,
        has_output=has_output,
        can_copy=can_copy,
    )
    prompt_line = f"-> {question} {suffix}"
    status_list: list[str] = [yes_status, no_status]
    clip_target: Path | None = None
    clip: tuple[list[str], str] | None = None
    if can_copy and out_path is not None:
        try:
            full_out = out_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            full_out = ""
        clip_target = resolve_clipboard_target(out_path, full_out)
        clip = clipboard_command(clip_target)
        status_list.append(f"✓ Copied {clip_target} to clipboard.")
        if clip is not None:
            status_list.append(f"✗ Clipboard copy failed; run: {clip[1]}")
        else:
            status_list.append(f"✗ No clipboard tool found for {clip_target}.")
    extra_keys: dict[str, str] = {}
    if has_script:
        extra_keys["s"] = "script"
        extra_keys["script"] = "script"
    if has_output:
        extra_keys["o"] = "output"
        extra_keys["output"] = "output"
    if can_copy:
        extra_keys["c"] = "copy"
        extra_keys["copy"] = "copy"
    box, rule_width, cursor_offset = format_prompt_box(
        title, content_lines, prompt_line, status_lines=status_list
    )
    _, border_col = _block_colors(title)
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    prefixed_prompt = _prefix_block_line(prompt_line, border_color=border_col)
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
            while True:
                action = read_confirm_key(
                    tty_r,
                    default_yes=default_yes,
                    default_no=not default_yes,
                    extra_keys=extra_keys,
                )
                if action == "script" and has_script and script_path is not None:
                    open_script_in_editor(script_path, tty_r, tty_w)
                    tty_w.write(f"\r\033[K{prefixed_prompt}\n\r\033[K{bottom}\r\033[1A\033[{cursor_offset}C")
                    tty_w.flush()
                    continue
                if action == "output" and has_output and out_path is not None:
                    open_script_in_editor(out_path, tty_r, tty_w)
                    tty_w.write(f"\r\033[K{prefixed_prompt}\n\r\033[K{bottom}\r\033[1A\033[{cursor_offset}C")
                    tty_w.flush()
                    continue
                if action == "view" and (has_output or has_script):
                    view_target = out_path if (has_output and out_path is not None) else script_path
                    if view_target is not None:
                        open_script_in_editor(view_target, tty_r, tty_w)
                        tty_w.write(f"\r\033[K{prefixed_prompt}\n\r\033[K{bottom}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "copy" and can_copy and clip_target is not None:
                    if clip is not None and copy_file_to_clipboard(clip[0], clip_target):
                        status_line = f"✓ Copied {clip_target} to clipboard."
                    elif clip is not None:
                        status_line = f"✗ Clipboard copy failed; run: {clip[1]}"
                    else:
                        status_line = f"✗ No clipboard tool found for {clip_target}."
                    approved = False
                    break
                if action == "yes":
                    approved = True
                    break
                if action == "no":
                    approved = False
                    break
            if status_line is None:
                status_line = yes_status if approved else no_status
            prefixed_status = _prefix_block_line(status_line, border_color=border_col)
            tty_w.write(f"\r\033[K{prefixed_status}\n\r\033[K{bottom}\n")
            tty_w.flush()
            return approved
        finally:
            if close_after:
                tty_w.close()
                tty_r.close()
    except OSError:
        return default_yes


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
) -> str:
    if not line:
        return "yes" if default_yes else "no"
    ans = line.strip().lower()
    if extra_keys and ans in extra_keys:
        return extra_keys[ans]
    if ans in ("v", "view", "e", "edit"):
        return "view"
    if default_yes and ans in ("", "y", "yes"):
        return "yes"
    if not default_yes and ans in ("y", "yes"):
        return "yes"
    if default_no and ans == "":
        return "no"
    if ans in ("n", "no", "q", "esc"):
        return "no"
    return "invalid"


def read_confirm_key(
    tty_r,
    default_yes: bool,
    default_no: bool = False,
    extra_keys: dict[str, str] | None = None,
) -> str:
    """Reads a single key: returns 'yes', 'no', 'view', or an extra_keys action."""
    flush_tty_input(tty_r)
    if not HAS_PTY or termios is None or tty is None:
        return _parse_confirm_line(
            tty_r.readline(), default_yes, default_no=default_no, extra_keys=extra_keys
        )
    try:
        fd = tty_r.fileno()
        old_attrs = termios.tcgetattr(fd)
    except Exception:
        return _parse_confirm_line(
            tty_r.readline(), default_yes, default_no=default_no, extra_keys=extra_keys
        )
    try:
        tty.setraw(fd, termios.TCSANOW)
        while True:
            ch = os.read(fd, 1)
            if not ch:
                return "no"
            ch_low = ch.decode("latin1").lower()
            if extra_keys and ch_low in extra_keys:
                return extra_keys[ch_low]
            if ch in (b"v", b"V", b"e", b"E"):
                return "view"
            if ch in (b"y", b"Y"):
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
    if approve_cmd:
        wdir = Path(str(summary.get("work_dir"))) if summary and summary.get("work_dir") else get_work_dir()
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
    default_yes = (len(findings) == 0 and approve_decision != "prompt")
    box, rule_width, cursor_offset = format_safety_box(
        label,
        findings,
        default_yes=default_yes,
        summary=summary,
        note=note,
        script_path=script_path,
    )
    _, border_col = _block_colors("BLOCK PLAN")
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    prompt_suffix = "[Y/n/v(iew)]:" if default_yes else "[y/n/v(iew)]:"
    raw_prompt = f"-> Execute this block? {prompt_suffix}"
    if findings and _use_color():
        raw_prompt = f"{_WARN_COLOR}{raw_prompt}{_ANSI_RESET}"
    prefixed_prompt = _prefix_block_line(raw_prompt, border_color=border_col)
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            while True:
                action = read_confirm_key(tty_r, default_yes=default_yes)
                if action == "view":
                    if script_path is not None and script_path.is_file():
                        open_script_in_editor(script_path, tty_r, tty_w)
                        tty_w.write(f"\r\033[K{prefixed_prompt}\n\r\033[K{bottom}\r\033[1A\033[{cursor_offset}C")
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
_ENC = None
_ENC_TRIED = False


def gpt_encoder():
    global _ENC, _ENC_TRIED
    if not _ENC_TRIED:
        _ENC_TRIED = True
        try:
            import tiktoken  # type: ignore[import-not-found]
            _ENC = tiktoken.get_encoding("o200k_base")
        except Exception:
            _ENC = None
    return _ENC


def count_tokens(data: bytes) -> dict[str, int | bool]:
    text = data.decode("utf-8", "replace")
    chars = len(text)
    lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    enc = gpt_encoder()
    if enc is not None:
        gpt = len(enc.encode(text, disallowed_special=()))
    else:
        gpt = math.ceil(chars / 4)
    return {
        "bytes": len(data),
        "lines": lines,
        "claude": math.ceil(chars / 3.5),
        "gpt": gpt,
        "gpt_exact": enc is not None,
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
    return f"{n / 1000:.1f}k"


def format_stats(data: bytes) -> str:
    s = count_tokens(data)
    lines = int(s["lines"])
    sz = _human_size(int(s["bytes"]))
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
    "START BUNDLE": "\x1b[1;36m",
    "BLOCK PLAN": "\x1b[1;33m",
    "END": "\x1b[1;32m",
    "SYNTAX ERROR": "\x1b[1;31m",
    "NOT RUN": "\x1b[1;31m",
    "MISSING PREVIOUS STEP": "\x1b[1;33m",
    "STEP ALREADY EXISTS": "\x1b[1;33m",
}
_BORDER_COLOR = "\x1b[2;36m"
_KEY_COLOR = "\x1b[2m"
_WARN_COLOR = "\x1b[1;31m"
_HIGHLIGHT_COLOR = "\x1b[1;33m"
_TAG_COLORS = {
    "write": "\x1b[1;33m",
    "exec": "\x1b[1;35m",
    "git": "\x1b[1;36m",
    "python": "\x1b[1;36m",
}
_ANSI_RESET = "\x1b[0m"


def _block_colors(title: str, has_exit: bool = False) -> tuple[str, str]:
    clean_title = title.strip()
    if clean_title == "END" and has_exit:
        t_col = "\x1b[1;31m"
    else:
        t_col = _TITLE_COLORS.get(clean_title, "\x1b[1;36m")
    if t_col.startswith("\x1b[1;"):
        b_col = "\x1b[2;" + t_col[4:]
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


def _colorize_kv_line(line: str) -> str:
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
        return f"{_KEY_COLOR}{key}{_ANSI_RESET}{spaces}{val}"
    return line


def _colorize_python_op_rest(rest: str) -> str:
    def _repl(m: re.Match[str]) -> str:
        kind = m.group(1)
        body = m.group(2)
        if kind == "reads:":
            return f"{_KEY_COLOR}{kind} {body}{_ANSI_RESET}"
        return f"{_HIGHLIGHT_COLOR}{kind} {body}{_ANSI_RESET}"

    return re.sub(r"\b(writes:|reads:)\s+([^;]+)", _repl, rest)


def _colorize_operation_lines(lines: list[str]) -> list[str]:
    if not _use_color():
        return lines
    out: list[str] = []
    last_tag = ""
    for line in lines:
        m = re.match(r"^(\s*)(\[([a-z0-9_-]+)\])(\s+)(.*)$", line)
        if m:
            indent, tag_br, tag, spaces, rest = m.groups()
            last_tag = tag
            if tag == "read":
                out.append(f"{indent}{_KEY_COLOR}{tag_br}{spaces}{rest}{_ANSI_RESET}")
            elif tag == "write":
                t_col = _TAG_COLORS["write"]
                out.append(f"{indent}{t_col}{tag_br}{_ANSI_RESET}{spaces}{t_col}{rest}{_ANSI_RESET}")
            elif tag == "python":
                t_col = _TAG_COLORS["python"]
                out.append(f"{indent}{t_col}{tag_br}{_ANSI_RESET}{spaces}{_colorize_python_op_rest(rest)}")
            elif tag in _TAG_COLORS:
                t_col = _TAG_COLORS[tag]
                out.append(f"{indent}{t_col}{tag_br}{_ANSI_RESET}{spaces}{rest}")
            else:
                out.append(line)
        elif line.startswith("  ") and not line.lstrip().startswith("[") and not line.rstrip().endswith(":"):
            if last_tag == "read":
                out.append(f"{_KEY_COLOR}{line}{_ANSI_RESET}")
            elif last_tag == "write":
                t_col = _TAG_COLORS["write"]
                out.append(f"{t_col}{line}{_ANSI_RESET}")
            elif last_tag == "python":
                out.append(_colorize_python_op_rest(line))
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


def display_width(text: str) -> int:
    clean = ANSI_RE.sub("", text)
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in clean)


def _hr_width() -> int:
    return max(40, shutil.get_terminal_size((80, 24)).columns)


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


def _render_block(
    title: str,
    content_lines: list[str],
    prompt_line: str | None = None,
) -> tuple[str, int, int]:
    clean_title = title.strip()
    hdr = clean_title
    width = max(min(_hr_width(), 48), display_width(hdr) + 8)
    aligned_lines = _align_kv_lines(content_lines)
    has_exit = any(l.startswith("Exit:") for l in aligned_lines)
    title_color, border_color = _block_colors(clean_title, has_exit=has_exit)
    top = _format_top_rule(title, width, title_color=title_color, border_color=border_color)
    bottom = _format_bottom_rule(width, border_color=border_color)
    rows = [_prefix_block_line(_colorize_kv_line(line), border_color=border_color) for line in aligned_lines]
    if not rows and prompt_line is None:
        rows = [_prefix_block_line("", border_color=border_color)]
    cursor_col_offset = 0
    if prompt_line is not None:
        if aligned_lines:
            rows.append(_prefix_block_line("", border_color=border_color))
        prefixed_prompt = _prefix_block_line(prompt_line, border_color=border_color)
        rows.append(prefixed_prompt)
        cursor_col_offset = display_width(prefixed_prompt)
    box = "\n".join([top, *rows, bottom])
    return box, width, cursor_col_offset


def _extract_last_error_line(out_path: Path, label: str | None = None) -> str:
    try:
        if not out_path.is_file():
            return ""
        raw = out_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    skip_prefixes: tuple[str, ...] = ()
    if label:
        skip_prefixes = (
            f"[{label}] START",
            f"[{label}] END",
            f"[{label}] STOP --fix",
            f"[{label}] <stdin> line ",
            f"[{label}] patched ",
            f"[{label}] SECURITY WARNING:",
        )
    term_cols = _hr_width()
    max_len = max(60, term_cols - 8)
    for line in reversed(raw.splitlines()):
        s = line.strip()
        if not s:
            continue
        if skip_prefixes and any(s.startswith(p) for p in skip_prefixes):
            continue
        if len(s) > max_len:
            return s[: max_len - 3] + "..."
        return s
    return ""


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


def build_box_body_lines(
    out_path: Path,
    rc: int | None = None,
    stats: str | None = None,
    extra_lines: list[str] | None = None,
    label: str | None = None,
    sdir: Path | None = None,
) -> list[str]:
    resolved_sdir = sdir if sdir is not None else _resolve_session_dir(label, out_path)
    if extra_lines is not None:
        detail_lines = list(extra_lines)
    else:
        detail_lines = []
        if rc is not None and rc != 0:
            detail_lines.append(f"Exit: {rc}")
            last_err = _extract_last_error_line(out_path, label=label)
            if last_err:
                detail_lines.append(f"Error: {last_err}")
            if label:
                fix_status = _format_end_fix_status(label, resolved_sdir)
                if fix_status:
                    detail_lines.append(f"Fix: {fix_status}")
        detail_lines.append(f"Output: {out_path}")
    if stats and not any(line.startswith("Stats:") for line in detail_lines):
        detail_lines.append(f"Stats: {stats}")
    has_header = any(line.startswith(("Block:", "Session:")) for line in detail_lines)
    if has_header or (label is None and sdir is None):
        return _align_kv_lines(detail_lines)
    hdr_lines = format_session_header_lines(label=label, sdir=resolved_sdir)
    if detail_lines:
        return _align_kv_lines([*hdr_lines, "", *detail_lines])
    return hdr_lines


def format_clipboard_box(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    stats: str | None = None,
    title_kind: str = "END",
    extra_lines: list[str] | None = None,
    cmd_str: str | None = None,
) -> tuple[str, int, int]:
    _ = ok, cmd_str
    body_lines = build_box_body_lines(out_path, rc=rc, stats=stats, extra_lines=extra_lines, label=label)
    prompt_line = "-> Copy to clipboard? [Enter/v(iew)/Esc]:"
    return _render_block(title_kind, body_lines, prompt_line=prompt_line)


def offer_clipboard_copy(
    label: str,
    out_path: Path,
    ok: bool = True,
    rc: int | None = None,
    title_kind: str = "END",
    extra_lines: list[str] | None = None,
) -> None:
    if in_run_block():
        return
    mode = clipboard_mode()
    if mode == "never":
        return
    clip = clipboard_command(out_path)
    if clip is None:
        return
    cmd, cmd_str = clip
    if mode == "auto":
        if copy_file_to_clipboard(cmd, out_path):
            sys.stdout.write(f"✓ Copied {out_path} to clipboard.\n")
        else:
            sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    if not sys.stdout.isatty():
        sys.stdout.write(f"[{label}] clipboard: {cmd_str}\n")
        sys.stdout.flush()
        return
    box, rule_width, cursor_offset = format_clipboard_box(
        label,
        out_path,
        ok=ok,
        rc=rc,
        stats=stats_line(out_path),
        title_kind=title_kind,
        extra_lines=extra_lines,
        cmd_str=cmd_str,
    )
    _, border_col = _block_colors(title_kind, has_exit=(rc is not None and rc != 0))
    bottom = _format_bottom_rule(rule_width, border_color=border_col)
    prefixed_line2 = _prefix_block_line("-> Copy to clipboard? [Enter/v(iew)/Esc]:", border_color=border_col)
    try:
        tty_w, tty_r = open_tty()
        with tty_w, tty_r:
            tty_w.write(f"\n{box}\r\033[1A\033[{cursor_offset}C")
            tty_w.flush()
            while True:
                action = read_clipboard_key(tty_r)
                if action == "view":
                    if out_path.is_file():
                        open_script_in_editor(out_path, tty_r, tty_w)
                        tty_w.write(f"\r\033[K{prefixed_line2}\n\r\033[K{bottom}\r\033[1A\033[{cursor_offset}C")
                        tty_w.flush()
                    continue
                if action == "copy":
                    if copy_file_to_clipboard(cmd, out_path):
                        status_line = f"✓ Copied {out_path} to clipboard."
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
