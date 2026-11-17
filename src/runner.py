def ensure_base() -> Path:
    BASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        BASE_DIR.chmod(0o700)
    except OSError:
        pass
    return BASE_DIR


def next_session_name(base: Path) -> str:
    used = set()
    for p in base.iterdir():
        m = re.fullmatch(r"s(\d+)", p.name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return f"s{n}"


def start_session(name: str | None = None, force: bool = False, sandbox_mode: str | None = None) -> Path:
    base = ensure_base()
    _warn_if_state_oversized(base)
    if not name:
        name = next_session_name(base)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SystemExit(f"{prog_name()}: invalid session name: {name!r}")
    sdir = base / name
    if sdir.exists():
        if not force:
            if not sys.stdin.isatty():
                raise SystemExit(f"{prog_name()}: session {sdir} already exists (use --force to overwrite)")
            if sys.stdout.isatty() and not no_clipboard():
                sess_hdr = format_session_header_lines(
                    label=name, sdir=sdir, sandbox_mode=sandbox_mode
                )
                ok = prompt_yes_no_box(
                    "SESSION ALREADY EXISTS",
                    [*sess_hdr, "", f"Directory: {sdir}"],
                    f"Overwrite session {name}?",
                    default_yes=False,
                    yes_status=f"✓ Overwriting session {name}.",
                    no_status=f"✗ Aborted overwriting session {name}.",
                )
                if not ok:
                    raise SystemExit(f"{prog_name()}: aborted")
            else:
                sys.stderr.write(f"Session {sdir} already exists. Overwrite? [y/N] ")
                sys.stderr.flush()
                ans = sys.stdin.readline().strip().lower()
                if ans not in ("y", "yes"):
                    raise SystemExit(f"{prog_name()}: aborted")
        shutil.rmtree(sdir)
    sdir.mkdir(mode=0o700, parents=True)
    ensure_session_bundle(sdir, sandbox_mode=sandbox_mode)
    return sdir


def parse_ref(ref: str, allow_fix_step: bool) -> tuple[str, str]:
    pattern = r"^([A-Za-z0-9._-]+)/(\d+(?:_\d+)?)$" if allow_fix_step else r"^([A-Za-z0-9._-]+)/(\d+)$"
    m = re.fullmatch(pattern, ref.strip())
    if not m:
        kind = "<session>/<step> (e.g. s1/2 or s1/2_1)" if allow_fix_step else "<session>/<step> (e.g. s1/1)"
        raise SystemExit(f"{prog_name()}: invalid block reference {ref!r}; expected {kind}")
    return m.group(1), m.group(2)


def next_fix_step(step: str, sdir: Path | None = None) -> str:
    base = step.split("_", 1)[0]
    min_next = 1
    if "_" in step:
        _, sub = step.split("_", 1)
        if sub.isdigit():
            min_next = int(sub) + 1
    if sdir is not None and sdir.is_dir():
        max_n = 0
        pat = re.compile(rf"^{re.escape(base)}_(\d+)$")
        for p in sdir.iterdir():
            m = pat.match(p.name)
            if m and p.is_dir():
                max_n = max(max_n, int(m.group(1)))
        return f"{base}_{max(min_next, max_n + 1)}"
    return f"{base}_{min_next}"


_CMP_OP_SYMBOLS: dict[type[ast.cmpop], str] = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}


def _short_repr(val: object, limit: int = 80) -> str:
    r = repr(val)
    if len(r) > limit:
        return r[: limit - 3] + "..."
    return r


def _format_fix_exception(
    exc: BaseException, fix_code: str, fix_path: Path, ns: dict[str, object]
) -> str:
    lineno: int | None = getattr(exc, "lineno", None)
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == str(fix_path):
            lineno = tb.tb_lineno
        tb = tb.tb_next

    lines = fix_code.splitlines()
    stmt_node: ast.stmt | None = None
    if lineno is not None:
        try:
            tree = ast.parse(fix_code)
            for node in ast.walk(tree):
                if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                    end_ln = getattr(node, "end_lineno", node.lineno) or node.lineno
                    if node.lineno <= lineno <= end_ln:
                        if stmt_node is None or node.lineno >= stmt_node.lineno:
                            stmt_node = node
        except Exception:
            stmt_node = None

    stmt_str = ""
    if stmt_node is not None:
        seg = ast.get_source_segment(fix_code, stmt_node)
        if seg:
            stmt_str = " ".join(l.strip() for l in seg.splitlines() if l.strip())
    if not stmt_str and lineno is not None and 1 <= lineno <= len(lines):
        stmt_str = lines[lineno - 1].strip()

    actual_part = ""
    if (
        isinstance(exc, AssertionError)
        and isinstance(stmt_node, ast.Assert)
        and isinstance(stmt_node.test, ast.Compare)
        and len(stmt_node.test.ops) == 1
        and len(stmt_node.test.comparators) == 1
    ):
        op_sym = _CMP_OP_SYMBOLS.get(type(stmt_node.test.ops[0]))
        if op_sym:
            try:
                left_expr = ast.Expression(body=stmt_node.test.left)
                right_expr = ast.Expression(body=stmt_node.test.comparators[0])
                ast.fix_missing_locations(left_expr)
                ast.fix_missing_locations(right_expr)
                left_val = eval(compile(left_expr, "<fix_eval>", "eval"), ns)
                right_val = eval(compile(right_expr, "<fix_eval>", "eval"), ns)
                actual_part = f" (actual: {_short_repr(left_val)} {op_sym} {_short_repr(right_val)})"
            except Exception:
                actual_part = ""

    exc_name = type(exc).__name__
    exc_msg = str(exc).strip()
    if lineno is not None and stmt_str:
        loc_str = f"at line {lineno}: {stmt_str}{actual_part}"
        if exc_msg:
            return f"fix raised {exc_name}: {exc_msg} ({loc_str})"
        return f"fix raised {exc_name} {loc_str}"
    if exc_msg:
        return f"fix raised {exc_name}: {exc_msg}"
    return f"fix raised {exc_name}"


def _find_fix_chain_scripts(sdir: Path, base_step: str) -> list[tuple[str, Path]]:
    chain: list[tuple[str, Path]] = []
    base_script = _find_step_script(sdir, base_step)
    if base_script.is_file():
        chain.append((base_step, base_script))
    if sdir.is_dir():
        fix_items: list[tuple[int, str, Path]] = []
        pat = re.compile(rf"^{re.escape(base_step)}_(\d+)$")
        for d in sdir.iterdir():
            m = pat.match(d.name)
            if m and d.is_dir():
                sub_idx = int(m.group(1))
                step_name = f"{base_step}_{sub_idx}"
                sp = _find_step_script(sdir, step_name)
                if sp.is_file():
                    fix_items.append((sub_idx, step_name, sp))
        for _, step_name, p in sorted(fix_items, key=lambda x: x[0]):
            chain.append((step_name, p))
    return chain


