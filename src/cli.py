def parse_version_from_source(source: str) -> str | None:
    m = re.search(r'^VERSION\s*=\s*["\x27]([^"\x27]+)["\x27]', source, flags=re.MULTILINE)
    return m.group(1) if m else None


def version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for p in re.split(r"[^0-9]+", v):
        if p:
            parts.append(int(p))
    return tuple(parts)


def fetch_remote_script(url: str | None = None) -> str:
    import urllib.request

    cfg_url, _ = get_setting("update_url")
    target_url = url or cfg_url
    if target_url.startswith(("http://", "https://")) and "?" not in target_url:
        target_url = f"{target_url}?t={int(time.time())}"
    req = urllib.request.Request(
        target_url,
        headers={"User-Agent": f"run_block/{VERSION}", "Cache-Control": "no-cache", "Pragma": "no-cache"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read().decode("utf-8")
    if REPO_MARKER and REPO_MARKER not in data:
        raise ValueError("downloaded file does not contain expected repository marker")
    ast.parse(data)
    return data


def cmd_check_update(url: str | None = None) -> int:
    prog = prog_name()
    try:
        remote_src = fetch_remote_script(url)
    except Exception as exc:
        sys.stderr.write(f"{prog}: failed to check for updates: {exc}\n")
        return 1
    remote_ver = parse_version_from_source(remote_src) or "unknown"
    if version_tuple(remote_ver) > version_tuple(VERSION):
        sys.stdout.write(f"{prog}: update available: {VERSION} -> {remote_ver} (run '{prog} --update')\n")
    else:
        sys.stdout.write(f"{prog} {VERSION} is up to date (remote: {remote_ver}).\n")
    return 0


def cmd_update(force: bool = False, url: str | None = None, target_path: Path | None = None) -> int:
    prog = prog_name()
    dest = target_path or Path(__file__).resolve()
    try:
        remote_src = fetch_remote_script(url)
    except Exception as exc:
        sys.stderr.write(f"{prog}: update failed: {exc}\n")
        return 1
    remote_ver = parse_version_from_source(remote_src) or "unknown"
    if not force and version_tuple(remote_ver) <= version_tuple(VERSION):
        sys.stdout.write(f"{prog} {VERSION} is already up to date.\n")
        return 0
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=f".{dest.name}.", dir=str(dest.parent))
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(remote_src)
            os.chmod(tmp_name, 0o755)
            os.replace(tmp_name, dest)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
    except Exception as exc:
        sys.stderr.write(f"{prog}: could not write updated binary to {dest}: {exc}\n")
        return 1
    sys.stdout.write(f"{prog}: updated {VERSION} -> {remote_ver} ({dest})\n")
    return 0


_SANDBOX_MODE_TOKENS = ("off", "0", "false", "on", "1", "true", "auto", "strict", "nonet", "no-net")


def _extract_prompt_args(argv: list[str]) -> tuple[list[str], list[str]]:
    prog = prog_name()
    rest: list[str] = []
    prompts: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-p", "--prompt"):
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog}: {a} requires an argument")
            prompts.append(argv[i + 1])
            i += 2
        elif a.startswith("--prompt="):
            prompts.append(a.split("=", 1)[1])
            i += 1
        else:
            rest.append(a)
            i += 1
    return rest, prompts


def _reject_prompt_for(command_label: str, usage: str) -> None:
    prog = prog_name()
    raise SystemExit(f"{prog}: -p/--prompt cannot be used with {command_label} (usage: {usage})")


