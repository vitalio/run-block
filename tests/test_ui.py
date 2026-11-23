#!/usr/bin/env python3
"""TUI boxes, ASCII fallback, colors, wrapping, height clamping, altscreen details, and SIGWINCH redraw."""

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


class TestUi(RunBlockTestCase):
    def test_error_line_prefers_traceback_root_cause_over_runner_tail(self):
        out = self.tmp / "out"
        out.write_text(
            "[s1/1] START\n"
            "Traceback (most recent call last):\n"
            '  File "/x/tests/test_a.py", line 12, in test_a\n'
            "    self.assertEqual(rc, 2)\n"
            "AssertionError: 0 != 2\n"
            "\n"
            "Ran 3 tests in 0.1s\n"
            "FAILED (failures=1)\n"
            "[s1/1] END (exit 1, 1s)\n",
            encoding="utf-8",
        )
        err = self.mod._extract_last_error_line(out, label="s1/1", max_width=100)
        self.assertEqual(err, "AssertionError: 0 != 2 (test_a.py:12)")
        out.write_text(
            "Hello world line\n"
            "Traceback (most recent call last):\n"
            '  File "t.py", line 3, in f\n'
            "AssertionError: 'Hello wrld' not found in output\n"
            "FAILED (failures=1)\n",
            encoding="utf-8",
        )
        err2 = self.mod._extract_last_error_line(out, label="s1/1", max_width=120)
        self.assertIn("closest: Hello world line", err2)
        # In-memory captured haystack embedded inside the AssertionError message itself
        out.write_text(
            "[s1/1] START\n"
            "Traceback (most recent call last):\n"
            '  File "t.py", line 9, in test_mem\n'
            "AssertionError: ' expected_token_alpha ' not found in 'header line\\nexpected_token_alpa\\nfooter line'\n"
            "Ran 1 test in 0.01s\n"
            "FAILED (failures=1)\n"
            "[s1/1] END (exit 1, 10ms)\n",
            encoding="utf-8",
        )
        err_mem = self.mod._extract_last_error_line(out, label="s1/1", max_width=160)
        self.assertIn("closest: expected_token_alpa", err_mem)
        # Wide CJK characters in traceback root cause must truncate by display width (char_width)
        wide_msg = "漢字" * 30
        out.write_text(
            "[s1/1] START\n"
            "Traceback (most recent call last):\n"
            '  File "t.py", line 5, in f\n'
            f"AssertionError: {wide_msg}\n"
            "FAILED (failures=1)\n",
            encoding="utf-8",
        )
        err_wide = self.mod._extract_last_error_line(out, label="s1/1", max_width=40)
        self.assertLessEqual(self.mod.display_width(err_wide), 34)
        self.assertTrue(err_wide.endswith("..."))
        out.write_text("boom\n[s1/1] END (exit 1, 1s)\n", encoding="utf-8")
        self.assertEqual(self.mod._extract_last_error_line(out, label="s1/1"), "boom")

    def test_stats_and_clipboard_box(self):
        f = self.tmp / "x.txt"
        f.write_text("hello\n", encoding="utf-8")
        s = self.mod.stats_line(f)
        self.assertIn("1 line · 6 chars · ~2 tokens", s)
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((84, 24))):
            box, c_w, c_off = self.mod.format_clipboard_box("s2/1", f, stats=s)
        self.assertEqual(c_w, 48)
        self.assertEqual(c_off, len("│ -> Copy to clipboard? [Y/n/p(rompt)/i(nfo)]:"))
        self.assertIn("╭─ END STEP ────", box)
        self.assertIn("│ Step:    s2/1", box)
        self.assertIn("│ Workdir: ", box)
        self.assertNotIn("Sandbox:", box)
        self.assertNotIn("END STEP (", box)
        self.assertIn(f"│ Output: {f}", box)
        self.assertIn("│ Stats:  1 line · 6 chars · ~2 tokens", box)
        self.assertIn("│ -> Copy to clipboard? [Y/n/p(rompt)/i(nfo)]:", box)
        lines = box.splitlines()
        self.assertEqual(len(lines), 9)
        self.assertEqual(len(lines[0]), 48)
        self.assertTrue(lines[0].startswith("╭─ END STEP ────"))
        self.assertEqual(lines[-2], "│ -> Copy to clipboard? [Y/n/p(rompt)/i(nfo)]:")
        self.assertEqual(lines[-1], "╰" + "─" * 47)
        self.assertEqual(self.mod.resolve_clipboard_target(Path("/tmp/fallback.txt"), f"Bundle: {f}\n"), f)

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
            box_err, _, _ = self.mod.format_clipboard_box("s2/2", f, ok=False, rc=2, stats=s)
        self.assertIn("╭─ END STEP ", box_err)
        self.assertIn("Step:    s2/2", box_err)
        self.assertIn("Exit:   2", box_err)
        self.assertIn(f"Output: {f}", box_err)
        self.assertIn("Stats:  1 line · 6 chars · ~2 tokens", box_err)

    def test_info_and_prompt_boxes_and_skipped_step_confirmation(self):
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))):
            info_box = self.mod.format_info_box("START SESSION", ["Session: s1", "Next-Block: s1/1"])
        info_lines = info_box.splitlines()
        self.assertTrue(info_lines[0].startswith("╭─ START SESSION ────"))
        self.assertEqual(len(info_lines[0]), 48)
        self.assertEqual(info_lines[1], "│ Session:    s1")
        self.assertEqual(info_lines[2], "│ Next-Block: s1/1")
        self.assertEqual(info_lines[-1], "╰" + "─" * 47)

        renum_st = "✓ Renumbering s1/2 -> s1/1."
        no_st = "✗ Canceled s1/2 (run s1/1 first)."
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))):
            p_box, p_width, p_off = self.mod.format_prompt_box(
                "MISSING PREVIOUS STEP",
                ["Step: s1/2", "", "Missing: s1/1"],
                "-> Renumber to s1/1? [r(enumber)/n]:",
                status_lines=(renum_st, no_st),
            )
        self.assertEqual(p_width, 48)
        self.assertEqual(p_off, len("│ -> Renumber to s1/1? [r(enumber)/n]:"))
        p_lines = p_box.splitlines()
        self.assertTrue(p_lines[0].startswith("╭─ MISSING PREVIOUS STEP ────"))
        self.assertEqual(p_lines[1], "│ Step: s1/2")
        self.assertEqual(p_lines[2], "│")
        self.assertEqual(p_lines[3], "│ Missing: s1/1")
        self.assertEqual(p_lines[4], "│")
        self.assertEqual(p_lines[-2], "│ -> Renumber to s1/1? [r(enumber)/n]:")
        self.assertEqual(p_lines[-1], "╰" + "─" * 47)

        # MISSING PREVIOUS STEP has no Enter default; 'r' renumbers
        tty_w = io.StringIO()
        tty_r = io.StringIO("\nr\n")
        res_miss = self.mod.prompt_yes_no_box(
            "MISSING PREVIOUS STEP",
            ["Step: s1/2", "", "Missing: s1/1"],
            "Renumber to s1/1?",
            default_yes=False,
            no_status=no_st,
            renumber_label="s1/1",
            renumber_status=renum_st,
            renumber_only=True,
            tty_streams=(tty_w, tty_r),
        )
        self.assertEqual(res_miss, "renumber")
        self.assertIn("╭─ MISSING PREVIOUS STEP ────", tty_w.getvalue())
        self.assertIn(f"\r\033[K│ {renum_st}\n", tty_w.getvalue())

        # Verify interactive declines do not emit duplicate NOT RUN / END boxes
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "prompt_yes_no_box", return_value=False) as mock_prompt:
            buf_dec = io.StringIO()
            buf_dec.isatty = lambda: True  # type: ignore[method-assign]
            with contextlib.redirect_stdout(buf_dec):
                rc_skip_dec = self.mod.cmd_normal("s9/2", "echo hi\n")
            self.assertEqual(rc_skip_dec, 2)
            self.assertEqual(buf_dec.getvalue(), "")
            self.assertEqual(mock_prompt.call_args[0][0], "MISSING PREVIOUS STEP")
            self.assertIn("Step:    s9/2", mock_prompt.call_args[0][1])
            self.assertIn("Missing: s9/1", mock_prompt.call_args[0][1])
            self.assertEqual(mock_prompt.call_args[1].get("renumber_label"), "s9/1")
            self.assertTrue(mock_prompt.call_args[1].get("renumber_only"))

            with contextlib.redirect_stdout(io.StringIO()):
                self.mod.cmd_normal("s9/1", "echo step1\n", auto_yes=True)
            buf_dup_dec = io.StringIO()
            buf_dup_dec.isatty = lambda: True  # type: ignore[method-assign]
            with contextlib.redirect_stdout(buf_dup_dec):
                rc_dup_dec = self.mod.cmd_normal("s9/1", "echo step1_again\n")
            self.assertEqual(rc_dup_dec, 2)
            self.assertEqual(buf_dup_dec.getvalue(), "")
            self.assertEqual(mock_prompt.call_args[0][0], "STEP ALREADY EXISTS")
            self.assertIn("Step:    s9/1", mock_prompt.call_args[0][1])
            self.assertIn("Next: s9/2", mock_prompt.call_args[0][1])
            self.assertEqual(mock_prompt.call_args[1].get("renumber_label"), "s9/2")
            self.assertTrue(mock_prompt.call_args[1].get("copy_on_yes"))

        with unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(False, "USER_ABORTED")):
            buf_abort = io.StringIO()
            with contextlib.redirect_stdout(buf_abort):
                rc_abort = self.mod.cmd_normal("s9/2", "echo step2\n")
            self.assertEqual(rc_abort, 130)
            self.assertEqual(buf_abort.getvalue(), "")
            self.assertTrue((self.tmp / "s9/2/aborted").is_file())

        # Verify STEP ALREADY EXISTS interactive actions when out exists: i(nfo) -> s(cript)/o(utput), and Enter copies out
        s_script = self.tmp / "s9/1/block.sh"
        s_out = self.tmp / "s9/1/out"
        viewed_paths: list[Path] = []

        def fake_editor(p: Path, _r, _w) -> None:
            viewed_paths.append(p)

        with unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_editor), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["true"], "xclip < out")), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy:
            tty_w_c = io.StringIO()
            tty_r_c = io.StringIO("i\ns\no\nq\n\n")
            res_c = self.mod.prompt_yes_no_box(
                "STEP ALREADY EXISTS",
                ["Step: s9/1", "", "Next: s9/2", f"Script: {s_script}", f"Output: {s_out}"],
                "Copy out to clipboard?",
                default_yes=True,
                no_status="✗ Keeping existing s9/1.",
                tty_streams=(tty_w_c, tty_r_c),
                script_path=s_script,
                out_path=s_out,
                renumber_label="s9/2",
                copy_on_yes=True,
            )
            self.assertEqual(res_c, "copy")
            self.assertEqual(viewed_paths, [s_script, s_out])
            mock_copy.assert_called_once_with(["true"], s_out)
            out_c_text = tty_w_c.getvalue()
            self.assertIn("-> Copy out to clipboard? [Y/n/r(enumber)/i(nfo)]:", out_c_text)
            self.assertIn("STEP ALREADY EXISTS · /", out_c_text)
            self.assertIn(f"✓ Copied {s_out} to clipboard.", out_c_text)

            # Pressing Esc on STEP ALREADY EXISTS exits without copying or overwriting
            for esc_input in ("esc\n", "\x1b\n"):
                with self.subTest(esc_input=repr(esc_input)):
                    tty_w_esc = io.StringIO()
                    tty_r_esc = io.StringIO(esc_input)
                    res_esc = self.mod.prompt_yes_no_box(
                        "STEP ALREADY EXISTS",
                        ["Step: s9/1", "", f"Output: {s_out}"],
                        "Copy out to clipboard?",
                        default_yes=True,
                        no_status="✗ Keeping existing s9/1.",
                        tty_streams=(tty_w_esc, tty_r_esc),
                        out_path=s_out,
                        renumber_label="s9/2",
                        copy_on_yes=True,
                    )
                    self.assertFalse(res_esc)
                    self.assertIn("✗ Keeping existing s9/1.", tty_w_esc.getvalue())

            # Unified prompt suffixes without Enter/Esc labels
            self.assertEqual(self.mod._build_prompt_yes_no_suffix(True), "[Y/n]:")
            self.assertEqual(self.mod._build_prompt_yes_no_suffix(False), "[y/N]:")
            self.assertEqual(
                self.mod._build_prompt_yes_no_suffix(
                    True, has_script=True, has_output=True, can_copy=True, has_renumber=True, copy_on_yes=True, has_info=True
                ),
                "[Y/n/r(enumber)/i(nfo)]:",
            )
            self.assertEqual(
                self.mod._build_prompt_yes_no_suffix(
                    False, has_script=True, has_output=False, has_renumber=True, renumber_only=True, has_info=True
                ),
                "[r(enumber)/n/i(nfo)]:",
            )
            self.assertEqual(
                self.mod._build_prompt_yes_no_suffix(False, has_renumber=True, renumber_only=True),
                "[r(enumber)/n]:",
            )
            self.assertEqual(
                self.mod._build_prompt_yes_no_suffix(False, has_info=True),
                "[y/N/i(nfo)]:",
            )

        # start_session() on existing session without --force fails immediately even on a TTY
        fake_tty_in = io.StringIO()
        fake_tty_in.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdin", fake_tty_in):
            with self.assertRaises(SystemExit) as cm_dup:
                self.mod.start_session("s9", force=False)
        self.assertIn("already exists (use --force to overwrite)", str(cm_dup.exception))

    def test_ascii_fallback_kv_alignment_and_tty_colors(self):
        # 1. ASCII fallback when stdout encoding is not UTF-8
        with io.TextIOWrapper(io.BytesIO(), encoding="ascii") as ascii_stream:
            with unittest.mock.patch.object(self.mod.sys, "stdout", ascii_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))):
                ascii_box = self.mod.format_info_box("START SESSION", ["Session: s1", "Next-Block: s1/1"])
        a_lines = ascii_box.splitlines()
        self.assertTrue(a_lines[0].startswith("+- START SESSION ----"))
        self.assertEqual(len(a_lines[0]), 48)
        self.assertEqual(a_lines[1], "| Session:    s1")
        self.assertEqual(a_lines[2], "| Next-Block: s1/1")
        self.assertEqual(a_lines[-1], "+" + "-" * 47)

        # 2. TTY-aware ANSI colors enabled on TTY without NO_COLOR, disabled with NO_COLOR or non-TTY
        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_no_color = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))):
                colored_box, _, c_off = self.mod.format_prompt_box(
                    "START STEP",
                    ["Step: s1/1", "Workdir: /tmp/proj"],
                    "-> Execute? [Y/n]:",
                )
            self.assertIn("\x1b[93m╭─ ", colored_box)
            self.assertIn("\x1b[1;93mSTART STEP\x1b[0m", colored_box)
            self.assertIn("\x1b[2mStep:\x1b[0m    s1/1", colored_box)
            self.assertIn("\x1b[2mWorkdir:\x1b[0m \x1b[1;33m/tmp/proj\x1b[0m", colored_box)
            self.assertEqual(c_off, len("│ -> Execute? [Y/n]:"))

            os.environ["NO_COLOR"] = "1"
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))):
                no_color_box = self.mod.format_info_box("NOT RUN", ["Reason: blocked"])
            self.assertNotIn("\x1b[", no_color_box)
            self.assertIn("╭─ NOT RUN ────", no_color_box)
        finally:
            if saved_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = saved_no_color

    def test_visual_hierarchy_border_colors_and_block_plan_highlights(self):
        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_no_color = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
                # 1. Matching non-dim border colors per block title (END STEP green vs END STEP with Exit red)
                end_ok = self.mod.format_info_box("END STEP", ["Step: s1/1"])
                self.assertIn("\x1b[92m╭─ \x1b[0m\x1b[1;92mEND STEP\x1b[0m", end_ok)
                self.assertIn("\x1b[92m│\x1b[0m", end_ok)
                self.assertIn("\x1b[92m╰", end_ok)

                end_err = self.mod.format_info_box("END STEP", ["Step: s1/1", "Exit: 2"])
                self.assertIn("\x1b[91m╭─ \x1b[0m\x1b[1;91mEND STEP\x1b[0m", end_err)
                self.assertIn("\x1b[91m│\x1b[0m", end_err)

                # 2. PLAN with matching Workdir (dimmed), Sandbox: off omitted,
                #    Operations color-coding, and Safety warnings + prompt highlight
                cwd_now = os.getcwd()
                script_warn = (
                    "cat README.md\n"
                    "git status -sb\n"
                    "rm -rf /tmp/f27_test\n"
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "Path('a.txt').read_text()\n"
                    "Path('b.txt').write_text('x')\n"
                    "PY\n"
                )
                findings = self.mod.scan_script_risks(script_warn)
                summary = self.mod.summarize_script_actions(script_warn, work_dir=Path(cwd_now))
                box_warn, _, _ = self.mod.format_safety_box(
                    "s1/2", findings, default_yes=False, summary=summary
                )
                self.assertIn("\x1b[93m╭─ \x1b[0m\x1b[1;93mSTART STEP\x1b[0m", box_warn)
                self.assertIn(f"\x1b[2mWorkdir: {cwd_now}\x1b[0m", box_warn)
                self.assertNotIn("Sandbox:", box_warn)
                self.assertIn("  1. \x1b[1;94m[read]\x1b[0m    \x1b[94mcat README.md\x1b[0m", box_warn)
                self.assertNotIn("\x1b[2m[read]", box_warn)
                self.assertIn("2. \x1b[1;36m[git]\x1b[0m     \x1b[36mgit status -sb\x1b[0m", box_warn)
                self.assertIn("3. \x1b[1;33m[write]\x1b[0m   \x1b[33mrm -rf /tmp/f27_test\x1b[0m", box_warn)
                self.assertNotIn("\x1b[1;33mrm -rf", box_warn)
                self.assertIn("4. \x1b[1;32m[python]\x1b[0m  \x1b[32m3 lines\x1b[0m", box_warn)
                self.assertIn("\x1b[2m├─ \x1b[0m\x1b[1;33m[write]\x1b[0m   \x1b[33mb.txt\x1b[0m", box_warn)
                self.assertIn("\x1b[2m└─ \x1b[0m\x1b[1;94m[read]\x1b[0m    \x1b[94ma.txt\x1b[0m", box_warn)
                self.assertNotIn("\x1b[2m[read]", box_warn)

                # Wrapped [read] continuation lines render in matching regular bright blue
                long_read = "cat " + "/".join(["segment"] * 12) + "/file.txt\n"
                sum_wrap = self.mod.summarize_script_actions(long_read, work_dir=Path(cwd_now))
                box_wrap, _, _ = self.mod.format_safety_box(
                    "s1/2b", [], default_yes=True, summary=sum_wrap
                )
                self.assertIn("  1. \x1b[1;94m[read]\x1b[0m  \x1b[94mcat ", box_wrap)
                self.assertIn("\x1b[94m             /segment/", box_wrap)
                self.assertNotIn("\x1b[2m[read]", box_wrap)
                self.assertNotIn("\x1b[2m          ", box_wrap)
                self.assertIn("\x1b[1;31mSafety warnings (1):\x1b[0m", box_warn)
                self.assertIn("\x1b[1;31m[fs-destructive]\x1b[0m", box_warn)
                self.assertIn("\x1b[1;93m-> Execute this block? [y/n/i(nfo)]:\x1b[0m", box_warn)
                self.assertNotIn("\x1b[1;31m-> Execute this block?", box_warn)

                # 3. PLAN with differing Workdir (highlighted) and no safety warnings (prompt uncolored)
                other_dir = self.tmp / "other_workdir"
                other_dir.mkdir()
                sum_clean = self.mod.summarize_script_actions("ls -la\n", work_dir=other_dir)
                box_clean, _, _ = self.mod.format_safety_box(
                    "s1/3", [], default_yes=True, summary=sum_clean
                )
                self.assertIn(f"\x1b[2mWorkdir:\x1b[0m \x1b[1;33m{other_dir}\x1b[0m", box_clean)
                self.assertIn("-> Execute this block? [Y/n/i(nfo)]:", box_clean)
                self.assertNotIn("\x1b[1;31m-> Execute this block?", box_clean)
                self.assertNotIn("\x1b[1;93m-> Execute this block?", box_clean)
        finally:
            if saved_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = saved_no_color

    def test_status_box_exit_error_and_dim_metadata(self):
        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_no_color = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
                self.assertEqual(
                    self.mod._colorize_kv_line("Exit: 0"),
                    "\x1b[2mExit:\x1b[0m 0",
                )

                end_box = self.mod.format_info_box(
                    "END STEP",
                    [
                        "Step: s1/1",
                        "Exit: 2",
                        "Error: boom",
                        "Fix: run_block --fix s1/1 (0/2 failed attempts)",
                        "Output: /tmp/s1/1/out",
                        "Stats: 1 line · 5 B · ~2 tokens",
                    ],
                )
                self.assertIn("\x1b[2mExit:\x1b[0m   \x1b[1;31m2\x1b[0m", end_box)
                self.assertIn("\x1b[2mError:\x1b[0m  \x1b[1;91mboom\x1b[0m", end_box)
                self.assertIn("\x1b[2mFix:    run_block --fix s1/1 (0/2 failed attempts)\x1b[0m", end_box)
                self.assertIn("\x1b[2mOutput: /tmp/s1/1/out\x1b[0m", end_box)
                self.assertIn("\x1b[2mStats:  1 line · 5 B · ~2 tokens\x1b[0m", end_box)

                syn_box = self.mod.format_info_box(
                    "SYNTAX ERROR",
                    [
                        "Block: s1/2",
                        "Exit: 2",
                        "Output: /tmp/s1/2/out",
                        "Error: unexpected EOF",
                        "Stats: 1 line · 15 B · ~4 tokens",
                    ],
                )
                self.assertIn("\x1b[2mExit:\x1b[0m   \x1b[1;31m2\x1b[0m", syn_box)
                self.assertIn("\x1b[2mError:\x1b[0m  \x1b[1;91munexpected EOF\x1b[0m", syn_box)
                self.assertIn("\x1b[2mOutput: /tmp/s1/2/out\x1b[0m", syn_box)
                self.assertIn("\x1b[2mStats:  1 line · 15 B · ~4 tokens\x1b[0m", syn_box)

                not_run_box = self.mod.format_info_box(
                    "NOT RUN",
                    [
                        "Block: s1/3",
                        "Reason: target script missing",
                        "Error: file not found",
                        "Output: /tmp/s1/3/out",
                        "Stats: 1 line · 20 B · ~5 tokens",
                    ],
                )
                self.assertIn("\x1b[2mError:\x1b[0m  \x1b[1;91mfile not found\x1b[0m", not_run_box)
                self.assertIn("\x1b[2mOutput: /tmp/s1/3/out\x1b[0m", not_run_box)
                self.assertIn("\x1b[2mStats:  1 line · 20 B · ~5 tokens\x1b[0m", not_run_box)
        finally:
            if saved_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = saved_no_color

    def test_distinct_operation_tag_colors(self):
        expected = {
            "read": "\x1b[1;94m",
            "write": "\x1b[1;33m",
            "exec": "\x1b[1;35m",
            "git": "\x1b[1;36m",
            "python": "\x1b[1;32m",
        }
        self.assertEqual(self.mod._TAG_COLORS, expected)
        self.assertEqual(len(set(self.mod._TAG_COLORS.values())), len(expected))

        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_no_color = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((96, 24))):
                script = (
                    "cat README.md\n"
                    "touch out.txt\n"
                    "pytest -q\n"
                    "git status -sb\n"
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "Path('in.txt').read_text()\n"
                    "Path('out.txt').write_text('ok')\n"
                    "PY\n"
                )
                summary = self.mod.summarize_script_actions(script, work_dir=Path(os.getcwd()))
                box, _, _ = self.mod.format_safety_box("s1/1", [], default_yes=True, summary=summary)
                self.assertIn("1. \x1b[1;94m[read]\x1b[0m    \x1b[94mcat README.md\x1b[0m", box)
                self.assertIn("2. \x1b[1;33m[write]\x1b[0m   \x1b[33mtouch out.txt\x1b[0m", box)
                self.assertIn("3. \x1b[1;35m[exec]\x1b[0m    \x1b[35mpytest -q\x1b[0m", box)
                self.assertIn("4. \x1b[1;36m[git]\x1b[0m     \x1b[36mgit status -sb\x1b[0m", box)
                self.assertIn("5. \x1b[1;32m[python]\x1b[0m  \x1b[32m3 lines\x1b[0m", box)
                self.assertIn("\x1b[2m├─ \x1b[0m\x1b[1;33m[write]\x1b[0m   \x1b[33mout.txt\x1b[0m", box)
                self.assertIn("\x1b[2m└─ \x1b[0m\x1b[1;94m[read]\x1b[0m    \x1b[94min.txt\x1b[0m", box)

                # Single-file inline writes/reads and calls in Python summaries
                single_py = (
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "Path('only.txt').write_text('ok')\n"
                    "PY\n"
                )
                single_sum = self.mod.summarize_script_actions(single_py, work_dir=Path(os.getcwd()))
                single_box, _, _ = self.mod.format_safety_box("s1/1b", [], default_yes=True, summary=single_sum)
                self.assertIn(
                    "1. \x1b[1;32m[python]\x1b[0m  \x1b[32m2 lines — \x1b[0m\x1b[33mwrites: only.txt\x1b[0m",
                    single_box,
                )

                single_read_py = (
                    "python3 - <<'PY'\n"
                    "from pathlib import Path\n"
                    "Path('src/ui.py').read_text()\n"
                    "PY\n"
                )
                sr_sum = self.mod.summarize_script_actions(single_read_py, work_dir=Path(os.getcwd()))
                sr_box, _, _ = self.mod.format_safety_box("s1/1c", [], default_yes=True, summary=sr_sum)
                self.assertIn(
                    "1. \x1b[1;32m[python]\x1b[0m  \x1b[32m2 lines — \x1b[0m\x1b[94mreads: src/ui.py\x1b[0m",
                    sr_box,
                )

                calls_py = (
                    "python3 - <<'PY'\n"
                    "import ast\n"
                    "ast.parse('x = 1')\n"
                    "PY\n"
                )
                calls_sum = self.mod.summarize_script_actions(calls_py, work_dir=Path(os.getcwd()))
                calls_box, _, _ = self.mod.format_safety_box("s1/1d", [], default_yes=True, summary=calls_sum)
                self.assertIn(
                    "1. \x1b[1;32m[python]\x1b[0m  \x1b[32m2 lines — calls: ast.parse\x1b[0m",
                    calls_box,
                )

                # Wrapped continuation lines keep regular matching body tint across all tags
                wrapped_lines = self.mod._colorize_operation_lines(
                    [
                        "  1. [read]    cat a.txt",
                        "               b.txt",
                        "  2. [write]   cp a.txt",
                        "               b.txt",
                        "  3. [exec]    custom_tool --arg1",
                        "               --arg2",
                        "  4. [git]     git log --oneline",
                        "               --graph",
                        "  5. [python]  3 lines — writes: a.py;",
                        "               reads: b.py; calls: ast.parse",
                    ]
                )
                self.assertEqual(
                    wrapped_lines,
                    [
                        "  1. \x1b[1;94m[read]\x1b[0m    \x1b[94mcat a.txt\x1b[0m",
                        "\x1b[94m               b.txt\x1b[0m",
                        "  2. \x1b[1;33m[write]\x1b[0m   \x1b[33mcp a.txt\x1b[0m",
                        "\x1b[33m               b.txt\x1b[0m",
                        "  3. \x1b[1;35m[exec]\x1b[0m    \x1b[35mcustom_tool --arg1\x1b[0m",
                        "\x1b[35m               --arg2\x1b[0m",
                        "  4. \x1b[1;36m[git]\x1b[0m     \x1b[36mgit log --oneline\x1b[0m",
                        "\x1b[36m               --graph\x1b[0m",
                        "  5. \x1b[1;32m[python]\x1b[0m  \x1b[32m3 lines — \x1b[0m\x1b[33mwrites: a.py\x1b[0m\x1b[32m;\x1b[0m",
                        "\x1b[32m               \x1b[0m\x1b[94mreads: b.py\x1b[0m\x1b[32m; calls: ast.parse\x1b[0m",
                    ],
                )
        finally:
            if saved_no_color is None:
                os.environ.pop("NO_COLOR", None)
            else:
                os.environ["NO_COLOR"] = saved_no_color

    def test_bright_error_title_border_and_distinct_prompt(self):
        self.assertEqual(self.mod._ERROR_COLOR, "\x1b[1;91m")
        self.assertFalse(self.mod._BORDER_COLOR.startswith("\x1b[2;"))
        self.assertEqual(self.mod._BORDER_COLOR, "\x1b[96m")

        expected_titles = {
            "START SESSION": ("\x1b[1;96m", "\x1b[96m"),
            "START STEP": ("\x1b[1;93m", "\x1b[93m"),
            "END STEP": ("\x1b[1;92m", "\x1b[92m"),
            "SYNTAX ERROR": ("\x1b[1;91m", "\x1b[91m"),
            "NOT RUN": ("\x1b[1;91m", "\x1b[91m"),
            "MISSING PREVIOUS STEP": ("\x1b[1;93m", "\x1b[93m"),
            "STEP ALREADY EXISTS": ("\x1b[1;93m", "\x1b[93m"),
            "CUSTOM TITLE": ("\x1b[1;96m", "\x1b[96m"),
        }
        for title, (exp_t, exp_b) in expected_titles.items():
            with self.subTest(title=title):
                t_col, b_col = self.mod._block_colors(title)
                self.assertEqual((t_col, b_col), (exp_t, exp_b))
                self.assertTrue(t_col.startswith("\x1b[1;9"))
                self.assertFalse(b_col.startswith("\x1b[2;"))

        self.assertEqual(self.mod._block_colors("END STEP", has_exit=True), ("\x1b[1;91m", "\x1b[91m"))
        self.assertNotEqual(self.mod._PROMPT_WARN_COLOR, self.mod._WARN_COLOR)

        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_nc = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((90, 24))):
                pref_warn = self.mod._safety_prompt_prefix(False, True, "\x1b[93m")
                self.assertIn(self.mod._PROMPT_WARN_COLOR + "-> Execute this block? [y/n/i(nfo)]:", pref_warn)
                self.assertNotIn(self.mod._WARN_COLOR + "-> Execute this block?", pref_warn)

                pref_clean = self.mod._safety_prompt_prefix(True, False, "\x1b[93m")
                self.assertNotIn(self.mod._PROMPT_WARN_COLOR, pref_clean)
                self.assertNotIn(self.mod._WARN_COLOR, pref_clean)
        finally:
            if saved_nc is not None:
                os.environ["NO_COLOR"] = saved_nc

    def test_conditional_sandbox_header_visibility(self):
        # 1. Disabled / empty sandbox modes omit Sandbox: in format_session_header_lines
        sdir_off = self.tmp / "s_off"
        sdir_off.mkdir(parents=True, exist_ok=True)
        (sdir_off / "0").write_text(
            f"Session: s_off\nNext-Block: s_off/1\nWorkdir: {self.tmp}\nSandbox: off\nDate: 2026-11-17 21:00 UTC\n",
            encoding="utf-8",
        )
        for mode in (None, "", "off", "0", "false", "disabled"):
            with self.subTest(mode=mode):
                hdrs = self.mod.format_session_header_lines(
                    label="s_off/1", sdir=sdir_off, work_dir=self.tmp, sandbox_mode=mode
                )
                self.assertFalse(any(line.startswith("Sandbox:") for line in hdrs), hdrs)

        # 2. Active sandbox modes render Sandbox: with full details
        expected_active = {
            "strict": "Sandbox: strict (rw: Workdir, /tmp; secrets: hidden; net: on)",
            "nonet": "Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)",
            "custom-wrap --ro": "Sandbox: custom-wrap --ro",
        }
        for mode, expected_line in expected_active.items():
            with self.subTest(active_mode=mode):
                hdrs = self.mod.format_session_header_lines(
                    label="s_off/1", sdir=sdir_off, work_dir=self.tmp, sandbox_mode=mode
                )
                self.assertIn(expected_line, hdrs)

        # 3. Standard TUI boxes hide Sandbox: off and show active sandbox modes
        proj = self.tmp / "f53_proj"
        proj.mkdir()
        sessions = self.tmp / "f53_sessions"
        env = {**os.environ, "RUN_BLOCK_DIR": str(sessions), "RUN_BLOCK_CWD": str(proj)}
        r_start_off = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input="Role: execute\n\nPrompt\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start_off.returncode, 0, r_start_off.stderr)
        self.assertNotIn("Sandbox:", r_start_off.stdout)
        self.assertNotIn("Sandbox:", (sessions / "s1" / "0").read_text(encoding="utf-8"))

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
        self.assertIn("Sandbox: off", r_sb_status.stdout)

        # NOT RUN and SYNTAX ERROR boxes omit Sandbox: when off
        buf_nr = io.StringIO()
        with contextlib.redirect_stdout(buf_nr):
            self.assertEqual(self.mod.cmd_normal("s_off/2", "echo skip\n"), 2)
        self.assertIn("╭─ NOT RUN ", buf_nr.getvalue())
        self.assertNotIn("Sandbox:", buf_nr.getvalue())

        buf_syn = io.StringIO()
        with contextlib.redirect_stdout(buf_syn):
            self.assertNotEqual(self.mod.cmd_normal("s_off/1", "if true; then\n"), 0)
        self.assertIn("╭─ SYNTAX ERROR ", buf_syn.getvalue())
        self.assertNotIn("Sandbox:", buf_syn.getvalue())

        # Active sandbox mode shows full Sandbox: line in BUNDLE, PLAN, END, NOT RUN, SYNTAX ERROR
        r_start_strict = self._run(
            [str(SCRIPT), "--start", "--session", "s2", "--sandbox", "strict"],
            input="Role: execute\n\nPrompt\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start_strict.returncode, 0, r_start_strict.stderr)
        self.assertIn(
            "Sandbox:    strict (rw: Workdir, /tmp; secrets: hidden; net: on)",
            r_start_strict.stdout,
        )

        sdir_strict = self.tmp / "s_strict"
        sdir_strict.mkdir()
        (sdir_strict / "0").write_text(
            f"Session: s_strict\nNext-Block: s_strict/1\nWorkdir: {self.tmp}\n"
            "Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)\n"
            "Date: 2026-11-17 21:00 UTC\n",
            encoding="utf-8",
        )
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
            plan_box, _, _ = self.mod.format_safety_box(
                "s_strict/1", [], default_yes=True, summary={"work_dir": str(self.tmp), "sandbox": "nonet", "meta": "1 line, bash"}
            )
        self.assertIn("Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)", plan_box)

        buf_nr_act = io.StringIO()
        with contextlib.redirect_stdout(buf_nr_act):
            self.assertEqual(self.mod.cmd_normal("s_strict/2", "echo skip\n", sandbox_override="nonet"), 2)
        self.assertIn("Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)", buf_nr_act.getvalue())

        buf_syn_act = io.StringIO()
        with contextlib.redirect_stdout(buf_syn_act):
            self.assertNotEqual(self.mod.cmd_normal("s_strict/1", "if true; then\n", sandbox_override="nonet"), 0)
        self.assertIn("Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)", buf_syn_act.getvalue())

        end_box_act, _, _ = self.mod.format_clipboard_box(
            "s_strict/1", sdir_strict / "1" / "out", ok=True, rc=0
        )
        self.assertIn("Sandbox: nonet (rw: Workdir, /tmp; secrets: hidden; net: off)", end_box_act)

    def test_end_not_run_syntax_error_headers_with_step_meta(self):
        import json

        # 1. _resolve_session_dir ignores <session>/<step>/meta.json and resolves parent session dir
        custom_sdir = self.tmp / "custom_sess"
        custom_step = custom_sdir / "1"
        custom_step.mkdir(parents=True)
        (custom_sdir / "0").write_text("Session: custom_sess\nNext-Block: custom_sess/1\n\nBody\n", encoding="utf-8")
        (custom_sdir / "meta.json").write_text(json.dumps({"headers": [["Role", "execute"]]}), encoding="utf-8")
        (custom_step / "meta.json").write_text(json.dumps({"duration_ms": 42, "exit_code": 0}), encoding="utf-8")
        (custom_step / "out").write_text("[custom_sess/1] START\nok\n[custom_sess/1] END (42ms)\n", encoding="utf-8")
        (custom_step / "block.sh").write_text("echo ok\n", encoding="utf-8")
        self.assertEqual(self.mod._resolve_session_dir("custom_sess/1", custom_step / "out"), custom_sdir)
        self.assertEqual(self.mod._resolve_session_dir("custom_sess/1", custom_step / "block.sh"), custom_sdir)

        # Also when 0 is absent, step meta.json does not mask session meta.json
        (custom_sdir / "0").unlink()
        self.assertEqual(self.mod._resolve_session_dir("custom_sess/1", custom_step / "out"), custom_sdir)

        # 2. Interactive & direct END, NOT RUN, and SYNTAX ERROR render all exposed headers identically to PLAN
        proj = self.tmp / "b10_proj"
        proj.mkdir()
        sessions = self.tmp / "b10_sessions"
        sessions.mkdir()
        sdir = sessions / "s1"
        sdir.mkdir()
        bundle_txt = (
            "Bundle-Command: agents_bundle role=execute task=B10\n"
            f"Workdir: {proj}\n"
            "Chat-Lang: Russian\n"
            "Role: execute\n"
            "Task: B10\n"
            "Title: Forward headers into END\n\n"
            "===== Prompt =====\nDo B10\n"
        )
        res = self.mod.format_start_bundle("s1", stdin_body=bundle_txt, work_dir=proj)
        (sdir / "0").write_text(str(res["full"]), encoding="utf-8")
        self.mod.write_session_meta(sdir, list(res["stdin_headers"]), bundle_plan=res["bundle_plan"])

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        saved_base = self.mod.BASE_DIR
        saved_cwd_env = os.environ.pop("RUN_BLOCK_CWD", None)
        self.mod.BASE_DIR = sessions
        try:
            with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
                plan_box, _, _ = self.mod.format_safety_box(
                    "s1/1", [], default_yes=True, summary={"work_dir": str(proj.resolve()), "meta": "1 line, bash"}
                )
            expected_headers = [
                f"Workdir:   {proj.resolve()}",
                "Chat-Lang: Russian",
                "Role:      execute",
                "Task:      B10",
                "Title:     Forward headers into END",
            ]
            for hdr_ln in expected_headers:
                with self.subTest(plan_hdr=hdr_ln):
                    self.assertIn(hdr_ln, plan_box)
            self.assertNotIn("Bundle-Command:", plan_box)

            # Interactive run_script creates s1/1/meta.json and invokes offer_clipboard_copy(..., sdir=sdir)
            fake_stdout = io.StringIO()
            fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
            tty_w_end = _KeepOpenStringIO()
            tty_r_end = io.StringIO("\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False),                  unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"),                  unittest.mock.patch.object(self.mod, "clipboard_command", side_effect=lambda p: (["pbcopy"], f"pbcopy < {p}")),                  unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_end, tty_r_end)),                  unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True),                  unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))),                  unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                rc_end = self.mod.cmd_normal("s1/1", "echo b10_ok\n", auto_yes=False)
            self.assertEqual(rc_end, 0)
            self.assertTrue((sdir / "1" / "meta.json").is_file())
            end_rendered = tty_w_end.getvalue()
            self.assertIn("╭─ END STEP ", end_rendered)
            for hdr_ln in expected_headers:
                with self.subTest(end_hdr=hdr_ln):
                    self.assertIn(hdr_ln, end_rendered)
            self.assertNotIn("Bundle-Command:", end_rendered)

            # Direct format_clipboard_box WITHOUT explicit sdir also resolves s1 (not s1/1)
            with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
                direct_end, _, _ = self.mod.format_clipboard_box("s1/1", sdir / "1" / "out", ok=True, rc=0)
            for hdr_ln in expected_headers:
                with self.subTest(direct_end_hdr=hdr_ln):
                    self.assertIn(hdr_ln, direct_end)

            # SYNTAX ERROR with step meta.json present renders all exposed headers in interactive prompt
            (sdir / "2").mkdir(parents=True, exist_ok=True)
            (sdir / "2" / "meta.json").write_text(json.dumps({"duration_ms": 1, "exit_code": 2}), encoding="utf-8")
            tty_w_syn = _KeepOpenStringIO()
            tty_r_syn = io.StringIO("esc\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False),                  unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"),                  unittest.mock.patch.object(self.mod, "clipboard_command", side_effect=lambda p: (["pbcopy"], f"pbcopy < {p}")),                  unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_syn, tty_r_syn)),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))),                  unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                rc_syn = self.mod.cmd_normal("s1/2", "if true; then\n", auto_yes=False)
            self.assertNotEqual(rc_syn, 0)
            syn_rendered = tty_w_syn.getvalue()
            self.assertIn("╭─ SYNTAX ERROR ", syn_rendered)
            for hdr_ln in expected_headers:
                with self.subTest(syn_hdr=hdr_ln):
                    self.assertIn(hdr_ln, syn_rendered)
            self.assertNotIn("Bundle-Command:", syn_rendered)

            # NOT RUN with step meta.json present renders all exposed headers in interactive prompt
            (sdir / "3").mkdir(parents=True, exist_ok=True)
            (sdir / "3" / "meta.json").write_text(json.dumps({"duration_ms": 1, "exit_code": 2}), encoding="utf-8")
            tty_w_nr = _KeepOpenStringIO()
            tty_r_nr = io.StringIO("esc\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False),                  unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"),                  unittest.mock.patch.object(self.mod, "clipboard_command", side_effect=lambda p: (["pbcopy"], f"pbcopy < {p}")),                  unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_nr, tty_r_nr)),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))),                  unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                rc_nr = self.mod.cmd_normal("s1/3", "", auto_yes=False)
            self.assertEqual(rc_nr, 2)
            nr_rendered = tty_w_nr.getvalue()
            self.assertIn("╭─ NOT RUN ", nr_rendered)
            for hdr_ln in expected_headers:
                with self.subTest(nr_hdr=hdr_ln):
                    self.assertIn(hdr_ln, nr_rendered)
            self.assertNotIn("Bundle-Command:", nr_rendered)
        finally:
            self.mod.BASE_DIR = saved_base
            if saved_cwd_env is not None:
                os.environ["RUN_BLOCK_CWD"] = saved_cwd_env

    def test_sigwinch_in_place_box_redraw(self):
        import pty
        import signal
        import threading
        import time

        if not (self.mod.HAS_PTY and hasattr(signal, "SIGWINCH")):
            self.skipTest("POSIX PTY and SIGWINCH required")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        # 1. read_clipboard_key & read_confirm_key detect SIGWINCH via self-pipe,
        #    debounce rapid bursts (~25ms), and restore previous SIGWINCH handler on exit
        prev_calls: list[int] = []
        orig_handler = signal.getsignal(signal.SIGWINCH)

        def custom_prev_handler(signum, _frame):
            prev_calls.append(signum)

        signal.signal(signal.SIGWINCH, custom_prev_handler)
        try:
            m_fd, s_fd = pty.openpty()
            try:
                tty_r = os.fdopen(os.dup(s_fd), "r", encoding="utf-8", errors="replace")
                with tty_r:
                    def _fire_burst() -> None:
                        deadline = time.monotonic() + 0.5
                        while signal.getsignal(signal.SIGWINCH) is custom_prev_handler and time.monotonic() < deadline:
                            time.sleep(0.002)
                        os.kill(os.getpid(), signal.SIGWINCH)
                        while len(prev_calls) < 1 and time.monotonic() < deadline:
                            time.sleep(0.001)
                        os.kill(os.getpid(), signal.SIGWINCH)

                    t1 = threading.Thread(target=_fire_burst, daemon=True)
                    t1.start()
                    try:
                        act1 = self.mod.read_clipboard_key(tty_r)
                    finally:
                        t1.join(timeout=1.0)
                    self.assertEqual(act1, "resize")
                    self.assertIs(signal.getsignal(signal.SIGWINCH), custom_prev_handler)
                    self.assertEqual(len(prev_calls), 2)

                tty_r2 = os.fdopen(os.dup(s_fd), "r", encoding="utf-8", errors="replace")
                with tty_r2:
                    t3 = threading.Timer(0.01, lambda: os.kill(os.getpid(), signal.SIGWINCH))
                    t3.start()
                    try:
                        act2 = self.mod.read_confirm_key(tty_r2, default_yes=True)
                    finally:
                        t3.join(timeout=1.0)
                    self.assertEqual(act2, "resize")
                    self.assertIs(signal.getsignal(signal.SIGWINCH), custom_prev_handler)
            finally:
                os.close(m_fd)
                os.close(s_fd)
        finally:
            signal.signal(signal.SIGWINCH, orig_handler)

        # 2. offer_clipboard_copy redraws START SESSION in place on shrink (96 -> 52) & widen (52 -> 96),
        #    and subsequent i(nfo) -> e(dit) redraws stay aligned
        os.environ["RUN_BLOCK_CWD"] = str(self.tmp)
        sdir = self.tmp / "s59"
        sdir.mkdir(parents=True, exist_ok=True)
        b0 = sdir / "0"
        b0.write_text(
            "Session: s59\nNext-Block: s59/1\n"
            f"Workdir: {self.tmp}\nSandbox: off\nDate: 2026-11-18 18:00 UTC\n"
            "Title: Long session title that clamps cleanly when terminal shrinks and expands on widen\n\n"
            "Initial bundle body\n",
            encoding="utf-8",
        )
        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        cur_cols = [96]

        def fake_term_size(_fallback=(80, 24)):
            return os.terminal_size((cur_cols[0], 24))

        def fake_edit(p: Path, _r, _w) -> None:
            p.write_text(p.read_text(encoding="utf-8") + "Edited line\n", encoding="utf-8")

        def _wait_box(tw, marker: str, count: int) -> None:
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                if (
                    tw.getvalue().count(marker) >= count
                    and getattr(signal.getsignal(signal.SIGWINCH), "__name__", "") == "_on_sigwinch"
                ):
                    time.sleep(0.003)
                    return
                time.sleep(0.002)

        m_fd2, s_fd2 = pty.openpty()
        try:
            tty_w2 = _KeepOpenStringIO()
            tty_r2 = os.fdopen(os.dup(s_fd2), "r", encoding="utf-8", errors="replace")
            with tty_r2:
                def _shrink_then_widen_then_edit():
                    _wait_box(tty_w2, "╭─ START SESSION ", 1)
                    cur_cols[0] = 52
                    os.kill(os.getpid(), signal.SIGWINCH)
                    _wait_box(tty_w2, "╭─ START SESSION ", 2)
                    cur_cols[0] = 96
                    os.kill(os.getpid(), signal.SIGWINCH)
                    _wait_box(tty_w2, "╭─ START SESSION ", 3)
                    os.write(m_fd2, b"i")
                    _wait_box(tty_w2, "\033[?1049h", 1)
                    os.write(m_fd2, b"e")
                    _wait_box(tty_w2, "(edited)", 1)
                    os.write(m_fd2, b"q")
                    _wait_box(tty_w2, "╭─ START SESSION ", 4)
                    os.write(m_fd2, b"\x1b")

                driver = threading.Thread(target=_shrink_then_widen_then_edit, daemon=True)
                with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                     unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
                     unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0}")), \
                     unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w2, tty_r2)), \
                     unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_edit), \
                     unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=fake_term_size), \
                     unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                    driver.start()
                    self.mod.offer_clipboard_copy("s59/0", b0, title_kind="START SESSION", sdir=sdir)
                    driver.join(timeout=2.0)

            rendered_b = tty_w2.getvalue()
            # Initial (96) + shrink (52) + widen (96) + e(dit) (96) = 4 START SESSION renders
            self.assertEqual(rendered_b.count("╭─ START SESSION "), 4)
            self.assertIn("\033[J╭─ START SESSION ", rendered_b)
            self.assertIn("Title:      Long session title that clamps", rendered_b)
            self.assertIn("(edited)", rendered_b)
            self.assertIn("│ Skipped clipboard copy.\n", rendered_b)
        finally:
            os.close(m_fd2)
            os.close(s_fd2)

        # 3. confirm_execution redraws START STEP in place on shrink (96 -> 50) and keeps subsequent i(nfo) -> e(dit) aligned
        step1 = sdir / "1"
        step1.mkdir(parents=True, exist_ok=True)
        sc1 = step1 / "block.sh"
        sc1.write_text("cat " + "/".join(["segment"] * 10) + "/file.txt\n", encoding="utf-8")
        sum1 = self.mod.summarize_script_actions(sc1.read_text(encoding="utf-8"), work_dir=self.tmp)
        cur_cols[0] = 96

        m_fd3, s_fd3 = pty.openpty()
        try:
            tty_w3 = _KeepOpenStringIO()
            tty_r3 = os.fdopen(os.dup(s_fd3), "r", encoding="utf-8", errors="replace")
            with tty_r3:
                def _plan_resize_and_edit():
                    _wait_box(tty_w3, "╭─ START STEP ", 1)
                    cur_cols[0] = 50
                    os.kill(os.getpid(), signal.SIGWINCH)
                    _wait_box(tty_w3, "╭─ START STEP ", 2)
                    os.write(m_fd3, b"i")
                    _wait_box(tty_w3, "\033[?1049h", 1)
                    os.write(m_fd3, b"e")
                    _wait_box(tty_w3, "(edited)", 1)
                    os.write(m_fd3, b"q")
                    _wait_box(tty_w3, "╭─ START STEP ", 3)
                    os.write(m_fd3, b"n")

                driver3 = threading.Thread(target=_plan_resize_and_edit, daemon=True)
                with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                     unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w3, tty_r3)), \
                     unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=lambda p, _r, _w: p.write_text("ls -la\n", encoding="utf-8")), \
                     unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=fake_term_size), \
                     unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                    driver3.start()
                    approved, reason = self.mod.confirm_execution(
                        "s59/1", sc1.read_text(encoding="utf-8"), summary=sum1, script_path=sc1
                    )
                    driver3.join(timeout=2.0)

            self.assertFalse(approved)
            self.assertEqual(reason, "USER_ABORTED")
            rendered_p = tty_w3.getvalue()
            # Initial (96) + shrink (50) + e(dit) (50) = 3 START STEP renders
            self.assertEqual(rendered_p.count("╭─ START STEP "), 3)
            self.assertIn("1. [read]  ls -la", rendered_p)
            self.assertIn("(edited)", rendered_p)
            self.assertIn("│ ✗ Aborted (--retry s59/1)\n", rendered_p)
        finally:
            os.close(m_fd3)
            os.close(s_fd3)

        # 4. prompt_yes_no_box redraws confirmation box in place on shrink (96 -> 48) and widen (48 -> 96)
        cur_cols[0] = 96
        m_fd4, s_fd4 = pty.openpty()
        try:
            tty_w4 = _KeepOpenStringIO()
            tty_r4 = os.fdopen(os.dup(s_fd4), "r", encoding="utf-8", errors="replace")
            with tty_r4:
                def _confirm_resize():
                    _wait_box(tty_w4, "╭─ STEP ALREADY EXISTS ", 1)
                    cur_cols[0] = 48
                    os.kill(os.getpid(), signal.SIGWINCH)
                    _wait_box(tty_w4, "╭─ STEP ALREADY EXISTS ", 2)
                    cur_cols[0] = 96
                    os.kill(os.getpid(), signal.SIGWINCH)
                    _wait_box(tty_w4, "╭─ STEP ALREADY EXISTS ", 3)
                    os.write(m_fd4, b"y")

                driver4 = threading.Thread(target=_confirm_resize, daemon=True)
                with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=fake_term_size), \
                     unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                    driver4.start()
                    res_yn = self.mod.prompt_yes_no_box(
                        "STEP ALREADY EXISTS",
                        ["Block:   s59/1", "Title:   Very long title that clamps at 48 cols and restores at 96 cols"],
                        "Overwrite s59/1?",
                        default_yes=False,
                        tty_streams=(tty_w4, tty_r4),
                    )
                    driver4.join(timeout=2.0)

            self.assertIs(res_yn, True)
            rendered_yn = tty_w4.getvalue()
            self.assertEqual(rendered_yn.count("╭─ STEP ALREADY EXISTS "), 3)
            self.assertIn("Title: Very long title that clamps at 48 cols…", rendered_yn)
            self.assertIn("Title: Very long title that clamps at 48 cols and restores at 96 cols", rendered_yn)
            self.assertIn("│ ✓ Confirmed by user.\n", rendered_yn)
        finally:
            os.close(m_fd4)
            os.close(s_fd4)

    def test_tui_box_wrapping_and_hanging_indents(self):
        def _assert_box_fits(box: str, max_cols: int, context: str) -> None:
            lines = box.splitlines()
            self.assertGreaterEqual(len(lines), 3, context)
            for idx, ln in enumerate(lines):
                with self.subTest(context=context, row=idx):
                    self.assertLessEqual(self.mod.display_width(ln), max_cols, f"{context}: {ln!r}")
                    if 0 < idx < len(lines) - 1:
                        plain = self.mod.ANSI_RE.sub("", ln)
                        self.assertTrue(plain == "│" or plain.startswith("│ "), f"{context}: {ln!r}")

        # 1. _wrap_box_line: no double-wrapping when fitting, aligned KV/list/tree/prompt hanging indents,
        #    and ANSI color preservation across wrapped rows
        self.assertEqual(self.mod._wrap_box_line("  1. [read]  short cmd", 40), ["  1. [read]  short cmd"])

        kv_wrapped = self.mod._wrap_box_line(
            "Workdir:   /Users/vitaly/Projects/very_long_repository_name/nested/subdir", 42
        )
        self.assertGreater(len(kv_wrapped), 1)
        self.assertTrue(kv_wrapped[0].startswith("Workdir:   /Users/"))
        for cont in kv_wrapped[1:]:
            self.assertTrue(cont.startswith("           "), repr(cont))
            self.assertLessEqual(self.mod.display_width(cont), 42)

        tree_wrapped = self.mod._wrap_box_line(
            "  ├─ [write]   alpha_file.py, beta_file.py, gamma_file.py, delta_file.py", 42
        )
        self.assertGreater(len(tree_wrapped), 1)
        for cont in tree_wrapped[1:]:
            self.assertTrue(cont.startswith("               "), repr(cont))
            self.assertLessEqual(self.mod.display_width(cont), 42)

        ws_wrapped = self.mod._wrap_box_line(
            "    indented detail message with many words that must wrap cleanly here", 38
        )
        self.assertGreater(len(ws_wrapped), 1)
        for cont in ws_wrapped[1:]:
            self.assertTrue(cont.startswith("    ") and not cont.startswith("     "), repr(cont))
            self.assertLessEqual(self.mod.display_width(cont), 38)

        pr_wrapped = self.mod._wrap_box_line(
            "-> Copy out to clipboard? [Y/n/r(enumber)/i(nfo)]:",
            44,
        )
        self.assertGreater(len(pr_wrapped), 1)
        for cont in pr_wrapped[1:]:
            self.assertTrue(cont.startswith("   ") and not cont.startswith("    "), repr(cont))
            self.assertLessEqual(self.mod.display_width(cont), 44)

        # 2. _extract_last_error_line clamps to narrow box width instead of 60-col floor
        narrow_step = self.tmp / "s58_err" / "1"
        narrow_step.mkdir(parents=True)
        long_err = "ValueError: " + ("x" * 120)
        (narrow_step / "out").write_text("[s58_err/1] START\n" + long_err + "\n", encoding="utf-8")
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((44, 24))):
            clamped_err = self.mod._extract_last_error_line(narrow_step / "out", label="s58_err/1")
        self.assertTrue(clamped_err.endswith("..."))
        self.assertLessEqual(self.mod.display_width(clamped_err), 36)

        # 3. All TUI box types wrap cleanly on 40, 48, 60, and 70 column terminals
        proj = self.tmp / "f58_proj_with_a_very_long_directory_name_segment"
        proj.mkdir()
        sessions = self.tmp / "f58_sessions_storage_dir"
        sdir = sessions / "s58"
        step1 = sdir / "1"
        step1.mkdir(parents=True)
        out_p = step1 / "out"
        scr_p = step1 / "block.sh"
        scr_p.write_text("cat " + "/".join(["segment"] * 8) + "/file.txt\nrm -rf /tmp/f58_warn_target\n", encoding="utf-8")
        out_p.write_text(
            "line one\nline two\n"
            "AssertionError: expected narrow terminal wrapping to preserve border alignment\n",
            encoding="utf-8",
        )
        bundle_p = sdir / "0"
        bundle_p.write_text(
            "Session: s58\n"
            "Next-Block: s58/1\n"
            f"Workdir: {proj}\n"
            "Sandbox: strict (rw: Workdir, /tmp; secrets: hidden; net: on)\n"
            "Date: 2026-11-18 18:45 UTC\n\n"
            "===== Prompt =====\nBody\n",
            encoding="utf-8",
        )
        self.mod.write_session_meta(
            sdir,
            [
                ("Role", "execute"),
                ("Task", "F58"),
                ("Title", "Wrap long lines inside all TUI boxes while preserving hanging indents across narrow terminals"),
            ],
        )

        old_base = self.mod.BASE_DIR
        self.mod.BASE_DIR = sessions
        try:
            op_timings = [
                {"step": 1, "tag": "read", "desc": "cat file", "duration_ms": 15},
                {"step": 2, "tag": "write", "desc": "write file", "duration_ms": 230},
                {"step": 3, "tag": "exec", "desc": "pytest -q", "duration_ms": 1400},
            ]
            findings = self.mod.scan_script_risks(scr_p.read_text(encoding="utf-8"))
            summary = self.mod.summarize_script_actions(scr_p.read_text(encoding="utf-8"), work_dir=proj)
            summary["sandbox"] = "strict"
            summary["cd_dirs"] = ["apps/very_long_subproject_a", "apps/very_long_subproject_b"]

            for cols in (40, 50, 64, 70):
                with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((cols, 24))):
                    # START SESSION
                    bundle_box, _, _ = self.mod.format_clipboard_box(
                        "s58/0",
                        bundle_p,
                        ok=True,
                        rc=0,
                        stats="120 lines · 4.2k chars · ~1.1k–1.2k tokens",
                        title_kind="START SESSION",
                        extra_lines=[f"Bundle: {bundle_p}"],
                        sdir=sdir,
                    )
                    _assert_box_fits(bundle_box, cols, f"START_SESSION@{cols}")
                    self.assertIn("│ Workdir:    ", bundle_box)
                    self.assertIn("│             ", bundle_box)

                    # PLAN
                    plan_box, _, _ = self.mod.format_safety_box(
                        "s58/1",
                        findings,
                        default_yes=False,
                        summary=summary,
                        note="Analyzer note with enough words to verify wrapping inside PLAN box",
                        script_path=scr_p,
                    )
                    _assert_box_fits(plan_box, cols, f"PLAN@{cols}")

                    # END STEP
                    end_box, _, _ = self.mod.format_clipboard_box(
                        "s58/1",
                        out_p,
                        ok=False,
                        rc=1,
                        stats="45 lines · 1.8k chars · ~450–515 tokens · 1.6s",
                        title_kind="END STEP",
                        op_timings=op_timings,
                        failed_step=3,
                        sdir=sdir,
                    )
                    _assert_box_fits(end_box, cols, f"END_STEP@{cols}")
                    self.assertNotIn("│ Steps:", end_box)
                    self.assertIn("│         ", end_box)

                    # NOT RUN & SYNTAX ERROR
                    nr_lines = self.mod.build_box_body_lines(
                        out_p,
                        rc=2,
                        stats="2 lines · 80 chars · ~20–23 tokens",
                        extra_lines=[
                            "Target: s58/1 -> s58/1_1",
                            "Reason: fix assertion failed because expected anchor did not match script content",
                            "  at line 4: assert text.count('very_long_anchor_name_exceeding_forty_cols') == 1",
                            "Guard: reached 2/2 failed --fix attempts for s58/1; switch to a fresh s58/2 block instead.",
                            f"Output: {out_p}",
                        ],
                        label="s58/1_1",
                        sdir=sdir,
                    )
                    nr_box = self.mod.format_info_box("NOT RUN", nr_lines)
                    _assert_box_fits(nr_box, cols, f"NOT_RUN@{cols}")

                    syn_lines = self.mod.build_box_body_lines(
                        out_p,
                        rc=2,
                        stats="3 lines · 95 chars · ~24–27 tokens",
                        extra_lines=[
                            "Exit: 2",
                            f"Script: {scr_p}",
                            f"Output: {out_p}",
                            "Error: syntax error near unexpected token in very_long_function_definition()",
                            "  line 12: if [ -f /very/long/path/inside/syntax/error/detail/message ]; then",
                        ],
                        label="s58/1",
                        sdir=sdir,
                    )
                    syn_box = self.mod.format_info_box("SYNTAX ERROR", syn_lines)
                    _assert_box_fits(syn_box, cols, f"SYNTAX_ERROR@{cols}")

                    # MISSING PREVIOUS STEP & STEP ALREADY EXISTS via prompt_yes_no_box
                    tty_w_miss = io.StringIO()
                    tty_r_miss = io.StringIO("y\n")
                    miss_ok = self.mod.prompt_yes_no_box(
                        "MISSING PREVIOUS STEP",
                        self.mod.format_session_header_lines(label="s58/3", sdir=sdir) + ["", "Missing: s58/2"],
                        "Run s58/3 even though previous step s58/2 has not run yet?",
                        default_yes=False,
                        tty_streams=(tty_w_miss, tty_r_miss),
                    )
                    self.assertTrue(miss_ok)
                    miss_box_part = tty_w_miss.getvalue().split("\r\033[1A")[0]
                    _assert_box_fits(miss_box_part, cols, f"MISSING_PREV@{cols}")

                    tty_w_exists = io.StringIO()
                    tty_r_exists = io.StringIO("r\n")
                    ex_res = self.mod.prompt_yes_no_box(
                        "STEP ALREADY EXISTS",
                        self.mod.format_session_header_lines(label="s58/1", sdir=sdir)
                        + ["", "Next: s58/2", f"Script: {scr_p}", f"Output: {out_p}"],
                        "Step s58/1 already exists. r(enumber) to s58/2 or R(estart)?",
                        default_yes=False,
                        tty_streams=(tty_w_exists, tty_r_exists),
                        script_path=scr_p,
                        out_path=out_p,
                        renumber_label="s58/2",
                    )
                    self.assertEqual(ex_res, "renumber")
                    ex_box_part = tty_w_exists.getvalue().split("\r\033[1A")[0]
                    _assert_box_fits(ex_box_part, cols, f"STEP_EXISTS@{cols}")

            # 4. TTY color mode keeps ANSI colors intact across wrapped KV and prompt lines
            tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            tty_stream.isatty = lambda: True  # type: ignore[method-assign]
            saved_nc = os.environ.pop("NO_COLOR", None)
            try:
                with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream), \
                     unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((44, 24))):
                    col_plan, _, col_off = self.mod.format_safety_box(
                        "s58/1", findings, default_yes=False, summary=summary, script_path=scr_p
                    )
                    _assert_box_fits(col_plan, 44, "COLOR_PLAN@44")
                    self.assertIn("\x1b[1;33m", col_plan)
                    self.assertIn("\x1b[0m\n\x1b[93m│\x1b[0m          \x1b[1;33m", col_plan)
                    last_prompt_row = col_plan.splitlines()[-2]
                    self.assertEqual(col_off, self.mod.display_width(last_prompt_row))

                    col_end, _, _ = self.mod.format_clipboard_box(
                        "s58/1", out_p, ok=False, rc=1, stats="10 lines · 200 chars", title_kind="END STEP", sdir=sdir
                    )
                    _assert_box_fits(col_end, 44, "COLOR_END@44")
                    self.assertIn("\x1b[1;91mAssertionError:", col_end)

                with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream):
                    col_wrap_box, _, col_wrap_off = self.mod._render_block(
                        "START STEP",
                        ["Step: s58/1", "Workdir: /tmp/f58_proj"],
                        prompt_line="\x1b[1;93m-> Execute this block? [y/n/i(nfo)]:\x1b[0m",
                        term_cols=36,
                    )
                    _assert_box_fits(col_wrap_box, 36, "COLOR_PROMPT@36")
                    self.assertIn("\x1b[0m\n\x1b[93m│\x1b[0m    \x1b[1;93m", col_wrap_box)
                    self.assertEqual(col_wrap_off, self.mod.display_width(col_wrap_box.splitlines()[-2]))
            finally:
                if saved_nc is not None:
                    os.environ["NO_COLOR"] = saved_nc
        finally:
            self.mod.BASE_DIR = old_base

    def test_progress_alignment_colors_and_silent_collapse(self):
        step_map = {
            1: {"step": 1, "tag": "exec", "desc": "mkdir -p out"},
            2: {"step": 2, "tag": "read", "desc": "cat a.txt"},
            3: {"step": 3, "tag": "exec", "desc": "very_long_command " + ("x" * 90)},
        }

        # 1. Column-0 alignment, neutral gray & red ANSI colors on TTY
        tty_utf8 = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_utf8.isatty = lambda: True  # type: ignore[method-assign]
        saved_nc = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_utf8), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))):
                t_seq = iter([10.0, 10.05, 10.30, 10.80])
                pf = self.mod._ProgressLineFilter(step_map, total_steps=3, clock=lambda: next(t_seq))
                # Step 1 has no output -> collapses in place on step 2 start
                ev1 = pf.feed_events("__RB_STEP__:1\n__RB_STEP__:2\n")
                self.assertEqual(ev1[0], ("prog", "\x1b[90m▸ [1/3] [exec] mkdir -p out\x1b[0m\n"))
                self.assertEqual(
                    ev1[1],
                    (
                        "prog",
                        "\033[1A\r\033[2K\x1b[90m✓ [1/3] [exec] mkdir -p out (50ms)\x1b[0m\n"
                        "\x1b[90m▸ [2/3] [read] cat a.txt\x1b[0m\n",
                    ),
                )
                # Step 2 emits output -> keeps banner above, prints ✓ at column 0 below
                ev2 = pf.feed_events("alpha\n__RB_STEP__:3\n")
                self.assertEqual(ev2[0], ("out", "alpha\n"))
                self.assertTrue(ev2[1][1].startswith("\x1b[90m✓ [2/3] (250ms)\x1b[0m\n"))
                self.assertNotIn("\033[1A", ev2[1][1])
                # Step 3 is silent and fails (rc=1) -> collapses in place in red, truncated to _hr_width()
                rem_out, rem_prog = pf.flush(rc=1)
                self.assertEqual(rem_out, "")
                self.assertTrue(rem_prog.startswith("\033[1A\r\033[2K\x1b[31m✗ [3/3] [exec] "))
                self.assertTrue(rem_prog.endswith("... (500ms)\x1b[0m\n"))
                plain_collapsed = self.mod.ANSI_RE.sub("", rem_prog[len("\033[1A\r\033[2K") :]).rstrip("\n")
                self.assertLessEqual(self.mod.display_width(plain_collapsed), 80)

                # Step with output that fails prints red ✗ at column 0 without 2-space indent
                pf_fail_out = self.mod._ProgressLineFilter(
                    {1: {"step": 1, "tag": "exec", "desc": "run"}},
                    total_steps=1,
                    clock=iter([1.0, 2.5]).__next__,
                )
                pf_fail_out.feed_events("__RB_STEP__:1\nerror line\n")
                _, fail_prog = pf_fail_out.flush(rc=2)
                self.assertEqual(fail_prog, "\x1b[31m✗ [1/1] (1.5s)\x1b[0m\n")
        finally:
            if saved_nc is not None:
                os.environ["NO_COLOR"] = saved_nc

        # 2. ASCII fallback (+ / x / >) at column 0 without ANSI when NO_COLOR=1
        tty_ascii = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
        tty_ascii.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", tty_ascii), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((50, 24))):
            pf_asc = self.mod._ProgressLineFilter(
                {
                    1: {"step": 1, "tag": "exec", "desc": "silent_cmd"},
                    2: {"step": 2, "tag": "exec", "desc": "noisy_fail"},
                },
                total_steps=2,
                clock=iter([0.0, 0.01, 0.21]).__next__,
            )
            ev_asc = pf_asc.feed_events("__RB_STEP__:1\n__RB_STEP__:2\nbad\n")
            self.assertEqual(ev_asc[0], ("prog", "> [1/2] [exec] silent_cmd\n"))
            self.assertEqual(
                ev_asc[1],
                ("prog", "\033[1A\r\033[2K+ [1/2] [exec] silent_cmd (10ms)\n> [2/2] [exec] noisy_fail\n"),
            )
            _, rem_asc = pf_asc.flush(rc=1)
            self.assertEqual(rem_asc, "x [2/2] (200ms)\n")

        # 3. Non-TTY suppresses in-place ANSI cursor overwrite even for silent steps
        pf_nontty = self.mod._ProgressLineFilter(
            {1: {"step": 1, "tag": "exec", "desc": "silent"}},
            total_steps=1,
            clock=iter([0.0, 0.02]).__next__,
            is_tty=False,
        )
        pf_nontty.feed_events("__RB_STEP__:1\n")
        _, rem_nontty = pf_nontty.flush(rc=0)
        self.assertEqual(rem_nontty, "✓ [1/1] (20ms)\n")
        self.assertNotIn("\033[1A", rem_nontty)

        # 4. End-to-end run_script: silent step collapses, stdout & stderr steps keep header and align at col 0
        work = self.tmp / "f56_work"
        work.mkdir()
        (work / "a.txt").write_text("hello_f56\n", encoding="utf-8")
        sdir = self.tmp / "s56"
        step1_dir = sdir / "1"
        step1_dir.mkdir(parents=True)
        script_p = step1_dir / "block.sh"
        out_p = step1_dir / "out"
        script_p.write_text("mkdir -p sub_dir\ncat a.txt\necho err_f56 >&2\n", encoding="utf-8")
        os.environ["RUN_BLOCK_CWD"] = str(work)
        buf_e2e = io.StringIO()
        buf_e2e.isatty = lambda: True  # type: ignore[method-assign]
        with unittest.mock.patch.object(self.mod.sys, "stdout", buf_e2e), \
             unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, "")), \
             unittest.mock.patch.object(self.mod, "offer_clipboard_copy"):
            rc_e2e = self.mod.run_script("s56/1", script_p, out_p, auto_yes=False)
        self.assertEqual(rc_e2e, 0)
        live_e2e = buf_e2e.getvalue()
        self.assertIn("\033[1A\r\033[2K✓ [1/3] [write] mkdir -p sub_dir (", live_e2e)
        self.assertIn("▸ [2/3] [read] cat a.txt\nhello_f56\n✓ [2/3] (", live_e2e)
        self.assertIn("▸ [3/3] [exec] echo err_f56 >&2\nerr_f56\n✓ [3/3] (", live_e2e)
        self.assertNotIn("  ✓ [", live_e2e)

    def test_height_clamping_altscreen_details_and_display_width(self):
        import pty
        import signal
        import threading
        import time
        # 1. display_width() treats Unicode combining (Mn/Me), zero-width format (Cf), and control (Cc) chars as 0,
        #    expands tabs to 8-col stops, and keeps _box_rows_above_prompt() exact
        self.assertEqual(self.mod.display_width("e\u0301"), 1)
        self.assertEqual(self.mod.display_width("a\u20dd"), 1)
        self.assertEqual(self.mod.display_width("a\u200bb\u200dc\ufeffd"), 4)
        self.assertEqual(self.mod.display_width("a\tb"), 9)
        self.assertEqual(self.mod.display_width("abcd\te"), 9)
        self.assertEqual(self.mod.display_width("\x1b[1;32mhi\t!\x1b[0m"), 9)
        tab_wrapped = self.mod._wrap_box_line("col1\tcol2\tcol3_overflow", 18)
        for ln in tab_wrapped:
            self.assertNotIn("\t", ln)
            self.assertLessEqual(self.mod.display_width(ln), 18)

        # 2. Inline boxes clamp to term_rows with '... +N more' across PLAN, END, BUNDLE, and confirmation dialogs
        os.environ["RUN_BLOCK_CWD"] = str(self.tmp)
        sdir = self.tmp / "s_b11"
        step1 = sdir / "1"
        step1.mkdir(parents=True)
        b0 = sdir / "0"
        many_parts = [
            "Session: s_b11",
            "Next-Block: s_b11/1",
            f"Workdir: {self.tmp}",
            "Sandbox: off",
            "Date: 2026-11-19 17:45 UTC",
            "",
        ]
        for idx in range(1, 14):
            many_parts.append(f"===== Part {idx} =====")
            many_parts.append(f"Body content for part {idx}")
        b0.write_text("\n".join(many_parts) + "\n", encoding="utf-8")
        self.mod.refresh_bundle_meta(b0)

        scr = step1 / "block.sh"
        scr.write_text("\n".join(f"cat file_{i}.txt" for i in range(16)) + "\n", encoding="utf-8")
        out_p = step1 / "out"
        out_p.write_text("line 1\nline 2\n", encoding="utf-8")
        sum_many = self.mod.summarize_script_actions(scr.read_text(encoding="utf-8"), work_dir=self.tmp)

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((80, 14))):
            plan_box, _, _ = self.mod.format_safety_box("s_b11/1", [], default_yes=True, summary=sum_many, script_path=scr)
            plan_rows = plan_box.splitlines()
            self.assertLessEqual(len(plan_rows), 14)
            self.assertTrue(plan_rows[0].startswith("╭─ START STEP "))
            self.assertTrue(any("... +" in r and " more" in r for r in plan_rows))

            end_box, _, _ = self.mod.format_clipboard_box(
                "s_b11/1",
                out_p,
                ok=True,
                rc=0,
                stats="2 lines · 14 chars",
                title_kind="END STEP",
                extra_lines=[f"Line {i}" for i in range(20)],
                sdir=sdir,
            )
            end_rows = end_box.splitlines()
            self.assertLessEqual(len(end_rows), 14)
            self.assertTrue(end_rows[0].startswith("╭─ END STEP "))
            self.assertTrue(any("... +" in r and " more" in r for r in end_rows))

            prompt_box, _, _ = self.mod.format_prompt_box(
                "STEP ALREADY EXISTS",
                [f"Detail line {i}" for i in range(20)],
                "-> Overwrite s_b11/1? [y/N]:",
            )
            prompt_rows = prompt_box.splitlines()
            self.assertLessEqual(len(prompt_rows), 14)
            self.assertTrue(prompt_rows[0].startswith("╭─ STEP ALREADY EXISTS "))
            self.assertTrue(any("... +" in r and " more" in r for r in prompt_rows))

        # 3. Fullscreen alternate-screen BUNDLE DETAILS scrolls (j/k/Down/Up/PgDn/PgUp), copies on Enter,
        #    and returns cleanly without duplicating inline '╭─ BUNDLE ' headers
        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w_scroll = _KeepOpenStringIO()
        # d -> j -> pgdn -> pgup -> k -> q -> esc
        tty_r_scroll = io.StringIO("d\nj\npgdn\npgup\nk\nq\nesc\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_scroll, tty_r_scroll)), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((80, 14))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy("s_b11/0", b0, title_kind="START SESSION", extra_lines=[f"Bundle: {b0}"], sdir=sdir)

        scroll_out = tty_w_scroll.getvalue()
        self.assertEqual(scroll_out.count("╭─ START SESSION "), 1)
        self.assertEqual(scroll_out.count("\033[?1049h"), 1)
        self.assertEqual(scroll_out.count("\033[?1049l"), 1)
        self.assertIn("Lines 1-", scroll_out)
        self.assertIn("Lines 2-", scroll_out)
        self.assertIn("Skipped clipboard copy.", scroll_out)

        # Enter inside fullscreen details copies to clipboard and exits cleanly
        tty_w_copy = _KeepOpenStringIO()
        tty_r_copy = io.StringIO("i\n\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_copy, tty_r_copy)), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_clip_enter, \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((80, 14))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy("s_b11/0", b0, title_kind="START SESSION", extra_lines=[f"Bundle: {b0}"], sdir=sdir)

        mock_clip_enter.assert_called_once_with(["pbcopy"], b0)
        copy_out = tty_w_copy.getvalue()
        self.assertEqual(copy_out.count("╭─ START SESSION "), 1)
        self.assertIn("\033[?1049h", copy_out)
        self.assertIn("\033[?1049l", copy_out)
        self.assertIn(f"Copied {b0} to clipboard.", copy_out)

        # 4. SIGWINCH height-only changes (rows: 24 -> 11 -> 24, cols fixed at 80) reflow PLAN, END, and confirm dialogs
        if self.mod.HAS_PTY and hasattr(signal, "SIGWINCH"):
            cur_size = [80, 24]

            def _h_size(_fallback=(80, 24)):
                return os.terminal_size((cur_size[0], cur_size[1]))

            def _wait_h_box(tw, marker: str, count: int) -> None:
                deadline = time.monotonic() + 1.5
                while time.monotonic() < deadline:
                    if (
                        tw.getvalue().count(marker) >= count
                        and getattr(signal.getsignal(signal.SIGWINCH), "__name__", "") == "_on_sigwinch"
                    ):
                        time.sleep(0.003)
                        return
                    time.sleep(0.002)

            # 4a. confirm_execution height shrink & restore
            m_fd1, s_fd1 = pty.openpty()
            try:
                tw1 = _KeepOpenStringIO()
                tr1 = os.fdopen(os.dup(s_fd1), "r", encoding="utf-8", errors="replace")
                with tr1:
                    def _drv1():
                        _wait_h_box(tw1, "╭─ START STEP ", 1)
                        cur_size[1] = 11
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw1, "╭─ START STEP ", 2)
                        cur_size[1] = 24
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw1, "╭─ START STEP ", 3)
                        os.write(m_fd1, b"n")

                    t1 = threading.Thread(target=_drv1, daemon=True)
                    with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                         unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw1, tr1)), \
                         unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=_h_size), \
                         unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                        t1.start()
                        self.mod.confirm_execution("s_b11/1", scr.read_text(encoding="utf-8"), summary=sum_many, script_path=scr)
                        t1.join(timeout=2.0)
                out1 = tw1.getvalue()
                self.assertEqual(out1.count("╭─ START STEP "), 3)
                self.assertIn("... +", out1)
            finally:
                os.close(m_fd1)
                os.close(s_fd1)

            # 4b. prompt_yes_no_box height shrink & restore
            cur_size[1] = 24
            m_fd2, s_fd2 = pty.openpty()
            try:
                tw2 = _KeepOpenStringIO()
                tr2 = os.fdopen(os.dup(s_fd2), "r", encoding="utf-8", errors="replace")
                with tr2:
                    def _drv2():
                        _wait_h_box(tw2, "╭─ CLEAN SESSIONS ", 1)
                        cur_size[1] = 10
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw2, "╭─ CLEAN SESSIONS ", 2)
                        cur_size[1] = 24
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw2, "╭─ CLEAN SESSIONS ", 3)
                        os.write(m_fd2, b"y")

                    t2 = threading.Thread(target=_drv2, daemon=True)
                    with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=_h_size), \
                         unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                        t2.start()
                        self.mod.prompt_yes_no_box(
                            "CLEAN SESSIONS",
                            [f"Session item {i}" for i in range(18)],
                            "Delete sessions?",
                            tty_streams=(tw2, tr2),
                        )
                        t2.join(timeout=2.0)
                out2 = tw2.getvalue()
                self.assertEqual(out2.count("╭─ CLEAN SESSIONS "), 3)
                self.assertIn("... +", out2)
            finally:
                os.close(m_fd2)
                os.close(s_fd2)

            # 4c. offer_clipboard_copy height shrink & restore
            cur_size[1] = 24
            m_fd3, s_fd3 = pty.openpty()
            try:
                tw3 = _KeepOpenStringIO()
                tr3 = os.fdopen(os.dup(s_fd3), "r", encoding="utf-8", errors="replace")
                with tr3:
                    def _drv3():
                        _wait_h_box(tw3, "╭─ END STEP ", 1)
                        cur_size[1] = 11
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw3, "╭─ END STEP ", 2)
                        cur_size[1] = 24
                        os.kill(os.getpid(), signal.SIGWINCH)
                        _wait_h_box(tw3, "╭─ END STEP ", 3)
                        os.write(m_fd3, b"\x1b")

                    t3 = threading.Thread(target=_drv3, daemon=True)
                    with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                         unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
                         unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {out_p}")), \
                         unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw3, tr3)), \
                         unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=_h_size), \
                         unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                        t3.start()
                        self.mod.offer_clipboard_copy(
                            "s_b11/1",
                            out_p,
                            title_kind="END STEP",
                            extra_lines=[f"Output row {i}" for i in range(18)],
                            sdir=sdir,
                        )
                        t3.join(timeout=2.0)
                out3 = tw3.getvalue()
                self.assertEqual(out3.count("╭─ END STEP "), 3)
                self.assertIn("... +", out3)
            finally:
                os.close(m_fd3)
                os.close(s_fd3)

    def test_end_drops_steps_and_info_viewer(self):
        old_base = self.mod.BASE_DIR
        self.mod.BASE_DIR = self.tmp
        try:
            sdir = self.tmp / "s54"
            sdir.mkdir(parents=True)
            bundle_in = (
                "Bundle-Command: agents_bundle role=work task=F54\n"
                "Bundle-Boundary: bnd54\n"
                "Role: work\n"
                "Task: F54\n"
                "Title: Long title for F54 info viewer verification\n\n"
                "===== Prompt =====\nHello F54\n"
            )
            b0 = sdir / "0"
            res = self.mod.format_start_bundle("s54", stdin_body=bundle_in, work_dir=self.tmp, sandbox_mode="off")
            b0.write_text(str(res["full"]), encoding="utf-8")
            self.mod.write_session_meta(sdir, res["stdin_headers"], bundle_plan=res["bundle_plan"])
            orig0 = sdir / "0.orig"
            orig0.write_text(str(res["full"]), encoding="utf-8")

            # 1. START SESSION i(nfo) exposes unfiltered headers (Sandbox: off, Bundle-*), bright white Stats:, and v(iew)
            tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
            tty_stream.isatty = lambda: True  # type: ignore[method-assign]
            saved_nc = os.environ.pop("NO_COLOR", None)
            try:
                with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream):
                    frame0, _, _ = self.mod._build_info_screen(
                        "START SESSION", "s54/0", 100, 30, 0, sdir=sdir, out_path=b0, edit_target=b0, allow_copy=True
                    )
                    compact_box, _, _ = self.mod.format_clipboard_box(
                        "s54/0", b0, stats=self.mod.stats_line(b0), title_kind="START SESSION", sdir=sdir, term_cols=100, term_rows=30
                    )
            finally:
                if saved_nc is not None:
                    os.environ["NO_COLOR"] = saved_nc
            self.assertIn("START SESSION · s54/0 · ", frame0)
            self.assertNotIn("╭─ INFO", frame0)
            self.assertNotIn("│ Session:", frame0)
            self.assertIn("Bundle:", frame0)
            self.assertNotIn("Stats:", frame0)
            self.assertIn("Sandbox:", frame0)
            self.assertIn("off", frame0)
            self.assertIn("Bundle-Command:", frame0)
            self.assertIn("agents_bundle role=work task=F54", frame0)
            self.assertIn("[total]", frame0)
            self.assertIn("\x1b[2mStats:", compact_box)
            self.assertNotIn("\x1b[97m", compact_box)

            # 2. v(iew) in i(nfo) opens plain-text report (no ANSI) in editor
            viewed_reports: list[str] = []

            def capture_view(p: Path, _r, _w) -> None:
                viewed_reports.append(p.read_text(encoding="utf-8"))

            class _KeepOpenStringIO(io.StringIO):
                def close(self) -> None:
                    pass

            fake_stdout = io.StringIO()
            fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
            tw_v = _KeepOpenStringIO()
            tr_v = io.StringIO("i\nv\nq\nesc\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                 unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
                 unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0}")), \
                 unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_v, tr_v)), \
                 unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=capture_view), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
                 unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                self.mod.offer_clipboard_copy("s54/0", b0, title_kind="START SESSION", sdir=sdir)
            self.assertEqual(len(viewed_reports), 1)
            self.assertNotIn("\x1b[", viewed_reports[0])
            self.assertRegex(viewed_reports[0], r"Sandbox:\s+off")
            self.assertRegex(viewed_reports[0], r"Bundle-Command:\s+agents_bundle role=work task=F54")

            # 3. END STEP omits Steps:, while i(nfo) shows the output breakdown table with TIME, (failed), and [total] rows
            step1 = sdir / "1"
            step1.mkdir()
            scr1 = step1 / "block.sh"
            orig_scr1 = step1 / "block.orig.sh"
            out1 = step1 / "out"
            orig_scr1.write_text("cat README.md\n", encoding="utf-8")
            scr1.write_text("cat README.md\nls missing\n", encoding="utf-8")
            out1.write_text("[s54/1] START\nls: missing: No such file\n\n[s54/1] END (exit 1, 1.0s)\n", encoding="utf-8")
            op_timings = [
                {"step": 1, "tag": "read", "desc": "cat README.md", "duration_ms": 200},
                {"step": 2, "tag": "read", "desc": "ls missing", "duration_ms": 800},
            ]
            self.mod.write_step_meta(step1, duration_ms=1000, exit_code=1, operations=op_timings, failed_step=2)
            end_body = self.mod.build_box_body_lines(out1, rc=1, stats=self.mod.stats_line(out1), label="s54/1", sdir=sdir)
            self.assertFalse(any(ln.startswith("Steps:") for ln in end_body))
            info_end, _, _ = self.mod._build_info_screen(
                "END STEP", "s54/1", 100, 32, 0, sdir=sdir, out_path=out1, script_path=scr1, rc=1
            )
            self.assertNotIn("Operations (", info_end)
            self.assertNotIn("Pre-execution Plan", info_end)
            self.assertIn("TIME", info_end)
            self.assertIn("[total]", info_end)
            self.assertIn("2 operations", info_end)
            self.assertIn("cat README.md", info_end)
            self.assertIn("ls missing (failed)", info_end)
            self.assertIn("800ms", info_end)
            self.assertIn("Script-Orig:", info_end)

            # 4. STEP ALREADY EXISTS i(nfo) -> O(verwrite) (with out) and o(verwrite) (without out)
            tw_ov = _KeepOpenStringIO()
            tr_ov = io.StringIO("i\nO\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                 unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
                 unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_ov, tr_ov)), \
                 unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
                 unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                rc_ov = self.mod.cmd_normal("s54/1", "echo overwritten_step\n", auto_yes=False)
            self.assertEqual(rc_ov, 0)
            self.assertIn("O(verwrite)", tw_ov.getvalue())
            self.assertIn("✓ Overwriting s54/1.", tw_ov.getvalue())
            self.assertIn("overwritten_step", out1.read_text(encoding="utf-8"))
            self.assertFalse(orig_scr1.exists())

            step2 = sdir / "2"
            step2.mkdir()
            (step2 / "block.sh").write_text("echo partial_2\n", encoding="utf-8")
            tw_ov2 = _KeepOpenStringIO()
            tr_ov2 = io.StringIO("i\no\n")
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                 unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="never"), \
                 unittest.mock.patch.object(self.mod, "open_tty", return_value=(tw_ov2, tr_ov2)), \
                 unittest.mock.patch.object(self.mod, "confirm_execution", return_value=(True, None)), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
                 unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                rc_ov2 = self.mod.cmd_normal("s54/2", "echo overwritten_no_out\n", auto_yes=False)
            self.assertEqual(rc_ov2, 0)
            self.assertIn("o(verwrite)", tw_ov2.getvalue())
            self.assertIn("overwritten_no_out", (step2 / "out").read_text(encoding="utf-8"))

            # 5. SESSION COMPLETED prompt shows [y/N/i(nfo)]: and i(nfo) displays Completed metadata
            self.mod.update_session_meta(sdir, completed=True, completed_at="2026-11-19T20:00:00Z", completed_note="done")
            tw_comp = _KeepOpenStringIO()
            tr_comp = io.StringIO("i\nq\nn\n")
            res_comp = self.mod.prompt_yes_no_box(
                "SESSION COMPLETED",
                ["Session: s54", "Completed: 2026-11-19T20:00:00Z"],
                "Reopen completed session s54?",
                default_yes=False,
                tty_streams=(tw_comp, tr_comp),
                label="s54",
                sdir=sdir,
            )
            self.assertFalse(res_comp)
            comp_out = tw_comp.getvalue()
            self.assertIn("-> Reopen completed session s54? [y/N/i(nfo)]:", comp_out)
            self.assertIn("SESSION COMPLETED · s54 · ", comp_out)
            self.assertRegex(comp_out, r"Completed:\s+2026-11-19T20:00:00Z")
            self.assertRegex(comp_out, r"Completed-Note:\s+done")
        finally:
            self.mod.BASE_DIR = old_base

    def test_borderless_info_home_shortened_title_prompt_and_tab_cursor(self):
        # 1. read_clipboard_key supports p/P in raw TTY and p/prompt in line mode
        for line_in in ("p\n", "P\n", "prompt\n", "PROMPT\n"):
            with self.subTest(line_in=line_in):
                self.assertEqual(self.mod.read_clipboard_key(io.StringIO(line_in)), "prompt")

        # 2. Home-shortened title bar (~path) and (edited) suffix in borderless _build_info_screen
        home_dir = Path.home()
        fake_in_home = home_dir / ".local/state/run_block/s77/0"
        self.assertEqual(self.mod._shorten_home_path(fake_in_home), "~/.local/state/run_block/s77/0")

        sdir = self.tmp / "s77"
        sdir.mkdir(parents=True)
        b0 = sdir / "0"
        nonce = "bnd77"
        stdin_text = (
            f"Bundle-Boundary: {nonce}\n"
            "Role: work\n\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","id":"pkg:r1","chain":["pkg","sub"]}} -->\n'
            "Rule 1 line\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","id":"pkg:r2","chain":["pkg","sub"]}} -->\n'
            "Rule 2 line\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind":"prompt","name":"Prompt"}} -->\n'
            "===== Prompt =====\nInitial prompt\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res = self.mod.format_start_bundle("s77", stdin_body=stdin_text, work_dir=self.tmp, sandbox_mode="off")
        b0.write_text(str(res["full"]), encoding="utf-8")
        self.mod.write_session_meta(sdir, list(res["stdin_headers"]), bundle_plan=res["bundle_plan"])

        with unittest.mock.patch.object(self.mod.Path, "home", return_value=self.tmp):
            frame, _, vp_rows = self.mod._build_info_screen(
                "START SESSION",
                "s77/0",
                100,
                28,
                0,
                sdir=sdir,
                out_path=b0,
                edit_target=b0,
                edited=False,
                allow_copy=True,
            )
        plain_frame = self.mod.ANSI_RE.sub("", frame)
        self.assertIn("START SESSION · s77/0 · ~/s77/0", plain_frame)
        self.assertNotIn("(edited)", plain_frame)
        self.assertNotIn("╭─", plain_frame)
        self.assertNotIn("╰─", plain_frame)
        self.assertNotIn("│ Session:", plain_frame)
        self.assertIn("Bundle:", plain_frame)
        self.assertNotIn("Stats:", plain_frame)

        # 3. p(rompt) inside fullscreen i(nfo) appends prompt, creates 0.orig, refreshes bundle_plan and [total] (edited)
        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        def stub_prompt_editor(p: Path, _r, _w) -> None:
            p.write_text("Appended from info screen\n", encoding="utf-8")

        tty_w = _KeepOpenStringIO()
        # p -> append prompt, then tab -> enter cursor mode, down -> move cursor, Enter -> open part, q -> back to cursor, Esc -> exit cursor, q -> exit info
        keys = iter(["prompt", "tab", "down", "copy", "back", "esc", "back"])
        cb_paths: list[Path] = []

        def on_edit(p: Path) -> dict[str, object]:
            cb_paths.append(p)
            self.mod.refresh_bundle_meta(p)
            return {"edited": True}

        with unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_prompt_editor),              unittest.mock.patch.object(self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys)),              unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 28)),              unittest.mock.patch.object(self.mod.Path, "home", return_value=self.tmp):
            info_res = self.mod._show_info_fullscreen(
                title_kind="START SESSION",
                label="s77/0",
                tty_r=io.StringIO(),
                tty_w=tty_w,
                sdir=sdir,
                out_path=b0,
                edit_target=b0,
                allow_copy=True,
                on_edit_callback=on_edit,
            )
        self.assertTrue(info_res["edited"])
        self.assertEqual(cb_paths, [b0])
        self.assertTrue((sdir / "0.orig").is_file())
        self.assertIn("Appended from info screen", b0.read_text(encoding="utf-8"))
        out_txt = self.mod.ANSI_RE.sub("", tty_w.getvalue())
        self.assertIn("START SESSION · s77/0 · ~/s77/0 (edited)", out_txt)
        self.assertIn("5 parts (edited)", out_txt)
        self.assertIn("PART 2/5 · s77/0", out_txt)

        # 4. Sequential row numbers (1..7), dim number coloring even on heavy warn/accent rows,
        #    top-to-bottom Tab cursor across folder rows, BUNDLE folder viewer with delimiters,
        #    and boundary-preserving e(dit) inside i(nfo)
        tty_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
        tty_stream.isatty = lambda: True  # type: ignore[method-assign]
        saved_nc = os.environ.pop("NO_COLOR", None)
        try:
            with unittest.mock.patch.object(self.mod.sys, "stdout", tty_stream):
                plan_77 = self.mod.load_session_bundle_plan(sdir, b0)
                assert plan_77 is not None
                raw_tbl = self.mod.format_bundle_parts_lines(plan_77, max_width=100)
                col_tbl = self.mod._colorize_bundle_lines(raw_tbl)
        finally:
            if saved_nc is not None:
                os.environ["NO_COLOR"] = saved_nc
        # Header has no '#' and is reverse-video; row 2 is heavy (>25%) but its row number '2 ' is colored with dim _KEY_COLOR
        self.assertNotIn("#", raw_tbl[0])
        self.assertIn("\x1b[7m", col_tbl[0])
        row2_col = next(ln for ln in col_tbl if "vitalio/run-block:run" in ln)
        self.assertIn(f"{self.mod._KEY_COLOR}2 {self.mod._ANSI_RESET}{self.mod._WARN_COLOR}", row2_col)

        # Verify top-to-bottom selectable rows 1..7 and folder viewer on row 3 (pkg (2)) and row 4 (sub (2))
        b0_raw = sdir / "0.raw"
        b0_raw.write_text(str(res["raw_full"]), encoding="utf-8")
        b0.write_text(str(res["full"]), encoding="utf-8")
        (sdir / "0.orig").unlink(missing_ok=True)
        self.mod.write_session_meta(sdir, list(res["stdin_headers"]), bundle_plan=res["bundle_plan"])

        seen_editor_texts: list[str] = []

        def stub_raw_editor(p: Path, _r, _w) -> None:
            txt = p.read_text(encoding="utf-8")
            seen_editor_texts.append(txt)
            p.write_text(txt.replace("Rule 1 line", "Rule 1 edited keeping boundary"), encoding="utf-8")

        tty_w_folder = _KeepOpenStringIO()
        # tab -> row 1, down -> row 2, down -> row 3 (pkg (2) folder), copy (Enter) -> open BUNDLE 3/7,
        # next_part -> row 4 (sub (2) folder, BUNDLE 4/7), next_part -> row 5 (PART 3/5 pkg:r1),
        # edit -> edits raw boundary-marked bundle, back -> exit info
        keys_folder = iter(["tab", "down", "down", "copy", "next_part", "next_part", "edit", "back"])
        with unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_raw_editor), \
             unittest.mock.patch.object(self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys_folder)), \
             unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 28)):
            res_folder = self.mod._show_info_fullscreen(
                title_kind="START SESSION",
                label="s77/0",
                tty_r=io.StringIO(),
                tty_w=tty_w_folder,
                sdir=sdir,
                out_path=b0,
                edit_target=b0,
                allow_copy=True,
                on_edit_callback=on_edit,
            )
        self.assertTrue(res_folder["edited"])
        folder_out = self.mod.ANSI_RE.sub("", tty_w_folder.getvalue())
        self.assertIn("BUNDLE 3/7 · s77/0", folder_out)
        self.assertIn("Source: pkg (2) (bundle)", folder_out)
        self.assertIn("===== [part 3/5] [rule] pkg:r1 (lines ", folder_out)
        self.assertIn("===== [part 4/5] [rule] pkg:r2 (lines ", folder_out)
        self.assertIn("BUNDLE 4/7 · s77/0", folder_out)
        self.assertIn("PART 3/5 · s77/0", folder_out)
        # Editor saw the raw boundary markers, while saved b0 and 0.orig are clean without markers
        self.assertEqual(len(seen_editor_texts), 1)
        self.assertIn(f"<!-- bundle:{nonce}:part", seen_editor_texts[0])
        after_b0 = b0.read_text(encoding="utf-8")
        self.assertNotIn(f"bundle:{nonce}", after_b0)
        self.assertIn("Rule 1 edited keeping boundary", after_b0)
        self.assertNotIn(f"bundle:{nonce}", (sdir / "0.orig").read_text(encoding="utf-8"))
        after_plan = self.mod.load_session_bundle_plan(sdir, b0)
        assert after_plan is not None
        self.assertEqual(after_plan["protocol"], "boundary")
        self.assertEqual(after_plan["part_count"], 5)

    def test_step_info_operation_cursor_and_slice_viewer(self):
        sdir = self.tmp / "s9"
        step_dir = sdir / "1"
        step_dir.mkdir(parents=True)
        script = step_dir / "block.sh"
        script.write_text("git status -sb\npython3 - <<'PY'\nprint(1)\nPY\nls -la\n", encoding="utf-8")
        out = step_dir / "out"
        out.write_text("ok\nline2\nline3\nline4\n", encoding="utf-8")
        timings = [
            {"step": 1, "tag": "git", "desc": "git status -sb", "duration_ms": 10,
             "lines": 1, "chars": 3, "gpt": 1, "claude": 1, "out_line_start": 1, "out_line_end": 1},
            {"step": 2, "tag": "python", "desc": "1 line", "duration_ms": 20,
             "lines": 3, "chars": 15, "gpt": 4, "claude": 5, "out_line_start": 2, "out_line_end": 4},
            {"step": 3, "tag": "read", "desc": "ls -la", "duration_ms": 5},
        ]
        common = dict(sdir=sdir, out_path=out, script_path=script, rc=0, op_timings=timings, allow_copy=True)

        frame, _, _ = self.mod._build_info_screen("END STEP", "s9/1", 100, 30, 0, **common)
        self.assertIn("Tab: parts", self.mod.ANSI_RE.sub("", frame))
        frame_cur, _, _ = self.mod._build_info_screen("END STEP", "s9/1", 100, 30, 0, part_cursor=2, **common)
        plain_cur = self.mod.ANSI_RE.sub("", frame_cur)
        self.assertIn("Enter: open part", plain_cur)
        self.assertIn("Tab/Esc: exit parts", plain_cur)

        buf = io.StringIO()
        # tab -> cursor on op 1, down -> op 2, Enter -> open PART 2/3, n -> PART 3/3, back -> cursor,
        # esc -> exit cursor, back -> exit info
        keys = iter(["tab", "down", "copy", "next_part", "back", "esc", "back"])
        with unittest.mock.patch.object(
            self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys)
        ), unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 30)):
            res = self.mod._show_info_fullscreen(
                title_kind="END STEP",
                label="s9/1",
                tty_r=io.StringIO(),
                tty_w=buf,
                **common,
            )
        self.assertEqual(res["action"], "back")
        shown = self.mod.ANSI_RE.sub("", buf.getvalue())
        self.assertIn("PART 2/3 · s9/1", shown)
        self.assertIn("Command: [python] 1 line", shown)
        self.assertIn("Script-Range: lines 2-4 of", shown)
        self.assertIn("Range: lines 2-4 of", shown)
        self.assertIn("line2", shown)
        self.assertIn("line4", shown)
        self.assertNotIn("print(1)", shown)
        self.assertIn("PART 3/3 · s9/1", shown)
        self.assertIn("Range: (no output)", shown)

        # Verify in-place out edit and script edit refresh share_pct, slice metrics, and operation viewer
        meta_path = step_dir / "meta.json"
        meta_path.write_text('{"exit_code": 0}\n', encoding="utf-8")
        opened_meta: list[Path] = []

        def stub_edit_step(target: Path, _r, _w) -> None:
            if target.name == "meta.json":
                opened_meta.append(target)
            elif target.name == "out":
                target.write_text("ok\nline2_expanded_output_text\nline3\nline4\nextra_tail\n", encoding="utf-8")
            elif target.name == "block.sh":
                target.write_text(
                    "git status -sb\npython3 - <<'PY'\nprint(1)\nprint(2)\nPY\nls -la src\n",
                    encoding="utf-8",
                )

        buf_edit = io.StringIO()
        keys_edit = iter(["output", "script", "tab", "down", "copy", "meta", "back", "esc", "back"])
        with unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_edit_step),              unittest.mock.patch.object(self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys_edit)),              unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 30)):
            res_edit = self.mod._show_info_fullscreen(
                title_kind="END STEP",
                label="s9/1",
                tty_r=io.StringIO(),
                tty_w=buf_edit,
                **common,
            )
        self.assertTrue(res_edit["edited"])
        self.assertEqual(opened_meta, [meta_path])
        shown_edit = self.mod.ANSI_RE.sub("", buf_edit.getvalue())
        self.assertIn("3 operations (edited)", shown_edit)
        self.assertIn("ls -la src", shown_edit)
        self.assertIn("Script-Range: lines 2-5 of", shown_edit)
        self.assertIn("line2_expanded_output_text", shown_edit)

        # Verify START SESSION _open_part_viewer m(eta) hotkey and footer hint in PART and BUNDLE views
        sdir_b = self.tmp / "s9_bundle"
        sdir_b.mkdir(parents=True)
        b0 = sdir_b / "0"
        nonce = "bnd9"
        stdin_b = (
            f"Bundle-Boundary: {nonce}\n\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","id":"pkg:r1","chain":["pkg"]}} -->\n'
            "Rule 1\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","id":"pkg:r2","chain":["pkg"]}} -->\n'
            "Rule 2\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_b = self.mod.format_start_bundle("s9_bundle", stdin_body=stdin_b, work_dir=self.tmp, sandbox_mode="off")
        b0.write_text(str(res_b["full"]), encoding="utf-8")
        self.mod.write_session_meta(sdir_b, list(res_b["stdin_headers"]), bundle_plan=res_b["bundle_plan"])
        s_meta = sdir_b / "meta.json"
        opened_b_meta: list[Path] = []

        def stub_open_b_meta(target: Path, _r, _w) -> None:
            opened_b_meta.append(target)

        buf_b = io.StringIO()
        keys_b = iter(["tab", "down", "down", "copy", "meta", "next_part", "meta", "back", "esc", "back"])
        with unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_open_b_meta),              unittest.mock.patch.object(self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys_b)),              unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 30)):
            self.mod._show_info_fullscreen(
                title_kind="START SESSION",
                label="s9_bundle/0",
                tty_r=io.StringIO(),
                tty_w=buf_b,
                sdir=sdir_b,
                out_path=b0,
                edit_target=b0,
                allow_copy=True,
            )
        self.assertEqual(opened_b_meta, [s_meta, s_meta])
        shown_b = self.mod.ANSI_RE.sub("", buf_b.getvalue())
        self.assertIn("BUNDLE 3/5 · s9_bundle/0", shown_b)
        self.assertIn("PART 3/4 · s9_bundle/0", shown_b)
        self.assertIn("e(dit) bundle · m(eta) · Esc: back", shown_b)

    def test_fullscreen_footer_meta_key_and_operation_table(self):
        for raw, key in (("m\n", "meta"), ("meta\n", "meta"), ("e\n", "edit"), ("o\n", "output")):
            with self.subTest(raw=raw):
                self.assertEqual(self.mod._parse_pager_line(raw), key)

        tail = ["m(eta)", "Esc: back"]
        fit, _, _ = self.mod._compose_pager_frame(["T"], ["a", "b"], 80, 10, 0, tail)
        plain_fit = self.mod.ANSI_RE.sub("", fit)
        self.assertNotIn("Lines ", plain_fit)
        self.assertNotIn("scroll", plain_fit)
        self.assertIn("m(eta) · Esc: back", plain_fit)
        long_items = [f"row{i}" for i in range(40)]
        over, _, _ = self.mod._compose_pager_frame(["T"], long_items, 80, 10, 0, tail)
        plain_over = self.mod.ANSI_RE.sub("", over)
        self.assertIn("Lines 1-8/40", plain_over)
        self.assertIn("PgUp/PgDn: scroll", plain_over)

        ops = [
            {"step": 1, "tag": "read", "desc": "cat a", "duration_ms": 200, "lines": 1, "chars": 10,
             "gpt": 3, "claude": 3, "share_pct": 20.0},
            {"step": 2, "tag": "exec", "desc": "make", "duration_ms": 800, "lines": 9, "chars": 40000,
             "gpt": 10000, "claude": 11500, "share_pct": 80.0},
        ]
        total = {"lines": 10, "chars": 50000, "gpt": 12500, "claude": 14400, "duration_ms": 1000}
        lines = self.mod.format_operation_table_lines(ops, total, max_width=100, edited=True, failed_step=2)
        plain = [self.mod.ANSI_RE.sub("", ln) for ln in lines]
        self.assertRegex(plain[0], r"%\s+CHARS\s+LINES\s+~TOK\s+TIME\s+KIND\s+SOURCE")
        self.assertRegex(plain[1], r"100\.0%.*1\.0s\s+\[total\]\s+2 operations \(edited\)")
        self.assertRegex(plain[-1], r"100\.0%.*\[total\]")
        self.assertTrue(any("make (failed)" in ln and "800ms" in ln for ln in plain))
        self.assertEqual(self.mod.bundle_row_heavy_level(plain[3]), "warn")
        self.assertEqual(self.mod.bundle_row_heavy_level(plain[2]), "accent")


    def test_start_step_and_info_render_model_reasoning(self):
        sdir = self.mod.start_session("s1")
        step_dir = sdir / "1"
        step_dir.mkdir(parents=True, exist_ok=True)
        script_path = step_dir / "block.sh"
        script_path.write_text("git status -sb\npython3 -m unittest\n", encoding="utf-8")
        reasoning_text = (
            "I will check the repository status and run the unit test suite to verify the changes."
        )
        (step_dir / "plan.md").write_text(reasoning_text + "\n", encoding="utf-8")
        summary = self.mod.summarize_script_actions(script_path.read_text(encoding="utf-8"))
        summary["reasoning"] = reasoning_text

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((88, 28))):
            box, _, _ = self.mod.format_safety_box(
                "s1/1",
                [],
                default_yes=True,
                summary=summary,
                script_path=script_path,
            )
        self.assertIn("Reasoning:", box)
        self.assertIn("I will check the repository status", box)
        self.assertLess(box.index("Reasoning:"), box.index("Operations:"))

        report = self.mod._build_plain_info_report(
            title_kind="START STEP",
            label="s1/1",
            sdir=sdir,
            script_path=script_path,
            summary=summary,
        )
        self.assertIn("Reasoning:", report)
        self.assertIn(reasoning_text, report)


if __name__ == "__main__":
    unittest.main()