def _consecutive_failed_fixes(sdir: Path, base_step: str) -> int:
    if not sdir.is_dir():
        return 0
    indices: set[int] = set()
    pat = re.compile(rf"^{re.escape(base_step)}_(\d+)$")
    for d in sdir.iterdir():
        m = pat.match(d.name)
        if m and d.is_dir():
            indices.add(int(m.group(1)))
    failures = 0
    for idx in sorted(indices):
        stem = f"{base_step}_{idx}"
        st = _step_status(sdir, stem)
        if st == "ABORTED":
            continue
        if st == "END":
            failures = 0
        else:
            failures += 1
    return failures


def write_private(path: Path, content: str, overwrite: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if overwrite else os.O_EXCL)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)


_EMBEDDED_PY_HEREDOC_RE = re.compile(r"\bpython3?(?:\s+[^\n]*?)?<<-?\s*['\"]?([A-Za-z0-9_]+)['\"]?")
_STDIN_TB_LINE_RE = re.compile(r'File "<stdin>", line (\d+)(?:, in ([^\n]+))?')


def _extract_python_heredoc_bodies(script_text: str) -> list[list[str]]:
    bodies: list[list[str]] = []
    eof_token: str | None = None
    strip_tabs = False
    cur_lines: list[str] = []
    for raw in script_text.splitlines():
        if eof_token is not None:
            cmp_line = raw.lstrip("\t") if strip_tabs else raw
            if cmp_line.strip() == eof_token:
                bodies.append(cur_lines)
                eof_token = None
                strip_tabs = False
                cur_lines = []
            else:
                cur_lines.append(cmp_line if strip_tabs else raw)
            continue
        m = _EMBEDDED_PY_HEREDOC_RE.search(raw)
        if m:
            eof_token = m.group(1)
            strip_tabs = "<<-" in raw
            cur_lines = []
    if eof_token is not None and cur_lines:
        bodies.append(cur_lines)
    return bodies


def _resolve_python_stdin_tracebacks(label: str, script_text: str, output_text: str) -> list[str]:
    matches = _STDIN_TB_LINE_RE.findall(output_text)
    if not matches:
        return []
    heredocs = _extract_python_heredoc_bodies(script_text)
    if not heredocs:
        return []
    resolved: list[str] = []
    seen: set[tuple[int, str]] = set()
    for raw_ln, raw_func in matches:
        try:
            lineno = int(raw_ln)
        except ValueError:
            continue
        if lineno < 1:
            continue
        func_name = (raw_func or "").strip()
        chosen_body: list[str] | None = None
        if len(heredocs) == 1:
            if lineno <= len(heredocs[0]):
                chosen_body = heredocs[0]
        else:
            if func_name and func_name != "<module>":
                def_pat = re.compile(rf"^\s*(?:async\s+)?def\s+{re.escape(func_name)}\b")
                for body in reversed(heredocs):
                    if lineno <= len(body) and any(def_pat.match(ln) for ln in body):
                        chosen_body = body
                        break
            if chosen_body is None:
                for body in reversed(heredocs):
                    if lineno <= len(body):
                        chosen_body = body
                        break
        if chosen_body is None:
            continue
        src_line = chosen_body[lineno - 1].strip()
        if not src_line:
            continue
        key = (lineno, src_line)
        if key in seen:
            continue
        seen.add(key)
        resolved.append(f"[{label}] <stdin> line {lineno}: {src_line}")
    return resolved


