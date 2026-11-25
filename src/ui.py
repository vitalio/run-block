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
    "group": "\x1b[1;34m",
    "rule": "\x1b[1;36m",
    "rules": "\x1b[1;36m",
    "cmd": "\x1b[1;35m",
    "file": "\x1b[1;94m",
    "prompt": "\x1b[1;33m",
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


def _colorize_kv_line(line: str, *, bright: bool = False) -> str:
    if not _use_color():
        return line
    m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*:)(\s+)(.*)$", line)
    if m:
        key, spaces, val = m.group(1), m.group(2), m.group(3)
        if bright:
            if key == "Workdir:" and not _is_same_cwd(val):
                return f"{key}{spaces}{_HIGHLIGHT_COLOR}{val}{_ANSI_RESET}"
            if key == "Exit:" and val.strip() != "0":
                return f"{key}{spaces}{_WARN_COLOR}{val}{_ANSI_RESET}"
            if key == "Error:":
                return f"{key}{spaces}{_ERROR_COLOR}{val}{_ANSI_RESET}"
            return line
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
    tab_re = re.compile(
        r"^(\s*)(\d+\s)?(\s*\S+%\s+\S+\s+\d+\s+~\S+\s+" + TABLE_TIME_COL_PATTERN + r")(\[([a-z0-9_-]+)\])(\s+)(.*)$"
    )
    hdr_re = re.compile(r"^(\s{2})((?:#\s+|\s+)%\s+CHARS\s+LINES\s+~TOK\s+(?:TIME\s+)?KIND\s+SOURCE)\s*$")
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


def char_width(ch: str) -> int:
    if unicodedata.category(ch) in ("Mn", "Me", "Cf", "Cc"):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


_char_display_width = char_width


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
    r"^(?:Reasoning:|Operations:|Safety warnings(?: \(\d+\))?:|Analyzer:|Bundle warnings(?: \(\d+\))?:|Parts(?: \(\d+\))?:)$"
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


_GENERIC_TAIL_RE = re.compile(r"^(?:FAILED\b|OK\b|Ran \d+ test|-{5,}$|={5,}$|make: |Error: Process completed)")
_TB_FRAME_RE = re.compile(r'^\s+File "([^"]+)", line (\d+)')
_ASSERT_MISSING_RE = re.compile(r"AssertionError: (['\"])(.+?)\1 not found in\s*(.*)$")


