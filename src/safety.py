# --- Detailed pre-execution block plan and safety scanner ---
RISK_RULES: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "git-destructive",
        "destructive Git operation",
        re.compile(
            r"\bgit\s+(?:reset\s+--hard|clean\s+-[A-Za-z]*f|push\s+[^\n]*(?:--force|-f\b|--delete)|branch\s+-D\b|tag\s+-d\b|checkout\s+--\s+\.|restore\s+\.|rebase\b|filter-branch\b)"
        ),
    ),
    (
        "git-push",
        "push to remote Git repository",
        re.compile(r"\bgit\s+(?:-C\s+\S+\s+)*push\b"),
    ),
    (
        "net-write",
        "network or remote file write",
        re.compile(
            r"(?:\b(?:curl|wget)\b[^\n]*(?:-X\s*(?:POST|PUT|DELETE|PATCH)\b|--data\b|--form\b|\s-d\s|\s-F\s)|\b(?:scp|rsync)\s)"
        ),
    ),
    (
        "fs-destructive",
        "recursive or destructive file deletion/overwrite",
        re.compile(
            r"(?:\brm\s+-[A-Za-z]*(?:r|f)[A-Za-z]*\b|\bshutil\.rmtree\s*\(|\bos\.(?:remove|unlink)\s*\(|\bdd\s+[^\n]*\bof=|\b(?:mkfs|shred|fdisk)\b|>>?\s*(?:/etc/|~/?\.(?:ssh|bashrc|zshrc|profile|gitconfig)|\$HOME/\.(?:ssh|bashrc|zshrc|profile|gitconfig)|\.git/(?:hooks|config)\b))"
        ),
    ),
    (
        "privilege-system",
        "privilege escalation or system modification",
        re.compile(
            r"(?:\b(?:sudo|doas|pkexec|chown|systemctl|service|killall|pkill)\b|\bkill\s+-9\b|\bchmod\s+[0-7]*777\b|\b(?:apt|apt-get|yum|dnf|pacman|brew)\s+(?:install|remove|purge)\b|\bpip3?\s+install\b|\bnpm\s+install\s+-g\b)"
        ),
    ),
    (
        "secrets-exposure",
        "shell trace or credential file access",
        re.compile(
            r"(?:\bset\s+-[A-Za-z]*x\b|\bbash\s+-[A-Za-z]*x\b|\.ssh/id_[A-Za-z0-9_]+(?!\.pub)\b|\.netrc\b|\.aws/credentials\b)"
        ),
    ),
    (
        "remote-exec",
        "piping remote content into a shell or eval",
        re.compile(
            r"(?:\b(?:curl|wget)\b[^\n]*\|\s*(?:sudo\s+)?(?:sh|bash|zsh|python3?)\b"
            r"|(?:^|[;|&(`{])\s*(?:!\s+|(?:if|elif|then|do|else|while|until|sudo|env|command|time)\s+)*"
            r"(?:[A-Za-z_][A-Za-z0-9_]*=(?:\"(?:\\.|[^\"\\])*\"|'[^']*'|[^\s;|&()]*)\s+)*eval\s+"
            r"|\bbase64\s+(?:-d|--decode)\b[^\n]*\|\s*(?:sh|bash|zsh|python3?)\b)"
        ),
    ),
    (
        "unicode-spoof",
        "hidden bidirectional or zero-width Unicode control characters",
        re.compile(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff\U000e0000-\U000e007f]"),
    ),
]


def get_active_risk_rules() -> list[tuple[str, str, re.Pattern[str]]]:
    raw_dis, _ = get_setting("safety_disable")
    disabled: set[str] = {
        x.strip().lower()
        for x in re.split(r"[,\s]+", raw_dis)
        if x.strip()
    }
    if "external-write" in disabled:
        disabled.update(("git-push", "net-write"))
    custom_map: dict[str, str] = {}
    env_rules = os.environ.get("RUN_BLOCK_SAFETY_RULES", "").strip()
    if env_rules:
        for item in env_rules.split(";"):
            part = item.strip()
            if not part:
                continue
            sep = "=" if "=" in part and (":" not in part or part.index("=") < part.index(":")) else (":" if ":" in part else "")
            if not sep:
                continue
            cat_raw, pat_raw = part.split(sep, 1)
            cat = cat_raw.strip().lower()
            pat_str = pat_raw.strip()
            if not cat:
                continue
            if pat_str.lower() in ("off", "none", "false", "0", "disable", "disabled"):
                disabled.add(cat)
                custom_map.pop(cat, None)
            elif pat_str:
                custom_map[cat] = pat_str
                disabled.discard(cat)

    active: list[tuple[str, str, re.Pattern[str]]] = []
    seen_cats: set[str] = set()
    for cat, desc, pat in RISK_RULES:
        if cat in disabled:
            continue
        if cat in custom_map:
            try:
                active.append((cat, desc, re.compile(custom_map[cat])))
                seen_cats.add(cat)
                continue
            except re.error:
                pass
        active.append((cat, desc, pat))
        seen_cats.add(cat)

    for cat, pat_str in custom_map.items():
        if cat in disabled or cat in seen_cats:
            continue
        try:
            active.append((cat, f"custom safety rule ({cat})", re.compile(pat_str)))
            seen_cats.add(cat)
        except re.error:
            pass
    return active

PY_HEREDOC_START_RE = re.compile(r"python3?\s+-[^\n]*<<-?['\"]?([A-Za-z0-9_]+)['\"]?")
PY_DASH_C_START_RE = re.compile(r"^python3?(?:\s+-[A-Za-z0-9]+)*\s+-c\s+(['\"])(.*)$")
SHELL_HEREDOC_START_RE = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
HEREDOC_REDIRECT_TARGET_RE = re.compile(r">>?\s*([^\s;<>&|]+)")
FOR_LOOP_RE = re.compile(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.+?)(?:\s*;\s*do|\s*)$")
VAR_ASSIGN_RE = re.compile(
    r"^(?:(?:export|local|readonly)\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$"
)
_SHELL_EXEC_CMD_RE = re.compile(
    r"(?:^|[;|&(`{\s])(?:sh|bash|zsh|dash|ksh)\s+(?:-[A-Za-z]+\s+)*-c\b|\bssh\s+"
)