def not_run_exit(
    label: str,
    sdir: Path,
    step_name: str,
    out_path: Path,
    msg: str,
    rc: int = 2,
    headless: bool = False,
    fix_target: str | None = None,
) -> int:
    step_dir = _step_dir(sdir, step_name)
    step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    line = msg if msg.endswith("\n") else msg + "\n"
    clean_msg = msg.strip()
    prefix = f"[{label}] NOT RUN:"
    detail = clean_msg[len(prefix):].strip() if clean_msg.startswith(prefix) else clean_msg
    detail_lines = detail.splitlines() or [detail]
    err_target = step_dir / "error" if out_path.exists() else out_path
    try:
        write_private(err_target, line, overwrite=True)
    except Exception:
        pass
    is_headless = headless or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    if is_headless:
        sys.stdout.write(line)
        sys.stdout.flush()
        return rc
    body_lines: list[str] = []
    if fix_target:
        body_lines.append(f"Target: {fix_target} -> {label}")
    body_lines.append(f"Reason: {detail_lines[0]}")
    stop_pat = re.compile(rf"^(?:\[{re.escape(label)}\]\s*)?STOP --fix:\s*(.*)$")
    for dline in detail_lines[1:]:
        m_stop = stop_pat.match(dline.strip())
        if m_stop:
            body_lines.append(f"Guard: {m_stop.group(1).strip()}")
        else:
            body_lines.append(f"  {dline}")
    body_lines.append(f"Output: {err_target}")
    can_prompt_clip = (
        not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(err_target) is not None
    )
    if can_prompt_clip:
        offer_clipboard_copy(label, err_target, ok=False, rc=rc, title_kind="NOT RUN", extra_lines=body_lines)
    else:
        full_body = build_box_body_lines(
            err_target, rc=rc, stats=stats_line(err_target), extra_lines=body_lines, label=label, sdir=sdir
        )
        sys.stdout.write(format_info_box("NOT RUN", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label, err_target, ok=False, rc=rc, title_kind="NOT RUN", extra_lines=body_lines)
    return rc


class _ProgressLineFilter:
    def __init__(
        self,
        step_map: dict[int, dict[str, object]],
        total_steps: int,
        marker_prefix: str = "__RB_STEP__:",
    ) -> None:
        self.step_map = step_map
        self.total_steps = total_steps
        self.marker_prefix = marker_prefix
        self.buf = ""
        self._marker_re = re.compile(rf"^{re.escape(marker_prefix)}(\d+)\r?$")

    def _format_step_banner(self, step_num: int) -> str:
        info = self.step_map.get(step_num)
        if not info:
            return ""
        tag = str(info.get("tag") or "")
        desc = str(info.get("desc") or "").replace("\n", " ").strip()
        prefix = f"[{step_num}/{self.total_steps}]"
        if tag:
            prefix = f"{prefix} [{tag}]"
        max_cols = max(40, _hr_width() - 4)
        avail = max(16, max_cols - len(prefix) - 1)
        if len(desc) > avail:
            desc = desc[: avail - 3] + "..."
        line = f"{prefix} {desc}".rstrip()
        arrow = "▸" if _supports_utf8() else ">"
        if _use_color():
            return f"\x1b[2;36m{arrow} {line}\x1b[0m\n"
        return f"{arrow} {line}\n"

    def feed(self, text: str) -> tuple[str, str]:
        self.buf += text
        out_parts: list[str] = []
        prog_parts: list[str] = []
        while "\n" in self.buf:
            line, rest = self.buf.split("\n", 1)
            self.buf = rest
            m = self._marker_re.match(line)
            if m:
                banner = self._format_step_banner(int(m.group(1)))
                if banner:
                    prog_parts.append(banner)
            else:
                out_parts.append(line + "\n")
        if self.buf:
            if not (
                self.marker_prefix.startswith(self.buf)
                or self.buf.startswith(self.marker_prefix)
            ):
                out_parts.append(self.buf)
                self.buf = ""
        return "".join(out_parts), "".join(prog_parts)

    def flush(self) -> tuple[str, str]:
        if not self.buf:
            return "", ""
        rem = self.buf
        self.buf = ""
        m = self._marker_re.match(rem)
        if m:
            banner = self._format_step_banner(int(m.group(1)))
            return "", banner
        return rem, ""


def _prepare_progress_script(
    script_text: str,
    step_dir: Path,
    step_lines: list[dict[str, object]],
    shell_bin: str,
    is_ps: bool,
    work_dir: Path,
) -> Path | None:
    if not step_lines:
        return None
    inst_text = instrument_script_for_progress(
        script_text, step_lines=step_lines, is_powershell=is_ps
    )
    if inst_text == script_text:
        return None
    ext = ".ps1" if is_ps else ".sh"
    fd, tmp_name = tempfile.mkstemp(prefix=".progress_", suffix=ext, dir=step_dir)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(inst_text)
        os.chmod(tmp_path, 0o600)
        if is_ps:
            ps_check = (
                "$err = $null; "
                "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$err); "
                "if ($err) { exit 1 }"
            )
            chk_cmd = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", ps_check, str(tmp_path)]
        else:
            chk_cmd = [shell_bin, "-n", str(tmp_path)]
        chk = subprocess.run(
            chk_cmd,
            cwd=work_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if chk.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            return None
        return tmp_path
    except Exception:
        tmp_path.unlink(missing_ok=True)
        return None


def _iter_child_streams(out_fd, err_fd):
    """Yield (is_err, text) chunks read concurrently from two child descriptors."""
    q: queue.Queue = queue.Queue()

    def _reader(fd, is_err):
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                break
            q.put((is_err, chunk))
        q.put((is_err, None))

    threads = [
        threading.Thread(target=_reader, args=(fd, flag), daemon=True)
        for fd, flag in ((out_fd, False), (err_fd, True))
    ]
    for th in threads:
        th.start()
    pending = len(threads)
    while pending:
        is_err, chunk = q.get()
        if chunk is None:
            pending -= 1
            continue
        yield is_err, chunk.decode("utf-8", "replace")
    for th in threads:
        th.join()


def _validate_step_script_syntax(
    label: str,
    script_path: Path,
    out_path: Path,
    work_dir: Path,
    shell_bin: str,
    is_ps: bool,
    sdir: Path,
    headless: bool = False,
    footer_on_fail: str | None = None,
) -> int:
    if is_ps:
        ps_check = (
            "$err = $null; "
            "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$err); "
            "if ($err) { foreach ($e in $err) { [Console]::Error.WriteLine($e.ToString()) }; exit 1 }"
        )
        chk_cmd = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", ps_check, str(script_path)]
    else:
        chk_cmd = [shell_bin, "-n", str(script_path)]
    chk = subprocess.run(
        chk_cmd,
        cwd=work_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if chk.returncode == 0:
        return 0
    start_line = f"[{label}] START\n\n"
    msg = chk.stdout or "syntax check failed\n"
    end_line = f"[{label}] END (syntax error, exit {chk.returncode})\n"
    if footer_on_fail:
        end_line += footer_on_fail if footer_on_fail.endswith("\n") else footer_on_fail + "\n"
    full_output = start_line + msg + end_line
    write_private(out_path, full_output, overwrite=True)
    if headless:
        sys.stdout.write(full_output)
        sys.stdout.flush()
        return chk.returncode
    err_lines = msg.rstrip("\n").splitlines() or ["syntax check failed"]
    box_lines = [
        f"Exit: {chk.returncode}",
        f"Script: {script_path}",
        f"Output: {out_path}",
        f"Error: {err_lines[0]}",
        *(f"  {eline}" for eline in err_lines[1:]),
    ]
    can_prompt_clip = (
        not in_run_block()
        and sys.stdout.isatty()
        and clipboard_mode() == "prompt"
        and clipboard_command(out_path) is not None
    )
    if can_prompt_clip:
        offer_clipboard_copy(label, out_path, ok=False, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines)
    else:
        full_body = build_box_body_lines(
            out_path, rc=chk.returncode, stats=stats_line(out_path), extra_lines=box_lines, label=label, sdir=sdir
        )
        sys.stdout.write(format_info_box("SYNTAX ERROR", full_body) + "\n")
        sys.stdout.flush()
        if not in_run_block():
            offer_clipboard_copy(label, out_path, ok=False, rc=chk.returncode, title_kind="SYNTAX ERROR", extra_lines=box_lines)
    return chk.returncode


def run_script(
    label: str,
    script_path: Path,
    out_path: Path,
    header_lines: list[str] | None = None,
    cleanup_on_abort: list[Path] | None = None,
    auto_yes: bool = False,
    sandbox_override: str | None = None,
    footer_on_fail: str | None = None,
) -> int:
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    step_dir = script_path.parent
    sdir = step_dir.parent
    work_dir = get_work_dir(sdir)
    sandbox_mode = get_sandbox_mode(sdir, override=sandbox_override)
    shell_bin, _ = get_setting("shell")
    is_ps = _is_powershell(shell_bin)
    script_text = script_path.read_text(encoding="utf-8")
    exec_cmd = (
        [shell_bin, "-NoProfile", "-File", str(script_path)]
        if is_ps
        else [shell_bin, str(script_path)]
    )

    rc_syn = _validate_step_script_syntax(
        label,
        script_path,
        out_path,
        work_dir,
        shell_bin,
        is_ps,
        sdir,
        headless=headless,
        footer_on_fail=footer_on_fail,
    )
    if rc_syn != 0:
        return rc_syn

    aborted_marker = step_dir / "aborted"
    summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
    summary_obj["sandbox"] = sandbox_mode
    approved, abort_reason = confirm_execution(
        label, script_text, summary=summary_obj, script_path=script_path, auto_yes=headless
    )
    if not approved:
        write_private(aborted_marker, "aborted\n", overwrite=True)
        if abort_reason == "USER_ABORTED":
            return 130
        reason_str = abort_reason or f"aborted by user (re-run with: {prog_name()} --retry {label})"
        return not_run_exit(
            label, sdir, step_dir.name, out_path, f"[{label}] NOT RUN: {reason_str}", rc=130, headless=headless
        )
    aborted_marker.unlink(missing_ok=True)

    if script_path.is_file():
        updated_text = script_path.read_text(encoding="utf-8")
        if updated_text != script_text:
            script_text = updated_text
            rc_syn = _validate_step_script_syntax(
                label,
                script_path,
                out_path,
                work_dir,
                shell_bin,
                is_ps,
                sdir,
                headless=headless,
                footer_on_fail=footer_on_fail,
            )
            if rc_syn != 0:
                return rc_syn
            summary_obj = summarize_script_actions(script_text, work_dir=work_dir)
            summary_obj["sandbox"] = sandbox_mode

    start_line = f"[{label}] START\n"
    log_chunks: list[str] = [start_line]
    err_chunks: list[str] = []

    def _emit(text: str, is_err: bool) -> None:
        if is_err:
            err_chunks.append(text)
            log_chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()
            return
        if progress_filter is not None:
            out_txt, prog_txt = progress_filter.feed(text)
            if out_txt:
                log_chunks.append(out_txt)
            if prog_txt or out_txt:
                sys.stdout.write(prog_txt + out_txt)
                sys.stdout.flush()
        else:
            log_chunks.append(text)
            sys.stdout.write(text)
            sys.stdout.flush()
    for h in header_lines or []:
        log_chunks.append(h)
    log_chunks.append("\n")
    if headless:
        sys.stdout.write("".join(log_chunks))
    elif header_lines:
        sys.stdout.write("".join(header_lines) + "\n")
    sys.stdout.flush()

    tty_in = None
    master_fd = None
    slave_fd = None
    err_master_fd = None
    err_slave_fd = None
    if HAS_PTY and sys.stdout.isatty() and not no_clipboard() and not headless:
        try:
            tty_in = open("/dev/tty", "rb", buffering=0)
            master_fd, slave_fd = pty.openpty()
            attrs = termios.tcgetattr(slave_fd)
            attrs[1] &= ~termios.ONLCR
            termios.tcsetattr(slave_fd, termios.TCSANOW, attrs)
            err_master_fd, err_slave_fd = pty.openpty()
            termios.tcsetattr(err_slave_fd, termios.TCSANOW, attrs)
        except OSError:
            if tty_in is not None:
                tty_in.close()
                tty_in = None
            if master_fd is not None:
                os.close(master_fd)
                master_fd = None
            if slave_fd is not None:
                os.close(slave_fd)
                slave_fd = None
            if err_master_fd is not None:
                os.close(err_master_fd)
                err_master_fd = None
            if err_slave_fd is not None:
                os.close(err_slave_fd)
                err_slave_fd = None

    step_lines = list(summary_obj.get("operation_steps") or [])
    use_progress = (
        not headless
        and not in_run_block()
        and sys.stdout.isatty()
        and get_setting("progress")[0] != "false"
        and bool(step_lines)
    )
    tmp_progress_path: Path | None = None
    progress_filter: _ProgressLineFilter | None = None
    if use_progress:
        tmp_progress_path = _prepare_progress_script(
            script_text, step_dir, step_lines, shell_bin, is_ps, work_dir
        )
        if tmp_progress_path is not None:
            step_map = {int(s["step"]): s for s in step_lines if s.get("step")}
            progress_filter = _ProgressLineFilter(step_map, len(step_lines))
            exec_cmd = (
                [shell_bin, "-NoProfile", "-File", str(tmp_progress_path)]
                if is_ps
                else [shell_bin, str(tmp_progress_path)]
            )

    bundle_file = sdir / "0"
    bundle_snapshot = bundle_file.read_bytes() if bundle_file.is_file() else None
    child_env = scrub_child_env({**os.environ, "IN_RUN_BLOCK": "1"}, sandbox_mode)
    exec_cmd = build_sandbox_exec(exec_cmd, work_dir=work_dir, base_dir=ensure_base(), sandbox_mode=sandbox_mode)
    try:
        if (
            master_fd is not None
            and slave_fd is not None
            and err_master_fd is not None
            and err_slave_fd is not None
        ):
            try:
                proc = subprocess.Popen(
                    exec_cmd,
                    cwd=work_dir,
                    stdin=tty_in if tty_in is not None else slave_fd,
                    stdout=slave_fd,
                    stderr=err_slave_fd,
                    env=child_env,
                    close_fds=True,
                )
                os.close(slave_fd)
                slave_fd = None
                os.close(err_slave_fd)
                err_slave_fd = None
                for is_err, text in _iter_child_streams(master_fd, err_master_fd):
                    _emit(text, is_err)
                rc = proc.wait()
            finally:
                if slave_fd is not None:
                    os.close(slave_fd)
                if err_slave_fd is not None:
                    os.close(err_slave_fd)
                if master_fd is not None:
                    os.close(master_fd)
                if err_master_fd is not None:
                    os.close(err_master_fd)
                if tty_in is not None:
                    tty_in.close()
        else:
            proc = subprocess.Popen(
                exec_cmd,
                cwd=work_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=child_env,
            )
            assert proc.stdout is not None and proc.stderr is not None
            for is_err, text in _iter_child_streams(proc.stdout.fileno(), proc.stderr.fileno()):
                _emit(text, is_err)
            proc.stdout.close()
            proc.stderr.close()
            rc = proc.wait()
        if progress_filter is not None:
            rem_out, rem_prog = progress_filter.flush()
            if rem_out:
                log_chunks.append(rem_out)
            if rem_prog or rem_out:
                sys.stdout.write(rem_prog + rem_out)
                sys.stdout.flush()
    finally:
        if tmp_progress_path is not None:
            tmp_progress_path.unlink(missing_ok=True)
    if bundle_snapshot is not None:
        if not bundle_file.is_file() or bundle_file.read_bytes() != bundle_snapshot:
            write_private(bundle_file, bundle_snapshot.decode("utf-8", "replace"), overwrite=True)
            warn_msg = f"\n[{label}] SECURITY WARNING: block attempted to modify {bundle_file.name} (reverted)\n"
            log_chunks.append(warn_msg)
            sys.stdout.write(warn_msg)
            sys.stdout.flush()
    if log_chunks and not log_chunks[-1].endswith("\n"):
        log_chunks.append("\n")
        sys.stdout.write("\n")
    stdin_diag_lines: list[str] = []
    if rc != 0:
        clean_so_far = CR_LINE_RE.sub("", ANSI_RE.sub("", "".join(log_chunks[1:]))).replace("\r\n", "\n")
        stdin_diag_lines = _resolve_python_stdin_tracebacks(label, script_text, clean_so_far)
        for diag in stdin_diag_lines:
            log_chunks.append(diag + "\n")
    exit_str = f" (exit {rc})" if rc != 0 else ""
    end_line = f"\n[{label}] END{exit_str}\n"
    if rc != 0 and footer_on_fail:
        end_line += footer_on_fail if footer_on_fail.endswith("\n") else footer_on_fail + "\n"
    log_chunks.append(end_line)
    full_output = CR_LINE_RE.sub("", ANSI_RE.sub("", "".join(log_chunks))).replace("\r\n", "\n")
    write_private(out_path, full_output)
    err_path = step_dir / "err"
    err_text = CR_LINE_RE.sub("", ANSI_RE.sub("", "".join(err_chunks))).replace("\r\n", "\n")
    if err_text.strip():
        write_private(err_path, err_text, overwrite=True)
    else:
        err_path.unlink(missing_ok=True)
    clip_target = resolve_clipboard_target(out_path, full_output)
    if headless:
        if stdin_diag_lines:
            sys.stdout.write("".join(d + "\n" for d in stdin_diag_lines))
        sys.stdout.write(end_line)
        sys.stdout.flush()
    elif in_run_block() or not sys.stdout.isatty() or clipboard_mode() != "prompt" or clipboard_command(clip_target) is None:
        end_body = build_box_body_lines(clip_target, rc=rc, stats=stats_line(clip_target), label=label, sdir=sdir)
        sys.stdout.write("\n" + format_info_box("END", end_body) + "\n")
        sys.stdout.flush()
    if not headless:
        offer_clipboard_copy(label, out_path, ok=(rc == 0), rc=rc)
    return rc


TRAILING_FENCE_RE = re.compile(r"(?:\r?\n)+(?:RUN_(?:BLOCK|FIX)\s*)?`{3,}\s*$")
SPLIT_HEADER_RE = re.compile(
    r"^\s*(?:`{3,}[A-Za-z0-9_-]*\s*\n)?\s*(?:[A-Za-z0-9_./-]+\s+)?run_block\b[^\n]*<<\s*['\"]?(RUN_(?:BLOCK|FIX))['\"]?\s*$"
)
FENCE_LINE_RE = re.compile(r"^`{3,}[A-Za-z0-9_-]*\s*$")


def _reassemble_split_payload(payload: str) -> tuple[str, str | None]:
    """Reconstruct payloads split by chat Markdown fences when inner triple backticks appear."""
    norm = payload.replace("\r\n", "\n")
    lines = norm.split("\n")

    first_nonempty = -1
    for idx, line in enumerate(lines):
        if line.strip():
            first_nonempty = idx
            break
    if first_nonempty == -1:
        return payload, None

    header_line = lines[first_nonempty]
    m = SPLIT_HEADER_RE.match(header_line)
    if not m:
        cleaned = TRAILING_FENCE_RE.sub("", norm)
        c_lines = cleaned.split("\n")
        # Also strip orphan Markdown fence lines when the local shell consumed the outer
        # `run_block ... <<'RUN_BLOCK'` header before passing stdin.
        stripped_orphan = [ln for ln in c_lines if not FENCE_LINE_RE.match(ln)]
        joined_orphan = "\n".join(stripped_orphan)
        out = (joined_orphan + "\n") if joined_orphan and not joined_orphan.endswith("\n") else joined_orphan
        return out, None

    delim = m.group(1)
    body_lines = lines[first_nonempty + 1 :]
    end_idx = -1
    for idx in range(len(body_lines) - 1, -1, -1):
        stripped = body_lines[idx].strip()
        if stripped == delim or re.fullmatch(rf"{re.escape(delim)}\s*`{{3,}}", stripped):
            end_idx = idx
            break

    if end_idx == -1:
        return (
            payload,
            f"unclosed {delim} heredoc on stdin (missing closing '{delim}' terminator — check for split Markdown fences)",
        )

    inner = body_lines[:end_idx]
    rebuilt: list[str] = []
    i = 0
    while i < len(inner):
        cur = inner[i]
        # A split caused by inner triple backticks turns a single line or fence boundary into:
        #   <prefix>        (or standalone closing ```)
        #   ```<lang>       (chat UI reopening the next code block)
        # Strip standalone Markdown fence lines introduced by chat renderer splitting.
        if FENCE_LINE_RE.match(cur):
            i += 1
            continue
        rebuilt.append(cur)
        i += 1

    joined = "\n".join(rebuilt)
    out = (joined + "\n") if joined and not joined.endswith("\n") else joined
    return out, None


def cmd_normal(
    ref: str, payload: str, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    payload, split_err = _reassemble_split_payload(payload)
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, step = parse_ref(ref, allow_fix_step=False)
    step_num = int(step)
    if step_num < 1:
        raise SystemExit(f"{prog_name()}: step number must be >= 1")
    base = ensure_base()
    _warn_if_state_oversized(base)
    sdir = base / session
    sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_session_bundle(sdir, sandbox_mode=sandbox_override)
    label = f"{session}/{step}"
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    if split_err:
        return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: {split_err}", headless=headless)

    aborted_marker = step_dir / "aborted"

    overwrite = aborted_marker.exists()
    if overwrite:
        out_path.unlink(missing_ok=True)
        aborted_marker.unlink(missing_ok=True)
        for orig_p in (step_dir / "block.orig.sh", step_dir / "block.orig.ps1", step_dir / "out.orig"):
            orig_p.unlink(missing_ok=True)
    elif script_path.exists() or out_path.exists():
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            existing_lines = []
            if script_path.exists():
                existing_lines.append(f"Script: {script_path}")
            if out_path.exists():
                existing_lines.append(f"Output: {out_path}")
            step_hdr = format_session_header_lines(
                label=label, sdir=sdir, sandbox_mode=sandbox_override
            )
            if prompt_yes_no_box(
                "STEP ALREADY EXISTS",
                [*step_hdr, "", *existing_lines],
                f"Overwrite and re-run {label}?",
                default_yes=False,
                yes_status=f"✓ Overwriting {label}.",
                no_status=f"✗ Keeping existing {label}.",
                script_path=script_path if script_path.exists() else None,
                out_path=out_path if out_path.exists() else None,
            ):
                overwrite = True
                out_path.unlink(missing_ok=True)
                for orig_p in (step_dir / "block.orig.sh", step_dir / "block.orig.ps1", step_dir / "out.orig"):
                    orig_p.unlink(missing_ok=True)
            else:
                return 2
        if not overwrite:
            return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: step already exists — output: {out_path}", headless=headless)
    if step_num > 1 and not _find_step_script(sdir, str(step_num - 1)).exists():
        prev_label = f"{session}/{step_num - 1}"
        allow_skip = False
        if sys.stdout.isatty() and not no_clipboard() and not headless:
            step_hdr = format_session_header_lines(
                label=label, sdir=sdir, sandbox_mode=sandbox_override
            )
            allow_skip = prompt_yes_no_box(
                "MISSING PREVIOUS STEP",
                [*step_hdr, "", f"Missing: {prev_label}"],
                f"Run {label} anyway?",
                default_yes=False,
                yes_status=f"✓ Proceeding with {label} (skipped {prev_label}).",
                no_status=f"✗ Canceled {label} (run {prev_label} first).",
            )
            if not allow_skip:
                return 2
        if not allow_skip:
            return not_run_exit(
                label,
                sdir,
                step,
                out_path,
                f"[{label}] NOT RUN: previous step {prev_label} has not been run yet",
                headless=headless,
            )
    if not payload.strip():
        return not_run_exit(label, sdir, step, out_path, f"[{label}] NOT RUN: empty script on stdin", headless=headless)

    step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_private(script_path, payload, overwrite=overwrite)
    return run_script(
        label,
        script_path,
        out_path,
        cleanup_on_abort=[script_path],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )


def cmd_fix(
    ref: str, fix_code: str, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    fix_code, split_err = _reassemble_split_payload(fix_code)
    headless = auto_yes or os.environ.get("RUN_BLOCK_HEADLESS") == "1"
    session, target = parse_ref(ref, allow_fix_step=True)
    target_ref = f"{session}/{target}"
    base_step = target.split("_", 1)[0]
    next_seq_ref = f"{session}/{int(base_step) + 1}"
    sdir = ensure_base() / session
    new_step = next_fix_step(target, sdir=sdir)
    label = f"{session}/{new_step}"
    new_step_dir = _step_dir(sdir, new_step)
    fix_path = new_step_dir / "fix.py"
    out_path = new_step_dir / "out"
    if split_err:
        return not_run_exit(
            label, sdir, new_step, out_path, f"[{label}] NOT RUN: {split_err}", headless=headless, fix_target=target_ref
        )

    chain = _find_fix_chain_scripts(sdir, base_step)
    if not chain:
        missing_script = _find_step_script(sdir, target)
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            f"[{label}] NOT RUN: target script {missing_script} does not exist",
            headless=headless,
            fix_target=target_ref,
        )

    max_attempts = int(get_setting("max_fix_attempts")[0])
    prior_failures = _consecutive_failed_fixes(sdir, base_step)
    if prior_failures >= max_attempts:
        return not_run_exit(
            label,
            sdir,
            new_step,
            out_path,
            (
                f"[{label}] NOT RUN: STOP --fix — reached max consecutive failed --fix attempts "
                f"({prior_failures}/{max_attempts}) for {session}/{base_step}; "
                f"emit a fresh {next_seq_ref} block instead"
            ),
            headless=headless,
            fix_target=target_ref,
        )

    reach_limit = (prior_failures + 1) >= max_attempts
    stop_directive = (
        f"[{label}] STOP --fix: reached {prior_failures + 1}/{max_attempts} failed --fix attempts "
        f"for {session}/{base_step}; switch to a fresh {next_seq_ref} block instead."
    )

    def _fail_not_run(reason: str) -> int:
        msg = f"[{label}] NOT RUN: {reason}"
        if reach_limit:
            msg += f"\n{stop_directive}"
        return not_run_exit(label, sdir, new_step, out_path, msg, headless=headless, fix_target=target_ref)

    if not fix_code.strip():
        return _fail_not_run("empty fix on stdin")

    ast_ok, ast_err = validate_fix_ast(fix_code)
    if not ast_ok:
        return _fail_not_run(f"unsafe construct in --fix ({ast_err})")

    direct_script = _find_step_script(sdir, target)
    if direct_script.is_file():
        primary = (target, direct_script)
    else:
        primary = chain[-1]

    candidates: list[tuple[str, Path]] = [primary]
    for cand_step, cand_path in reversed(chain):
        if all(cand_step != c[0] for c in candidates):
            candidates.append((cand_step, cand_path))

    chosen_step: str | None = None
    chosen_script: Path | None = None
    chosen_orig: str = ""
    chosen_new: str = ""
    primary_err: str | None = None

    for idx, (cand_step, cand_script) in enumerate(candidates):
        cand_orig = cand_script.read_text(encoding="utf-8")
        ns: dict[str, object] = {
            "__builtins__": dict(SAFE_FIX_BUILTINS),
            "text": cand_orig,
            "re": re,
        }
        try:
            exec(compile(fix_code, str(fix_path), "exec"), ns)
        except Exception as exc:
            if idx == 0:
                primary_err = _format_fix_exception(exc, fix_code, fix_path, ns)
            continue
        cand_new = ns.get("text")
        if not isinstance(cand_new, str):
            if idx == 0:
                primary_err = "fix did not leave a string in 'text'"
            continue
        if cand_new == cand_orig:
            if idx == 0:
                primary_err = f"fix made no changes to {cand_script}"
            continue
        chosen_step = cand_step
        chosen_script = cand_script
        chosen_orig = cand_orig
        chosen_new = cand_new
        break

    if chosen_step is None or chosen_script is None:
        return _fail_not_run(primary_err or f"fix made no changes to {primary[1]}")

    ext = chosen_script.suffix or _script_ext()
    new_step_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    script_path = new_step_dir / f"block{ext}"
    write_private(fix_path, fix_code)
    write_private(script_path, chosen_new)
    diff = "".join(
        difflib.unified_diff(
            chosen_orig.splitlines(keepends=True),
            chosen_new.splitlines(keepends=True),
            fromfile=f"{chosen_step}/{chosen_script.name}",
            tofile=f"{new_step}/block{ext}",
        )
    )
    header = [f"[{label}] patched {chosen_step}/{chosen_script.name} -> {new_step}/block{ext}:\n", diff]
    return run_script(
        label,
        script_path,
        out_path,
        header_lines=header,
        cleanup_on_abort=[fix_path, script_path],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
        footer_on_fail=stop_directive if reach_limit else None,
    )


def _step_sort_key(stem: str) -> tuple[int, int]:
    if "_" in stem:
        b, s = stem.split("_", 1)
        return (int(b) if b.isdigit() else 0, int(s) if s.isdigit() else 0)
    return (int(stem) if stem.isdigit() else 0, 0)


def _step_status(sdir: Path, stem: str) -> str:
    step_d = _step_dir(sdir, stem)
    if (step_d / "aborted").exists():
        return "ABORTED"
    for candidate in (step_d / "out", step_d / "error"):
        if candidate.is_file():
            txt = candidate.read_text(encoding="utf-8", errors="replace")
            label = f"{sdir.name}/{stem}"
            matches = re.findall(rf"^\[{re.escape(label)}\]\s+(END|SUCCESS|FAILED|NOT RUN)([^\n]*)", txt, flags=re.MULTILINE)
            if matches:
                kind, rest = matches[-1]
                return (kind + rest.split("—")[0]).strip()
            return "DONE"
    return "SAVED"


def _find_latest_step(session: str | None = None) -> tuple[str, str]:
    base = ensure_base()
    if session:
        sdirs = [base / session] if (base / session).is_dir() else []
    else:
        sdirs = sorted(
            [p for p in base.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    for sdir in sdirs:
        scripts = [p.parent.name for p in _iter_session_scripts(sdir)]
        if scripts:
            return sdir.name, scripts[-1]
    raise SystemExit(f"{prog_name()}: no saved blocks found in {base}")


def cmd_list(session: str | None = None) -> int:
    base = ensure_base()
    _warn_if_state_oversized(base)
    if not session:
        sdirs = sorted([p for p in base.iterdir() if p.is_dir()], key=lambda p: (_session_mtime(p), p.name))
        if not sdirs:
            sys.stdout.write(f"No sessions in {base} (0 B)\n")
            return 0
        sys.stdout.write(f"Sessions in {base}:\n")
        total_bytes = 0
        for sdir in sdirs:
            scripts = [p.parent.name for p in _iter_session_scripts(sdir)]
            has_bundle = (sdir / "0").is_file()
            sz = _dir_size_bytes(sdir)
            total_bytes += sz
            if scripts:
                last = f"{sdir.name}/{scripts[-1]} ({_step_status(sdir, scripts[-1])})"
            elif has_bundle:
                last = f"{sdir.name}/0 (BUNDLE)"
            else:
                last = "empty"
            sys.stdout.write(f"  {sdir.name:<8}  {len(scripts):>3} block(s)  {_human_size(sz):>9}   last: {last}\n")
        sys.stdout.write(f"Total storage: {_human_size(total_bytes)} ({len(sdirs)} session(s))\n")
        session = sdirs[-1].name
        sys.stdout.write(f"\nRecent blocks in {session}:\n")
    else:
        sdir = base / session
        if not sdir.is_dir():
            raise SystemExit(f"{prog_name()}: session {session!r} not found in {base}")
        sys.stdout.write(f"Blocks in {session} ({_human_size(_dir_size_bytes(sdir))}):\n")
    sdir = base / session
    if (sdir / "0").is_file():
        ref0 = f"{session}/0"
        sys.stdout.write(f"  {ref0:<10}  {'BUNDLE':<24}  Session context bundle (0)\n")
    script_paths = _iter_session_scripts(sdir)
    for sp in script_paths[-15:]:
        stem = sp.parent.name
        st = _step_status(sdir, stem)
        sh_text = sp.read_text(encoding="utf-8", errors="replace")
        summary = summarize_script_actions(sh_text, work_dir=get_work_dir(sdir))
        rows = summary.get("rows") or []
        desc = "; ".join(f"{k}: {v}" for k, v in rows[:2]) if rows else ""
        if len(desc) > 56:
            desc = desc[:53] + "..."
        ref = f"{session}/{stem}"
        sys.stdout.write(f"  {ref:<10}  {st:<24}  {desc}\n")
    return 0


def cmd_show(ref: str | None = None) -> int:
    if ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    if step == "0":
        bundle_path = sdir / "0"
        if bundle_path.is_file():
            orig_bundle = _orig_file_backup_path(bundle_path)
            b_suffix = f" (edited) (original: {orig_bundle})" if orig_bundle.is_file() else ""
            sys.stdout.write(f"=== [{session}/0] Bundle: {bundle_path}{b_suffix} ===\n")
            sys.stdout.write(bundle_path.read_text(encoding="utf-8", errors="replace"))
            return 0
        raise SystemExit(f"{prog_name()}: bundle {session}/0 not found ({bundle_path})")
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    err_path = step_dir / "error"
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    orig_path = _orig_backup_path(script_path)
    status_str = _step_status(sdir, step)
    script_edited = f" (edited) (original: {orig_path})" if orig_path.is_file() else ""
    sys.stdout.write(f"=== [{session}/{step}] Script: {script_path} ({status_str}){script_edited} ===\n")
    sys.stdout.write(script_path.read_text(encoding="utf-8", errors="replace"))
    if out_path.is_file():
        out_orig = _orig_file_backup_path(out_path)
        out_edited = f" (edited) (original: {out_orig})" if out_orig.is_file() else ""
        sys.stdout.write(f"\n=== [{session}/{step}] Output: {out_path}{out_edited} ===\n")
        sys.stdout.write(out_path.read_text(encoding="utf-8", errors="replace"))
    if err_path.is_file():
        sys.stdout.write(f"\n=== [{session}/{step}] Error: {err_path} ===\n")
        sys.stdout.write(err_path.read_text(encoding="utf-8", errors="replace"))
    return 0


def cmd_retry(
    ref: str | None = None, auto_yes: bool = False, sandbox_override: str | None = None
) -> int:
    if ref:
        session, step = parse_ref(ref, allow_fix_step=True)
    else:
        session, step = _find_latest_step()
    sdir = ensure_base() / session
    step_dir = _step_dir(sdir, step)
    script_path = _find_step_script(sdir, step)
    out_path = step_dir / "out"
    if not script_path.is_file():
        raise SystemExit(f"{prog_name()}: block {session}/{step} not found ({script_path})")
    out_path.unlink(missing_ok=True)
    (step_dir / "out.orig").unlink(missing_ok=True)
    (step_dir / "error").unlink(missing_ok=True)
    (step_dir / "aborted").unlink(missing_ok=True)
    return run_script(
        f"{session}/{step}",
        script_path,
        out_path,
        cleanup_on_abort=[],
        auto_yes=auto_yes,
        sandbox_override=sandbox_override,
    )


def _find_latest_session_dir() -> Path | None:
    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return sdirs[0] if sdirs else None


def cmd_sandbox(argv: list[str]) -> int:
    prog = prog_name()
    if in_run_block():
        sys.stderr.write(f"{prog}: cannot modify session sandbox settings from inside a running block\n")
        return 2
    mode_arg: str | None = None
    session_arg: str | None = None
    for a in argv:
        if re.fullmatch(r"s\d+", a) and session_arg is None and mode_arg is not None:
            session_arg = a
        elif mode_arg is None and a.lower() in ("off", "0", "false", "on", "1", "true", "auto", "strict", "nonet", "no-net"):
            mode_arg = normalize_sandbox_mode(a)
        elif session_arg is None and re.fullmatch(r"[A-Za-z0-9._-]+", a) and (ensure_base() / a).is_dir():
            session_arg = a
        elif mode_arg is None:
            mode_arg = normalize_sandbox_mode(a)
        else:
            raise SystemExit(f"{prog}: usage: {prog} --sandbox [off|strict|nonet] [session]")

    base = ensure_base()
    sdir = (base / session_arg) if session_arg else _find_latest_session_dir()
    backend = detect_sandbox_backend()
    if mode_arg is None:
        cur_mode = get_sandbox_mode(sdir)
        sess_lbl = sdir.name if sdir is not None else "(no active session)"
        sys.stdout.write(
            f"Session: {sess_lbl}\n"
            f"Sandbox: {format_sandbox_header(cur_mode)}\n"
            f"Backend: {backend}\n"
        )
        return 0
    if sdir is None:
        sdir = start_session(session_arg, sandbox_mode=mode_arg)
    else:
        sdir.mkdir(mode=0o700, parents=True, exist_ok=True)
        set_session_bundle_header(sdir, "Sandbox", format_sandbox_header(mode_arg))
    sys.stdout.write(
        f"Updated {sdir.name}/0 -> Sandbox: {format_sandbox_header(mode_arg)} (backend: {backend})\n"
    )
    return 0


def _dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _session_mtime(sdir: Path) -> float:
    latest = 0.0
    try:
        latest = sdir.stat().st_mtime
        for p in sdir.iterdir():
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                pass
    except OSError:
        pass
    return latest


_STATE_WARNED_DIRS: set[str] = set()


def _warn_if_state_oversized(base: Path) -> None:
    key = str(base)
    if key in _STATE_WARNED_DIRS:
        return
    raw_limit, _ = get_setting("max_state_mb")
    try:
        limit_mb = float(raw_limit)
    except ValueError:
        limit_mb = 100.0
    if limit_mb <= 0:
        return
    total_bytes = _dir_size_bytes(base)
    if total_bytes > limit_mb * 1024 * 1024:
        _STATE_WARNED_DIRS.add(key)
        prog = prog_name()
        sys.stderr.write(
            f"{prog}: warning: state directory {base} uses {_human_size(total_bytes)} "
            f"(exceeds {limit_mb:g} MB limit; run '{prog} --clean' to prune old sessions)\n"
        )
        sys.stderr.flush()


def _parse_nonneg_float(raw: str, flag_name: str) -> float:
    prog = prog_name()
    try:
        val = float(raw)
    except ValueError:
        raise SystemExit(f"{prog}: invalid {flag_name} value: {raw!r}")
    if math.isnan(val) or math.isinf(val) or val < 0:
        raise SystemExit(f"{prog}: {flag_name} must be >= 0")
    return val


def cmd_clean(argv: list[str]) -> int:
    prog = prog_name()
    usage_msg = (
        f"{prog}: usage: {prog} --clean [--keep N | --older-than DAYS | --max-size MB | --all] [--yes] [session...]"
    )
    keep: int | None = None
    older_than_days: float | None = None
    max_size_mb: float | None = None
    clean_all = False
    yes = False
    target_names: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--all":
            clean_all = True
            i += 1
        elif a in ("-y", "--yes", "--force"):
            yes = True
            i += 1
        elif a == "--keep":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --keep requires a non-negative integer")
            try:
                keep = int(argv[i + 1])
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {argv[i + 1]!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 2
        elif a.startswith("--keep="):
            val_s = a.split("=", 1)[1]
            try:
                keep = int(val_s)
            except ValueError:
                raise SystemExit(f"{prog}: invalid --keep value: {val_s!r}")
            if keep < 0:
                raise SystemExit(f"{prog}: --keep must be >= 0")
            i += 1
        elif a == "--older-than":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --older-than requires a non-negative number of days")
            older_than_days = _parse_nonneg_float(argv[i + 1], "--older-than")
            i += 2
        elif a.startswith("--older-than="):
            older_than_days = _parse_nonneg_float(a.split("=", 1)[1], "--older-than")
            i += 1
        elif a == "--max-size":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: --max-size requires a non-negative size in MB")
            max_size_mb = _parse_nonneg_float(argv[i + 1], "--max-size")
            i += 2
        elif a.startswith("--max-size="):
            max_size_mb = _parse_nonneg_float(a.split("=", 1)[1], "--max-size")
            i += 1
        elif a.startswith("-"):
            raise SystemExit(usage_msg)
        else:
            if not re.fullmatch(r"[A-Za-z0-9._-]+", a):
                raise SystemExit(f"{prog}: invalid session name: {a!r}")
            if a not in target_names:
                target_names.append(a)
            i += 1

    has_policy_flag = clean_all or keep is not None or older_than_days is not None or max_size_mb is not None
    if target_names and has_policy_flag:
        raise SystemExit(f"{prog}: cannot combine explicit session names with --keep/--older-than/--max-size/--all")

    base = ensure_base()
    sdirs = sorted(
        [p for p in base.iterdir() if p.is_dir()],
        key=lambda p: (_session_mtime(p), p.name),
    )
    sizes_by_dir: dict[Path, int] = {d: _dir_size_bytes(d) for d in sdirs}
    total_before = sum(sizes_by_dir.values())

    if target_names:
        by_name = {d.name: d for d in sdirs}
        to_remove: list[Path] = []
        for name in target_names:
            if name not in by_name:
                raise SystemExit(f"{prog}: session {name!r} not found in {base}")
            to_remove.append(by_name[name])
    elif clean_all:
        to_remove = list(sdirs)
    else:
        if not has_policy_flag:
            keep = 5
        remove_set: set[Path] = set()
        if older_than_days is not None:
            cutoff = time.time() - older_than_days * 86400.0
            for d in sdirs:
                if _session_mtime(d) < cutoff:
                    remove_set.add(d)
        if keep is not None:
            remaining = [d for d in sdirs if d not in remove_set]
            if keep == 0:
                remove_set.update(remaining)
            elif len(remaining) > keep:
                remove_set.update(remaining[: len(remaining) - keep])
        if max_size_mb is not None:
            max_bytes = int(max_size_mb * 1024 * 1024)
            remaining = [d for d in sdirs if d not in remove_set]
            rem_total = sum(sizes_by_dir[d] for d in remaining)
            for d in remaining:
                if rem_total <= max_bytes:
                    break
                remove_set.add(d)
                rem_total -= sizes_by_dir[d]
        to_remove = [d for d in sdirs if d in remove_set]

    if not to_remove:
        sys.stdout.write(
            f"Nothing to clean in {base} ({len(sdirs)} session(s), {_human_size(total_before)} total).\n"
        )
        return 0

    freed_bytes = sum(sizes_by_dir[d] for d in to_remove)
    remaining_bytes = max(0, total_before - freed_bytes)
    details = ", ".join(f"{d.name} ({_human_size(sizes_by_dir[d])})" for d in to_remove)
    if not yes and sys.stdin.isatty() and sys.stdout.isatty() and not no_clipboard():
        ok = prompt_yes_no_box(
            "CLEAN SESSIONS",
            [
                f"Directory: {base}",
                f"Total size: {_human_size(total_before)}",
                f"Remove: {len(to_remove)} session(s) ({details})",
                f"Free: {_human_size(freed_bytes)} ({freed_bytes:,} bytes)",
            ],
            f"Delete {len(to_remove)} session(s)?",
            default_yes=False,
            yes_status=f"✓ Removing {len(to_remove)} session(s).",
            no_status="✗ Clean canceled.",
        )
        if not ok:
            return 2

    for d in to_remove:
        shutil.rmtree(d, ignore_errors=True)
    kept = len(sdirs) - len(to_remove)
    sys.stdout.write(
        f"Cleaned {len(to_remove)} session(s) ({details}; {_human_size(freed_bytes)} / {freed_bytes:,} bytes freed) "
        f"from {base}; {kept} kept ({_human_size(remaining_bytes)} remaining).\n"
    )
    return 0