def _extract_haystack_candidates(haystack_raw: str) -> list[str]:
    text = haystack_raw.strip()
    if not text:
        return []
    try:
        val = ast.literal_eval(text)
        if isinstance(val, str):
            text = val
        elif isinstance(val, (list, tuple, set)):
            out: list[str] = []
            for item in val:
                s = str(item).strip()
                if s:
                    out.extend(ln.strip() for ln in s.splitlines() if ln.strip())
            return out
    except Exception:
        if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
            text = text[1:-1]
        text = text.replace("\\n", "\n").replace("\\t", "\t")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _traceback_root_cause(raw: str) -> str:
    """Summarize the last Traceback in captured output as `Exc: msg (file:line)`."""
    lines = raw.splitlines()
    tb_idx = -1
    for i, ln in enumerate(lines):
        if ln.startswith("Traceback (most recent call last):"):
            tb_idx = i
    if tb_idx == -1:
        return ""
    loc = ""
    exc_line = ""
    exc_idx = -1
    for offset, ln in enumerate(lines[tb_idx + 1 :], start=tb_idx + 1):
        m = _TB_FRAME_RE.match(ln)
        if m:
            loc = f"{Path(m.group(1)).name}:{m.group(2)}"
            continue
        if ln.startswith((" ", "\t")) or not ln.strip():
            continue
        exc_line = ln.strip()
        exc_idx = offset
        break
    if not exc_line:
        return ""
    summary = f"{exc_line} ({loc})" if loc else exc_line
    m_miss = _ASSERT_MISSING_RE.search(exc_line)
    if m_miss:
        needle = m_miss.group(2)
        haystack_tail = [m_miss.group(3)] if m_miss.group(3) else []
        if exc_idx != -1:
            for extra_ln in lines[exc_idx + 1 :]:
                s_extra = extra_ln.strip()
                if not s_extra or _GENERIC_TAIL_RE.match(s_extra) or s_extra.startswith("["):
                    break
                haystack_tail.append(s_extra)
        pool = [ln.strip() for ln in lines[:tb_idx] if ln.strip()]
        for cand in _extract_haystack_candidates("\n".join(haystack_tail)):
            if cand and cand not in pool:
                pool.append(cand)
        close = difflib.get_close_matches(needle, pool, n=1, cutoff=0.6)
        if close:
            summary += f"; closest: {close[0]}"
    return summary


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
    last = _last_nonempty_line(out_path, skip_prefixes, max_len)
    if last and not _GENERIC_TAIL_RE.match(last):
        return last
    try:
        raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.is_file() else ""
    except OSError:
        raw = ""
    cause = _traceback_root_cause(raw)
    if not cause:
        return last
    if display_width(cause) > max_len:
        budget = max(1, max_len - 3)
        acc: list[str] = []
        cur_w = 0
        for ch in cause:
            cw = char_width(ch)
            if cur_w + cw > budget:
                break
            acc.append(ch)
            cur_w += cw
        cause = "".join(acc).rstrip() + "..."
    return cause


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
    edited: bool = False,
) -> tuple[list[str], list[str]]:
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
        b_breakdown, b_warnings = _build_start_bundle_parts(
            resolved_sdir,
            err_src,
            details=bundle_details,
            max_width=max_width,
            plan=bundle_plan_obj,
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
    rc: int | None = None,
    stats: str | None = None,
    title_kind: str = "END STEP",
    extra_lines: list[str] | None = None,
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
            if "duration_ms" in data or "exit_code" in data or "operations" in data or "reasoning" in data or "outcome" in data:
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
    base = default_base_dir()
    if label:
        sess = label.split("/", 1)[0].strip()
        if sess and (base / sess).is_dir():
            return base / sess
    if path_hint is not None:
        for anc in (path_hint.parent, path_hint.parent.parent):
            if re.fullmatch(r"s\d+", anc.name):
                return anc
    if label:
        sess = label.split("/", 1)[0].strip()
        if sess:
            return base / sess
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


def _format_reasoning_lines(reasoning: str, max_width: int, *, max_lines: int | None = 6) -> list[str]:
    clean = reasoning.strip()
    if not clean:
        return []
    hdr = f"{_KEY_COLOR}Reasoning:{_ANSI_RESET}" if _use_color() else "Reasoning:"
    wrapped: list[str] = []
    avail = max(16, max_width - 2)
    raw_lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    for rline in raw_lines:
        wrapped.extend(
            textwrap.wrap(rline, width=avail, initial_indent="  ", subsequent_indent="  ")
            or [f"  {rline}"]
        )
    if max_lines is not None and max_lines > 0 and len(wrapped) > max_lines:
        kept = max(1, max_lines - 1)
        hidden = len(wrapped) - kept
        hint = f"  ... +{hidden} more"
        if _use_color():
            hint = f"{_KEY_COLOR}{hint}{_ANSI_RESET}"
        wrapped = [*wrapped[:kept], hint]
    return [hdr, *wrapped]


def _resolve_step_reasoning(
    reasoning: str | None = None,
    summary: dict[str, object] | None = None,
    script_path: Path | None = None,
    step_dir: Path | None = None,
) -> str:
    if reasoning and str(reasoning).strip():
        return str(reasoning).strip()
    if summary and isinstance(summary.get("reasoning"), str) and str(summary["reasoning"]).strip():
        return str(summary["reasoning"]).strip()
    target_dir = step_dir if step_dir is not None else (script_path.parent if script_path is not None else None)
    if target_dir is not None:
        meta = read_step_meta(target_dir)
        if isinstance(meta.get("reasoning"), str) and str(meta["reasoning"]).strip():
            return str(meta["reasoning"]).strip()
        plan_md = target_dir / "plan.md"
        if plan_md.is_file():
            try:
                txt = plan_md.read_text(encoding="utf-8", errors="replace").strip()
                if txt:
                    return txt
            except OSError:
                pass
    return ""


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
    reasoning: str | None = None,
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
    resolved_reasoning = _resolve_step_reasoning(reasoning, summary=summary, script_path=script_path)
    if resolved_reasoning:
        if content_lines:
            content_lines.append("")
        content_lines.extend(_format_reasoning_lines(resolved_reasoning, max_row_len))
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
    term_cols: int | None = None,
    term_rows: int | None = None,
) -> tuple[str, int, int]:
    return _render_block(
        title,
        content_lines,
        prompt_line=prompt_line,
        term_cols=term_cols,
        term_rows=term_rows,
    )


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