def _parse_var_assignment(line: str) -> tuple[str, list[str]] | None:
    """Parses a pure shell variable or array assignment without trailing commands or substitutions."""
    m = VAR_ASSIGN_RE.match(line.strip())
    if not m:
        return None
    name, rhs = m.group(1), m.group(2)
    if rhs == "":
        return name, [""]
    if rhs[0].isspace():
        if rhs.lstrip().startswith("#"):
            return name, [""]
        return None
    n = len(rhs)
    if rhs[0] == "(":
        i = 1
        in_sq = False
        in_ansi_sq = False
        in_dq = False
        closed = False
        while i < n:
            ch = rhs[i]
            if in_sq:
                if ch == "'":
                    in_sq = False
                i += 1
                continue
            if in_ansi_sq:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "'":
                    in_ansi_sq = False
                i += 1
                continue
            if in_dq:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == "`":
                    return None
                if ch == chr(36) and i + 1 < n and rhs[i + 1] == "(":
                    return None
                if ch == '"':
                    in_dq = False
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == "`":
                return None
            if ch == chr(36) and i + 1 < n and rhs[i + 1] == "(":
                return None
            if ch == chr(36) and i + 1 < n and rhs[i + 1] == "'":
                in_ansi_sq = True
                i += 2
                continue
            if ch == "'":
                in_sq = True
                i += 1
                continue
            if ch == '"':
                in_dq = True
                i += 1
                continue
            if ch == "(":
                return None
            if ch == ")":
                closed = True
                break
            i += 1
        if not closed or in_sq or in_ansi_sq or in_dq:
            return None
        tail = rhs[i + 1 :].strip()
        if tail and not tail.startswith("#"):
            return None
        return name, _parse_for_items(rhs[1:i])
    i = 0
    while i < n:
        ch = rhs[i]
        if ch.isspace() or ch in ";|&()":
            break
        if ch == "`":
            return None
        if ch == chr(36):
            if i + 1 < n and rhs[i + 1] == "(":
                return None
            if i + 1 < n and rhs[i + 1] == "'":
                i += 2
                while i < n:
                    if rhs[i] == "\\" and i + 1 < n:
                        i += 2
                        continue
                    if rhs[i] == "'":
                        i += 1
                        break
                    i += 1
                else:
                    return None
                continue
        if ch == "'":
            i += 1
            while i < n and rhs[i] != "'":
                i += 1
            if i >= n:
                return None
            i += 1
            continue
        if ch == '"':
            i += 1
            while i < n:
                c2 = rhs[i]
                if c2 == "\\" and i + 1 < n:
                    i += 2
                    continue
                if c2 == "`":
                    return None
                if c2 == chr(36) and i + 1 < n and rhs[i + 1] == "(":
                    return None
                if c2 == '"':
                    i += 1
                    break
                i += 1
            else:
                return None
            continue
        if ch == "\\":
            if i + 1 >= n:
                return None
            i += 2
            continue
        i += 1
    word = rhs[:i]
    tail = rhs[i:]
    if not word:
        return None
    if tail:
        if not tail[0].isspace():
            return None
        tail_s = tail.strip()
        if tail_s and not tail_s.startswith("#"):
            return None
    try:
        vals = shlex.split(word)
    except ValueError:
        vals = [word.strip("'\"")]
    return name, vals or [""]


def _strip_single_quoted_literals(line: str) -> str:
    """Replaces single-quoted shell string literal contents with empty quotes."""
    out: list[str] = []
    n = len(line)
    i = 0
    in_dq = False
    while i < n:
        ch = line[i]
        if in_dq:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_dq = False
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(ch)
            out.append(line[i + 1])
            i += 2
            continue
        if ch == '"':
            in_dq = True
            out.append(ch)
            i += 1
            continue
        if ch == chr(36) and i + 1 < n and line[i + 1] == "'":
            out.append(chr(36) + "''")
            i += 2
            while i < n:
                if line[i] == "\\" and i + 1 < n:
                    i += 2
                    continue
                if line[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        if ch == "'":
            out.append("''")
            i += 1
            while i < n and line[i] != "'":
                i += 1
            if i < n:
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)
CONTROL_FLOW_SKIP_RE = re.compile(
    r"^(?:\{|\}|do|done|then|else|fi|esac|(?:while|until|if|elif)\s+.+?;\s*(?:do|then)|case\s+.+\s+in)$"
)


def _parse_for_items(raw_items: str) -> list[str]:
    cleaned = raw_items.strip().rstrip(";").strip()
    try:
        tokens = shlex.split(cleaned)
    except ValueError:
        tokens = [t.strip("'\"") for t in cleaned.split() if t.strip("'\"")]
    return [t for t in tokens if t]


def _expand_sh_vars(target: str, sh_vars: dict[str, list[str]]) -> list[str]:
    clean = target.strip().strip('"').strip("'")
    for var_name, vals in sh_vars.items():
        pat = re.compile(rf"\$\{{?{re.escape(var_name)}\}}?")
        if pat.search(clean) and vals:
            return [pat.sub(v, clean) for v in vals]
    return [clean]


def _add_unique(items: list[str], val: str, limit: int | None = None) -> None:
    clean = val.strip()
    if clean and clean not in items and (limit is None or len(items) < limit):
        items.append(clean)


def _has_trailing_continuation(line: str) -> bool:
    stripped = line.rstrip()
    if not stripped or stripped.lstrip().startswith("#"):
        return False
    bs = 0
    for ch in reversed(stripped):
        if ch == "\\":
            bs += 1
        else:
            break
    return (bs % 2) == 1


def _has_unquoted_redirect(cmd: str) -> bool:
    in_sq = False
    in_dq = False
    escaped = False
    for ch in cmd:
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_sq:
            escaped = True
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            continue
        if ch == ">" and not in_sq and not in_dq:
            return True
    return False


def _advance_quote_state(
    line: str,
    state: str | None,
    *,
    is_powershell: bool = False,
) -> str | None:
    """Tracks open single/ANSI-C/double quote state across a physical line."""
    esc = "`" if is_powershell else "\\"
    n = len(line)
    i = 0
    while i < n:
        ch = line[i]
        if state is None:
            if ch == "#" and (i == 0 or line[i - 1].isspace() or line[i - 1] in ";|&()"):
                break
            if ch == esc:
                i += 2
                continue
            if not is_powershell and ch == chr(36) and i + 1 < n and line[i + 1] == "'":
                state = chr(36) + "'"
                i += 2
                continue
            if ch == "'":
                state = "'"
                i += 1
                continue
            if ch == '"':
                state = '"'
                i += 1
                continue
            i += 1
        elif state == "'":
            if ch == "'":
                state = None
            i += 1
        elif state == chr(36) + "'":
            if ch == "\\":
                i += 2
                continue
            if ch == "'":
                state = None
            i += 1
        else:  # state == '"'
            if ch == esc:
                i += 2
                continue
            if ch == '"':
                state = None
            i += 1
    return state


def _iter_logical_lines(script_text: str) -> list[tuple[int, str]]:
    """Joins shell line continuations and multiline quoted strings outside heredocs and python -c blocks."""
    out: list[tuple[int, str]] = []
    eof_token: str | None = None
    py_quote: str | None = None
    quote_state: str | None = None
    cont_buf: list[str] = []
    cont_start: int = 0

    for idx, raw in enumerate(script_text.splitlines(), start=1):
        s = raw.strip()
        if eof_token is not None:
            out.append((idx, raw))
            if s == eof_token:
                eof_token = None
            continue
        if py_quote is not None:
            out.append((idx, raw))
            if s == py_quote or (s.endswith(py_quote) and not s.endswith("\\" + py_quote)):
                py_quote = None
            continue

        if quote_state is not None:
            quote_state = _advance_quote_state(raw, quote_state)
            if quote_state is not None:
                if s:
                    cont_buf.append(s)
                continue
            if _has_trailing_continuation(raw):
                piece = raw.rstrip()[:-1].strip()
                if piece:
                    cont_buf.append(piece)
                continue
            if s:
                cont_buf.append(s)
            logical = " ".join(cont_buf)
            logical_idx = cont_start
            cont_buf = []
        elif cont_buf:
            q_after = _advance_quote_state(raw, None)
            if q_after is not None:
                quote_state = q_after
                if s:
                    cont_buf.append(s)
                continue
            if _has_trailing_continuation(raw):
                piece = raw.rstrip()[:-1].strip()
                if piece:
                    cont_buf.append(piece)
                continue
            if s:
                cont_buf.append(s)
            logical = " ".join(cont_buf)
            logical_idx = cont_start
            cont_buf = []
        else:
            if s and not s.startswith("#"):
                m_pyc_early = PY_DASH_C_START_RE.match(s)
                if m_pyc_early:
                    q_ch, rest = m_pyc_early.group(1), m_pyc_early.group(2)
                    out.append((idx, raw))
                    if not (rest.endswith(q_ch) and not rest.endswith("\\" + q_ch)):
                        py_quote = q_ch
                    continue
                q_after = _advance_quote_state(raw, None)
                if q_after is not None:
                    quote_state = q_after
                    cont_start = idx
                    cont_buf = [raw.rstrip()]
                    continue
            if _has_trailing_continuation(raw):
                cont_start = idx
                first_piece = raw.rstrip()[:-1].rstrip()
                cont_buf = [first_piece] if first_piece else []
                continue
            logical = raw
            logical_idx = idx

        out.append((logical_idx, logical))
        ls = logical.strip()
        if not ls or ls.startswith("#"):
            continue
        m_py = PY_HEREDOC_START_RE.search(ls)
        if m_py:
            eof_token = m_py.group(1)
            continue
        m_pyc = PY_DASH_C_START_RE.match(ls)
        if m_pyc:
            q_ch, rest = m_pyc.group(1), m_pyc.group(2)
            if not (rest.endswith(q_ch) and not rest.endswith("\\" + q_ch)):
                py_quote = q_ch
            continue
        m_sh = SHELL_HEREDOC_START_RE.search(ls)
        if m_sh:
            eof_token = m_sh.group(1)

    if cont_buf:
        out.append((cont_start, " ".join(cont_buf)))
    return out


