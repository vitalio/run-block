#!/usr/bin/env python3
"""CLI entrypoint, build.py, install.sh, self-update, and session state tests."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

try:
    from tests.helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module
except ImportError:
    from helpers import INSTALL_SH, ROOT, SCRIPT, RunBlockTestCase, load_module  # type: ignore[no-redef]


class TestCli(RunBlockTestCase):
    def test_help_and_version(self):
        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        self.assertIn("Usage:", r.stdout)
        self.assertIn("--plan", r.stdout)
        self.assertNotIn("--config", r.stdout)
        self.assertNotIn("--agents", r.stdout)
        self.assertIn("--start", r.stdout)
        self.assertNotIn("--init-start", r.stdout)
        self.assertNotIn("--agents-install", r.stdout)

        rv = self._run_subprocess([str(SCRIPT), "--version"])
        self._assert_ok(rv)
        ver_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        self.assertEqual(rv.stdout.strip(), f"run_block {ver_file}")

        # Verify urllib.request and tiktoken are not loaded during normal CLI startup and token counting
        lazy_check = "\n".join([
            "import contextlib, importlib.machinery, importlib.util, io, sys",
            f"loader = importlib.machinery.SourceFileLoader('rb', {str(SCRIPT)!r})",
            "spec = importlib.util.spec_from_loader('rb', loader)",
            "mod = importlib.util.module_from_spec(spec)",
            "loader.exec_module(mod)",
            "mod.count_tokens(b'hello world')",
            "mod.parse_bundle_fragments('===== Prompt =====')",
            "buf = io.StringIO()",
            "with contextlib.redirect_stdout(buf):",
            "    mod.main(['--version'])",
            "assert 'urllib.request' not in sys.modules, 'urllib.request loaded eagerly'",
            "assert 'tiktoken' not in sys.modules, 'tiktoken loaded'",
        ])
        r_lazy = subprocess.run([sys.executable, "-c", lazy_check], capture_output=True, text=True, check=False)
        self.assertEqual(r_lazy.returncode, 0, msg=f"stdout:\n{r_lazy.stdout}\nstderr:\n{r_lazy.stderr}")

    def test_f42_done_cli_flags_and_help(self):
        r = self._run_subprocess([str(SCRIPT), "-h"])
        self._assert_ok(r)
        self.assertIn("--done [session] [-m NOTE]", r.stdout)
        self.assertIn("[DONE]", r.stdout)
        self.assertIn("next free step", r.stdout)

        self.mod.start_session("s1")
        bad_cases = (
            (["--done", "nosuch"], "not found"),
            (["--done", "s1", "-m"], "-m requires an argument"),
            (["--done", "s1", "s2"], "usage:"),
            (["--done", "--bogus"], "usage:"),
            (["--done", "-p", "x"], "cannot be used"),
        )
        for args, needle in bad_cases:
            with self.subTest(args=args):
                rb = self._run([str(SCRIPT), *args])
                self.assertEqual(rb.returncode, 1, msg=rb.stdout + rb.stderr)
                self.assertIn(needle, rb.stderr)

        r_open = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_open)
        self.assertRegex(r_open.stdout, r"s1 .*last: s1/0 \(bundle\)\s+next: s1/1")
        r_done = self._run([str(SCRIPT), "--done", "-y", "s1", "-m", "wrap"])
        self._assert_ok(r_done)
        self.assertIn("[s1] END SESSION", r_done.stdout)
        self.assertIn("Note: wrap", r_done.stdout)
        r_list = self._run([str(SCRIPT), "--list"])
        self._assert_ok(r_list)
        self.assertRegex(r_list.stdout, r"s1 .*\[DONE\]")

    def test_embedded_rules_files_exist(self):
        self.assertFalse((ROOT / "src/bundles").exists())
        ab_txt = (ROOT / ".agents_bundle").read_text(encoding="utf-8")
        self.assertNotIn("bundle vitalio/run_block", ab_txt)
        bash_md = (ROOT / "src/rules/blocks/bash.md").read_text(encoding="utf-8")
        pwsh_md = (ROOT / "src/rules/blocks/pwsh.md").read_text(encoding="utf-8")
        self.assertIn("## Terminal blocks (`{cmd:run_block}`)", bash_md)
        self.assertIn("## Terminal blocks (`{cmd:run_block}`)", pwsh_md)
        self.assertIn("ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT)", bash_md)
        self.assertIn("small, targeted patch", bash_md)
        self.assertIn("comparable in size to the original block", bash_md)
        readme_md = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("small, targeted patches", readme_md)

    def test_self_update_and_check_update(self):
        installed = self.tmp / "my_block"
        shutil.copy2(SCRIPT, installed)
        remote_file = self.tmp / "remote_run_block"
        cur_v = self.mod.VERSION
        src = SCRIPT.read_text(encoding="utf-8").replace(f'VERSION = "{cur_v}"', 'VERSION = "9.9.9"', 1)
        remote_file.write_text(src, encoding="utf-8")
        url = remote_file.as_uri()

        env = {**os.environ, "RUN_BLOCK_UPDATE_URL": url}
        r_chk = self._run([str(installed), "--check-update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_chk.returncode, 0)
        self.assertIn(f"{cur_v} -> 9.9.9", r_chk.stdout)

        r_up = self._run([str(installed), "--update"], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(r_up.returncode, 0)
        self.assertIn(f"updated {cur_v} -> 9.9.9", r_up.stdout)

    def test_install_sh_fresh_and_conflict(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}

        r1 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r1.returncode, 0, r1.stderr)
        self.assertTrue((bin_dir / "run_block").is_file())
        self.assertIn("Installed: run_block", r1.stdout)

        (bin_dir / "run_block").write_text("#!/bin/sh\necho other_tool\n", encoding="utf-8")
        (bin_dir / "run_block").chmod(0o755)
        r2 = subprocess.run(
            ["sh", str(INSTALL_SH), "--dir", str(bin_dir), "--yes"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((bin_dir / "run_term_block").is_file())
        self.assertIn("Installed: run_term_block", r2.stdout)

    def test_powershell_mode_and_agents(self):
        fake_pwsh = self.tmp / "pwsh"
        fake_pwsh.write_text(
            "#!/bin/sh\n"
            "if [ \"$3\" = \"-Command\" ]; then\n"
            "  grep -q 'SYNTAX_ERR' \"$5\" && { echo 'ParseError: missing closing brace' >&2; exit 1; }\n"
            "  exit 0\n"
            "fi\n"
            "if [ \"$2\" = \"-File\" ]; then\n"
            "  sh \"$3\"\n"
            "  exit $?\n"
            "fi\n"
            "exit 0\n",
            encoding="utf-8",
        )
        fake_pwsh.chmod(0o755)
        os.environ["RUN_BLOCK_SHELL"] = str(fake_pwsh)
        try:
            self.assertTrue(self.mod._is_powershell())
            self.assertEqual(self.mod._script_ext(), ".ps1")
            pwsh_md = (ROOT / "src/rules/blocks/pwsh.md").read_text(encoding="utf-8")
            self.assertIn("powershell", pwsh_md)
            self.assertIn("'@ | {cmd:run_block} s1/1", pwsh_md)
            self.assertIn("fresh `pwsh` process", pwsh_md)
            self.assertIn("small, targeted patch", pwsh_md)
            self.assertIn("comparable in size to the original block", pwsh_md)

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_ok = self.mod.cmd_normal("s1/1", "echo ps1_ran_ok\n")
                self.assertEqual(rc_ok, 0)
                self.assertTrue((self.tmp / "s1/1/block.ps1").is_file())
                rc_err = self.mod.cmd_normal("s1/2", "echo SYNTAX_ERR\n")
                self.assertNotEqual(rc_err, 0)
                rc_fix = self.mod.cmd_fix("s1/2", "text = text.replace('SYNTAX_ERR', 'fixed_ps1')\n")
                self.assertEqual(rc_fix, 0)
                self.assertTrue((self.tmp / "s1/2_1/block.ps1").is_file())
                self.assertTrue((self.tmp / "s1/2_1/fix.py").is_file())
            self.assertIn("ps1_ran_ok", (self.tmp / "s1/1/out").read_text(encoding="utf-8"))
            self.assertIn("fixed_ps1", (self.tmp / "s1/2_1/out").read_text(encoding="utf-8"))
        finally:
            os.environ.pop("RUN_BLOCK_SHELL", None)

    def test_clean_sessions_and_build_py_check(self):
        r_bhelp = subprocess.run([sys.executable, str(ROOT / "build.py"), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bhelp.returncode, 0)
        self.assertIn("Usage:", r_bhelp.stdout)
        r_bchk = subprocess.run([sys.executable, str(ROOT / "build.py"), "--check"], capture_output=True, text=True, check=False)
        self.assertEqual(r_bchk.returncode, 0, r_bchk.stderr)

        for idx in range(1, 5):
            sdir = self.tmp / f"s{idx}"
            step1 = sdir / "1"
            step1.mkdir(parents=True)
            (step1 / "block.sh").write_text(f"echo {idx}\n", encoding="utf-8")
            (step1 / "out").write_text(f"out {idx}\n", encoding="utf-8")
            os.utime(sdir, (1000 + idx * 10, 1000 + idx * 10))

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_clean(["--keep", "2", "--yes"])
        self.assertEqual(rc, 0)
        self.assertIn("Cleaned 2 session(s)", buf.getvalue())
        self.assertIn("s1 (", buf.getvalue())
        self.assertIn("remaining).", buf.getvalue())
        remaining = sorted(p.name for p in self.tmp.iterdir() if p.is_dir())
        self.assertEqual(remaining, ["s3", "s4"])

        buf_all = io.StringIO()
        with contextlib.redirect_stdout(buf_all):
            rc_all = self.mod.cmd_clean(["--all", "--yes"])
        self.assertEqual(rc_all, 0)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.is_dir()], [])

    def test_persistent_state_dir_and_prune_controls(self):
        # 1. Default base_dir resolution across POSIX XDG, POSIX fallback, Windows, and RUN_BLOCK_DIR
        saved_xdg = os.environ.get("XDG_STATE_HOME")
        saved_local = os.environ.get("LOCALAPPDATA")
        try:
            os.environ.pop("RUN_BLOCK_DIR", None)
            os.environ["XDG_STATE_HOME"] = str(self.tmp / "xdg_state")
            with unittest.mock.patch.object(self.mod.os, "name", "posix"):
                self.assertEqual(
                    self.mod.default_base_dir("run_block"),
                    self.tmp / "xdg_state" / "run_block",
                )
                os.environ.pop("XDG_STATE_HOME", None)
                self.assertEqual(
                    self.mod.default_base_dir("run_block"),
                    Path.home() / ".local" / "state" / "run_block",
                )

            from pathlib import PureWindowsPath as _PWP

            class PureWindowsPath(_PWP):
                def expanduser(self):
                    return self

                @classmethod
                def home(cls):
                    return cls("C:/Users/alice")

            win_local = PureWindowsPath("C:/Users/alice/AppData/Local")
            win_home = PureWindowsPath.home()
            with unittest.mock.patch.object(self.mod.os, "name", "nt"), unittest.mock.patch.object(self.mod, "Path", PureWindowsPath):
                os.environ["LOCALAPPDATA"] = str(win_local)
                self.assertEqual(
                    self.mod.get_setting("base_dir", "run_block"),
                    (str(win_local / "run_block" / "state"), "default"),
                )
                os.environ.pop("LOCALAPPDATA", None)
                self.assertEqual(
                    self.mod.get_setting("base_dir", "run_block"),
                    (str(win_home / "AppData" / "Local" / "run_block" / "state"), "default"),
                )

            os.environ["RUN_BLOCK_DIR"] = str(self.tmp / "explicit_override")
            self.assertEqual(self.mod.default_base_dir("run_block"), self.tmp / "explicit_override")
        finally:
            os.environ["RUN_BLOCK_DIR"] = str(self.tmp)
            if saved_xdg is None:
                os.environ.pop("XDG_STATE_HOME", None)
            else:
                os.environ["XDG_STATE_HOME"] = saved_xdg
            if saved_local is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = saved_local

        # 2. Sandbox rules keep persistent BASE_DIR read-only even when Workdir is HOME
        home_dir = Path.home().resolve()
        persistent_bdir = home_dir / ".local" / "state" / "run_block"
        with unittest.mock.patch.object(self.mod.sys, "platform", "darwin"), unittest.mock.patch.object(self.mod.Path, "is_file", return_value=True):
            sb_cmd = self.mod.build_sandbox_exec(["bash", "1.sh"], home_dir, persistent_bdir, "strict")
            self.assertEqual(sb_cmd[0], "/usr/bin/sandbox-exec")
            profile = sb_cmd[2]
            allow_idx = profile.index(f'(allow file-write* (subpath "{home_dir}"))')
            deny_idx = profile.index(f'(deny file-write* (subpath "{persistent_bdir}"))')
            self.assertLess(allow_idx, deny_idx)

        # 3. Create sessions with known sizes and timestamps for --list, --clean, and size warning
        import time as _time
        now = _time.time()
        specs = [
            ("s1", 600, now - 10 * 86400),
            ("s2", 1400, now - 5 * 86400),
            ("s3", 2200, now - 2 * 86400),
            ("s4", 800, now - 60),
        ]
        for name, payload_sz, ts in specs:
            sdir = self.tmp / name
            step1 = sdir / "1"
            step1.mkdir(parents=True)
            f_out = step1 / "out"
            f_out.write_bytes(b"x" * payload_sz)
            os.utime(f_out, (ts, ts))
            os.utime(step1, (ts, ts))
            os.utime(sdir, (ts, ts))

        # --list displays per-session and total storage sizes
        list_buf = io.StringIO()
        with contextlib.redirect_stdout(list_buf):
            self.assertEqual(self.mod.cmd_list(), 0)
        list_out = list_buf.getvalue()
        self.assertIn("600 B", list_out)
        self.assertIn("1.4 KB", list_out)
        self.assertIn("2.1 KB", list_out)
        self.assertIn("Total storage: 4.9 KB (4 session(s))", list_out)

        # Oversized state directory emits warning on stderr when exceeding RUN_BLOCK_MAX_STATE_MB
        saved_max_mb = os.environ.get("RUN_BLOCK_MAX_STATE_MB")
        try:
            self.mod._STATE_WARNED_DIRS.clear()
            os.environ["RUN_BLOCK_MAX_STATE_MB"] = "0.002"
            err_buf = io.StringIO()
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err_buf):
                self.assertEqual(self.mod.cmd_list(), 0)
            self.assertIn("warning: state directory", err_buf.getvalue())
            self.assertIn("exceeds 0.002 MB limit", err_buf.getvalue())
        finally:
            if saved_max_mb is None:
                os.environ.pop("RUN_BLOCK_MAX_STATE_MB", None)
            else:
                os.environ["RUN_BLOCK_MAX_STATE_MB"] = saved_max_mb

        # --clean --older-than 7 removes s1 (10 days old)
        c1_buf = io.StringIO()
        with contextlib.redirect_stdout(c1_buf):
            self.assertEqual(self.mod.cmd_clean(["--older-than", "7", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s1 (600 B)", c1_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s2", "s3", "s4"])

        # --clean --max-size 0.003 removes oldest remaining (s2: 1400 B) so remaining (s3+s4 = 3000 B) <= 3145 B
        c2_buf = io.StringIO()
        with contextlib.redirect_stdout(c2_buf):
            self.assertEqual(self.mod.cmd_clean(["--max-size", "0.003", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s2 (1.4 KB)", c2_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s3", "s4"])

        # --clean <session> removes specific session by name
        c3_buf = io.StringIO()
        with contextlib.redirect_stdout(c3_buf):
            self.assertEqual(self.mod.cmd_clean(["s3", "--yes"]), 0)
        self.assertIn("Cleaned 1 session(s) (s3 (2.1 KB)", c3_buf.getvalue())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.is_dir()), ["s4"])

    def test_b3_subproject_workdir_resolution_and_overrides(self):
        repo = self.tmp / "monorepo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(repo), check=True)
        (repo / "AGENTS.md").write_text("# Monorepo root\n", encoding="utf-8")

        subproj = repo / "apps" / "canary"
        subproj_nested = subproj / "src"
        subproj_nested.mkdir(parents=True)
        (subproj / ".agents_bundle").write_text("ruleset vitalio/agents-rules:default\n", encoding="utf-8")

        regular_subdir = repo / "packages" / "plain"
        regular_subdir.mkdir(parents=True)

        sessions_dir = self.tmp / "b3_sessions"
        base_env = {**os.environ, "RUN_BLOCK_DIR": str(sessions_dir)}
        base_env.pop("RUN_BLOCK_CWD", None)

        # 1. Starting session from nested dir inside a subproject with .agents_bundle keeps subproject root
        r_sub = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_sub.returncode, 0, r_sub.stderr)
        s1_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s1")
        self.assertEqual(Path(s1_hdrs["workdir"]).resolve(), subproj.resolve())

        # Subsequent step run from monorepo root still executes in persisted subproject Workdir
        r_sub_step = self._run(
            [str(SCRIPT), "-y", "s1/1"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_sub_step.returncode, 0, r_sub_step.stderr)
        self.assertIn(str(subproj.resolve()), r_sub_step.stdout)

        # 2. Subproject with AGENTS.md (without .agents_bundle) also resolves to subproject root
        subproj_agents = repo / "apps" / "docs_sub"
        subproj_agents.mkdir(parents=True)
        (subproj_agents / "AGENTS.md").write_text("# Subproject rules\n", encoding="utf-8")
        r_agents = self._run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_agents),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_agents.returncode, 0, r_agents.stderr)
        s2_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s2")
        self.assertEqual(Path(s2_hdrs["workdir"]).resolve(), subproj_agents.resolve())

        # 3. Regular Git subdir without .agents_bundle or AGENTS.md climbs to Git toplevel
        r_reg = self._run(
            [str(SCRIPT), "--start", "--session", "s3"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(regular_subdir),
            env=base_env,
            check=False,
        )
        self.assertEqual(r_reg.returncode, 0, r_reg.stderr)
        s3_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s3")
        self.assertEqual(Path(s3_hdrs["workdir"]).resolve(), repo.resolve())

        # 4. RUN_BLOCK_CWD=cwd forces exact $PWD even inside subproject
        env_cwd = {**base_env, "RUN_BLOCK_CWD": "cwd"}
        r_cwd = self._run(
            [str(SCRIPT), "--start", "--session", "s4"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=env_cwd,
            check=False,
        )
        self.assertEqual(r_cwd.returncode, 0, r_cwd.stderr)
        s4_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s4")
        self.assertEqual(Path(s4_hdrs["workdir"]).resolve(), subproj_nested.resolve())

        # 5. Explicit RUN_BLOCK_CWD=/path overrides subproject and session Workdir
        explicit_dir = self.tmp / "explicit_target"
        explicit_dir.mkdir()
        env_exp = {**base_env, "RUN_BLOCK_CWD": str(explicit_dir)}
        r_exp = self._run(
            [str(SCRIPT), "--start", "--session", "s5"],
            input="Role: execute\n",
            capture_output=True,
            text=True,
            cwd=str(subproj_nested),
            env=env_exp,
            check=False,
        )
        self.assertEqual(r_exp.returncode, 0, r_exp.stderr)
        s5_hdrs = self.mod.parse_bundle_headers(sessions_dir / "s5")
        self.assertEqual(Path(s5_hdrs["workdir"]).resolve(), explicit_dir.resolve())

    def test_f79_nested_in_run_block_subcommand_guards(self):
        # Create an initial session and step so retry/fix/show/list/sandbox have targets
        self._assert_ok(self._run(["--start", "--session", "s1"], input="Task: F79\n\nhello\n"))
        self._assert_ok(self._run(["-y", "s1/1"], input="echo first\n"))

        nested_env = {
            **os.environ,
            "IN_RUN_BLOCK": "1",
            "RUN_BLOCK_PARENT_SESSION": "s1",
            "RUN_BLOCK_PARENT_STEP": "1",
        }

        # 1. Nested step execution (<session>/<step>, --fix, --retry) is rejected with exit 2
        for label, argv, stdin_payload in (
            ("step", ["s1/2"], "echo nested\n"),
            ("fix", ["--fix", "s1/1"], "text = text.replace('first', 'second')\n"),
            ("retry", ["--retry", "s1/1"], ""),
            ("retry_implicit", ["--retry"], ""),
        ):
            with self.subTest(case=label):
                proc = self._run(argv, input=stdin_payload, env=nested_env)
                self.assertEqual(proc.returncode, 2, msg=proc.stderr)
                self.assertIn("cannot run", proc.stderr)
                self.assertIn("from inside a running block (active step: s1/1)", proc.stderr)

        # 2. Read-only subcommands (--list, --show, --bundle-plan, --plan, --sandbox) succeed
        r_list = self._run(["--list", "s1"], env=nested_env)
        self._assert_ok(r_list)
        self.assertIn("Blocks in s1", r_list.stdout)

        r_show = self._run(["--show", "s1/1"], env=nested_env)
        self._assert_ok(r_show)
        self.assertIn("echo first", r_show.stdout)

        r_bplan = self._run(["--bundle-plan", "s1"], env=nested_env)
        self._assert_ok(r_bplan)
        self.assertIn("[total]", r_bplan.stdout)

        r_plan = self._run(["--plan"], input="echo safe\n", env=nested_env)
        self._assert_ok(r_plan)
        self.assertIn('"operations"', r_plan.stdout)

        r_sb_ro = self._run(["--sandbox"], env=nested_env)
        self._assert_ok(r_sb_ro)
        self.assertIn("Session: s1", r_sb_ro.stdout)

        # Sandbox mutation remains rejected with exit 2
        r_sb_mut = self._run(["--sandbox", "strict", "s1"], env=nested_env)
        self.assertEqual(r_sb_mut.returncode, 2)
        self.assertIn("cannot modify session sandbox settings from inside a running block", r_sb_mut.stderr)


if __name__ == "__main__":
    unittest.main()