def _parse_list_args(argv: list[str], usage: str) -> tuple[str | None, str | None]:
    session: str | None = None
    query: str | None = None
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--filter":
            if i + 1 >= len(argv):
                raise SystemExit(f"{prog_name()}: --filter requires an argument")
            query = argv[i + 1]
            i += 2
        elif a.startswith("--filter="):
            query = a.split("=", 1)[1]
            i += 1
        elif a.startswith("-") or session is not None:
            raise SystemExit(f"{prog_name()}: usage: {usage}")
        else:
            session = a
            i += 1
    if session is not None and query is not None:
        raise SystemExit(f"{prog_name()}: --filter cannot be combined with a session (usage: {usage})")
    return session, query


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    prog = prog_name()
    if "-h" in raw_args or "--help" in raw_args:
        sys.stdout.write(usage_text())
        return 0
    if "-V" in raw_args or "--version" in raw_args:
        sys.stdout.write(f"{prog} {VERSION}\n")
        return 0

    has_bare_sandbox_flag = False
    for idx, tok in enumerate(raw_args):
        if tok == "--sandbox":
            if idx + 1 >= len(raw_args) or raw_args[idx + 1].lower() not in _SANDBOX_MODE_TOKENS:
                has_bare_sandbox_flag = True

    args, prompt_args = _extract_prompt_args(raw_args)

    if args and args[0] == "--plan":
        if prompt_args:
            _reject_prompt_for("--plan", f"{prog} --plan < script.sh")
        if len(args) != 1:
            raise SystemExit(f"{prog}: usage: {prog} --plan < script.sh")
        return cmd_plan(sys.stdin.read())
    if args and args[0] == "--bundle-plan":
        if prompt_args:
            _reject_prompt_for("--bundle-plan", f"{prog} --bundle-plan [<session>] [--json] [--full] [--part N]")
        return cmd_bundle_plan(args[1:])
    if args and args[0] == "--clean":
        if prompt_args:
            _reject_prompt_for(
                "--clean",
                f"{prog} --clean [--keep N | --older-than DAYS | --max-size MB | --all] [--yes] [session...]",
            )
        return cmd_clean(args[1:])

    has_start_opt = any(
        x in ("--start", "--bundle", "--session", "--force") or x.startswith("--session=")
        for x in args
    )
    if args and args[0] == "--sandbox" and not has_start_opt:
        rest_sb = args[1:]
        if not any("/" in x or x.startswith("-") for x in rest_sb):
            has_session_arg = len(rest_sb) >= 2 or (
                len(rest_sb) == 1 and rest_sb[0].lower() not in _SANDBOX_MODE_TOKENS
            )
            if in_run_block() or has_session_arg or has_bare_sandbox_flag or (
                sys.stdin.isatty() and not prompt_args
            ):
                if prompt_args:
                    _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
                return cmd_sandbox(rest_sb)

    auto_yes = False
    sandbox_override: str | None = None
    filtered: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("-y", "--yes", "--headless"):
            auto_yes = True
            i += 1
        elif a == "--no-sandbox":
            sandbox_override = "off"
            i += 1
        elif a.startswith("--sandbox="):
            sandbox_override = a.split("=", 1)[1] or "strict"
            i += 1
        elif a == "--sandbox":
            if i + 1 < len(args) and args[i + 1].lower() in _SANDBOX_MODE_TOKENS:
                sandbox_override = args[i + 1]
                i += 2
            else:
                sandbox_override = "strict"
                i += 1
        else:
            filtered.append(a)
            i += 1
    args = filtered

    if not args:
        if sandbox_override is not None and not has_start_opt:
            if in_run_block() or has_bare_sandbox_flag or (sys.stdin.isatty() and not prompt_args):
                if prompt_args:
                    _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
                return cmd_sandbox([sandbox_override])
        return cmd_start([], sandbox_override=sandbox_override, prompt=prompt_args)

    if sandbox_override is not None and len(args) == 1 and "/" not in args[0] and not args[0].startswith("-"):
        if prompt_args:
            _reject_prompt_for("--sandbox", f"{prog} --sandbox [off|strict|nonet] [session]")
        return cmd_sandbox([sandbox_override, args[0]])

    if args[0] in ("--list", "-l"):
        list_usage = f"{prog} --list [session | --filter TEXT]"
        if prompt_args:
            _reject_prompt_for(args[0], list_usage)
        list_session, list_query = _parse_list_args(args[1:], list_usage)
        return cmd_list(list_session, query=list_query)

    if args[0] == "--info":
        info_usage = f"{prog} --info [session]"
        if prompt_args:
            _reject_prompt_for("--info", info_usage)
        if len(args) > 2 or (len(args) == 2 and args[1].startswith("-")):
            raise SystemExit(f"{prog}: usage: {info_usage}")
        return cmd_info(args[1] if len(args) == 2 else None)

    if args[0] == "--done":
        done_usage = f"{prog} --done [-y] [session] [-m NOTE]"
        if prompt_args:
            _reject_prompt_for("--done", done_usage)
        done_note: str | None = None
        done_session: str | None = None
        j = 1
        while j < len(args):
            tok = args[j]
            if tok == "-m":
                if j + 1 >= len(args):
                    raise SystemExit(f"{prog}: -m requires an argument")
                done_note = args[j + 1]
                j += 2
            elif tok.startswith("-") or done_session is not None:
                raise SystemExit(f"{prog}: usage: {done_usage}")
            else:
                done_session = tok
                j += 1
        return cmd_done(done_session, note=done_note, auto_yes=auto_yes)

    if args[0] == "--show":
        show_usage = f"{prog} --show [session[/step]] [--part N | --script | --out]"
        if prompt_args:
            _reject_prompt_for("--show", show_usage)
        only_flags = [a for a in args[1:] if a in ("--script", "--out")]
        show_args = [a for a in args[1:] if a not in ("--script", "--out")]
        show_rest, show_part = parse_part_option(show_args, show_usage)
        if len(show_rest) > 1 or len(set(only_flags)) > 1 or (only_flags and show_part is not None):
            raise SystemExit(f"{prog}: usage: {show_usage}")
        return cmd_show(
            show_rest[0] if show_rest else None,
            part=show_part,
            only=only_flags[0][2:] if only_flags else None,
        )

    if args[0] in ("--retry", "--rerun"):
        if prompt_args:
            _reject_prompt_for(args[0], f"{prog} --retry [-y] [session[/step]]")
        if len(args) > 2:
            raise SystemExit(f"{prog}: usage: {prog} --retry [-y] [session[/step]]")
        return cmd_retry(
            args[1] if len(args) == 2 else None, auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if args[0] == "--check-update":
        if prompt_args:
            _reject_prompt_for("--check-update", f"{prog} --check-update")
        if len(args) != 1:
            raise SystemExit(f"{prog}: usage: {prog} --check-update")
        return cmd_check_update()

    if args[0] in ("--update", "--self-update"):
        if prompt_args:
            _reject_prompt_for(args[0], f"{prog} --update [--force]")
        force = "--force" in args[1:]
        rest = [a for a in args[1:] if a != "--force"]
        if rest:
            raise SystemExit(f"{prog}: usage: {prog} --update [--force]")
        return cmd_update(force=force)

    if args[0] in ("--start", "--bundle"):
        return cmd_start(args[1:], sandbox_override=sandbox_override, prompt=prompt_args)

    if args[0] == "--fix":
        if prompt_args:
            _reject_prompt_for("--fix", f"{prog} --fix [-y] <session>/<target>")
        if len(args) != 2:
            raise SystemExit(f"{prog}: usage: {prog} --fix [-y] <session>/<target>")
        return cmd_fix(
            args[1], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
        )

    if args[0] in ("--session", "--force") or args[0].startswith("--session="):
        return cmd_start(args, sandbox_override=sandbox_override, prompt=prompt_args)

    if prompt_args:
        if len(args) == 1 and "/" in args[0] and not args[0].startswith("-"):
            _reject_prompt_for(args[0], f"{prog} [-y] <session>/<step>")
        return cmd_start(args, sandbox_override=sandbox_override, prompt=prompt_args)

    if len(args) != 1 or args[0].startswith("-"):
        raise SystemExit(
            f"{prog}: usage: {prog} [-y] <session>/<step> (or pipe bundle to '{prog}' to start a session; see --help)"
        )
    return cmd_normal(
        args[0], sys.stdin.read(), auto_yes=auto_yes, sandbox_override=sandbox_override
    )


if __name__ == "__main__":
    raise SystemExit(main())