def _extract_py_path_expr(node: ast.AST, var_map: dict[str, list[str]]) -> list[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.Name):
        return list(var_map.get(node.id, []))
    if isinstance(node, ast.JoinedStr):
        parts: list[list[str]] = []
        for val in node.values:
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                parts.append([val.value])
            elif isinstance(val, ast.FormattedValue):
                sub = _extract_py_path_expr(val.value, var_map)
                if not sub:
                    return []
                parts.append(sub)
            else:
                return []
        acc = [""]
        for group in parts:
            acc = [a + b for a in acc for b in group]
        return acc
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left = _extract_py_path_expr(node.left, var_map)
        right = _extract_py_path_expr(node.right, var_map)
        if right:
            valid_left = [l for l in left if l and not l.startswith("<")]
            if valid_left:
                return [f"{l.rstrip('/')}/{r.lstrip('/')}" for l in valid_left for r in right]
            return right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "Path" and node.args:
            return _extract_py_path_expr(node.args[0], var_map)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "home":
            return ["~"]
    return []


def _extract_py_iter_paths(iter_node: ast.AST, var_map: dict[str, list[str]]) -> list[str]:
    if isinstance(iter_node, (ast.Tuple, ast.List, ast.Set)):
        vals: list[str] = []
        for elt in iter_node.elts:
            vals.extend(_extract_py_path_expr(elt, var_map))
        return vals
    if isinstance(iter_node, ast.Name) and iter_node.id in var_map:
        return list(var_map[iter_node.id])
    return []


def _analyze_python_ast(
    py_code: str,
    writes: list[str],
    reads: list[str],
    execs: list[str],
    py_risks: list[dict[str, object]],
    start_line_offset: int = 0,
) -> None:
    try:
        tree = ast.parse(py_code)
    except Exception:
        return
    var_map: dict[str, list[str]] = {}

    def _visit(node: ast.AST) -> None:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            seq_vals = _extract_py_iter_paths(node.value, var_map)
            if seq_vals:
                var_map[node.targets[0].id] = seq_vals
            else:
                p = _extract_py_path_expr(node.value, var_map)
                if p:
                    var_map[node.targets[0].id] = p
        elif isinstance(node, ast.For):
            if isinstance(node.target, ast.Name):
                items = _extract_py_iter_paths(node.iter, var_map)
                if items:
                    var_map[node.target.id] = items
            elif isinstance(node.target, (ast.Tuple, ast.List)) and isinstance(node.iter, (ast.Tuple, ast.List)):
                names = [elt.id if isinstance(elt, ast.Name) else "" for elt in node.target.elts]
                if any(names):
                    buckets: dict[str, list[str]] = {n: [] for n in names if n}
                    for row in node.iter.elts:
                        if isinstance(row, (ast.Tuple, ast.List)) and len(row.elts) == len(names):
                            for n, cell in zip(names, row.elts):
                                if n:
                                    buckets[n].extend(_extract_py_path_expr(cell, var_map))
                    for n, vals in buckets.items():
                        if vals:
                            var_map[n] = vals

        if isinstance(node, ast.Call):
            unparsed = ast.unparse(node) if hasattr(ast, "unparse") else ""
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                owners = _extract_py_path_expr(node.func.value, var_map)
                mod_name = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
                if attr in ("write_text", "write_bytes"):
                    if owners:
                        for o in owners:
                            _add_unique(writes, o)
                    else:
                        _add_unique(writes, "file (python)")
                elif attr in ("read_text", "read_bytes") and owners:
                    for o in owners:
                        _add_unique(reads, o)
                elif attr == "parse" and mod_name == "ast":
                    _add_unique(execs, "ast.parse")
                elif mod_name in ("shutil", "os") and attr in ("copy", "copy2", "move", "replace") and len(node.args) >= 2:
                    dsts = _extract_py_path_expr(node.args[-1], var_map)
                    if dsts:
                        for d in dsts:
                            _add_unique(writes, d)
                    else:
                        _add_unique(writes, f"{mod_name}.{attr}")
                elif (
                    (mod_name == "shutil" and attr == "rmtree")
                    or (mod_name == "os" and attr in ("remove", "unlink", "rmdir", "system"))
                    or (attr in ("unlink", "rmdir") and mod_name not in ("shutil", "os"))
                ):
                    if mod_name in ("shutil", "os"):
                        targets = _extract_py_path_expr(node.args[0], var_map) if node.args else []
                    else:
                        targets = owners
                    if targets:
                        for t in targets:
                            _add_unique(writes, f"{attr}({t})")
                    else:
                        _add_unique(writes, f"{attr}(...)")
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "fs-destructive",
                        "description": "destructive Python call",
                        "snippet": unparsed or (f"{mod_name}.{attr}(...)" if mod_name else f"{attr}(...)"),
                    })
                elif mod_name == "subprocess" and attr in ("run", "Popen", "call", "check_call", "check_output"):
                    _add_unique(execs, f"subprocess.{attr}")
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "remote-exec",
                        "description": "Python subprocess execution",
                        "snippet": unparsed or f"subprocess.{attr}(...)",
                    })
                elif mod_name == "os" and attr in ("popen", "execl", "execle", "execlp", "execv", "execve", "execvp", "spawnl", "spawnv"):
                    _add_unique(execs, f"os.{attr}")
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "remote-exec",
                        "description": "Python process execution",
                        "snippet": unparsed or f"os.{attr}(...)",
                    })
                elif attr in ("urlopen", "urlretrieve") or (mod_name == "socket" and attr in ("connect", "create_connection")):
                    _add_unique(execs, f"{mod_name or 'net'}.{attr}")
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "net-write",
                        "description": "Python network call",
                        "snippet": unparsed or f"{attr}(...)",
                    })
            elif isinstance(node.func, ast.Name):
                fn_id = node.func.id
                if fn_id == "open" and len(node.args) >= 2:
                    mode_node = node.args[1]
                    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
                        if any(m in mode_node.value for m in ("w", "a", "x")):
                            targets = _extract_py_path_expr(node.args[0], var_map)
                            if targets:
                                for t in targets:
                                    _add_unique(writes, t)
                            else:
                                _add_unique(writes, "open(..., 'w')")
                elif fn_id in ("eval", "exec", "__import__"):
                    _add_unique(execs, fn_id)
                    py_risks.append({
                        "line": start_line_offset + getattr(node, "lineno", 1),
                        "category": "remote-exec",
                        "description": f"dynamic Python {fn_id}()",
                        "snippet": unparsed or f"{fn_id}(...)",
                    })

        for child in ast.iter_child_nodes(node):
            _visit(child)

    _visit(tree)


