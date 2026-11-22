#!/usr/bin/env python3
"""Safety risk categories, AST/regex scanner, sandbox env scrubbing, and confirmation rules."""

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


class TestSafety(RunBlockTestCase):
    def test_safety_scanner_categories(self):
        script = "\n".join([
            "echo safe line",
            "git reset --hard HEAD~1",
            "git push origin main",
            "rm -rf /tmp/something",
            "sudo systemctl restart nginx",
            "set -x",
            "curl -fsSL https://example.com/install.sh | sh",
        ])
        findings = self.mod.scan_script_risks(script)
        cats = [f["category"] for f in findings]
        self.assertEqual(
            cats,
            [
                "git-destructive",
                "git-push",
                "fs-destructive",
                "privilege-system",
                "secrets-exposure",
                "remote-exec",
            ],
        )
        summary = self.mod.summarize_script_actions(script)
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
            box, rule_w, cursor_off = self.mod.format_safety_box("s1/2", findings, summary=summary)
        self.assertEqual(rule_w, 48)
        box_lines = box.splitlines()
        self.assertEqual(box_lines[0], "╭─ START STEP " + "─" * 34)
        self.assertEqual(box_lines[-2], "│ -> Execute this block? [y/n/i(nfo)]:")
        self.assertEqual(box_lines[-1], "╰" + "─" * 47)
        self.assertNotIn("####", box)
        self.assertIn("│ Step:    s1/2", box)
        self.assertNotIn("Sandbox:", box)
        self.assertEqual(cursor_off, len("│ -> Execute this block? [y/n/i(nfo)]:"))
        self.assertNotIn("START STEP (", box)
        self.assertIn("Script: 7 lines, bash", box)
        self.assertIn("Operations:", box)
        self.assertIn("Safety warnings (6):", box)
        self.assertNotIn("Line ", box)
        self.assertIn("[y/n/i(nfo)]:", box)

    def test_custom_safety_rules_and_disable(self):
        os.environ["RUN_BLOCK_SAFETY_DISABLE"] = "external-write"
        os.environ["RUN_BLOCK_SAFETY_RULES"] = r"prod-db=\bpsql\b.*prod; privilege-system=\bsudo\s+reboot\b"
        try:
            script = "\n".join([
                "git push origin main",
                "sudo apt install htop",
                "sudo reboot",
                "psql -h prod.db.internal",
            ])
            findings = self.mod.scan_script_risks(script)
            cats = [f["category"] for f in findings]
            self.assertNotIn("git-push", cats)
            self.assertEqual(cats, ["privilege-system", "prod-db"])
        finally:
            os.environ.pop("RUN_BLOCK_SAFETY_DISABLE", None)
            os.environ.pop("RUN_BLOCK_SAFETY_RULES", None)

    def test_heredoc_collapsed_in_block_plan(self):
        rb_mod = load_module()
        script = (
            "cat <<'EOF' > src/example.py\n"
            + "\n".join(f"line_{i} = {i}" for i in range(40))
            + "\nEOF\n"
            "git status -sb\n"
        )
        summary = rb_mod.summarize_script_actions(script, Path("/tmp"))
        ops = summary["operations"]
        self.assertEqual(len(ops), 2)
        self.assertEqual(ops[0][0], "write")
        self.assertIn("cat <<'EOF' > src/example.py (40 lines)", ops[0][1])
        self.assertEqual(ops[1], ("git", "git status -sb"))

        multi_cd = "cd /tmp\nls -la\ncd /var\nls -la\n"
        sum_cd = rb_mod.summarize_script_actions(multi_cd, Path("/home"))
        box_cd, _, _ = rb_mod.format_safety_box("s1/4", [], default_yes=True, summary=sum_cd)
        self.assertIn("╭─ START STEP ", box_cd)
        self.assertIn("Step:    s1/4", box_cd)
        self.assertIn("  /tmp:", box_cd)
        stripped_lines = [l.strip() for l in box_cd.splitlines()]
        idx_var = stripped_lines.index("│   /var:")
        self.assertEqual(stripped_lines[idx_var - 1], "│     1. [read]  ls -la")

    def test_sandbox_header_cli_and_env_scrubbing(self):
        proj = self.tmp / "sb_proj"
        proj.mkdir()
        env = {
            **os.environ,
            "RUN_BLOCK_DIR": str(self.tmp / "sb_sessions"),
            "RUN_BLOCK_CWD": str(proj),
            "OPENAI_API_KEY": "sk-secret-test-key",
            "GITHUB_TOKEN": "ghp-secret-token",
        }
        r_start = self._run(
            [str(SCRIPT), "--start", "--session", "s1", "--sandbox", "strict"],
            input="Context body\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        b_txt = (self.tmp / "sb_sessions/s1/0").read_text(encoding="utf-8")
        self.assertIn("Sandbox: strict (rw: Workdir, /tmp; secrets: hidden; net: on)", b_txt)

        # Toggle sandbox via CLI (with non-TTY stdin as in CI)
        r_sb_nonet = self._run(
            [str(SCRIPT), "--sandbox", "nonet", "s1"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_sb_nonet.returncode, 0, r_sb_nonet.stderr)
        b_txt2 = (self.tmp / "sb_sessions/s1/0").read_text(encoding="utf-8")
        self.assertIn("Sandbox: nonet", b_txt2)

        # Query sandbox status for a named session with non-TTY stdin
        r_sb_status = self._run(
            [str(SCRIPT), "--sandbox", "s1"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_sb_status.returncode, 0, r_sb_status.stderr)
        self.assertIn("Session: s1", r_sb_status.stdout)
        self.assertIn("Sandbox: nonet", r_sb_status.stdout)

        # Calling --sandbox from inside a running block must be rejected
        env_inside = {**env, "IN_RUN_BLOCK": "1"}
        r_inside = self._run(
            [str(SCRIPT), "--sandbox", "off", "s1"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_inside,
            check=False,
        )
        self.assertEqual(r_inside.returncode, 2)
        self.assertIn("cannot modify session sandbox settings from inside a running block", r_inside.stderr)

        # Verify secret env scrubbing
        scrubbed = self.mod.scrub_child_env(
            {"PATH": "/usr/bin", "OPENAI_API_KEY": "secret", "GITHUB_TOKEN": "tok", "SSH_AUTH_SOCK": "/tmp/sock"},
            "nonet",
        )
        self.assertEqual(scrubbed, {"PATH": "/usr/bin"})

    def test_unicode_spoof_python_ast_risks_and_external_dir_grouping(self):
        script = (
            "echo normal\n"
            "echo \u202ehidden\n"
            "python3 - <<'PY'\n"
            "import subprocess, urllib.request\n"
            "subprocess.run(['id'])\n"
            "urllib.request.urlopen('https://example.com')\n"
            "eval('1+1')\n"
            "PY\n"
        )
        findings = self.mod.scan_script_risks(script)
        cats = [f["category"] for f in findings]
        self.assertIn("unicode-spoof", cats)
        self.assertIn("remote-exec", cats)
        self.assertIn("net-write", cats)

        ext_script = (
            'cat "$HOME/proj_a/VERSION"\n'
            'cat "$HOME/proj_a/README.md"\n'
            'cat "$HOME/proj_b/README.md"\n'
        )
        summary = self.mod.summarize_script_actions(ext_script, Path("/tmp"))
        groups = summary["operation_groups"]
        self.assertEqual(groups[0][0], "$HOME/proj_a")
        self.assertEqual(groups[1][0], "$HOME/proj_b")

        loop_subshell_script = (
            'for repo in "$HOME/proj_a" "$HOME/proj_b"; do\n'
            '(\n'
            'cd "$repo"\n'
            'python3 build.py\n'
            ')\n'
            'done\n'
            'nl -ba src/safety.py\n'
            'for repo in "$HOME/proj_a" "$HOME/proj_b"; do\n'
            'git -C "$repo" status --porcelain\n'
            'done\n'
        )
        dash_c_script = "python3 -c '\nimport ast, pathlib\nfor p in pathlib.Path(\".\").rglob(\"*.py\"):\n    ast.parse(p.read_text())\n'\n"
        dc_sum = self.mod.summarize_script_actions(dash_c_script, Path("/tmp/work"))
        self.assertEqual(dc_sum["operations"], [("python", "3 lines — calls: ast.parse")])
        self.assertIn("1 python block", dc_sum["meta"])
        dc_risk_script = "python3 -c '\nimport shutil\nshutil.rmtree(\"/tmp/x\")\n'\n"
        dc_risks = self.mod.scan_script_risks(dc_risk_script)
        self.assertTrue(any(r["category"] == "fs-destructive" for r in dc_risks))
        F3 = chr(96) * 3
        self.assertEqual(self.mod._reassemble_split_payload(f"echo ok\nRUN_BLOCK{F3}\n"), ("echo ok\n", None))
        split_paste = (
            f"run_block s4/1 <<'RUN_BLOCK'\n"
            f"echo before_fence\n"
            f"{F3}\n"
            f"{F3}text\n"
            f"echo after_fence\n"
            f"RUN_BLOCK\n"
            f"{F3}\n"
        )
        rebuilt, split_err = self.mod._reassemble_split_payload(split_paste)
        self.assertIsNone(split_err)
        self.assertEqual(rebuilt, "echo before_fence\necho after_fence\n")

        headerless_split = (
            f"echo line_one\n"
            f"{F3}\n"
            f"{F3}python\n"
            f"echo line_two\n"
        )
        self.assertEqual(
            self.mod._reassemble_split_payload(headerless_split),
            ("echo line_one\necho line_two\n", None),
        )

        with contextlib.redirect_stdout(io.StringIO()):
            rc_split = self.mod.cmd_normal("s4/1", split_paste, auto_yes=True)
        self.assertEqual(rc_split, 0)
        out_split = (self.tmp / "s4/1/out").read_text(encoding="utf-8")
        self.assertIn("before_fence\nafter_fence", out_split)

        unclosed_paste = (
            f"run_block s4/2 <<'RUN_BLOCK'\n"
            f"echo missing_end\n"
            f"{F3}\n"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            rc_recovered = self.mod.cmd_normal("s4/2", unclosed_paste, auto_yes=True)
        self.assertEqual(rc_recovered, 0)
        out_recovered = (self.tmp / "s4/2/out").read_text(encoding="utf-8")
        self.assertIn("missing_end", out_recovered)

        truly_unclosed = "run_block s4/3 <<'RUN_BLOCK'\necho never_closed\n"
        buf_unclosed = io.StringIO()
        with contextlib.redirect_stdout(buf_unclosed):
            rc_unclosed = self.mod.cmd_normal("s4/3", truly_unclosed, auto_yes=True)
        self.assertEqual(rc_unclosed, 2)
        self.assertIn("unclosed RUN_BLOCK heredoc", buf_unclosed.getvalue())

        split_fix_paste = (
            f"run_block --fix s4/1 <<'RUN_FIX'\n"
            f"text = text.replace('before_fence', 'fixed_before')\n"
            f"{F3}\n"
            f"{F3}python\n"
            f"text = text.replace('after_fence', 'fixed_after')\n"
            f"RUN_FIX\n"
            f"{F3}\n"
        )
        with contextlib.redirect_stdout(io.StringIO()):
            rc_sfix = self.mod.cmd_fix("s4/1", split_fix_paste, auto_yes=True)
        self.assertEqual(rc_sfix, 0)
        out_sfix = (self.tmp / "s4/1_1/out").read_text(encoding="utf-8")
        self.assertIn("fixed_before\nfixed_after", out_sfix)
        loop_sum = self.mod.summarize_script_actions(loop_subshell_script, Path("/tmp/work"))
        self.assertEqual(loop_sum["cd_dirs"], ["$HOME/proj_a", "$HOME/proj_b"])
        loop_groups = loop_sum["operation_groups"]
        self.assertEqual(
            loop_groups,
            [
                ("$HOME/proj_a, $HOME/proj_b", [("exec", "python3 build.py")]),
                ("", [("read", "nl -ba src/safety.py")]),
                ("$HOME/proj_a, $HOME/proj_b", [("git", "git status --porcelain")]),
            ],
        )

    def test_b2_continuations_quoted_echo_external_paths_and_multidir_python(self):
        # 1. Backslash continuations joined before classifying & scanning risks (but not inside heredocs)
        cont_script = (
            "git status \\\n"
            "  --porcelain\n"
            "rm \\\n"
            "  -rf /tmp/b2_target\n"
            "cat <<'EOF' > notes.txt\n"
            "line_with_trailing \\\n"
            "second_heredoc_line\n"
            "EOF\n"
        )
        c_sum = self.mod.summarize_script_actions(cont_script, Path("/tmp/work"))
        self.assertEqual(
            c_sum["operations"],
            [
                ("git", "git status --porcelain"),
                ("write", "rm -rf /tmp/b2_target"),
                ("write", "cat <<'EOF' > notes.txt (2 lines)"),
            ],
        )
        c_risks = self.mod.scan_script_risks(cont_script)
        self.assertEqual([r["category"] for r in c_risks], ["fs-destructive"])

        # 2. Quoted '>' in echo/printf is ignored; unquoted '>' is preserved
        echo_script = (
            'echo "10 > 5"\n'
            "printf '%s -> %s\\n' a b\n"
            'echo "msg > inside" > actual_out.txt\n'
        )
        e_sum = self.mod.summarize_script_actions(echo_script, Path("/tmp/work"))
        self.assertEqual(e_sum["operations"], [("exec", 'echo "msg > inside" > actual_out.txt')])

        # 3. Absolute external /home/<user>/<repo>/... paths and *_CWD=/path prefixes
        ext_abs_script = (
            "cat /home/alice/projects/sibling_repo/VERSION\n"
            "OTHER_CWD=/home/alice/projects/third_repo pytest -q\n"
        )
        ext_sum = self.mod.summarize_script_actions(
            ext_abs_script, Path("/home/alice/projects/current_repo")
        )
        self.assertEqual(
            ext_sum["operation_groups"],
            [
                ("/home/alice/projects/sibling_repo", [("read", "cat VERSION")]),
                ("/home/alice/projects/third_repo", [("exec", "pytest -q")]),
            ],
        )

        # 4. Python AST: loop targets, Path.unlink()/rmdir() + fs-destructive risk, and multi-dir >12 paths without dropping
        many_src = ", ".join(f'"src/f{i}.py"' for i in range(10))
        many_tests = ", ".join(f'"tests/t{i}.py"' for i in range(6))
        py_script = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"for p in ({many_src}):\n"
            "    Path(p).write_text('x')\n"
            f"for t in ({many_tests}):\n"
            "    Path(t).read_text()\n"
            "for old in ('src/stale.py', 'tests/old_dir'):\n"
            "    Path(old).unlink()\n"
            "Path('tests/empty_dir').rmdir()\n"
            "PY\n"
        )
        p_sum = self.mod.summarize_script_actions(py_script, Path("/tmp/work"))
        p_groups = dict(p_sum["operation_groups"])
        self.assertIn("src", p_groups)
        self.assertIn("tests", p_groups)
        src_writes = dict(p_groups["src"])["write"]
        self.assertIn("(+3 more, 11 total)", src_writes)
        self.assertIn("tests/t5.py", dict(p_sum["rows"])["read"])
        self.assertIn("unlink(src/stale.py)", dict(p_sum["rows"])["write"])
        self.assertIn("rmdir(tests/empty_dir)", dict(p_sum["rows"])["write"])

        p_risks = self.mod.scan_script_risks(py_script)
        fs_risks = [r for r in p_risks if r["category"] == "fs-destructive"]
        self.assertGreaterEqual(len(fs_risks), 2)

    def test_b6_multiline_quoted_strings_in_plan_and_instrumentation(self):
        # 1. Multiline ANSI-C single-quoted ($'...') and double-quoted ("...") arguments
        #    with escaped quotes/backslashes stay collapsed as single operations.
        script = (
            "todo_md edit F1 -b " + chr(36) + "'First line\n"
            "Second line with \\'quote\\'\n"
            "Third line'\n"
            'todo_md add "Title" -b "Line A \\"inner\\"\n'
            "Line B \\\\\n"
            'Line C"\n'
            "git status -sb\n"
        )
        summary = self.mod.summarize_script_actions(script, Path("/tmp/work"))
        steps = summary["operation_steps"]
        self.assertEqual([s["step"] for s in steps], [1, 2, 3])
        self.assertEqual([s["tag"] for s in steps], ["exec", "exec", "git"])
        self.assertEqual([s["line"] for s in steps], [1, 4, 7])
        self.assertEqual(len(summary["operations"]), 3)

        inst = self.mod.instrument_script_for_progress(script, is_powershell=False)
        ok_syn, syn_err, _ = self.mod.check_script_syntax(inst, self.tmp)
        self.assertTrue(ok_syn, syn_err)
        self.assertEqual(inst.count("__RB_STEP__:"), 3)
        self.assertIn("printf '%s\\n' '__RB_STEP__:1'\ntodo_md edit F1", inst)
        self.assertIn("printf '%s\\n' '__RB_STEP__:2'\ntodo_md add", inst)
        self.assertIn("printf '%s\\n' '__RB_STEP__:3'\ngit status -sb", inst)
        self.assertNotIn("Second line with 'quote'\nprintf", inst)
        self.assertNotIn("Line B \\\nprintf", inst)

        # Executing the instrumented script preserves exact multiline string arguments
        proc = subprocess.run(
            [
                "bash",
                "-c",
                'todo_md() { printf "ARG:%s\n" "' + chr(36) + '@"; }; git() { echo GIT_OK; }; ' + inst,
            ],
            cwd=str(self.tmp),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Second line with 'quote'\nThird line", proc.stdout)
        self.assertIn('Line A "inner"\nLine B \\\nLine C', proc.stdout)

        # 2. Compound keywords (fi/done) inside multiline quotes do not corrupt depth tracking
        nested_script = (
            "if true; then\n"
            '  echo "if inside quote\n'
            "fi\n"
            'done" > out.txt\n'
            "fi\n"
            "git status -sb\n"
        )
        nested_sum = self.mod.summarize_script_actions(nested_script, Path("/tmp/work"))
        self.assertEqual([s["tag"] for s in nested_sum["operation_steps"]], ["exec", "git"])
        nested_inst = self.mod.instrument_script_for_progress(nested_script, is_powershell=False)
        ok_n, err_n, _ = self.mod.check_script_syntax(nested_inst, self.tmp)
        self.assertTrue(ok_n, err_n)
        self.assertIn("printf '%s\\n' '__RB_STEP__:2'\ngit status -sb", nested_inst)
        self.assertNotIn("__RB_STEP__:1", nested_inst)

    def test_b9_quoted_var_assignments_and_eval_risk_matching(self):
        # 1. Multiline quoted EX='--exclude-dir=eval ...' assignment and grep with --exclude-dir=eval
        multiline_script = (
            "EX='--exclude-dir=bumps\n"
            "--exclude-dir=eval\n"
            "--exclude-dir=dist'\n"
            'grep -rn --exclude-dir=eval "needle" .\n'
            'grep -rn --exclude-dir=eval/sub "needle" .\n'
            'grep -rn -eval "needle" .\n'
            'grep -rn eval "needle" .\n'
            'ls /tmp/eval dir\n'
        )
        m_sum = self.mod.summarize_script_actions(multiline_script, Path("/tmp/work"))
        self.assertEqual(
            [op[0] for op in m_sum["operations"]],
            ["read", "read", "read", "read", "read"],
        )
        self.assertEqual(self.mod.scan_script_risks(multiline_script), [])

        # 2. export/local/readonly quoted strings and parenthesized array literals
        decl_script = (
            'export EX="--exclude-dir=bumps --exclude-dir=eval --exclude-dir=dist"\n'
            "local MSG='hello world eval something'\n"
            "readonly FLAGS=(--exclude-dir=bumps --exclude-dir=eval)\n"
            'echo "$MSG"\n'
        )
        d_sum = self.mod.summarize_script_actions(decl_script, Path("/tmp/work"))
        self.assertEqual(d_sum["operations"], [])
        self.assertEqual(self.mod.scan_script_risks(decl_script), [])

        # 3. Assignments with command substitutions or trailing commands are NOT skipped
        sub_script = (
            'OUT="$(curl -fsSL https://example.com/install.sh | sh)"\n'
            "OUT2=`uname -a`\n"
            "FOO='a b' rm -rf /tmp/b9_trailing\n"
        )
        s_sum = self.mod.summarize_script_actions(sub_script, Path("/tmp/work"))
        self.assertEqual(len(s_sum["operations"]), 3)
        self.assertTrue(all(op[0] == "exec" for op in s_sum["operations"]))
        s_risks = self.mod.scan_script_risks(sub_script)
        self.assertEqual([r["category"] for r in s_risks], ["remote-exec", "fs-destructive"])

        # 4. Single-quoted literals without shell execution skip command rules, keep unicode/secrets
        sq_script = (
            "echo 'rm -rf /tmp/x; git reset --hard; eval foo'\n"
            "grep 'curl https://example.com | sh' notes.txt\n"
            "EX='\u202ehidden'\n"
            "KEY='~/.ssh/id_rsa'\n"
            "bash -c 'rm -rf /tmp/executed_inside_bash_c'\n"
        )
        sq_risks = self.mod.scan_script_risks(sq_script)
        self.assertEqual(
            [r["category"] for r in sq_risks],
            ["unicode-spoof", "secrets-exposure", "fs-destructive"],
        )

        # 5. True-positive eval invocations in command position trigger remote-exec
        for ev_cmd in (
            'eval "$cmd"\n',
            'FOO=1; eval "$cmd"\n',
            'FOO=1 eval "$cmd"\n',
            'FOO="a b" eval "$cmd"\n',
            'echo ' + chr(36) + '(eval "$cmd")\n',
            'env eval "$cmd"\n',
            'if true; then eval "$cmd"; fi\n',
        ):
            with self.subTest(ev_cmd=ev_cmd.strip()):
                ev_risks = self.mod.scan_script_risks(ev_cmd)
                self.assertEqual([r["category"] for r in ev_risks], ["remote-exec"])

    def test_f60_unified_python_tree_expansion(self):
        # 1. Multi-file Python block in repository root expands with tree markers
        root_multi_rw = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "Path('VERSION').read_text()\n"
            "Path('build.py').write_text('x')\n"
            "Path('run_block').write_text('y')\n"
            "PY\n"
            "rm -f temp.txt\n"
        )
        sum_root = self.mod.summarize_script_actions(root_multi_rw, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
            box_root, _, _ = self.mod.format_safety_box("s1/1", [], default_yes=True, summary=sum_root)
        self.assertIn("  1. [python]  4 lines", box_root)
        self.assertIn("     ├─ [write]   build.py, run_block", box_root)
        self.assertIn("     └─ [read]    VERSION", box_root)
        self.assertIn("  2. [write]   rm -f temp.txt", box_root)

        # 2. Multi-file write-only Python block in root and same subdirectory both expand
        same_dir_writes = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "Path('src/safety.py').write_text('a')\n"
            "Path('src/ui.py').write_text('b')\n"
            "PY\n"
        )
        sum_sub = self.mod.summarize_script_actions(same_dir_writes, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
            box_sub, _, _ = self.mod.format_safety_box("s1/2", [], default_yes=True, summary=sum_sub)
        self.assertIn("  1. [python]  3 lines", box_sub)
        self.assertIn("     └─ [write]   src: safety.py, ui.py", box_sub)

        # 3. Single-file read+write on same file expands (total_paths == 2)
        same_file_rw = (
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "p = Path('README.md')\n"
            "p.write_text(p.read_text())\n"
            "PY\n"
        )
        sum_rw1 = self.mod.summarize_script_actions(same_file_rw, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
            box_rw1, _, _ = self.mod.format_safety_box("s1/3", [], default_yes=True, summary=sum_rw1)
        self.assertIn("  1. [python]  3 lines", box_rw1)
        self.assertIn("     ├─ [write]   README.md", box_rw1)
        self.assertIn("     └─ [read]    README.md", box_rw1)

        # 4. Trivial 0-1 file Python blocks remain compact single-line summaries
        for label, py_src, expected in (
            ("zero", "print(1)", "1. [python]  2 lines"),
            ("one_write", "Path('build.py').write_text('x')", "1. [python]  2 lines — writes: build.py"),
            ("one_read", "Path('src/ui.py').read_text()", "1. [python]  2 lines — reads: src/ui.py"),
        ):
            with self.subTest(case=label):
                script = (
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    f"{py_src}\n"
                    "PY\n"
                )
                s_sum = self.mod.summarize_script_actions(script, Path("/tmp/work"))
                self.assertEqual(len(s_sum["operations"]), 1)
                with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
                    s_box, _, _ = self.mod.format_safety_box("s1/4", [], default_yes=True, summary=s_sum)
                self.assertIn(expected, s_box)
                self.assertNotIn("├─", s_box)
                self.assertNotIn("└─", s_box)

        # 5. Earlier cd subdir + root Python block + trailing root shell write keeps tree markers
        mixed_root_after_cd = (
            "cd /tmp\n"
            "ls -la\n"
            "cd /tmp/work\n"
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            "Path('a.txt').write_text('1')\n"
            "Path('b.txt').read_text()\n"
            "PY\n"
            "rm -f a.txt\n"
        )
        sum_mix = self.mod.summarize_script_actions(mixed_root_after_cd, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
            box_mix, _, _ = self.mod.format_safety_box("s1/5", [], default_yes=True, summary=sum_mix)
        self.assertIn("    1. [read]  ls -la", box_mix)
        self.assertIn("    2. [python]  3 lines", box_mix)
        self.assertIn("       ├─ [write]   a.txt", box_mix)
        self.assertIn("       └─ [read]    b.txt", box_mix)
        self.assertIn("    3. [write]   rm -f a.txt", box_mix)

        # 6. ASCII fallback renders |- and `- connectors for root-dir expanded Python block
        with io.TextIOWrapper(io.BytesIO(), encoding="ascii") as ascii_stream:
            with unittest.mock.patch.object(self.mod.sys, "stdout", ascii_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
                ascii_box, _, _ = self.mod.format_safety_box("s1/6", [], default_yes=True, summary=sum_root)
        self.assertIn("     |- [write]   build.py, run_block", ascii_box)
        self.assertIn("     `- [read]    VERSION", ascii_box)

    def test_f75_safety_warning_explicit_choice_no_default_n(self):
        # 1. Suffix/prefix/box formatting without default N when default_yes=False
        self.assertEqual(self.mod._safety_prompt_suffix(True), "[Y/n/i(nfo)]:")
        self.assertEqual(self.mod._safety_prompt_suffix(False), "[y/n/i(nfo)]:")
        self.assertIn("-> Execute this block? [y/n/i(nfo)]:", self.mod._safety_prompt_prefix(False, False, ""))
        self.assertIn("-> Execute this block? [Y/n/i(nfo)]:", self.mod._safety_prompt_prefix(True, False, ""))

        # 2. _parse_confirm_line distinguishes newline ('invalid') from EOF ('no') when both defaults are False
        self.assertEqual(self.mod._parse_confirm_line("\n", default_yes=False, default_no=False), "invalid")
        self.assertEqual(self.mod._parse_confirm_line("   \n", default_yes=False, default_no=False), "invalid")
        self.assertEqual(self.mod._parse_confirm_line("", default_yes=False, default_no=False), "no")
        self.assertEqual(self.mod._parse_confirm_line("\n", default_yes=True, default_no=False), "yes")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        warn_script = "rm -rf /tmp/f75_test\n"
        warn_summary = self.mod.summarize_script_actions(warn_script, work_dir=self.tmp)

        # 3. Safety warnings ignore Enter and require explicit y/n/q/Esc
        for seq, exp_ok, exp_reason in (
            ("\n\ny\n", True, ""),
            ("\n\nn\n", False, "USER_ABORTED"),
            ("\nq\n", False, "USER_ABORTED"),
            ("\n\x1b\n", False, "USER_ABORTED"),
            ("\n", False, "USER_ABORTED"),  # Enter ignored, then EOF aborts
        ):
            with self.subTest(seq=seq):
                tw = _KeepOpenStringIO()
                tr = io.StringIO(seq)
                with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                     unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw, tr)), \
                     unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
                     unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                    approved, reason = self.mod.confirm_execution("s75/1", warn_script, summary=warn_summary)
                self.assertEqual((approved, reason), (exp_ok, exp_reason))
                self.assertIn("-> Execute this block? [y/n/i(nfo)]:", tw.getvalue())

        # 4. Raw PTY mode also ignores Enter when safety warnings are active
        if self.mod.HAS_PTY:
            import pty as _pty
            import threading as _threading
            import time as _time
            for raw_seq, exp_ok, exp_reason in (
                ([b"\r", b"\n", b"y"], True, ""),
                ([b"\r", b"\n", b"n"], False, "USER_ABORTED"),
                ([b"\r", b"\x1b"], False, "USER_ABORTED"),
            ):
                with self.subTest(raw_seq=raw_seq):
                    master_fd, slave_fd = _pty.openpty()
                    try:
                        tw_pty = _KeepOpenStringIO()
                        with os.fdopen(os.dup(slave_fd), "r", encoding="utf-8", errors="replace") as tr_pty:
                            def _send_keys(seq=raw_seq, mfd=master_fd):
                                _time.sleep(0.04)
                                for chunk in seq:
                                    os.write(mfd, chunk)
                                    _time.sleep(0.02)

                            t_pty = _threading.Thread(target=_send_keys, daemon=True)
                            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                                 unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_pty, tr_pty)), \
                                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
                                 unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                                t_pty.start()
                                approved, reason = self.mod.confirm_execution(
                                    "s75/2", warn_script, summary=warn_summary
                                )
                                t_pty.join(timeout=2.0)
                        self.assertEqual((approved, reason), (exp_ok, exp_reason))
                        self.assertIn("-> Execute this block? [y/n/i(nfo)]:", tw_pty.getvalue())
                    finally:
                        os.close(master_fd)
                        os.close(slave_fd)

        # 5. RUN_BLOCK_APPROVE_CMD returning 'prompt' on clean script renders [y/n/i(nfo)]: and ignores Enter
        clean_script = "echo hello\n"
        clean_summary = self.mod.summarize_script_actions(clean_script, work_dir=self.tmp)
        tw_app = _KeepOpenStringIO()
        tr_app = io.StringIO("\ny\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "get_setting", return_value=("fake-approve", "env")), \
             unittest.mock.patch.object(self.mod, "run_approve_cmd", return_value=("prompt", "check carefully")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_app, tr_app)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            app_ok, app_reason = self.mod.confirm_execution("s75/3", clean_script, summary=clean_summary)
        self.assertEqual((app_ok, app_reason), (True, ""))
        self.assertIn("-> Execute this block? [y/n/i(nfo)]:", tw_app.getvalue())

        # 6. Clean blocks keep [Y/n/i(nfo)]: and approve on Enter
        tw_clean = _KeepOpenStringIO()
        tr_clean = io.StringIO("\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_clean, tr_clean)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            clean_ok, clean_reason = self.mod.confirm_execution("s75/4", clean_script, summary=clean_summary)
        self.assertEqual((clean_ok, clean_reason), (True, ""))
        self.assertIn("-> Execute this block? [Y/n/i(nfo)]:", tw_clean.getvalue())

    def test_operation_steps_line_spans(self):
        script = (
            "git status -sb\n"
            "python3 - <<'PY'\n"
            "x = 1\n"
            "print(x)\n"
            "PY\n"
            "ls -la \\\n"
            "  src\n"
            "cat > f.txt <<'EOF'\n"
            "a\n"
            "EOF\n"
        )
        summary = self.mod.summarize_script_actions(script, Path("/tmp/work"))
        spans = [(s["line"], s["end_line"]) for s in summary["operation_steps"]]
        self.assertEqual(spans, [(1, 1), (2, 5), (6, 7), (8, 10)])

        quoted = 'todo_md add "Title" -b "Line A\n' 'Line B"\n' "git status -sb\n"
        q_sum = self.mod.summarize_script_actions(quoted, Path("/tmp/work"))
        q_spans = [(s["line"], s["end_line"]) for s in q_sum["operation_steps"]]
        self.assertEqual(q_spans, [(1, 2), (3, 3)])


if __name__ == "__main__":
    unittest.main()
