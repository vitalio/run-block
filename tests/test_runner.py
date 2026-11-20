#!/usr/bin/env python3
"""Step execution, --plan, --fix chaining and AST validation, step collision renumbering, and --list/--show/--retry."""

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


class TestRunner(RunBlockTestCase):
    def test_plan_cli_and_headless_and_approve_cmd(self):
        import json
        r_plan = self._run(
            [str(SCRIPT), "--plan"],
            input="git status -sb\nrm -rf /tmp/x\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_plan.returncode, 0, r_plan.stderr)
        plan_data = json.loads(r_plan.stdout)
        self.assertTrue(plan_data["syntax_ok"])
        self.assertFalse(plan_data["safe"])
        self.assertEqual(plan_data["findings"][0]["category"], "fs-destructive")

        r_bad_plan = self._run(
            [str(SCRIPT), "--plan"],
            input="if true; then\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_bad_plan.returncode, 1)
        bad_data = json.loads(r_bad_plan.stdout)
        self.assertFalse(bad_data["syntax_ok"])

        r_headless = self._run(
            [str(SCRIPT), "-y", "s1/1"],
            input="echo headless_ok\n",
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(r_headless.returncode, 0)
        self.assertIn("[s1/1] START\n", r_headless.stdout)
        self.assertIn("headless_ok", r_headless.stdout)
        self.assertRegex(r_headless.stdout, r"\[s1/1\] END \([^)\n]+\)\n")
        self.assertNotIn("[END]", r_headless.stdout)

        env_reject = {**os.environ, "RUN_BLOCK_APPROVE_CMD": "echo 'Blocked by LLM policy' && exit 1"}
        r_rej = self._run(
            [str(SCRIPT), "-y", "s1/2"],
            input="echo should_not_run\n",
            capture_output=True,
            text=True,
            env=env_reject,
            check=False,
        )
        self.assertEqual(r_rej.returncode, 130)
        self.assertIn("NOT RUN: Blocked by LLM policy", r_rej.stdout)

        box, _, _ = self.mod.format_safety_box(
            "s1/3", [], default_yes=True, summary=self.mod.summarize_script_actions("ls -la\n"), note="LLM review: read-only ls"
        )
        self.assertIn("Analyzer:", box)
        self.assertIn("LLM review: read-only ls", box)

    def test_start_autoincrement(self):
        s1 = self.mod.start_session()
        s2 = self.mod.start_session()
        self.assertEqual(s1.name, "s1")
        self.assertEqual(s2.name, "s2")

    def test_normal_execution_and_duplicate_guard(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc1 = self.mod.cmd_normal("s1/1", "echo hello_world in_rb=$IN_RUN_BLOCK\n")
            self.assertEqual(rc1, 0)
            rc_dup = self.mod.cmd_normal("s1/1", "echo again\n")
            self.assertEqual(rc_dup, 2)
            rc_skip = self.mod.cmd_normal("s1/3", "echo step3\n")
            self.assertEqual(rc_skip, 2)
        self.assertTrue((self.tmp / "s1/1/block.sh").is_file())
        out1 = (self.tmp / "s1/1/out").read_text(encoding="utf-8")
        self.assertIn("hello_world in_rb=1", out1)
        self.assertIn("[s1/1] START\n", out1)
        self.assertRegex(out1, r"\[s1/1\] END \([^)\n]+\)\n")
        self.assertIn("╭─ END STEP ", buf.getvalue())
        self.assertIn("Step:    s1/1", buf.getvalue())
        self.assertIn("╭─ NOT RUN ", buf.getvalue())
        self.assertIn("Step:    s1/3", buf.getvalue())

    def test_failed_execution_and_chained_fixes(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal("s1/1", "echo bad_cmd\nexit 3\n")
            self.assertEqual(rc, 3)
            # 1st failed fix on s1/1: rich AssertionError diagnostics in s1/1_1.txt
            bad_fix = "old_3 = 'missing'\nassert text.count(old_3) == 2\n"
            self.assertEqual(self.mod.cmd_fix("s1/1", bad_fix), 2)
            # 2nd fix targets s1/1_1 (which was NOT RUN and had no script): falls back to 1.sh,
            # allocates s1/1_2 without overwriting s1/1_1.txt, and fails with exit 4 (reaching limit=2)
            fix1 = "text = text.replace('exit 3', 'exit 4')\n"
            self.assertEqual(self.mod.cmd_fix("s1/1_1", fix1), 4)
            # 3rd fix on s1/1 is rejected by the max-attempts loop guard
            self.assertEqual(self.mod.cmd_fix("s1/1", fix1), 2)

            # On s1/2: test chained fix and automatic latest-vs-base anchor resolution
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo bad2\nexit 3\n"), 3)
            self.assertEqual(self.mod.cmd_fix("s1/2", fix1), 4)
            fix2 = "assert text.count('exit 4') == 1\ntext = text.replace('exit 4', 'echo fixed_ok')\n"
            # Even when targeting base s1/2, anchor from 2_1.sh resolves against 2_1.sh -> 2_2.sh
            self.assertEqual(self.mod.cmd_fix("s1/2", fix2), 0)

        out_f1 = (self.tmp / "s1/1_1/out").read_text(encoding="utf-8")
        self.assertIn("at line 2: assert text.count(old_3) == 2 (actual: 0 == 2)", out_f1)
        out_f2 = (self.tmp / "s1/1_2/out").read_text(encoding="utf-8")
        self.assertIn("STOP --fix", out_f2)
        self.assertIn("s1/2", out_f2)
        out_f3 = (self.tmp / "s1/1_3/out").read_text(encoding="utf-8")
        self.assertIn("NOT RUN: STOP --fix", out_f3)
        self.assertIn("emit a fresh s1/2 block instead", out_f3)
        self.assertTrue((self.tmp / "s1/2_2/fix.py").is_file())
        self.assertTrue((self.tmp / "s1/2_2/block.sh").is_file())
        out_s2_f2 = (self.tmp / "s1/2_2/out").read_text(encoding="utf-8")
        self.assertIn("patched 2_1/block.sh -> 2_2/block.sh", out_s2_f2)
        self.assertIn("fixed_ok", out_s2_f2)

    def test_syntax_error_does_not_run(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal("s1/1", "if true; then\n")
        self.assertNotEqual(rc, 0)
        out = (self.tmp / "s1/1/out").read_text(encoding="utf-8")
        self.assertIn("END (syntax error", out)
        rendered = buf.getvalue()
        self.assertIn("╭─ SYNTAX ERROR ", rendered)
        self.assertIn("Step:    s1/1", rendered)
        self.assertNotIn("SYNTAX ERROR (", rendered)
        self.assertIn("Exit: ", rendered)
        self.assertIn("Script: ", rendered)
        self.assertIn("Output: ", rendered)
        self.assertIn("Error: ", rendered)
        box_lines = rendered.strip().splitlines()
        self.assertTrue(box_lines[0].startswith("╭─ SYNTAX ERROR ────"))
        self.assertEqual(box_lines[-1], "╰" + "─" * (len(box_lines[0]) - 1))
        self.assertIn("│ Exit:   ", rendered)
        self.assertIn("│ Output: ", rendered)

    def test_list_show_and_retry(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo first_step\n")
        r_list = self._run([str(SCRIPT), "--list"], capture_output=True, text=True, check=False)
        self.assertEqual(r_list.returncode, 0)
        self.assertIn("s1/1", r_list.stdout)
        self.assertRegex(r_list.stdout, r"END \([^)\n]+\)")

        r_show = self._run([str(SCRIPT), "--show", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_show.returncode, 0)
        self.assertIn("echo first_step", r_show.stdout)

        r_retry = self._run([str(SCRIPT), "--retry", "s1/1"], capture_output=True, text=True, check=False)
        self.assertEqual(r_retry.returncode, 0)
        self.assertIn("first_step", r_retry.stdout)

    def test_f61_step_collision_interactive_renumbering(self):
        # 1. next_free_step and first_missing_step scan existing step & fix directories cleanly
        s_scan = self.tmp / "s_scan"
        s_scan.mkdir(parents=True, exist_ok=True)
        self.assertEqual(self.mod.next_free_step(s_scan, min_step=1), 1)
        self.assertEqual(self.mod.first_missing_step(s_scan), 1)
        for d_name in ("1", "2", "8", "8_1"):
            (s_scan / d_name).mkdir()
        (s_scan / "1" / "block.sh").write_text("echo 1\n", encoding="utf-8")
        (s_scan / "2" / "out").write_text("ok\n", encoding="utf-8")
        self.assertEqual(self.mod.first_missing_step(s_scan), 3)
        (s_scan / "2" / "aborted").write_text("", encoding="utf-8")
        self.assertEqual(self.mod.first_missing_step(s_scan), 2)
        self.assertEqual(self.mod.next_free_step(s_scan, min_step=9), 9)
        self.assertEqual(self.mod.next_free_step(s_scan, min_step=3), 9)

        # 2. prompt_yes_no_box handles case-insensitive r/R -> renumber, copy_on_yes, and renumber_only (no Enter default)
        for r_key in ("r\n", "R\n"):
            with self.subTest(r_key=r_key):
                tty_w_r = io.StringIO()
                tty_r_r = io.StringIO(r_key)
                res_renum = self.mod.prompt_yes_no_box(
                    "STEP ALREADY EXISTS",
                    ["Step: s154/8", "", "Next: s154/9"],
                    "Renumber to s154/9?",
                    default_yes=False,
                    no_status="✗ Keeping existing s154/8.",
                    tty_streams=(tty_w_r, tty_r_r),
                    renumber_label="s154/9",
                    renumber_status="✓ Renumbering s154/8 -> s154/9.",
                    renumber_only=True,
                )
                self.assertEqual(res_renum, "renumber")
                out_r_text = tty_w_r.getvalue()
                self.assertIn("-> Renumber to s154/9? [r(enumber)/n/i(nfo)]:", out_r_text)
                self.assertIn("✓ Renumbering s154/8 -> s154/9.", out_r_text)

        # renumber_only ignores Enter and 'y' (requires explicit r or n/Esc)
        tty_w_no_def = io.StringIO()
        tty_r_no_def = io.StringIO("\ny\nr\n")
        res_no_def = self.mod.prompt_yes_no_box(
            "STEP ALREADY EXISTS",
            ["Step: s154/8", "", "Next: s154/9"],
            "Renumber to s154/9?",
            default_yes=False,
            tty_streams=(tty_w_no_def, tty_r_no_def),
            renumber_label="s154/9",
            renumber_only=True,
        )
        self.assertEqual(res_no_def, "renumber")

        class _NoCloseStringIO(io.StringIO):
            def close(self) -> None:
                pass

        # 3. End-to-end cmd_normal collision: choosing 'r' preserves s154/8, runs as s154/9, and writes renumber Note in out
        s154 = self.tmp / "s154"
        s154.mkdir(parents=True, exist_ok=True)
        for idx in range(1, 9):
            with contextlib.redirect_stdout(io.StringIO()):
                rc_init = self.mod.cmd_normal(f"s154/{idx}", f"echo original_step_{idx}\n", auto_yes=True)
            self.assertEqual(rc_init, 0)
        orig_8_script = (s154 / "8" / "block.sh").read_text(encoding="utf-8")
        orig_8_out = (s154 / "8" / "out").read_text(encoding="utf-8")

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w_coll = _NoCloseStringIO()
        tty_r_coll = io.StringIO("r\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_coll, tty_r_coll)), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)) as mock_exec, \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_renum = self.mod.cmd_normal(
                "s154/8",
                "# Block: s154/8\necho renumbered_to_nine\n",
                auto_yes=False,
            )
        self.assertEqual(rc_renum, 0)
        self.assertEqual(mock_exec.call_args[0][0], "s154/9")
        self.assertIn("# Block: s154/9", mock_exec.call_args[0][1])
        self.assertEqual((s154 / "8" / "block.sh").read_text(encoding="utf-8"), orig_8_script)
        self.assertEqual((s154 / "8" / "out").read_text(encoding="utf-8"), orig_8_out)
        self.assertTrue((s154 / "9" / "block.sh").is_file())
        out_9 = (s154 / "9" / "out").read_text(encoding="utf-8")
        self.assertIn("[s154/9] START", out_9)
        self.assertIn("[s154/9] Note: renumbered from s154/8 to s154/9; continue from s154/9.", out_9)
        self.assertIn("renumbered_to_nine", out_9)
        self.assertIn("[s154/9] END", out_9)
        meta_9 = self.mod.read_step_meta(s154 / "9")
        self.assertEqual(meta_9.get("renumbered_from"), "s154/8")
        self.assertIn("-> Copy out to clipboard? [Y/n/r(enumber)/i(nfo)]:", tty_w_coll.getvalue())
        self.assertIn("✓ Renumbering s154/8 -> s154/9.", tty_w_coll.getvalue())

        # 4. Choosing Enter on STEP ALREADY EXISTS (with out) copies existing out to clipboard and exits 0
        tty_w_cp = _NoCloseStringIO()
        tty_r_cp = io.StringIO("\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], "pbcopy < out")), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_cp, \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_cp, tty_r_cp)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_cp = self.mod.cmd_normal("s154/8", "echo should_not_overwrite\n", auto_yes=False)
        self.assertEqual(rc_cp, 0)
        mock_cp.assert_called_once_with(["pbcopy"], s154 / "8" / "out")
        self.assertEqual((s154 / "8" / "out").read_text(encoding="utf-8"), orig_8_out)

        # 5. STEP ALREADY EXISTS when out is missing prompts [r(enumber)/n/i(nfo)]: with no Enter default
        (s154 / "10").mkdir()
        (s154 / "10" / "block.sh").write_text("echo partial\n", encoding="utf-8")
        tty_w_noout = _NoCloseStringIO()
        tty_r_noout = io.StringIO("r\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_noout, tty_r_noout)), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_noout = self.mod.cmd_normal("s154/10", "echo moved_to_11\n", auto_yes=False)
        self.assertEqual(rc_noout, 0)
        self.assertIn("-> Renumber to s154/11? [r(enumber)/n/i(nfo)]:", tty_w_noout.getvalue())
        self.assertIn("[s154/11] Note: renumbered from s154/10 to s154/11; continue from s154/11.", (s154 / "11" / "out").read_text(encoding="utf-8"))

        # 6. MISSING PREVIOUS STEP renumbers to first_missing_step (s154/14 -> s154/12) and writes Note in out
        tty_w_mp = _NoCloseStringIO()
        tty_r_mp = io.StringIO("r\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_mp, tty_r_mp)), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            rc_mp = self.mod.cmd_normal("s154/14", "# Block: s154/14\necho gap_filled\n", auto_yes=False)
        self.assertEqual(rc_mp, 0)
        mp_tty = tty_w_mp.getvalue()
        self.assertIn("Missing: s154/13", mp_tty)
        self.assertIn("Next:    s154/12", mp_tty)
        self.assertIn("-> Renumber to s154/12? [r(enumber)/n/i(nfo)]:", mp_tty)
        out_12 = (s154 / "12" / "out").read_text(encoding="utf-8")
        self.assertIn("[s154/12] Note: renumbered from s154/14 to s154/12; continue from s154/12.", out_12)
        self.assertEqual(self.mod.read_step_meta(s154 / "12").get("renumbered_from"), "s154/14")

        # 7. Embedded rules instruct agents to continue from renumbered step
        for rule_rel in ("src/rules/blocks/bash.md", "src/rules/blocks/pwsh.md"):
            rule_txt = (ROOT / rule_rel).read_text(encoding="utf-8")
            self.assertIn("Note: renumbered from <session>/<old> to <session>/<new>", rule_txt)

    def test_fix_ast_validation_and_bundle_tamper_revert(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.mod.cmd_normal("s1/1", "echo safe_step_1\n")
        # 1. Unsafe --fix constructs must be rejected before exec()
        marker = self.tmp / "pwned.txt"
        for unsafe_fix in (
            f"import os\nos.system('touch {marker}')\n",
            f"__import__('os').system('touch {marker}')\n",
            "text = text.__class__.__name__\n",
            f"open('{marker}', 'w').write('x')\n",
        ):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.mod.cmd_fix("s1/1", unsafe_fix, auto_yes=True)
            self.assertEqual(rc, 2)
            self.assertIn("NOT RUN: unsafe construct in --fix", buf.getvalue())
            self.assertFalse(marker.exists())
            shutil.rmtree(self.tmp / "s1/1_1", ignore_errors=True)

        # 2. Tampering with 0 inside a running block must be automatically reverted
        bundle_file = self.tmp / "s1/0"
        orig_bundle = bundle_file.read_text(encoding="utf-8")
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = self.mod.cmd_normal(
                "s1/2",
                f"echo 'Sandbox: off' > {bundle_file}\n",
                auto_yes=True,
            )
        self.assertEqual(rc2, 0)
        self.assertEqual(bundle_file.read_text(encoding="utf-8"), orig_bundle)
        self.assertIn("SECURITY WARNING: block attempted to modify 0 (reverted)", buf2.getvalue())

    def test_b5_python_stdin_traceback_and_enriched_end_not_run_boxes(self):
        # 1. Embedded python3 heredoc failure resolves File "<stdin>", line <N> into output before END
        py_fail_script = (
            "python3 - <<'PY'\n"
            "def compute():\n"
            "    items = [10, 20]\n"
            "    return items[5]\n"
            "compute()\n"
            "PY\n"
        )
        buf_end = io.StringIO()
        with contextlib.redirect_stdout(buf_end):
            rc = self.mod.cmd_normal("s1/1", py_fail_script)
        self.assertEqual(rc, 1)
        out_txt = (self.tmp / "s1/1/out").read_text(encoding="utf-8")
        self.assertIn("[s1/1] <stdin> line 4: compute()", out_txt)
        self.assertIn("[s1/1] <stdin> line 3: return items[5]", out_txt)
        self.assertRegex(out_txt, r"\[s1/1\] END \(exit 1, [^)\n]+\)")
        self.assertLess(out_txt.index("[s1/1] <stdin> line 3: return items[5]"), out_txt.index("[s1/1] END (exit 1,"))

        # END box displays Error: <last_error_line> and Fix: status line
        end_rendered = buf_end.getvalue()
        self.assertIn("╭─ END STEP ", end_rendered)
        self.assertIn("Exit:   1", end_rendered)
        self.assertIn("Error:  IndexError: list index out of range", end_rendered)
        self.assertIn(f"Fix:    {self.mod.prog_name()} --fix s1/1 (0/2 failed attempts)", end_rendered)

        # 2. Failed --fix NOT RUN box shows Target: <session>/<target> -> <label> and clean Guard: line
        buf_fix1 = io.StringIO()
        with contextlib.redirect_stdout(buf_fix1):
            rc_f1 = self.mod.cmd_fix("s1/1", "assert text.count('nonexistent') == 1\n")
        self.assertEqual(rc_f1, 2)
        f1_rendered = buf_fix1.getvalue()
        self.assertIn("╭─ NOT RUN ", f1_rendered)
        self.assertIn("Target: s1/1 -> s1/1_1", f1_rendered)
        self.assertIn("Reason: fix raised AssertionError at line 1:", f1_rendered)
        self.assertNotIn("Guard:", f1_rendered)

        # 3. Second failed --fix reaches max attempts (2/2): Guard: line has no duplicate [s1/1_2] prefix in box,
        # while clipboard file retains full [s1/1_2] STOP --fix directive
        buf_fix2 = io.StringIO()
        with contextlib.redirect_stdout(buf_fix2):
            rc_f2 = self.mod.cmd_fix("s1/1_1", "text = text\n")
        self.assertEqual(rc_f2, 2)
        f2_rendered = buf_fix2.getvalue()
        self.assertIn("Target: s1/1_1 -> s1/1_2", f2_rendered)
        self.assertIn(
            "Guard:  reached 2/2 failed --fix attempts for s1/1; switch to a fresh s1/2 block instead.",
            re.sub(r"\n│\s+", " ", f2_rendered),
        )
        self.assertNotIn("[s1/1_2] STOP --fix:", f2_rendered)
        f2_clip = (self.tmp / "s1/1_2/out").read_text(encoding="utf-8")
        self.assertIn("[s1/1_2] STOP --fix: reached 2/2 failed --fix attempts for s1/1", f2_clip)

        # 4. END box after exhausting --fix attempts shows STOP --fix guard state in Fix:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_normal("s1/2", "echo boom\nexit 5\n", auto_yes=True), 5)
            self.assertEqual(self.mod.cmd_fix("s1/2", "text = text.replace('exit 5', 'exit 6')\n", auto_yes=True), 6)
        buf_end_stop = io.StringIO()
        with contextlib.redirect_stdout(buf_end_stop):
            rc_f2_run = self.mod.cmd_fix("s1/2_1", "text = text.replace('exit 6', 'exit 7')\n")
        self.assertEqual(rc_f2_run, 7)
        end_stop_rendered = buf_end_stop.getvalue()
        self.assertIn("Error:  boom", end_stop_rendered)
        self.assertIn("Fix:    STOP --fix (2/2 failed attempts; emit a fresh s1/3 block instead)", end_stop_rendered)

    def test_f29_operation_step_lines_and_instrumented_scripts(self):
        # 1. Top-level line mapping keeps nested Python AST sub-entries under parent Python step
        many_src = ", ".join(f'"src/f{i}.py"' for i in range(6))
        many_tests = ", ".join(f'"tests/t{i}.py"' for i in range(6))
        script = (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "echo starting\n"
            "git status \\\n"
            "  --porcelain\n"
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"for p in ({many_src}):\n"
            "    Path(p).write_text('x')\n"
            f"for t in ({many_tests}):\n"
            "    Path(t).read_text()\n"
            "PY\n"
            "cat <<'EOF' > note.txt\n"
            "hello\n"
            "EOF\n"
            "if [ -d src ]; then\n"
            "  ls -la src\n"
            "fi\n"
            "rm -f note.txt\n"
        )
        summary = self.mod.summarize_script_actions(script, Path("/tmp/work"))
        steps = summary["operation_steps"]
        self.assertEqual([s["step"] for s in steps], [1, 2, 3, 4, 5])
        self.assertEqual([s["tag"] for s in steps], ["git", "python", "write", "read", "write"])
        self.assertEqual([s["line"] for s in steps], [4, 6, 13, 17, 19])
        # Nested Python AST sub-entries are still in operations, without extra step numbers
        self.assertGreater(len(summary["operations"]), len(steps))

        # 2. Bash instrumentation emits markers before top-level ops, skips heredocs/continuations/if-bodies, and passes bash -n
        inst_bash = self.mod.instrument_script_for_progress(script, is_powershell=False)
        ok_syn, syn_err, _ = self.mod.check_script_syntax(inst_bash, self.tmp)
        self.assertTrue(ok_syn, syn_err)
        self.assertIn("printf '%s\\n' '__RB_STEP__:1'\ngit status \\\n  --porcelain", inst_bash)
        self.assertIn("printf '%s\\n' '__RB_STEP__:2'\npython3 - <<'PY'", inst_bash)
        self.assertIn("printf '%s\\n' '__RB_STEP__:3'\ncat <<'EOF' > note.txt", inst_bash)
        self.assertNotIn("__RB_STEP__:4", inst_bash)
        self.assertIn("printf '%s\\n' '__RB_STEP__:5'\nrm -f note.txt", inst_bash)

        # Executing instrumented bash script emits step markers in order without breaking heredocs or continuations
        (self.tmp / "src").mkdir(exist_ok=True)
        (self.tmp / "tests").mkdir(exist_ok=True)
        for i in range(6):
            (self.tmp / f"tests/t{i}.py").write_text("ok", encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-c", "git() { echo GIT_OK; }; rm() { echo RM_OK; }; " + inst_bash],
            cwd=str(self.tmp),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        markers = [ln for ln in proc.stdout.splitlines() if ln.startswith("__RB_STEP__:")]
        self.assertEqual(markers, ["__RB_STEP__:1", "__RB_STEP__:2", "__RB_STEP__:3", "__RB_STEP__:5"])

        # 3. Multiline python3 -c, for/while/case bodies are safely skipped and valid syntax
        complex_bash = (
            "python3 -c '\n"
            "x = 1\n"
            "print(x)\n"
            "'\n"
            "for item in a b; do\n"
            "  cat missing_or_ok\n"
            "done\n"
            "case x in\n"
            "  x)\n"
            "    ls\n"
            "    ;;\n"
            "esac\n"
            "while false; do\n"
            "  rm -f x\n"
            "done\n"
            "git status -sb\n"
        )
        inst_complex = self.mod.instrument_script_for_progress(complex_bash, is_powershell=False)
        ok_c, err_c, _ = self.mod.check_script_syntax(inst_complex, self.tmp)
        self.assertTrue(ok_c, err_c)
        self.assertIn("printf '%s\\n' '__RB_STEP__:1'\npython3 -c '", inst_complex)
        self.assertIn("printf '%s\\n' '__RB_STEP__:7'\ngit status -sb", inst_complex)
        for skipped in ("__RB_STEP__:2", "__RB_STEP__:3", "__RB_STEP__:4", "__RB_STEP__:5", "__RB_STEP__:6"):
            self.assertNotIn(skipped, inst_complex)

        # 4. PowerShell instrumentation skips here-strings, backtick continuations, and brace blocks
        ps_script = (
            "git status `\n"
            "  --porcelain\n"
            "if (Test-Path src) {\n"
            "  ls src\n"
            "}\n"
            "cat <<'EOF' > out.txt\n"
            "body\n"
            "EOF\n"
            "rm -f out.txt\n"
        )
        inst_ps = self.mod.instrument_script_for_progress(ps_script, is_powershell=True)
        self.assertIn("Write-Output '__RB_STEP__:1'\ngit status `", inst_ps)
        self.assertNotIn("__RB_STEP__:2", inst_ps)
        self.assertNotIn("__RB_STEP__:4", inst_ps)
        self.assertIn("Write-Output '__RB_STEP__:5'\ncat <<'EOF' > out.txt", inst_ps)
        self.assertIn("Write-Output '__RB_STEP__:6'\nrm -f out.txt", inst_ps)

    def test_f30_numbered_block_plan_and_live_progress_execution(self):
        # 1. PLAN numbers top-level operations and keeps Python AST sub-entries unnumbered
        many_src = ", ".join(f'"src/f{i}.py"' for i in range(6))
        many_tests = ", ".join(f'"tests/t{i}.py"' for i in range(6))
        script_num = (
            "git status -sb\n"
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"for p in ({many_src}):\n"
            "    Path(p).write_text('x')\n"
            f"for t in ({many_tests}):\n"
            "    Path(t).read_text()\n"
            "PY\n"
            "rm -f note.txt\n"
        )
        sum_num = self.mod.summarize_script_actions(script_num, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
            box_num, _, _ = self.mod.format_safety_box("s1/1", [], default_yes=True, summary=sum_num)
        self.assertIn("  1. [git]     git status -sb", box_num)
        self.assertIn("  2. [python]  5 lines", box_num)
        self.assertIn("     ├─ [write]   src: f0.py", box_num)
        self.assertIn("     └─ [read]    tests: t0.py", box_num)
        self.assertIn("  3. [write]   rm -f note.txt", box_num)

        # 2. RUN_BLOCK_PROGRESS config setting
        os.environ.pop("RUN_BLOCK_PROGRESS", None)
        self.assertEqual(self.mod.get_setting("progress"), ("true", "default"))
        os.environ["RUN_BLOCK_PROGRESS"] = "0"
        self.assertEqual(self.mod.get_setting("progress"), ("false", "env"))
        os.environ.pop("RUN_BLOCK_PROGRESS", None)

        # 3. End-to-end interactive execution emits live progress and filters markers from out
        work = self.tmp / "f30_work"
        work.mkdir()
        (work / "a.txt").write_text("alpha\n", encoding="utf-8")
        (work / "b.txt").write_text("beta\n", encoding="utf-8")
        sdir = self.tmp / "s30"
        step1_dir = sdir / "1"
        step1_dir.mkdir(parents=True)
        script_p = step1_dir / "block.sh"
        out_p = step1_dir / "out"
        script_p.write_text("cat a.txt\ncat b.txt\n", encoding="utf-8")
        os.environ["RUN_BLOCK_CWD"] = str(work)
        buf_live = io.StringIO()
        buf_live.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", buf_live), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")), \
             unittest.mock.patch.object(self.mod, "offer_clipboard_copy"):
            rc_live = self.mod.run_script("s30/1", script_p, out_p, auto_yes=False)
        self.assertEqual(rc_live, 0)
        live_stdout = buf_live.getvalue()
        self.assertIn("[1/2] [read] cat a.txt", live_stdout)
        self.assertIn("[2/2] [read] cat b.txt", live_stdout)
        self.assertNotIn("__RB_STEP__:", live_stdout)
        saved_out = out_p.read_text(encoding="utf-8")
        self.assertIn("alpha\nbeta\n", saved_out)
        self.assertNotIn("__RB_STEP__:", saved_out)
        self.assertNotIn("[1/2]", saved_out)
        self.assertEqual(list(step1_dir.glob(".progress_*")), [])

        # 4. RUN_BLOCK_PROGRESS=0 opts out of instrumentation
        step2_dir = sdir / "2"
        step2_dir.mkdir(parents=True)
        script_p2 = step2_dir / "block.sh"
        out_p2 = step2_dir / "out"
        script_p2.write_text("cat a.txt\n", encoding="utf-8")
        os.environ["RUN_BLOCK_PROGRESS"] = "0"
        buf_optout = io.StringIO()
        buf_optout.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", buf_optout), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")), \
             unittest.mock.patch.object(self.mod, "offer_clipboard_copy"):
            rc_optout = self.mod.run_script("s30/2", script_p2, out_p2, auto_yes=False)
        self.assertEqual(rc_optout, 0)
        self.assertNotIn("[1/1]", buf_optout.getvalue())
        self.assertIn("alpha", out_p2.read_text(encoding="utf-8"))
        os.environ.pop("RUN_BLOCK_PROGRESS", None)

        # 5. Fallback to original script when instrumented copy fails syntax validation
        step3_dir = sdir / "3"
        step3_dir.mkdir(parents=True)
        script_p3 = step3_dir / "block.sh"
        out_p3 = step3_dir / "out"
        script_p3.write_text("cat a.txt\n", encoding="utf-8")
        buf_fb = io.StringIO()
        buf_fb.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", buf_fb), \
             unittest.mock.patch.object(self.mod, "instrument_script_for_progress", return_value="if true; then\n"), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")), \
             unittest.mock.patch.object(self.mod, "offer_clipboard_copy"):
            rc_fb = self.mod.run_script("s30/3", script_p3, out_p3, auto_yes=False)
        self.assertEqual(rc_fb, 0)
        self.assertIn("alpha", out_p3.read_text(encoding="utf-8"))
        self.assertEqual(list(step3_dir.glob(".progress_*")), [])

        # 6. Help and README document RUN_BLOCK_PROGRESS
        r_help = self._run([str(SCRIPT), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r_help.returncode, 0, r_help.stderr)
        self.assertIn("RUN_BLOCK_PROGRESS", r_help.stdout)
        self.assertIn("RUN_BLOCK_PROGRESS", (ROOT / "README.md").read_text(encoding="utf-8"))

    def test_b7_separate_stderr_capture_and_error_line(self):
        # stderr diagnostic printed mid-run followed by more stdout must win in END Error:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = self.mod.cmd_normal(
                "s1/1", "echo out_before\necho err_diag >&2\necho out_after\nexit 3\n"
            )
        self.assertEqual(rc, 3)
        out_txt = (self.tmp / "s1/1/out").read_text(encoding="utf-8")
        for needle in ("out_before", "err_diag", "out_after"):
            with self.subTest(needle=needle):
                self.assertIn(needle, out_txt)
        self.assertEqual((self.tmp / "s1/1/err").read_text(encoding="utf-8"), "err_diag\n")
        self.assertIn("Error:  err_diag", buf.getvalue())
        self.assertNotIn("Error:  out_after", buf.getvalue())

        # Without stderr output: no err file, Error: falls back to the last line of out
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            rc2 = self.mod.cmd_normal("s1/2", "echo only_out\nexit 4\n")
        self.assertEqual(rc2, 4)
        self.assertFalse((self.tmp / "s1/2/err").exists())
        self.assertIn("Error:  only_out", buf2.getvalue())

        # Retry of a step that no longer writes to stderr removes the stale err file
        (self.tmp / "s1/2/err").write_text("stale\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.mod.cmd_retry("s1/2", auto_yes=True), 4)
        self.assertFalse((self.tmp / "s1/2/err").exists())

        # Direct helper: prefers err, ignores blank trailing lines, falls back to out
        step = self.tmp / "s7/1"
        step.mkdir(parents=True)
        (step / "out").write_text("[s7/1] START\n\nlast_out\n\n[s7/1] END (exit 1)\n", encoding="utf-8")
        self.assertEqual(self.mod._extract_last_error_line(step / "out", label="s7/1"), "last_out")
        (step / "err").write_text("first_err\nlast_err\n\n", encoding="utf-8")
        self.assertEqual(self.mod._extract_last_error_line(step / "out", label="s7/1"), "last_err")
        (step / "err").write_text("\n  \n", encoding="utf-8")
        self.assertEqual(self.mod._extract_last_error_line(step / "out", label="s7/1"), "last_out")

    def test_f51_block_plan_edit_backup_recalc_and_syntax_error(self):
        # 1. START STEP prompt shows i(nfo), keeps d(etails) as alias
        self.assertEqual(self.mod._safety_prompt_suffix(True), "[Y/n/i(nfo)]:")
        self.assertEqual(self.mod._safety_prompt_suffix(False), "[y/n/i(nfo)]:")
        self.assertEqual(
            self.mod.read_confirm_key(io.StringIO("i\n"), default_yes=True, extra_keys={"i": "info", "d": "info"}),
            "info",
        )
        self.assertEqual(
            self.mod.read_confirm_key(io.StringIO("d\n"), default_yes=True, extra_keys={"i": "info", "d": "info"}),
            "info",
        )

        # 2. First edit creates block.orig.sh, subsequent edit preserves block.orig.sh,
        #    recomputes operations/stats/warnings/default_yes, and redraws PLAN with (edited)
        work = self.tmp / "f51_work"
        work.mkdir()
        sdir = self.tmp / "s1"
        step1 = sdir / "1"
        step1.mkdir(parents=True)
        script_path = step1 / "block.sh"
        orig_path = step1 / "block.orig.sh"
        initial_script = "echo safe\nls -la\n"
        script_path.write_text(initial_script, encoding="utf-8")

        initial_summary = self.mod.summarize_script_actions(initial_script, work_dir=work)
        initial_summary["sandbox"] = "off"
        edit_1_script = "cat README.md\nrm -rf /tmp/f51_danger\n"
        edit_2_script = "cat README.md\ngit status -sb\nrm -rf /tmp/f51_danger_2\n"
        edits_iter = iter([edit_1_script, edit_2_script])

        def fake_editor(p: Path, _r, _w) -> None:
            p.write_text(next(edits_iter), encoding="utf-8")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        # Press 'i' to open i(nfo), 'e' twice to edit (creating block.orig.sh once),
        # 'q' to return to START STEP (now [y/n/i(nfo)]:), then 'y' to approve.
        tty_r = io.StringIO("i\ne\ne\nq\ny\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_editor), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            approved, reason = self.mod.confirm_execution(
                "s1/1", initial_script, summary=initial_summary, script_path=script_path
            )
        self.assertTrue(approved)
        self.assertEqual(reason, "")
        self.assertTrue(orig_path.is_file())
        self.assertEqual(orig_path.read_text(encoding="utf-8"), initial_script)
        self.assertEqual(script_path.read_text(encoding="utf-8"), edit_2_script)

        tty_out = tty_w.getvalue()
        self.assertEqual(tty_out.count("╭─ START STEP "), 2)
        self.assertEqual(tty_out.count("╭─ INFO · s1/1 "), 3)
        self.assertIn("Original Plan (block.orig.sh):", tty_out)
        self.assertIn("-> Execute this block? [Y/n/i(nfo)]:", tty_out)
        self.assertIn("-> Execute this block? [y/n/i(nfo)]:", tty_out)
        self.assertIn("Safety warnings (1):", tty_out)
        self.assertIn("[fs-destructive]", tty_out)
        self.assertIn("rm -rf /tmp/f51_danger_2", tty_out)
        self.assertIn("(edited)", tty_out)

        sum1 = self.mod.summarize_script_actions(edit_1_script, work_dir=work)
        sum2 = self.mod.summarize_script_actions(edit_2_script, work_dir=work)
        self.assertIn(str(sum1["meta"]), tty_out)
        self.assertIn(f"{sum2['meta']} (edited)", tty_out)

        # --show notes the original backup
        buf_show = io.StringIO()
        with contextlib.redirect_stdout(buf_show):
            rc_show = self.mod.cmd_show("s1/1")
        self.assertEqual(rc_show, 0)
        self.assertIn(f"(edited) (original: {orig_path})", buf_show.getvalue())

        # 3. Post-edit syntax error shows SYNTAX ERROR and aborts execution
        step2 = sdir / "2"
        step2.mkdir(parents=True)
        bad_script_p = step2 / "block.sh"
        bad_out_p = step2 / "out"
        bad_script_p.write_text("echo ok\n", encoding="utf-8")

        def inject_syntax_error(_label, _txt, summary=None, script_path=None, auto_yes=False):
            script_path.write_text("if true; then\n", encoding="utf-8")
            return True, ""

        os.environ["RUN_BLOCK_CWD"] = str(work)
        buf_syn = io.StringIO()
        with unittest.mock.patch.object(self.mod, "confirm_execution", side_effect=inject_syntax_error), \
             contextlib.redirect_stdout(buf_syn):
            rc_syn = self.mod.run_script("s1/2", bad_script_p, bad_out_p, auto_yes=False)
        self.assertNotEqual(rc_syn, 0)
        self.assertIn("╭─ SYNTAX ERROR ", buf_syn.getvalue())
        self.assertIn("END (syntax error", bad_out_p.read_text(encoding="utf-8"))

        # 4. PowerShell backup uses .orig.ps1
        ps_path = step2 / "block.ps1"
        self.assertEqual(self.mod._orig_backup_path(ps_path), step2 / "block.orig.ps1")

    def test_f52_end_output_edit_backup_recalc_and_show_markers(self):
        # 1. END STEP prompt unifies behind i(nfo)
        f = self.tmp / "s1" / "1" / "out"
        f.parent.mkdir(parents=True, exist_ok=True)
        initial_out = "[s1/1] START\nnoisy stderr line\n\n[s1/1] END (exit 2)\n"
        f.write_text(initial_out, encoding="utf-8")
        err_f = f.with_name("err")
        err_f.write_text("noisy stderr line\n", encoding="utf-8")

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
            end_box, _, _ = self.mod.format_clipboard_box("s1/1", f, ok=False, rc=2, stats=self.mod.stats_line(f))
            self.assertIn("-> Copy to clipboard? [Y/n/i(nfo)]:", end_box)
            self.assertIn("Error:  noisy stderr line", end_box)

        # 2. Inside END STEP i(nfo), e(dit) creates out.orig and o(utput) preserves out.orig;
        #    recomputes stats_line(), re-extracts Error: from edited out (not stale err),
        #    refreshes resolve_clipboard_target(), and redraws END STEP with (edited)
        attach_file = self.tmp / "attached_report.txt"
        attach_file.write_text("attached report body\nline 2\n", encoding="utf-8")
        edit_1_out = "[s1/1] START\ntrimmed detail\ncleaned failure reason\n\n[s1/1] END (exit 2)\n"
        edit_2_out = (
            "[s1/1] START\ntrimmed detail\n"
            f"Bundle: {attach_file}\nupdated final error\n\n[s1/1] END (exit 2)\n"
        )
        edits_iter = iter([edit_1_out, edit_2_out])

        def fake_end_editor(p: Path, _r, _w) -> None:
            p.write_text(next(edits_iter), encoding="utf-8")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        tty_r = io.StringIO("i\ne\no\nq\n\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", side_effect=lambda p: (["pbcopy"], f"pbcopy < {p}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_end_editor), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy, \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((120, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy("s1/1", f, ok=False, rc=2)

        orig_out = f.with_name("out.orig")
        self.assertTrue(orig_out.is_file())
        self.assertEqual(orig_out.read_text(encoding="utf-8"), initial_out)
        self.assertEqual(f.read_text(encoding="utf-8"), edit_2_out)
        mock_copy.assert_called_once_with(["pbcopy"], attach_file)

        tty_out = tty_w.getvalue()
        self.assertEqual(tty_out.count("╭─ END STEP "), 2)
        self.assertEqual(tty_out.count("╭─ INFO · s1/1 "), 3)
        self.assertIn("Error:  noisy stderr line", tty_out)
        self.assertIn("Error:       cleaned failure reason", tty_out)
        self.assertIn("Error:  updated final error", tty_out)
        self.assertIn(f"Output: {attach_file}", tty_out)
        attach_stats = self.mod.stats_line(attach_file)
        assert attach_stats is not None
        self.assertIn(f"Stats:  {attach_stats} (edited)", tty_out)
        self.assertIn(f"✓ Copied {attach_file} to clipboard.", tty_out)

        # 3. START SESSION preserves 0.orig on first e(dit) inside i(nfo) without overwriting on subsequent edits
        b0 = self.tmp / "s1" / "0"
        initial_0 = "Session: s1\nNext-Block: s1/1\n\nInitial bundle\n"
        b0.write_text(initial_0, encoding="utf-8")
        b0_edits = iter([initial_0 + "Edit 1\n", initial_0 + "Edit 2\n"])
        tty_w0 = _KeepOpenStringIO()
        tty_r0 = io.StringIO("i\ne\ne\nq\nesc\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w0, tty_r0)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=lambda p, _r, _w: p.write_text(next(b0_edits), encoding="utf-8")), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy("s1/0", b0, title_kind="START SESSION", extra_lines=[f"Bundle: {b0}"])

        orig_0 = self.tmp / "s1" / "0.orig"
        self.assertTrue(orig_0.is_file())
        self.assertEqual(orig_0.read_text(encoding="utf-8"), initial_0)
        self.assertIn("(edited)", tty_w0.getvalue())

        # 4. --show surfaces (edited) markers for 0.orig, block.orig.*, and out.orig
        buf_show0 = io.StringIO()
        with contextlib.redirect_stdout(buf_show0):
            self.assertEqual(self.mod.cmd_show("s1/0"), 0)
        self.assertIn(f"(edited) (original: {orig_0})", buf_show0.getvalue())

        b_script = self.tmp / "s1" / "1" / "block.sh"
        b_script.write_text("echo edited\n", encoding="utf-8")
        b_orig = self.tmp / "s1" / "1" / "block.orig.sh"
        b_orig.write_text("echo orig\n", encoding="utf-8")
        buf_show1 = io.StringIO()
        with contextlib.redirect_stdout(buf_show1):
            self.assertEqual(self.mod.cmd_show("s1/1"), 0)
        show1_out = buf_show1.getvalue()
        self.assertIn(f"Script: {b_script}", show1_out)
        self.assertIn(f"(edited) (original: {b_orig})", show1_out)
        self.assertIn(f"Output: {f} (edited) (original: {orig_out})", show1_out)

    def test_f49_block_and_operation_durations_and_sub_items(self):
        # 1. format_duration covers ms, s, m, and h ranges cleanly
        self.assertEqual(self.mod.format_duration(0.0), "0ms")
        self.assertEqual(self.mod.format_duration(0.015), "15ms")
        self.assertEqual(self.mod.format_duration(0.999), "999ms")
        self.assertEqual(self.mod.format_duration(0.9996), "1.0s")
        self.assertEqual(self.mod.format_duration(3.42), "3.4s")
        self.assertEqual(self.mod.format_duration(65.2), "1m 5s")
        self.assertEqual(self.mod.format_duration(3665.0), "1h 1m 5s")

        # 2. Wall-clock block duration excludes PLAN confirmation wait
        work = self.tmp / "f49_work"
        work.mkdir()
        (work / "a.txt").write_text("alpha\n", encoding="utf-8")
        (work / "b.txt").write_text("beta\n", encoding="utf-8")
        os.environ["RUN_BLOCK_CWD"] = str(work)

        sdir = self.tmp / "s49"
        step1_dir = sdir / "1"
        step1_dir.mkdir(parents=True)
        script1 = step1_dir / "block.sh"
        out1 = step1_dir / "out"
        script1.write_text("echo ok_step\n", encoding="utf-8")

        fake_clock_vals = iter([1000.0, 1002.4])  # Popen..wait = 2.4s (after confirmation)

        def confirm_with_wait(*_args, **_kwargs):
            # Even if confirmation takes 100s, exec_started is captured after confirm_execution
            return True, ""

        buf1 = io.StringIO()
        with unittest.mock.patch.object(self.mod, "confirm_execution", side_effect=confirm_with_wait), \
             unittest.mock.patch.object(self.mod.time, "monotonic", side_effect=lambda: next(fake_clock_vals)), \
             contextlib.redirect_stdout(buf1):
            rc1 = self.mod.run_script("s49/1", script1, out1, auto_yes=False)
        self.assertEqual(rc1, 0)
        out1_txt = out1.read_text(encoding="utf-8")
        self.assertIn("[s49/1] END (2.4s)\n", out1_txt)
        self.assertIn("· 2.4s", buf1.getvalue())
        self.assertIn("Stats:  ", buf1.getvalue())
        self.assertEqual(self.mod._step_status(sdir, "1"), "END (2.4s)")
        meta1 = self.mod.read_step_meta(step1_dir)
        self.assertEqual(meta1.get("duration_ms"), 2400)
        self.assertEqual(meta1.get("exit_code"), 0)

        # Stats: still shows duration when RUN_BLOCK_TOKEN_STATS=false
        saved_tok = os.environ.get("RUN_BLOCK_TOKEN_STATS")
        os.environ["RUN_BLOCK_TOKEN_STATS"] = "false"
        try:
            end_no_tok = self.mod.build_box_body_lines(
                out1, rc=0, stats=self.mod.stats_line(out1), label="s49/1", sdir=sdir
            )
            self.assertTrue(any(ln.rstrip().endswith("2.4s") and ln.startswith("Stats:") for ln in end_no_tok))
        finally:
            if saved_tok is None:
                os.environ.pop("RUN_BLOCK_TOKEN_STATS", None)
            else:
                os.environ["RUN_BLOCK_TOKEN_STATS"] = saved_tok

        # 3. _ProgressLineFilter tracks per-operation durations and interleaved events deterministically
        t_seq = iter([10.0, 10.25, 13.65])
        step_map = {
            1: {"step": 1, "tag": "read", "desc": "cat a.txt"},
            2: {"step": 2, "tag": "exec", "desc": "pytest -q"},
        }
        pf = self.mod._ProgressLineFilter(step_map, total_steps=2, clock=lambda: next(t_seq))
        events = pf.feed_events("__RB_STEP__:1\nalpha\n__RB_STEP__:2\nfail\n")
        self.assertEqual(events[0][0], "prog")
        self.assertIn("[1/2] [read] cat a.txt", events[0][1])
        self.assertEqual(events[1], ("out", "alpha\n"))
        self.assertEqual(events[2][0], "prog")
        self.assertIn("✓ [1/2] (250ms)", events[2][1])
        self.assertIn("[2/2] [exec] pytest -q", events[2][1])
        self.assertEqual(events[3], ("out", "fail\n"))
        rem_out, rem_prog = pf.flush(rc=1)
        self.assertEqual(rem_out, "")
        self.assertIn("✗ [2/2] (3.4s)", rem_prog)
        self.assertEqual(
            pf.operation_timings(),
            [
                {"step": 1, "tag": "read", "desc": "cat a.txt", "duration_ms": 250},
                {"step": 2, "tag": "exec", "desc": "pytest -q", "duration_ms": 3400},
            ],
        )

        # 4. Interactive run_script records per-op timings in live output, END box, and meta.json, and surfaces in -l
        step2_dir = sdir / "2"
        step2_dir.mkdir(parents=True)
        script2 = step2_dir / "block.sh"
        out2 = step2_dir / "out"
        script2.write_text("cat a.txt\ncat missing_file_f49\n", encoding="utf-8")
        buf2 = io.StringIO()
        buf2.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", buf2), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")), \
             unittest.mock.patch.object(self.mod, "offer_clipboard_copy"):
            rc2 = self.mod.run_script("s49/2", script2, out2, auto_yes=False)
        self.assertNotEqual(rc2, 0)
        live2 = buf2.getvalue()
        self.assertIn("✓ [1/2] (", live2)
        self.assertIn("✗ [2/2] (", live2)
        self.assertNotIn("Steps:", live2)
        out2_txt = out2.read_text(encoding="utf-8")
        self.assertRegex(out2_txt, rf"\[s49/2\] END \(exit {rc2}, [^)\n]+\)\n")
        meta2 = self.mod.read_step_meta(step2_dir)
        self.assertEqual(meta2.get("exit_code"), rc2)
        self.assertEqual(meta2.get("failed_step"), 2)
        self.assertEqual(len(meta2.get("operations") or []), 2)

        list_buf = io.StringIO()
        with contextlib.redirect_stdout(list_buf):
            self.assertEqual(self.mod.cmd_list("s49"), 0)
        list_out = list_buf.getvalue()
        self.assertIn("END (2.4s)", list_out)
        self.assertIn(f"END (exit {rc2},", list_out)

        # 5. PLAN visually nests AST-expanded sub-items in both flat, multi-dir, ASCII, and color modes
        mixed_script = (
            "cd /tmp\n"
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            + "\n".join(f"Path('src/f{i}.py').write_text('x')" for i in range(6))
            + "\n"
            + "\n".join(f"Path('tests/t{i}.py').read_text()" for i in range(5))
            + "\nPY\n"
            "cd /var\n"
            "ls -la\n"
        )
        mixed_sum = self.mod.summarize_script_actions(mixed_script, Path("/tmp/work"))
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
            mixed_box, _, _ = self.mod.format_safety_box("s49/3", [], default_yes=True, summary=mixed_sum)
        self.assertIn("  /tmp:", mixed_box)
        self.assertIn("    1. [python]  12 lines", mixed_box)
        self.assertIn("       ├─ [write]   src/f0.py", mixed_box)
        self.assertIn("       └─ [read]    tests/t0.py", mixed_box)
        self.assertIn("  /var:", mixed_box)
        self.assertIn("    2. [read]  ls -la", mixed_box)

        # ASCII fallback uses |- and `- connectors
        with io.TextIOWrapper(io.BytesIO(), encoding="ascii") as ascii_stream:
            with unittest.mock.patch.object(self.mod.sys, "stdout", ascii_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
                ascii_box, _, _ = self.mod.format_safety_box("s49/3", [], default_yes=True, summary=mixed_sum)
        self.assertIn("       |- [write]   src/f0.py", ascii_box)
        self.assertIn("       `- [read]    tests/t0.py", ascii_box)

        # Colorized sub-items preserve [write] and [read] tag colors
        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_nc = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
                col_box, _, _ = self.mod.format_safety_box("s49/3", [], default_yes=True, summary=mixed_sum)
            self.assertIn("\x1b[93m", col_box)
            self.assertIn("\x1b[2m├─ \x1b[0m\x1b[1;33m[write]\x1b[0m", col_box)
            self.assertIn("\x1b[2m└─ \x1b[0m\x1b[1;94m[read]\x1b[0m", col_box)
        finally:
            if saved_nc is not None:
                os.environ["NO_COLOR"] = saved_nc


if __name__ == "__main__":
    unittest.main()