def summarize_script_actions(script_text: str, work_dir: Path | None = None) -> dict[str, object]:
    wdir = work_dir if work_dir is not None else get_work_dir()
    lines = script_text.splitlines()
    non_empty = [l for l in lines if l.strip()]
    writes: list[str] = []
    reads: list[str] = []
    git_cmds: list[str] = []
    exec_cmds: list[str] = []
    cd_dirs: list[str] = []
    operations: list[tuple[str, str]] = []
    operation_groups: list[tuple[str, list[tuple[str, str]]]] = []
    operation_steps: list[dict[str, object]] = []
    cur_group_dir = ""
    dir_stack: list[str] = []
    sh_vars: dict[str, list[str]] = {}

    home_str = str(Path.home())
    abs_home_prefixes = [home_str]
    for pfx in ("/home", "/Users"):
        if pfx not in abs_home_prefixes:
            abs_home_prefixes.append(pfx)
    abs_home_re = re.compile(
        r"(?:(?:"
        + "|".join(re.escape(p) for p in abs_home_prefixes)
        + r")/[A-Za-z0-9._-]+|(?:"
        + re.escape(home_str)
        + r"))(?:/[A-Za-z0-9._-]+)+"
    )

    def _resolve_external_repo_dir(token: str) -> str | None:
        clean = token.strip().strip("'\"")
        if not clean:
            return None
        w_res = wdir.resolve()
        w_parent = w_res.parent

        def _is_external(cand: str) -> bool:
            try:
                exp = os.path.expanduser(cand.replace("$HOME", home_str))
                res = (wdir / exp).resolve()
                return res != w_res and res != w_parent
            except Exception:
                return True

        parts = clean.split("/")
        if len(parts) >= 2 and parts[0] in ("$HOME", "~", ".."):
            cand1 = f"{parts[0]}/{parts[1]}"
            try:
                exp1 = os.path.expanduser(cand1.replace("$HOME", home_str))
                res1 = (wdir / exp1).resolve()
                if res1 == w_parent and len(parts) >= 3:
                    cand2 = f"{cand1}/{parts[2]}"
                    if _is_external(cand2):
                        return cand2
                if _is_external(cand1):
                    return cand1
            except Exception:
                return cand1
            return None

        if clean.startswith("/"):
            m_abs = abs_home_re.search(clean)
            if m_abs:
                matched = m_abs.group(0)
                aparts = matched.split("/")
                if len(aparts) >= 4 and aparts[1] in ("home", "Users"):
                    cand1 = "/".join(aparts[:4])
                    try:
                        res1 = Path(cand1).resolve()
                        if res1 == w_parent and len(aparts) >= 5:
                            cand2 = "/".join(aparts[:5])
                            if _is_external(cand2):
                                return cand2
                        if _is_external(cand1):
                            return cand1
                    except Exception:
                        return cand1
                elif home_str != "/" and matched.startswith(home_str.rstrip("/") + "/"):
                    h_parts = home_str.rstrip("/").split("/")
                    if len(aparts) > len(h_parts):
                        cand1 = "/".join(aparts[: len(h_parts) + 1])
                        if _is_external(cand1):
                            return cand1
        return None

    def _infer_op_dir(cmd_str: str) -> tuple[str, str]:
        m_cwd_env = re.match(
            r'^([A-Za-z_][A-Za-z0-9_]*_CWD)=("[^"]+"|\'[^\']+\'|[^\s;|&#()]+)\s+(.+)$',
            cmd_str,
        )
        if m_cwd_env:
            raw_cwd = m_cwd_env.group(2).strip("'\"")
            rest_cmd = m_cwd_env.group(3)
            expanded_cwd = _expand_sh_vars(raw_cwd, sh_vars)
            target_cwd = ", ".join(expanded_cwd)
            try:
                exp0 = os.path.expanduser(expanded_cwd[0].replace("$HOME", home_str))
                if (wdir / exp0).resolve() != wdir.resolve():
                    return target_cwd, rest_cmd
            except Exception:
                return target_cwd, rest_cmd
        if cur_group_dir:
            return cur_group_dir, cmd_str
        m_git_c = re.match(r"^git\s+-C\s+([^\s]+)\s+(.+)$", cmd_str)
        if m_git_c:
            expanded_d = _expand_sh_vars(m_git_c.group(1), sh_vars)
            return ", ".join(expanded_d), f"git {m_git_c.group(2)}"
        tokens = re.findall(
            r"(?:\$HOME|~|\.\.|/home/[A-Za-z0-9._-]+|/Users/[A-Za-z0-9._-]+|"
            + re.escape(home_str)
            + r")(?:/[^\s'\";|&]+)+",
            cmd_str,
        )
        if tokens:
            ext_dir = _resolve_external_repo_dir(tokens[0])
            if ext_dir:
                short_cmd = (
                    cmd_str.replace(f"{ext_dir}/", "")
                    .replace(f'"{ext_dir}"', ".")
                    .replace(f"'{ext_dir}'", ".")
                    .replace(ext_dir, ".")
                )
                return ext_dir, short_cmd
        return cur_group_dir, cmd_str

    def _append_group_item(g_dir: str, tag: str, short_desc: str) -> None:
        if not operation_groups or operation_groups[-1][0] != g_dir:
            operation_groups.append((g_dir, [(tag, short_desc)]))
        else:
            operation_groups[-1][1].append((tag, short_desc))

    def add_op(tag: str, desc: str, line: int = 0) -> None:
        operations.append((tag, desc))
        g_dir, short_desc = _infer_op_dir(desc) if tag in ("read", "write", "git", "exec") else (cur_group_dir, desc)
        _append_group_item(g_dir, tag, short_desc)
        operation_steps.append(
            {
                "step": len(operation_steps) + 1,
                "line": line,
                "tag": tag,
                "desc": desc,
                "dir": g_dir,
            }
        )

    py_blocks = 0
    py_eof: str | None = None
    py_quote: str | None = None
    py_buf: list[str] = []
    py_start = 0
    sh_eof: str | None = None

    def _py_item_dir_and_rel(item: str) -> tuple[str, str]:
        m_del = re.match(r"^([a-z_]+)\((.+)\)$", item)
        prefix = f"{m_del.group(1)}(" if m_del else ""
        suffix = ")" if m_del else ""
        raw_p = m_del.group(2) if m_del else item
        if raw_p in ("file (python)", "open(..., 'w')", "..."):
            return cur_group_dir, item
        ext_dir = _resolve_external_repo_dir(raw_p)
        if ext_dir:
            rel = raw_p[len(ext_dir) :].lstrip("/") or "."
            return ext_dir, f"{prefix}{rel}{suffix}"
        if cur_group_dir:
            return cur_group_dir, item
        p_norm = raw_p.removeprefix("./")
        if "/" in p_norm and not p_norm.startswith("/"):
            parent, name = p_norm.rsplit("/", 1)
            return parent, f"{prefix}{name}{suffix}"
        return "", item

    def _format_py_items(items: list[str], max_shown: int = 8) -> str:
        if len(items) <= max_shown:
            return ", ".join(items)
        shown = ", ".join(items[:max_shown])
        rem = len(items) - max_shown
        return f"{shown} (+{rem} more, {len(items)} total)"

    def _emit_py_op(buf_lines: list[str], start_line: int) -> None:
        pw: list[str] = []
        pr: list[str] = []
        pe: list[str] = []
        _analyze_python_ast("\n".join(buf_lines), pw, pr, pe, [], start_line)
        for x in pw:
            _add_unique(writes, x)
        for x in pr:
            _add_unique(reads, x)
        for x in pe:
            _add_unique(exec_cmds, x)

        dir_buckets: dict[str, dict[str, list[str]]] = {}
        for kind, raw_list in (("write", pw), ("read", pr)):
            for entry in raw_list:
                g_dir, rel_entry = _py_item_dir_and_rel(entry)
                bucket = dir_buckets.setdefault(g_dir, {"write": [], "read": []})
                if rel_entry not in bucket[kind]:
                    bucket[kind].append(rel_entry)

        n_lines = len([ln for ln in buf_lines if ln.strip()]) or len(buf_lines) or 1
        total_paths = len(pw) + len(pr)
        has_external = any(bool(d) and d != cur_group_dir for d in dir_buckets)
        if len(dir_buckets) > 1 or has_external or total_paths > 8:
            head_desc = f"{n_lines} line{'s' if n_lines != 1 else ''}" + (
                f" — calls: {', '.join(pe)}" if pe else ""
            )
            add_op("python", head_desc, line=start_line)
            for g_dir, bucket in dir_buckets.items():
                for kind in ("write", "read"):
                    k_items = bucket[kind]
                    if not k_items:
                        continue
                    formatted = _format_py_items(k_items)
                    op_text = f"{g_dir}: {formatted}" if (g_dir and g_dir != cur_group_dir) else formatted
                    operations.append((kind, op_text))
                    _append_group_item(g_dir, kind, formatted)
            return

        parts = []
        if pw:
            parts.append("writes: " + _format_py_items(pw))
        if pr:
            parts.append("reads: " + _format_py_items(pr))
        if pe:
            parts.append("calls: " + ", ".join(pe))
        desc = f"{n_lines} line{'s' if n_lines != 1 else ''}" + (f" — {'; '.join(parts)}" if parts else "")
        add_op("python", desc, line=start_line)
    sh_cmd: str = ""
    sh_lines: int = 0
    sh_start: int = 0

    for idx, raw in _iter_logical_lines(script_text):
        s = raw.strip()
        if py_eof is not None:
            if s == py_eof:
                _emit_py_op(py_buf, py_start)
                py_eof = None
                py_buf = []
            else:
                py_buf.append(raw)
            continue
        if py_quote is not None:
            if s == py_quote or (s.endswith(py_quote) and not s.endswith("\\" + py_quote)):
                if s != py_quote:
                    py_buf.append(raw.rstrip()[:-1])
                _emit_py_op(py_buf, py_start)
                py_quote = None
                py_buf = []
            else:
                py_buf.append(raw)
            continue
        if sh_eof is not None:
            if s == sh_eof:
                line_lbl = f"{sh_lines} line{'s' if sh_lines != 1 else ''}"
                m_redir = HEREDOC_REDIRECT_TARGET_RE.search(sh_cmd)
                if m_redir:
                    target_f = m_redir.group(1).strip("'\"")
                    _add_unique(writes, target_f)
                    add_op("write", f"{sh_cmd} ({line_lbl})", line=sh_start)
                elif re.match(r"^git\s+", sh_cmd):
                    _add_unique(git_cmds, sh_cmd)
                    add_op("git", f"{sh_cmd} ({line_lbl})", line=sh_start)
                else:
                    _add_unique(exec_cmds, sh_cmd)
                    add_op("exec", f"{sh_cmd} ({line_lbl})", line=sh_start)
                sh_eof = None
                sh_cmd = ""
                sh_lines = 0
                sh_start = 0
            else:
                sh_lines += 1
            continue
        if not s or s.startswith("#"):
            continue
        m_py = PY_HEREDOC_START_RE.search(s)
        if m_py:
            py_blocks += 1
            py_eof = m_py.group(1)
            py_buf = []
            py_start = idx
            continue
        m_pyc = PY_DASH_C_START_RE.match(s)
        if m_pyc:
            py_blocks += 1
            q_ch, rest = m_pyc.group(1), m_pyc.group(2)
            if rest.endswith(q_ch) and not rest.endswith("\\" + q_ch):
                _emit_py_op([rest[:-1]], idx)
            else:
                py_quote = q_ch
                py_buf = [rest] if rest.strip() else []
                py_start = idx
            continue
        m_sh = SHELL_HEREDOC_START_RE.search(s)
        if m_sh:
            sh_eof = m_sh.group(1)
            sh_cmd = s
            sh_lines = 0
            sh_start = idx
            continue
        if re.match(r"^(?:echo|printf)\b", s) and not _has_unquoted_redirect(s):
            continue
        if re.match(r"^set\s+[+-][A-Za-z]", s):
            continue
        if s == "(":
            dir_stack.append(cur_group_dir)
            continue
        if s == ")":
            cur_group_dir = dir_stack.pop() if dir_stack else ""
            continue
        m_for = FOR_LOOP_RE.match(s)
        if m_for:
            items = _parse_for_items(m_for.group(2))
            if items:
                sh_vars[m_for.group(1)] = items
            continue
        parsed_var = _parse_var_assignment(s)
        if parsed_var is not None:
            sh_vars[parsed_var[0]] = parsed_var[1]
            continue
        if CONTROL_FLOW_SKIP_RE.match(s):
            continue
        m_cd = re.match(r"^cd\s+(.+)$", s)
        if m_cd:
            expanded_targets = _expand_sh_vars(m_cd.group(1), sh_vars)
            if len(expanded_targets) > 1:
                cur_group_dir = ", ".join(expanded_targets)
                for t in expanded_targets:
                    _add_unique(cd_dirs, t)
            else:
                raw_target = expanded_targets[0]
                cur_group_dir = raw_target
                try:
                    exp_path = os.path.expanduser(raw_target.replace("$HOME", str(Path.home())))
                    resolved_cd = (wdir / exp_path).resolve()
                    if resolved_cd != wdir.resolve():
                        _add_unique(cd_dirs, raw_target)
                    else:
                        cur_group_dir = ""
                except Exception:
                    _add_unique(cd_dirs, raw_target)
            continue
        if re.match(r"^git\s+", s):
            _add_unique(git_cmds, s)
            add_op("git", s, line=idx)
            continue
        if re.match(r"^(?:rm|cp|mv|mkdir|chmod|touch)\s+", s):
            _add_unique(writes, s)
            add_op("write", s, line=idx)
            continue
        if re.match(r"^(?:cat|nl|grep|ls|head|tail|find|which|command\s+-v|wc|stat|file|sed\s+-n)\s+", s):
            _add_unique(reads, s)
            add_op("read", s, line=idx)
            continue
        add_op("exec", s, line=idx)
        _add_unique(exec_cmds, s)

    rows: list[tuple[str, str]] = []
    for label, bucket in (
        ("write", writes),
        ("read", reads),
        ("git", git_cmds),
        ("exec", exec_cmds),
    ):
        if bucket:
            rows.append((label, ", ".join(bucket)))
    sh_tag = "pwsh" if _is_powershell() else "bash"
    meta = f"{len(non_empty)} line{'s' if len(non_empty) != 1 else ''}"
    if py_blocks:
        meta += f", {sh_tag} + {py_blocks} python block{'s' if py_blocks != 1 else ''}"
    else:
        meta += f", {sh_tag}"
    if get_setting("token_stats")[0] != "false":
        fn_stats = globals().get("format_stats")
        if callable(fn_stats):
            stats_s = str(fn_stats(script_text.encode("utf-8")))
            if " · " in stats_s:
                meta += " · " + stats_s.split(" · ", 1)[1]
    return {
        "meta": meta,
        "rows": rows,
        "operations": operations,
        "operation_groups": operation_groups,
        "operation_steps": operation_steps,
        "cd_dirs": cd_dirs,
        "work_dir": str(wdir),
    }

def _bash_compound_delta(line: str) -> tuple[int, int, bool]:
    """Returns (opens, closes, starts_with_closer) for bash control-flow keywords outside quotes/comments."""
    in_sq = False
    in_dq = False
    escaped = False
    cleaned: list[str] = []
    for ch in line:
        if escaped:
            cleaned.append(" ")
            escaped = False
            continue
        if ch == "\\" and not in_sq:
            cleaned.append(" ")
            escaped = True
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            cleaned.append(" ")
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            cleaned.append(" ")
            continue
        if ch == "#" and not in_sq and not in_dq:
            break
        cleaned.append(" " if (in_sq or in_dq) else ch)

    s = "".join(cleaned).strip()
    if not s:
        return 0, 0, False
    starts_closer = bool(re.match(r"^(?:fi|done|esac|elif|else|\}|\))\b", s))
    opens = 0
    closes = 0
    cmd_pos = True
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in (";", "|", "&", "{", "("):
            if ch == ";" and i + 1 < n and s[i + 1] == ";":
                i += 2
            elif ch in ("|", "&") and i + 1 < n and s[i + 1] == ch:
                i += 2
            else:
                i += 1
            cmd_pos = True
            continue
        if ch in ("}", ")"):
            i += 1
            cmd_pos = True
            continue
        m_word = re.match(r"[A-Za-z_][A-Za-z0-9_]*", s[i:])
        if m_word:
            word = m_word.group(0)
            if cmd_pos:
                if word in ("if", "for", "while", "until", "case"):
                    opens += 1
                elif word in ("fi", "done", "esac"):
                    closes += 1
                cmd_pos = word in ("then", "do", "else")
            i += len(word)
            continue
        cmd_pos = False
        i += 1
    return opens, closes, starts_closer


def _pwsh_brace_delta(line: str) -> tuple[int, int, bool]:
    """Returns (opens, closes, starts_with_closer) for PowerShell braces outside quotes/comments."""
    in_sq = False
    in_dq = False
    escaped = False
    opens = 0
    closes = 0
    first_non_ws = ""
    for ch in line:
        if not first_non_ws and not ch.isspace():
            first_non_ws = ch
        if escaped:
            escaped = False
            continue
        if ch == "`" and not in_sq:
            escaped = True
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            continue
        if ch == "#" and not in_sq and not in_dq:
            break
        if not in_sq and not in_dq:
            if ch == "{":
                opens += 1
            elif ch == "}":
                closes += 1
    starts_closer = first_non_ws == "}" or bool(re.match(r"^(?:elseif|else|catch|finally)\b", line.strip(), re.IGNORECASE))
    return opens, closes, starts_closer


def instrument_script_for_progress(
    script_text: str,
    step_lines: list[dict[str, object]] | None = None,
    *,
    is_powershell: bool | None = None,
    marker_prefix: str = "__RB_STEP__:",
) -> str:
    """Returns an instrumented script copy emitting step markers before top-level operations."""
    steps = (
        step_lines
        if step_lines is not None
        else list(summarize_script_actions(script_text).get("operation_steps") or [])
    )
    line_to_step: dict[int, int] = {}
    for item in steps:
        ln = int(item.get("line") or 0)
        st = int(item.get("step") or 0)
        if ln > 0 and st > 0 and ln not in line_to_step:
            line_to_step[ln] = st
    if not line_to_step:
        return script_text

    ps_mode = _is_powershell() if is_powershell is None else bool(is_powershell)
    out: list[str] = []
    eof_token: str | None = None
    py_quote: str | None = None
    ps_here_quote: str | None = None
    in_continuation = False
    quote_state: str | None = None
    depth = 0

    for idx, raw_line in enumerate(script_text.splitlines(keepends=True), start=1):
        line_no_nl = raw_line.rstrip("\r\n")
        s = line_no_nl.strip()

        if ps_here_quote is not None:
            out.append(raw_line)
            if line_no_nl.startswith(ps_here_quote):
                ps_here_quote = None
            continue

        if eof_token is not None:
            out.append(raw_line)
            if s == eof_token:
                eof_token = None
            continue

        if py_quote is not None:
            out.append(raw_line)
            if s == py_quote or (s.endswith(py_quote) and not s.endswith("\\" + py_quote)):
                py_quote = None
            continue

        if quote_state is not None:
            out.append(raw_line)
            quote_state = _advance_quote_state(line_no_nl, quote_state, is_powershell=ps_mode)
            if quote_state is None:
                if ps_mode:
                    in_continuation = line_no_nl.rstrip().endswith("`")
                else:
                    in_continuation = _has_trailing_continuation(line_no_nl)
            continue

        if in_continuation:
            out.append(raw_line)
            q_after = _advance_quote_state(line_no_nl, None, is_powershell=ps_mode)
            if q_after is not None:
                quote_state = q_after
                in_continuation = False
                continue
            if ps_mode:
                in_continuation = line_no_nl.rstrip().endswith("`")
            else:
                in_continuation = _has_trailing_continuation(line_no_nl)
            continue

        if ps_mode:
            opens, closes, starts_closer = _pwsh_brace_delta(line_no_nl)
        else:
            opens, closes, starts_closer = _bash_compound_delta(line_no_nl)

        if idx in line_to_step and depth == 0 and not starts_closer:
            step_num = line_to_step[idx]
            indent = line_no_nl[: len(line_no_nl) - len(line_no_nl.lstrip(" \t"))]
            if ps_mode:
                out.append(f"{indent}Write-Output '{marker_prefix}{step_num}'\n")
            else:
                out.append(f"{indent}printf '%s\\n' '{marker_prefix}{step_num}'\n")

        out.append(raw_line)

        if not s or s.startswith("#"):
            continue

        if ps_mode:
            if s.endswith("@'") and not s.startswith("#"):
                ps_here_quote = "'@"
                continue
            if s.endswith('@"') and not s.startswith("#"):
                ps_here_quote = '"@'
                continue
            q_after = _advance_quote_state(line_no_nl, None, is_powershell=True)
            if q_after is not None:
                quote_state = q_after
                depth = max(0, depth + opens - closes)
                continue
            if line_no_nl.rstrip().endswith("`"):
                in_continuation = True
                continue
        else:
            m_py = PY_HEREDOC_START_RE.search(s)
            if m_py:
                eof_token = m_py.group(1)
                depth = max(0, depth + opens - closes)
                continue
            m_pyc = PY_DASH_C_START_RE.match(s)
            if m_pyc:
                q_ch, rest = m_pyc.group(1), m_pyc.group(2)
                if not (rest.endswith(q_ch) and not rest.endswith("\\" + q_ch)):
                    py_quote = q_ch
                    depth = max(0, depth + opens - closes)
                    continue
            m_sh = SHELL_HEREDOC_START_RE.search(s)
            if m_sh:
                eof_token = m_sh.group(1)
                depth = max(0, depth + opens - closes)
                continue
            q_after = _advance_quote_state(line_no_nl, None, is_powershell=False)
            if q_after is not None:
                quote_state = q_after
                depth = max(0, depth + opens - closes)
                continue
            if _has_trailing_continuation(line_no_nl):
                in_continuation = True
                continue

        depth = max(0, depth + opens - closes)

    return "".join(out)



def scan_script_risks(script_text: str) -> list[dict[str, object]]:
    active_rules = get_active_risk_rules()
    active_cats = {cat for cat, _, _ in active_rules}
    findings: list[dict[str, object]] = []
    py_eof_token: str | None = None
    py_quote_token: str | None = None
    py_buf: list[str] = []
    py_start = 0
    sh_eof_token: str | None = None
    sh_scan_body: bool = False
    cur_cd_dir: str = ""
    cd_stack: list[str] = []
    sh_vars: dict[str, list[str]] = {}
    for idx, raw_line in _iter_logical_lines(script_text):
        stripped = raw_line.strip()
        if py_eof_token is not None:
            if stripped == py_eof_token:
                py_f: list[dict[str, object]] = []
                _analyze_python_ast("\n".join(py_buf), [], [], [], py_f, py_start)
                for pf in py_f:
                    if str(pf.get("category")) in active_cats:
                        if cur_cd_dir:
                            pf = {**pf, "snippet": f"{pf['snippet']}  (in {cur_cd_dir})"}
                        findings.append(pf)
                py_eof_token = None
                py_buf = []
            else:
                py_buf.append(raw_line)
            continue
        if py_quote_token is not None:
            if stripped == py_quote_token or (stripped.endswith(py_quote_token) and not stripped.endswith("\\" + py_quote_token)):
                if stripped != py_quote_token:
                    py_buf.append(raw_line.rstrip()[:-1])
                py_f2: list[dict[str, object]] = []
                _analyze_python_ast("\n".join(py_buf), [], [], [], py_f2, py_start)
                for pf in py_f2:
                    if str(pf.get("category")) in active_cats:
                        if cur_cd_dir:
                            pf = {**pf, "snippet": f"{pf['snippet']}  (in {cur_cd_dir})"}
                        findings.append(pf)
                py_quote_token = None
                py_buf = []
            else:
                py_buf.append(raw_line)
            continue
        if sh_eof_token is not None:
            if stripped == sh_eof_token:
                sh_eof_token = None
                sh_scan_body = False
                continue
            if not sh_scan_body:
                continue

        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "(":
            cd_stack.append(cur_cd_dir)
            continue
        if stripped == ")":
            cur_cd_dir = cd_stack.pop() if cd_stack else ""
            continue
        m_for = FOR_LOOP_RE.match(stripped)
        if m_for:
            items = _parse_for_items(m_for.group(2))
            if items:
                sh_vars[m_for.group(1)] = items
            continue
        parsed_var = _parse_var_assignment(stripped)
        if parsed_var is not None:
            sh_vars[parsed_var[0]] = parsed_var[1]
            for category, desc, pat in active_rules:
                if category not in ("unicode-spoof", "secrets-exposure"):
                    continue
                if pat.search(stripped):
                    clean_snip = re.sub(r"\s+", " ", stripped).replace("│", "|")
                    if cur_cd_dir and "-C " not in clean_snip:
                        clean_snip = f"{clean_snip}  (in {cur_cd_dir})"
                    findings.append(
                        {
                            "line": idx,
                            "category": category,
                            "description": desc,
                            "snippet": clean_snip,
                        }
                    )
                    break
            continue
        m_cd = re.match(r"^cd\s+(.+)$", stripped)
        if m_cd:
            cur_cd_dir = ", ".join(_expand_sh_vars(m_cd.group(1), sh_vars))
            continue
        m_py = PY_HEREDOC_START_RE.search(stripped)
        if m_py:
            py_eof_token = m_py.group(1)
            py_buf = []
            py_start = idx
            continue
        m_pyc = PY_DASH_C_START_RE.match(stripped)
        if m_pyc:
            q_ch, rest = m_pyc.group(1), m_pyc.group(2)
            if rest.endswith(q_ch) and not rest.endswith("\\" + q_ch):
                py_f_inline: list[dict[str, object]] = []
                _analyze_python_ast(rest[:-1], [], [], [], py_f_inline, idx)
                for pf in py_f_inline:
                    if str(pf.get("category")) in active_cats:
                        if cur_cd_dir:
                            pf = {**pf, "snippet": f"{pf['snippet']}  (in {cur_cd_dir})"}
                        findings.append(pf)
            else:
                py_quote_token = q_ch
                py_buf = [rest] if rest.strip() else []
                py_start = idx
            continue
        if sh_eof_token is None:
            m_sh = SHELL_HEREDOC_START_RE.search(stripped)
            if m_sh:
                sh_eof_token = m_sh.group(1)
                sh_scan_body = bool(re.search(r"\b(?:sh|bash|zsh|sudo|eval)\b", stripped))
        cmd_view = _strip_single_quoted_literals(stripped)
        has_sq_shell_exec = bool(_SHELL_EXEC_CMD_RE.search(cmd_view))
        for category, desc, pat in active_rules:
            target_line = (
                stripped
                if (has_sq_shell_exec or category in ("unicode-spoof", "secrets-exposure"))
                else cmd_view
            )
            if pat.search(target_line):
                clean_snip = re.sub(r"\s+", " ", stripped).replace("│", "|")
                if cur_cd_dir and "-C " not in clean_snip:
                    clean_snip = f"{clean_snip}  (in {cur_cd_dir})"
                findings.append(
                    {
                        "line": idx,
                        "category": category,
                        "description": desc,
                        "snippet": clean_snip,
                    }
                )
                break
    deduped: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for f in findings:
        pair = (str(f["category"]), str(f["snippet"]))
        if pair not in seen_pairs:
            seen_pairs.add(pair)
            deduped.append(f)
    return deduped


def check_script_syntax(script_text: str, work_dir: Path | None = None) -> tuple[bool, str | None, int]:
    wdir = work_dir if work_dir is not None else get_work_dir()
    shell_bin, _ = get_setting("shell")
    is_ps = _is_powershell(shell_bin)
    ext = ".ps1" if is_ps else ".sh"
    fd, tmp_name = tempfile.mkstemp(prefix="rb_chk_", suffix=ext)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_text)
        if is_ps:
            ps_check = (
                "$err = $null; "
                "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0], [ref]$null, [ref]$err); "
                "if ($err) { foreach ($e in $err) { [Console]::Error.WriteLine($e.ToString()) }; exit 1 }"
            )
            chk_cmd = [shell_bin, "-NoProfile", "-NonInteractive", "-Command", ps_check, str(tmp_path)]
        else:
            chk_cmd = [shell_bin, "-n", str(tmp_path)]
        chk = subprocess.run(
            chk_cmd,
            cwd=wdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if chk.returncode != 0:
            return False, (chk.stdout or "syntax check failed").strip(), chk.returncode
        return True, None, 0
    finally:
        tmp_path.unlink(missing_ok=True)


def analyze_script(
    script_text: str,
    work_dir: Path | None = None,
    label: str | None = None,
    check_syntax: bool = True,
) -> dict[str, object]:
    wdir = (work_dir if work_dir is not None else get_work_dir()).resolve()
    summary = summarize_script_actions(script_text, work_dir=wdir)
    findings = scan_script_risks(script_text)
    syntax_ok = True
    syntax_error: str | None = None
    if check_syntax:
        syntax_ok, syntax_error, _ = check_script_syntax(script_text, work_dir=wdir)
    return {
        "label": label or "",
        "syntax_ok": syntax_ok,
        "syntax_error": syntax_error,
        "work_dir": str(wdir),
        "meta": summary.get("meta", ""),
        "rows": [list(r) for r in (summary.get("rows") or [])],
        "operations": [list(op) for op in (summary.get("operations") or [])],
        "operation_steps": list(summary.get("operation_steps") or []),
        "operation_groups": [
            [g_dir, [list(op) for op in g_items]]
            for g_dir, g_items in (summary.get("operation_groups") or [])
        ],
        "cd_dirs": list(summary.get("cd_dirs") or []),
        "findings": findings,
        "safe": bool(syntax_ok and len(findings) == 0),
    }


def run_approve_cmd(
    approve_cmd: str,
    label: str,
    script_text: str,
    plan: dict[str, object],
    script_path: Path | None = None,
) -> tuple[str, str]:
    """Runs external approval command. Returns (decision, note) where decision is 'approve', 'prompt', or 'reject'."""
    payload = {
        **plan,
        "label": label,
        "script_path": str(script_path) if script_path is not None else "",
        "script": script_text,
    }
    env = {
        **os.environ,
        "RUN_BLOCK_LABEL": label,
        "RUN_BLOCK_WORKDIR": str(plan.get("work_dir") or ""),
    }
    if script_path is not None:
        env["RUN_BLOCK_SCRIPT"] = str(script_path)
    try:
        proc = subprocess.run(
            approve_cmd,
            shell=True,
            input=json.dumps(payload, ensure_ascii=False) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            check=False,
        )
    except Exception as exc:
        return "reject", f"approve command failed: {exc}"
    note = (proc.stdout or "").strip()
    if proc.returncode == 0:
        return "approve", note
    if proc.returncode == 2:
        return "prompt", note
    return "reject", (note or f"rejected by approve command (exit {proc.returncode})")


def cmd_plan(stdin_text: str) -> int:
    plan = analyze_script(stdin_text, check_syntax=True)
    sys.stdout.write(json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    return 0 if plan.get("syntax_ok") else 1


SAFE_FIX_BUILTINS: dict[str, object] = {
    "AssertionError": AssertionError,
    "Exception": Exception,
    "IndexError": IndexError,
    "KeyError": KeyError,
    "RuntimeError": RuntimeError,
    "TypeError": TypeError,
    "ValueError": ValueError,
    "False": False,
    "None": None,
    "True": True,
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "chr": chr,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "ord": ord,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

FORBIDDEN_FIX_CALLS: set[str] = {
    "__import__",
    "breakpoint",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "hasattr",
    "input",
    "locals",
    "memoryview",
    "open",
    "quit",
    "setattr",
    "type",
    "vars",
}


def validate_fix_ast(fix_code: str) -> tuple[bool, str | None]:
    """Validates that a --fix snippet only performs safe in-memory text/regex transformations."""
    try:
        tree = ast.parse(fix_code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "import statements are not allowed in --fix patches"
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.ClassDef, ast.AsyncFunctionDef)):
            return False, f"{type(node).__name__} is not allowed in --fix patches"
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            return False, f"access to private/dunder attribute {node.attr!r} is not allowed in --fix"
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return False, f"access to dunder name {node.id!r} is not allowed in --fix"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_FIX_CALLS:
                return False, f"call to {node.func.id}() is not allowed in --fix"
    return True, None


SECRET_ENV_RE = re.compile(
    r"^(?:.*_(?:API_KEY|SECRET|SECRET_KEY|TOKEN|PASSWORD|PASSWD|PRIVATE_KEY|CREDENTIAL|CREDENTIALS)|"
    r"AWS_(?:ACCESS_KEY_ID|SECRET_ACCESS_KEY|SESSION_TOKEN)|"
    r"GH_TOKEN|GITHUB_TOKEN|GITLAB_TOKEN|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY)$",
    re.IGNORECASE,
)


def scrub_child_env(env: dict[str, str], sandbox_mode: str) -> dict[str, str]:
    norm = normalize_sandbox_mode(sandbox_mode)
    if norm == "off":
        return env
    cleaned = {k: v for k, v in env.items() if not SECRET_ENV_RE.match(k)}
    if norm == "nonet":
        cleaned.pop("SSH_AUTH_SOCK", None)
        cleaned.pop("SSH_AGENT_PID", None)
    return cleaned


def detect_sandbox_backend() -> str:
    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        return "bwrap"
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        return "sandbox-exec"
    return "env-only"


def build_sandbox_exec(
    exec_cmd: list[str],
    work_dir: Path,
    base_dir: Path,
    sandbox_mode: str,
) -> list[str]:
    norm = normalize_sandbox_mode(sandbox_mode)
    if norm == "off":
        return exec_cmd
    if norm not in ("strict", "nonet"):
        return shlex.split(norm) + list(exec_cmd)

    wdir = work_dir.resolve()
    bdir = base_dir.resolve()
    home = Path.home().resolve()
    secret_rel_subpaths = (".ssh", ".aws", ".gnupg", ".kube", ".config/gh", ".config/gcloud")

    if sys.platform.startswith("linux") and shutil.which("bwrap"):
        cmd: list[str] = [
            "bwrap",
            "--ro-bind", "/", "/",
            "--dev", "/dev",
            "--proc", "/proc",
            "--tmpfs", "/tmp",
            "--die-with-parent",
        ]
        for rel in secret_rel_subpaths:
            sp = home / rel
            if sp.is_dir():
                cmd.extend(["--tmpfs", str(sp)])
        if wdir.exists():
            cmd.extend(["--bind", str(wdir), str(wdir)])
            git_hooks = wdir / ".git" / "hooks"
            if git_hooks.is_dir():
                cmd.extend(["--ro-bind", str(git_hooks), str(git_hooks)])
        if bdir.exists():
            cmd.extend(["--ro-bind", str(bdir), str(bdir)])
        if norm == "nonet":
            cmd.append("--unshare-net")
        cmd.extend(["--", *exec_cmd])
        return cmd

    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        tmp_real = Path(tempfile.gettempdir()).resolve()
        rules = [
            "(version 1)",
            "(allow default)",
            '(deny file-write* (subpath "/"))',
            f'(allow file-write* (subpath "{tmp_real}"))',
            '(allow file-write* (subpath "/private/tmp"))',
            '(allow file-write* (subpath "/dev"))',
            f'(allow file-write* (subpath "{wdir}"))',
            f'(deny file-write* (subpath "{bdir}"))',
        ]
        git_hooks = wdir / ".git" / "hooks"
        if git_hooks.exists():
            rules.append(f'(deny file-write* (subpath "{git_hooks}"))')
        for rel in secret_rel_subpaths:
            sp = home / rel
            if sp.exists():
                rules.append(f'(deny file-read* (subpath "{sp}"))')
                rules.append(f'(deny file-write* (subpath "{sp}"))')
        if norm == "nonet":
            rules.append('(deny network* (remote ip))')
        profile = " ".join(rules)
        return ["/usr/bin/sandbox-exec", "-p", profile, *exec_cmd]

    return exec_cmd
