#!/usr/bin/env python3
"""Bundle initialization, Bundle-* protocol, fragment parser, top-style table, --bundle-plan, --part, and -p/--prompt."""

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


class TestBundle(RunBlockTestCase):
    def test_stdin_start_bundle_without_args_and_with_start_flag(self):
        proj = self.tmp / "proj"
        proj.mkdir()
        env = {**os.environ, "RUN_BLOCK_DIR": str(self.tmp / "sessions"), "RUN_BLOCK_CWD": str(proj)}

        bundle_input = (
            "Bundle-Command: agents_bundle role=execute task=F14\n"
            "Chat-Lang: Russian\n"
            "Role: execute\n"
            "Task: F14\n\n"
            "===== File: AGENTS.md =====\n# My Project Rules\n\n===== Prompt =====\nWork on task F1\n"
        )
        r_pipe = self._run(
            [str(SCRIPT)],
            input=bundle_input,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_pipe.returncode, 0, r_pipe.stderr)
        self.assertIn("╭─ START SESSION ", r_pipe.stdout)
        self.assertIn("Session:    s1", r_pipe.stdout)
        self.assertIn("Next-Block: s1/1", r_pipe.stdout)
        self.assertNotIn("Sandbox:", r_pipe.stdout)
        self.assertNotIn("Bundle-Command:", r_pipe.stdout)
        self.assertIn("Chat-Lang:  Russian", r_pipe.stdout)
        self.assertIn("Role:       execute", r_pipe.stdout)
        self.assertIn("Task:       F14", r_pipe.stdout)
        self.assertNotIn("Date:", r_pipe.stdout)
        bundle1 = (self.tmp / "sessions/s1/0").read_text(encoding="utf-8")
        self.assertIn("Session: s1\nNext-Block: s1/1\nWorkdir:", bundle1)
        self.assertIn("\nSandbox: off\n", bundle1)
        self.assertNotIn("Bundle-Command:", bundle1)
        self.assertNotIn("Chat-Lang:", bundle1)
        self.assertNotIn("Role:", bundle1)
        self.assertNotIn("Task:", bundle1)
        meta1 = self.mod.read_session_meta(self.tmp / "sessions/s1")
        self.assertEqual(
            meta1.get("headers"),
            [
                ["Bundle-Command", "agents_bundle role=execute task=F14"],
                ["Chat-Lang", "Russian"],
                ["Role", "execute"],
                ["Task", "F14"],
            ],
        )
        self.assertRegex(bundle1, r"(?m)^Date: \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
        from datetime import datetime, timedelta, timezone
        sample_now = datetime(2026, 11, 16, 1, 13, tzinfo=timezone(timedelta(hours=3)))
        fmt_res = self.mod.format_start_bundle("s9", stdin_body="Body", work_dir=proj, now=sample_now)
        self.assertIn("Date: 2026-11-15 22:13 UTC", fmt_res["console_lines"])
        self.assertIn("\nDate: 2026-11-15 22:13 UTC\n", fmt_res["full"])
        self.assertIn("===== File: AGENTS.md =====", bundle1)
        self.assertIn("Work on task F1", bundle1)
        s1_hdrs = self.mod.parse_bundle_headers(self.tmp / "sessions/s1")
        self.assertEqual(s1_hdrs.get("role"), "execute")
        self.assertEqual(s1_hdrs.get("task"), "F14")

        r_step1 = self._run(
            [str(SCRIPT), "s1/1"],
            input="echo ran_s1_step1\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_step1.returncode, 0, r_step1.stderr)
        self.assertIn("╭─ END STEP ", r_step1.stdout)
        self.assertIn("Step:      s1/1", r_step1.stdout)
        self.assertNotIn("Bundle-Command:", r_step1.stdout)
        self.assertIn("Chat-Lang: Russian", r_step1.stdout)
        self.assertIn("Role:      execute", r_step1.stdout)
        self.assertIn("Task:      F14", r_step1.stdout)
        self.assertIn("ran_s1_step1", r_step1.stdout)

        r_start = self._run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input=bundle_input,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        self.assertIn("╭─ START SESSION ", r_start.stdout)
        self.assertIn("Session:    s2", r_start.stdout)

        # Re-running --start on an existing session without --force fails immediately
        r_start_dup = self._run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input=bundle_input,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertNotEqual(r_start_dup.returncode, 0)
        self.assertIn("already exists (use --force to overwrite)", r_start_dup.stderr)

        r_show0 = self._run(
            [str(SCRIPT), "--show", "s2/0"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_show0.returncode, 0)
        self.assertIn("Bundle:", r_show0.stdout)

        # Running s1/2 from a completely unrelated directory when RUN_BLOCK_CWD=auto
        # must still execute in the session's Workdir recorded in s1/0.
        other_dir = self.tmp / "other_unrelated_dir"
        other_dir.mkdir()
        env_auto = {**os.environ, "RUN_BLOCK_DIR": str(self.tmp / "sessions")}
        env_auto.pop("RUN_BLOCK_CWD", None)
        r_cross = self._run(
            [str(SCRIPT), "-y", "s1/2"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(other_dir),
            env=env_auto,
            check=False,
        )
        self.assertEqual(r_cross.returncode, 0, r_cross.stderr)
        self.assertIn(str(proj.resolve()), r_cross.stdout)

        # Implicit session creation via s3/1 (without prior --start) must also create s3/0
        r_imp1 = self._run(
            [str(SCRIPT), "-y", "s3/1"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_auto,
            check=False,
        )
        self.assertEqual(r_imp1.returncode, 0, r_imp1.stderr)
        s3_bundle = self.tmp / "sessions/s3/0"
        self.assertTrue(s3_bundle.is_file())
        hdrs = self.mod.parse_bundle_headers(s3_bundle.parent)
        self.assertEqual(hdrs.get("session"), "s3")
        self.assertEqual(hdrs.get("next-block"), "s3/1")
        self.assertEqual(Path(hdrs["workdir"]).resolve(), proj.resolve())
        self.assertRegex(hdrs.get("date", ""), r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")

        # Subsequent step s3/2 run from other_dir also uses s3/0 Workdir
        r_imp2 = self._run(
            [str(SCRIPT), "-y", "s3/2"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(other_dir),
            env=env_auto,
            check=False,
        )
        self.assertEqual(r_imp2.returncode, 0, r_imp2.stderr)
        self.assertIn(str(proj.resolve()), r_imp2.stdout)

    def test_f28_stdin_preamble_metadata_and_legacy_fallback(self):
        self.assertNotIn("bundle-command", self.mod.HIDDEN_SESSION_HEADER_KEYS)
        self.assertNotIn("chat-lang", self.mod.HIDDEN_SESSION_HEADER_KEYS)

        hdrs, body = self.mod.parse_stdin_preamble(
            "Role: plan\nTask: F28\n\n===== Prompt =====\nDo work\n"
        )
        self.assertEqual(hdrs, [("Role", "plan"), ("Task", "F28")])
        self.assertEqual(body, "===== Prompt =====\nDo work")

        hdrs_only, body_only = self.mod.parse_stdin_preamble("Role: execute\n")
        self.assertEqual(hdrs_only, [("Role", "execute")])
        self.assertEqual(body_only, "")

        no_hdrs, plain_body = self.mod.parse_stdin_preamble("Plain text\n\nMore text\n")
        self.assertEqual(no_hdrs, [])
        self.assertEqual(plain_body, "Plain text\n\nMore text")

        bad_preamble, bad_body = self.mod.parse_stdin_preamble(
            "Summary: first\nnot a header line\n\nBody\n"
        )
        self.assertEqual(bad_preamble, [])
        self.assertEqual(bad_body, "Summary: first\nnot a header line\n\nBody")

        # Stdin Workdir/Sandbox headers in preamble must not override run_block's own 0 headers
        proj = self.tmp / "f28_proj"
        proj.mkdir()
        env = {**os.environ, "RUN_BLOCK_DIR": str(self.tmp / "f28_sessions"), "RUN_BLOCK_CWD": str(proj)}
        r = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input="Workdir: /nonexistent/evil\nSandbox: strict\nRole: execute\n\nBody text\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        s1_dir = self.tmp / "f28_sessions/s1"
        parsed = self.mod.parse_bundle_headers(s1_dir)
        self.assertEqual(Path(parsed["workdir"]).resolve(), proj.resolve())
        self.assertEqual(parsed["sandbox"], "off")
        self.assertEqual(parsed["role"], "execute")

        # Legacy session fallback: headers in <session>/0 without meta.json still display
        legacy_dir = self.tmp / "f28_sessions/s9"
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "0").write_text(
            f"Session: s9\nNext-Block: s9/1\nWorkdir: {proj}\nSandbox: off\n"
            "Date: 2026-11-16 09:00 UTC\nRole: audit\n\nLegacy body\n",
            encoding="utf-8",
        )
        legacy_lines = self.mod.format_session_header_lines(label="s9/1", sdir=legacy_dir)
        self.assertTrue(any("Role:" in ln and "audit" in ln for ln in legacy_lines))

    def test_f33_start_bundle_edit_prompt_and_editor_flow(self):
        bundle_file = self.tmp / "s1" / "0"
        bundle_file.parent.mkdir(parents=True, exist_ok=True)
        bundle_file.write_text("Session: s1\nNext-Block: s1/1\n\nOriginal prompt\n", encoding="utf-8")

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((84, 24))):
            sb_box, _, sb_off = self.mod.format_clipboard_box(
                "s1",
                bundle_file,
                title_kind="START SESSION",
                extra_lines=["Session: s1", "Next-Block: s1/1", f"Bundle: {bundle_file}"],
            )
            self.assertIn("-> Copy to clipboard? [Y/n/a(ppend)/i(nfo)]:", sb_box)
            self.assertNotIn("[Y/n/v(iew)]:", sb_box)
            self.assertEqual(sb_off, len("│ -> Copy to clipboard? [Y/n/a(ppend)/i(nfo)]:"))

            end_box, _, _ = self.mod.format_clipboard_box("s1/1", bundle_file, title_kind="END STEP")
            self.assertIn("-> Copy to clipboard? [Y/n/a(ppend)/i(nfo)]:", end_box)
            for kind in ("NOT RUN", "SYNTAX ERROR"):
                with self.subTest(title_kind=kind):
                    other_box, _, _ = self.mod.format_clipboard_box("s1/1", bundle_file, title_kind=kind)
                    self.assertIn("-> Copy to clipboard? [Y/n/a(ppend)/i(nfo)]:", other_box)
                    self.assertNotIn("[Y/n/v(iew)]:", other_box)

        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("i\n")), "info")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("I\n")), "info")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("d\n")), "info")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("\n")), "copy")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("esc\n")), "skip")

        edited_calls: list[Path] = []

        def fake_edit(p: Path, _r, _w) -> None:
            edited_calls.append(p)
            p.write_text("Session: s1\nNext-Block: s1/1\n\nEdited prompt\n", encoding="utf-8")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        tty_r = io.StringIO("i\ne\nq\n\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False),              unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"),              unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {bundle_file}")),              unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)),              unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_edit),              unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy,              unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy(
                "s1",
                bundle_file,
                title_kind="START SESSION",
                extra_lines=["Session: s1", "Next-Block: s1/1", f"Bundle: {bundle_file}"],
            )
        self.assertEqual(edited_calls, [bundle_file])
        mock_copy.assert_called_once_with(["pbcopy"], bundle_file)
        self.assertIn("Edited prompt", bundle_file.read_text(encoding="utf-8"))
        self.assertIn("-> Copy to clipboard? [Y/n/a(ppend)/i(nfo)]:", tty_w.getvalue())
        self.assertIn(f"✓ Copied {bundle_file} to clipboard.", tty_w.getvalue())

        tty_w_esc = _KeepOpenStringIO()
        tty_r_esc = io.StringIO("i\ne\nq\nesc\n")
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False),              unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"),              unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {bundle_file}")),              unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_esc, tty_r_esc)),              unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=fake_edit),              unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy_esc,              unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy(
                "s1",
                bundle_file,
                title_kind="START SESSION",
                extra_lines=["Session: s1", "Next-Block: s1/1", f"Bundle: {bundle_file}"],
            )
        mock_copy_esc.assert_not_called()
        self.assertIn("Skipped clipboard copy.", tty_w_esc.getvalue())

    def test_f45_stdin_workdir_header_preference(self):
        target = self.tmp / "piped_target"
        target.mkdir()
        other_cwd = self.tmp / "other_cwd"
        other_cwd.mkdir()
        saved_cwd_env = os.environ.pop("RUN_BLOCK_CWD", None)
        old_cwd = os.getcwd()
        try:
            os.chdir(other_cwd)
            # 1. Existing Workdir header in stdin preamble is preferred over auto-resolved cwd
            res = self.mod.format_start_bundle(
                "s1",
                stdin_body=f"Workdir: {target}\nRole: execute\n\nPrompt body\n",
            )
            self.assertIn(f"Workdir: {target.resolve()}\n", res["full"])
            self.assertIn(f"Workdir: {target.resolve()}", res["console_lines"])

            # 2. Hyphenated Work-Dir header also resolves when directory exists
            res_hy = self.mod.format_start_bundle(
                "s2",
                stdin_body=f"Work-Dir: {target}\n\nPrompt body\n",
            )
            self.assertIn(f"Workdir: {target.resolve()}\n", res_hy["full"])

            # 3. Nonexistent Workdir header is ignored and falls back to get_work_dir()
            res_bad = self.mod.format_start_bundle(
                "s3",
                stdin_body=f"Workdir: {self.tmp / 'missing_dir'}\n\nPrompt body\n",
            )
            self.assertIn(f"Workdir: {other_cwd.resolve()}\n", res_bad["full"])

            # 4. Explicit work_dir argument still overrides stdin Workdir header
            res_arg = self.mod.format_start_bundle(
                "s4",
                stdin_body=f"Workdir: {target}\n\nPrompt body\n",
                work_dir=other_cwd,
            )
            self.assertIn(f"Workdir: {other_cwd.resolve()}\n", res_arg["full"])

            # 5. Explicit RUN_BLOCK_CWD overrides stdin Workdir header
            os.environ["RUN_BLOCK_CWD"] = "cwd"
            res_env_cwd = self.mod.format_start_bundle(
                "s5",
                stdin_body=f"Workdir: {target}\n\nPrompt body\n",
            )
            self.assertIn(f"Workdir: {other_cwd.resolve()}\n", res_env_cwd["full"])
            os.environ.pop("RUN_BLOCK_CWD", None)
        finally:
            os.chdir(old_cwd)
            if saved_cwd_env is not None:
                os.environ["RUN_BLOCK_CWD"] = saved_cwd_env

        # 6. End-to-end CLI pipe records Workdir in <session>/0 and executes steps there
        sessions_dir = self.tmp / "f45_sessions"
        env_auto = {**os.environ, "RUN_BLOCK_DIR": str(sessions_dir)}
        env_auto.pop("RUN_BLOCK_CWD", None)
        r_start = self._run(
            [str(SCRIPT)],
            input=f"Workdir: {target}\nRole: execute\n\nPrompt body\n",
            capture_output=True,
            text=True,
            cwd=str(other_cwd),
            env=env_auto,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        unwrapped_start = re.sub(r"\n│\s+", "", r_start.stdout)
        self.assertIn(str(target.resolve()), unwrapped_start)
        bundle_txt = (sessions_dir / "s1" / "0").read_text(encoding="utf-8")
        self.assertIn(f"Workdir: {target.resolve()}\n", bundle_txt)
        r_step = self._run(
            [str(SCRIPT), "-y", "s1/1"],
            input="pwd\n",
            capture_output=True,
            text=True,
            cwd=str(other_cwd),
            env=env_auto,
            check=False,
        )
        self.assertEqual(r_step.returncode, 0, r_step.stderr)
        self.assertIn(str(target.resolve()), r_step.stdout)

    def test_f50_start_bundle_edit_recalculates_stats_and_redraws_box(self):
        sdir = self.tmp / "s1"
        sdir.mkdir(parents=True, exist_ok=True)
        bundle_file = sdir / "0"
        initial_text = (
            "Session: s1\n"
            "Next-Block: s1/1\n"
            f"Workdir: {self.tmp}\n"
            "Sandbox: off\n"
            "Date: 2026-11-17 13:00 UTC\n\n"
            "Short prompt\n"
        )
        bundle_file.write_text(initial_text, encoding="utf-8")
        initial_stats = self.mod.stats_line(bundle_file)
        assert initial_stats is not None

        edited_text = initial_text + ("extra line of context for token growth\n" * 18)

        def stub_editor(p: Path, _r, _w) -> None:
            p.write_text(edited_text, encoding="utf-8")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        tty_r = io.StringIO("i\ne\nq\n\n")
        refresh_calls: list[Path] = []
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {bundle_file}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_editor), \
             unittest.mock.patch.object(self.mod, "refresh_bundle_meta", side_effect=lambda p: refresh_calls.append(p)), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy, \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((84, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy(
                "s1/0",
                bundle_file,
                title_kind="START SESSION",
                extra_lines=[f"Bundle: {bundle_file}"],
            )

        updated_stats = self.mod.stats_line(bundle_file)
        assert updated_stats is not None
        self.assertNotEqual(initial_stats, updated_stats)
        self.assertEqual(refresh_calls, [bundle_file])
        mock_copy.assert_called_once_with(["pbcopy"], bundle_file)

        tty_out = tty_w.getvalue()
        self.assertIn(f"Stats:  {initial_stats}", tty_out)
        self.assertIn(f"Stats:  {updated_stats}", tty_out)
        self.assertEqual(tty_out.count("╭─ START SESSION "), 2)

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((84, 24))):
            initial_box, _, _ = self.mod.format_clipboard_box(
                "s1/0",
                bundle_file,
                stats=initial_stats,
                title_kind="START SESSION",
                extra_lines=[f"Bundle: {bundle_file}"],
            )
        expected_up = self.mod._box_rows_above_prompt(initial_box, 84)
        self.assertIn(f"\r\033[{expected_up}A\033[J╭─ START SESSION ", tty_out)
        self.assertIn("╭─ START SESSION " + "─" * 31, tty_out)
        self.assertIn("╰" + "─" * 47, tty_out)

        # Terminal resize during i(nfo) -> e(dit) recalculates border width and final bottom rule
        tty_w_resize = _KeepOpenStringIO()
        tty_r_resize = io.StringIO("i\ne\nq\nesc\n")
        sizes = [
            os.terminal_size((44, 24)),
            os.terminal_size((44, 24)),
            os.terminal_size((76, 24)),
            os.terminal_size((76, 24)),
        ]
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {bundle_file}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w_resize, tty_r_resize)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=lambda p, _r, _w: p.write_text(initial_text, encoding="utf-8")), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True), \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", side_effect=sizes), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy(
                "s1/0",
                bundle_file,
                title_kind="START SESSION",
                extra_lines=[f"Bundle: {bundle_file}"],
            )
        resize_out = tty_w_resize.getvalue()
        self.assertIn("╭─ START SESSION " + "─" * 27, resize_out)
        self.assertIn("╭─ START SESSION " + "─" * 31, resize_out)
        self.assertTrue(resize_out.endswith("\r\033[K│ Skipped clipboard copy.\n\r\033[K" + ("╰" + "─" * 47) + "\n"))

        # Unchanged <session>/0 does not trigger refresh_bundle_meta; hook in refresh_bundle_meta runs when changed
        hook_calls: list[tuple[Path, Path]] = []
        with unittest.mock.patch.dict(self.mod.refresh_bundle_meta.__globals__, {"refresh_bundle_plan_meta": lambda s, b: hook_calls.append((s, b))}):
            self.mod.refresh_bundle_meta(bundle_file)
        self.assertEqual(hook_calls, [(sdir, bundle_file)])

    def test_f46_bundle_input_protocol_headers_and_fragment_parser(self):
        # 1. Header filtering: Bundle-* never forwarded to <session>/0; Bundle-Expose / Bundle-Hide
        #    control forwarding without overriding Session, Next-Block, Workdir, Sandbox, or Date.
        proj = self.tmp / "f46_proj"
        proj.mkdir()
        sessions = self.tmp / "f46_sessions"
        env = {**os.environ, "RUN_BLOCK_DIR": str(sessions), "RUN_BLOCK_CWD": str(proj)}
        nonce = "deadbeef1234"
        cmd_prefix = chr(36)

        bundle_payload = (
            "Bundle-Command: agents_bundle role=execute task=F46\n"
            f"Bundle-Boundary: {nonce}\n"
            "Bundle-Expose: Chat-Lang, Role, Task, Bundle-Command, Workdir, Sandbox, Session, Next-Block, Date, Secret-Tag\n"
            "Bundle-Hide: Secret-Tag\n"
            "Session: fake_session\n"
            "Next-Block: fake_session/99\n"
            "Workdir: /nonexistent/hijack\n"
            "Sandbox: strict\n"
            "Date: 1999-01-01 00:00 UTC\n"
            "Chat-Lang: Russian\n"
            "Role: execute\n"
            "Task: F46\n"
            "Secret-Tag: hidden-value\n"
            "Unlisted-Header: meta-only\n\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"vitalio/run_block:blocks/bash\", \"group\": \"vitalio/run_block\", \"via\": \"vitalio/run_block\"}} -->\n"
            "## Terminal blocks\n"
            "Rule body line 2\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"cmd\", \"name\": \"git status -sb\", \"group\": \".agents_bundle\", \"via\": \".agents_bundle\", \"rc\": 0, \"ms\": 7}} -->\n"
            f"===== {cmd_prefix} git status -sb =====\n"
            "## main...origin/main\n"
            f"<!-- bundle:{nonce}:end -->\n\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"include\", \"name\": \"AGENTS.md\", \"group\": \"local\", \"via\": \".agents_bundle\"}} -->\n"
            f"===== {cmd_prefix} cat AGENTS.md =====\n"
            "# Rules\n"
            "<!-- bundle:other_nonce:part {\"kind\": \"literal\"} -->\n"
            f"<!-- bundle:{nonce}:end -->\n\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"prompt\", \"group\": \"cli\", \"via\": \"cli\"}} -->\n"
            "===== Prompt =====\n"
            "Implement F46\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )

        r_start = self._run(
            [str(SCRIPT)],
            input=bundle_payload,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)

        b0 = (sessions / "s1" / "0").read_text(encoding="utf-8")
        # Core 5 headers cannot be overridden by stdin preamble
        self.assertIn("Session: s1\n", b0)
        self.assertIn("Next-Block: s1/1\n", b0)
        self.assertIn(f"Workdir: {proj.resolve()}\n", b0)
        self.assertIn("Sandbox: off\n", b0)
        self.assertNotIn("fake_session", b0)
        self.assertNotIn("/nonexistent/hijack", b0)
        self.assertNotIn("1999-01-01", b0)
        # Bundle-* transport headers never appear in <session>/0
        self.assertNotIn("Bundle-Command:", b0)
        self.assertNotIn("Bundle-Boundary:", b0)
        self.assertNotIn("Bundle-Expose:", b0)
        self.assertNotIn("Bundle-Hide:", b0)
        # Exposed non-hidden headers appear in <session>/0; hidden/unlisted do not
        self.assertIn("Chat-Lang: Russian\n", b0)
        self.assertIn("Role: execute\n", b0)
        self.assertIn("Task: F46\n", b0)
        self.assertNotIn("Secret-Tag:", b0)
        self.assertNotIn("Unlisted-Header:", b0)
        # Matching boundary markers are stripped, non-matching inner comment preserved
        self.assertNotIn(f"bundle:{nonce}:", b0)
        self.assertIn("<!-- bundle:other_nonce:part", b0)
        self.assertIn("## Terminal blocks\nRule body line 2\n", b0)
        self.assertIn("Implement F46", b0)

        # meta.json keeps all headers and structured bundle_plan without raw text bodies
        meta = self.mod.read_session_meta(sessions / "s1")
        hdr_dict = dict(meta["headers"])
        self.assertEqual(hdr_dict.get("Bundle-Boundary"), nonce)
        self.assertEqual(hdr_dict.get("Secret-Tag"), "hidden-value")
        self.assertEqual(hdr_dict.get("Unlisted-Header"), "meta-only")

        plan = meta.get("bundle_plan")
        self.assertIsInstance(plan, dict)
        self.assertEqual(plan["protocol"], "boundary")
        self.assertEqual(plan["boundary"], nonce)
        self.assertEqual(plan["part_count"], 4)
        parts = plan["parts"]
        self.assertEqual([p["kind"] for p in parts], ["rule", "cmd", "include", "prompt"])
        self.assertEqual(parts[0]["id"], "vitalio/run_block:blocks/bash")
        self.assertEqual(parts[0]["name"], "vitalio/run_block:blocks/bash")
        self.assertEqual(parts[1]["rc"], 0)
        self.assertEqual(parts[1]["ms"], 7)
        self.assertEqual(parts[2]["name"], "AGENTS.md")
        for p in parts:
            self.assertNotIn("body", p)
            self.assertNotIn("text", p)
            self.assertGreater(p["lines"], 0)
            self.assertGreater(p["bytes"], 0)
            self.assertGreater(p["gpt"], 0)
            self.assertGreater(p["claude"], 0)
            self.assertGreater(p["share_pct"], 0.0)
        hdr_entry = plan.get("header") or {}
        self.assertGreater(hdr_entry.get("chars", 0), 0)
        self.assertAlmostEqual(sum(p["share_pct"] for p in parts) + hdr_entry["share_pct"], 100.0, delta=0.5)
        self.assertEqual(plan["chars"], sum(p["chars"] for p in parts) + hdr_entry["chars"])
        self.assertEqual(plan["bytes"], sum(p["bytes"] for p in parts) + hdr_entry["bytes"])
        self.assertEqual(plan["lines"], sum(p["lines"] for p in parts) + hdr_entry["lines"])
        self.assertEqual(plan["chars"], len(b0))

        # 2. Bundle-Expose: * with Bundle-Hide forwards all non-Bundle non-reserved headers except hidden
        exp_all = self.mod.filter_exposed_headers([
            ("Bundle-Expose", "*"),
            ("Bundle-Hide", "Internal-Id"),
            ("Bundle-Command", "cmd"),
            ("Workdir", "/tmp"),
            ("Role", "plan"),
            ("Internal-Id", "42"),
            ("Task", "F46"),
        ])
        self.assertEqual(exp_all, [("Role", "plan"), ("Task", "F46")])

        # 3. Fallback to ===== ... ===== section splitting when no Bundle-Boundary is present
        sec_body = (
            "===== Rules =====\n"
            "Rule A\n\n"
            f"===== {cmd_prefix} git status -sb =====\n"
            "## main\n\n"
            "===== File: README.md =====\n"
            "# Title\n\n"
            "===== Prompt =====\n"
            "Do work\n"
        )
        clean_sec, sec_plan = self.mod.parse_bundle_fragments(sec_body, boundary=None)
        self.assertEqual(clean_sec, sec_body.strip())
        self.assertEqual(sec_plan["protocol"], "sections")
        self.assertIsNone(sec_plan["boundary"])
        self.assertEqual(sec_plan["part_count"], 4)
        self.assertEqual(
            [(p["kind"], p.get("name")) for p in sec_plan["parts"]],
            [
                ("rules", "Rules"),
                ("cmd", "git status -sb"),
                ("file", "README.md"),
                ("prompt", "Prompt"),
            ],
        )

        # 4. Plain bundle without boundary and without headers injects Rules + Prompt into meta.json
        r_plain = self._run(
            [str(SCRIPT), "--start", "--session", "s2"],
            input="Plain prompt without headers or sections\n",
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_plain.returncode, 0, r_plain.stderr)
        meta2 = self.mod.read_session_meta(sessions / "s2")
        self.assertNotIn("headers", meta2)
        self.assertEqual(meta2["bundle_plan"]["protocol"], "sections")
        self.assertEqual(meta2["bundle_plan"]["part_count"], 2)
        self.assertEqual(
            [(part["kind"], part["name"]) for part in meta2["bundle_plan"]["parts"]],
            [("rules", "Rules"), ("prompt", "Prompt")],
        )

        # 5. Editing <session>/0 refreshes bundle_plan in meta.json via refresh_bundle_meta
        b0_path = sessions / "s1" / "0"
        b0_path.write_text(
            "Session: s1\nNext-Block: s1/1\nWorkdir: /tmp\nSandbox: off\nDate: 2026-11-18 08:00 UTC\n\n"
            "===== Prompt =====\nUpdated body line 1\nUpdated body line 2\n",
            encoding="utf-8",
        )
        self.mod.refresh_bundle_meta(b0_path)
        meta_after = self.mod.read_session_meta(sessions / "s1")
        self.assertEqual(meta_after["bundle_plan"]["protocol"], "sections")
        self.assertEqual(meta_after["bundle_plan"]["part_count"], 1)
        self.assertEqual(dict(meta_after["headers"]).get("Bundle-Boundary"), nonce)

    def test_f68_top_style_table_kinds_groups_heavy_and_header(self) -> None:
        def _part(idx, kind, name, chain, chars, share):
            return {
                "index": idx, "kind": kind, "name": name, "chain": chain, "lines": 1,
                "chars": chars, "bytes": chars, "gpt": chars // 4, "claude": chars // 3,
                "share_pct": share,
            }

        plan = {
            "protocol": "boundary", "part_count": 3, "lines": 3, "chars": 1000,
            "bytes": 1000, "gpt": 250, "claude": 330,
            "parts": [
                _part(1, "rule", "g:solo", ["g"], 300, 30.0),
                _part(2, "rule", "root:r", [], 100, 10.0),
                _part(3, "prompt", "Prompt", [], 50, 5.0),
            ],
            "warnings": [],
        }
        lines = self.mod.format_bundle_summary_lines(plan, max_width=100)
        text = "\n".join(lines)
        self.assertRegex(lines[0], r"^\s+% +CHARS +LINES +~TOK +KIND +SOURCE$")
        self.assertIn(".agents_bundle", lines[1])
        self.assertNotRegex(text, r"\d+L\b|\d+ ch\b| tok\b|[├└]─ \d+\.")
        self.assertIn("[bundle]  g:solo", text)
        self.assertIn("[rule]    root:r", text)
        self.assertLess(text.index("external (not from .agents_bundle)"), text.index("[prompt]"))
        levels = {}
        for ln in lines:
            for name in ("g:solo", "root:r", "Prompt"):
                if ln.endswith(name):
                    levels[name] = self.mod.bundle_row_heavy_level(ln)
        self.assertEqual(levels, {"g:solo": "warn", "root:r": "accent", "Prompt": ""})

        full = "Session: s1\nRole: work\n\nalpha\nbeta\n"
        rec = self.mod.reconcile_bundle_plan(
            {
                "protocol": "boundary",
                "parts": [
                    {"index": 1, "kind": "prompt", "name": "Prompt", "lines": 10,
                     "chars": 500, "bytes": 500, "gpt": 100, "claude": 100},
                ],
            },
            full,
        )
        hdr = rec.get("header")
        self.assertIsInstance(hdr, dict)
        self.assertEqual(hdr["name"], "Headers & spacing")
        self.assertGreater(hdr["chars"], 0)

    def test_f47_bundle_diagnostics_details_view_and_cli(self):
        proj = self.tmp / "f47_proj"
        proj.mkdir()
        sessions = self.tmp / "f47_sessions"
        env = {**os.environ, "RUN_BLOCK_DIR": str(sessions), "RUN_BLOCK_CWD": str(proj)}
        nonce = "f47nonce99"
        cmd_prefix = chr(36)

        # 1. Warnings: non-zero rc, empty cmd output (raw and header-only), oversized fragment/total,
        #    and secret detection in non-rule parts while ignoring rule parts and never leaking secret literals.
        secret_tok = "ghp_" + ("A1b2C3d4E5" * 3)
        env_secret = "SECRET_" + "TOKEN_VALUE_12345"
        big_text = "word " * 400
        bundle_warn = (
            "Bundle-Command: agents_bundle role=execute task=F47\n"
            f"Bundle-Boundary: {nonce}\n"
            "Bundle-Expose: Role, Task\n"
            "Role: execute\n"
            "Task: F47\n\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"r:bash\", \"group\": \"vitalio/run_block\"}} -->\n"
            f"Rule mentions {secret_tok} and OPENAI_API_KEY={env_secret} and ~/.ssh/id_rsa\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"r:pwsh\", \"group\": \"vitalio/run_block\"}} -->\n"
            "PowerShell rule body\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"cmd\", \"name\": \"git diff\", \"group\": \".agents_bundle\", \"rc\": 0, \"ms\": 5}} -->\n"
            f"===== {cmd_prefix} git diff =====\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"cmd\", \"name\": \"failing_cmd\", \"group\": \".agents_bundle\", \"rc\": 2, \"ms\": 9}} -->\n"
            "error output\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"file\", \"name\": \".env.bak\", \"group\": \"files\"}} -->\n"
            f"OPENAI_API_KEY={env_secret}\n"
            f"{big_text}\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )

        env_thresh = {
            **env,
            "RUN_BLOCK_FRAGMENT_MAX_TOKENS": "100",
            "RUN_BLOCK_BUNDLE_MAX_TOKENS": "150",
        }
        r_start = self._run(
            [str(SCRIPT)],
            input=bundle_warn,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_thresh,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        # Inline BUNDLE stays compact (headers, Bundle:, Stats:, warnings) without Summary table or leaking secret value
        self.assertIn("(6 parts)\n│\n│ Bundle warnings (6):", r_start.stdout)
        self.assertNotIn("│ Summary:", r_start.stdout)
        self.assertIn("Bundle warnings (6):", r_start.stdout)
        self.assertIn("[cmd_empty]", r_start.stdout)
        self.assertIn("[cmd_rc]", r_start.stdout)
        self.assertIn("[fragment_oversized]", r_start.stdout)
        self.assertIn("[secret_detected]", r_start.stdout)
        self.assertIn("[token_budget]", r_start.stdout)
        self.assertNotIn(env_secret, r_start.stdout)

        meta = self.mod.read_session_meta(sessions / "s1")
        plan_meta = meta.get("bundle_plan")
        self.assertIsInstance(plan_meta, dict)
        warn_codes = [w["code"] for w in plan_meta.get("warnings", [])]
        self.assertEqual(
            warn_codes,
            ["fragment_oversized", "cmd_empty", "cmd_rc", "fragment_oversized", "secret_detected", "token_budget"],
        )
        self.assertNotIn(env_secret, (sessions / "s1" / "meta.json").read_text(encoding="utf-8"))
        # Rule fragments (parts 1 and 2) must not trigger secret_detected
        self.assertTrue(all(w.get("part_index") not in (1, 2) for w in plan_meta["warnings"] if w["code"] == "secret_detected"))

        # 2. Interactive START SESSION i(nfo) toggle (with d(etails) alias) in offer_clipboard_copy
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("d\n")), "info")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("D\n")), "info")
        self.assertEqual(self.mod.read_clipboard_key(io.StringIO("i\n")), "info")
        b0_path = sessions / "s1" / "0"

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        tty_r = io.StringIO("d\nd\nesc\n")
        old_dir = self.mod.BASE_DIR
        self.mod.BASE_DIR = sessions
        saved_frag = os.environ.get("RUN_BLOCK_FRAGMENT_MAX_TOKENS")
        saved_bud = os.environ.get("RUN_BLOCK_BUNDLE_MAX_TOKENS")
        os.environ["RUN_BLOCK_FRAGMENT_MAX_TOKENS"] = "100"
        os.environ["RUN_BLOCK_BUNDLE_MAX_TOKENS"] = "150"
        try:
            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
                 unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
                 unittest.mock.patch.object(self.mod, "clipboard_command", return_value=(["pbcopy"], f"pbcopy < {b0_path}")), \
                 unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)), \
                 unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 36))), \
                 unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
                self.mod.offer_clipboard_copy(
                    "s1/0",
                    b0_path,
                    title_kind="START SESSION",
                    extra_lines=[f"Bundle: {b0_path}"],
                )
        finally:
            self.mod.BASE_DIR = old_dir
            if saved_frag is None:
                os.environ.pop("RUN_BLOCK_FRAGMENT_MAX_TOKENS", None)
            else:
                os.environ["RUN_BLOCK_FRAGMENT_MAX_TOKENS"] = saved_frag
            if saved_bud is None:
                os.environ.pop("RUN_BLOCK_BUNDLE_MAX_TOKENS", None)
            else:
                os.environ["RUN_BLOCK_BUNDLE_MAX_TOKENS"] = saved_bud

        tty_out = tty_w.getvalue()
        self.assertEqual(tty_out.count("╭─ START SESSION "), 1)
        self.assertNotIn("│ Summary:", tty_out)
        self.assertIn("\033[?1049h", tty_out)
        self.assertIn("\033[?1049l", tty_out)
        self.assertIn("╭─ INFO · s1/0 ", tty_out)
        self.assertNotIn("│ Summary (", tty_out)
        self.assertEqual(tty_out.count("│ Parts (6 parts):"), 1)
        self.assertIn("[rule]    ├─ r:bash", tty_out)
        self.assertIn("% CHARS LINES", tty_out)
        self.assertIn("[header]  Headers & spacing", tty_out)
        self.assertIn("[cmd]     └─ failing_cmd", tty_out)
        self.assertIn("rc=2", tty_out)
        self.assertIn("Skipped clipboard copy.", tty_out)

        # 3. run_block --bundle-plan CLI: session mode, --full, --json, stdin mode, legacy 0 fallback, and errors
        import json
        r_bp_sess = self._run(
            [str(SCRIPT), "--bundle-plan", "s1"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_thresh,
            check=False,
        )
        self.assertEqual(r_bp_sess.returncode, 0, r_bp_sess.stderr)
        self.assertIn("Bundle Plan (s1, protocol: boundary):", r_bp_sess.stdout)
        self.assertIn("Summary (6 parts):", r_bp_sess.stdout)
        self.assertIn("Warnings (6):", r_bp_sess.stdout)
        self.assertNotIn("Parts (6):", r_bp_sess.stdout)

        r_bp_full = self._run(
            [str(SCRIPT), "--bundle-plan", "--full", "s1"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_thresh,
            check=False,
        )
        self.assertEqual(r_bp_full.returncode, 0, r_bp_full.stderr)
        self.assertIn("Parts (6):", r_bp_full.stdout)
        self.assertIn("failing_cmd", r_bp_full.stdout)
        self.assertIn("rc=2", r_bp_full.stdout)

        r_bp_json = self._run(
            [str(SCRIPT), "--bundle-plan", "s1", "--json"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_thresh,
            check=False,
        )
        self.assertEqual(r_bp_json.returncode, 0, r_bp_json.stderr)
        j_sess = json.loads(r_bp_json.stdout)
        self.assertEqual(j_sess["session"], "s1")
        self.assertEqual(j_sess["part_count"], 6)
        self.assertEqual(len(j_sess["warnings"]), 6)

        r_bp_stdin = self._run(
            [str(SCRIPT), "--bundle-plan", "--json", "--full"],
            input=bundle_warn,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env_thresh,
            check=False,
        )
        self.assertEqual(r_bp_stdin.returncode, 0, r_bp_stdin.stderr)
        j_stdin = json.loads(r_bp_stdin.stdout)
        self.assertEqual(j_stdin["protocol"], "boundary")
        self.assertEqual(len(j_stdin["warnings"]), 5)

        # Fallback to <session>/0 when meta.json lacks bundle_plan
        legacy_s = sessions / "s_legacy"
        legacy_s.mkdir(parents=True)
        (legacy_s / "0").write_text(
            f"Session: s_legacy\nNext-Block: s_legacy/1\nWorkdir: {proj}\nSandbox: off\nDate: 2026-11-18 08:00 UTC\n\n"
            f"===== {cmd_prefix} git status -sb =====\n===== Prompt =====\nDo task\n",
            encoding="utf-8",
        )
        r_bp_leg = self._run(
            [str(SCRIPT), "--bundle-plan", "s_legacy", "--full"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_bp_leg.returncode, 0, r_bp_leg.stderr)
        self.assertIn("protocol: sections", r_bp_leg.stdout)
        self.assertIn("[cmd_empty]", r_bp_leg.stdout)

        # Missing session fails explicitly
        r_bp_missing = self._run(
            [str(SCRIPT), "--bundle-plan", "no_such_sess"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertNotEqual(r_bp_missing.returncode, 0)

        # 4. Help & documentation sync
        r_help = self._run([str(SCRIPT), "-h"], capture_output=True, text=True, check=False)
        self.assertEqual(r_help.returncode, 0, r_help.stderr)
        self.assertIn("--bundle-plan", r_help.stdout)
        self.assertIn("--bundle-plan", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("--bundle-plan", (ROOT / "src/rules/blocks/bash.md").read_text(encoding="utf-8"))
        self.assertIn("--bundle-plan", (ROOT / "src/rules/blocks/pwsh.md").read_text(encoding="utf-8"))

    def test_f55_hide_bundle_transport_headers_and_clamp_long_title(self):
        proj = self.tmp / "f55_proj"
        proj.mkdir()
        sessions = self.tmp / "f55_sessions"
        env = {**os.environ, "RUN_BLOCK_DIR": str(sessions), "RUN_BLOCK_CWD": str(proj)}
        long_title = (
            "Hide Bundle-* transport headers from TUI boxes and clamp overly long "
            "Title headers cleanly with an ellipsis instead of wrapping onto multiple lines"
        )
        bundle_payload = (
            "Bundle-Command: agents_bundle role=execute task=F55\n"
            "Bundle-Boundary: deadbeef55\n"
            "Bundle-Expose: Role, Task, Title\n"
            "Bundle-Hide: Internal-Flag\n"
            "Bundle-Custom: extra-transport\n"
            "Role: execute\n"
            "Task: F55\n"
            f"Title: {long_title}\n\n"
            "===== Prompt =====\n"
            "Implement F55\n"
        )

        # 1. BUNDLE excludes all Bundle-* headers and clamps long Title to a single line
        r_start = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input=bundle_payload,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        for hidden_hdr in (
            "Bundle-Command:",
            "Bundle-Boundary:",
            "Bundle-Expose:",
            "Bundle-Hide:",
            "Bundle-Custom:",
        ):
            with self.subTest(start_hidden=hidden_hdr):
                self.assertNotIn(hidden_hdr, r_start.stdout)
        self.assertIn("Role:       execute", r_start.stdout)
        self.assertIn("Task:       F55", r_start.stdout)
        title_lines = [ln for ln in r_start.stdout.splitlines() if "Title:" in ln]
        self.assertEqual(len(title_lines), 1)
        self.assertTrue(title_lines[0].endswith("…"))
        self.assertLessEqual(self.mod.display_width(title_lines[0]), 80)

        # meta.json and parse_bundle_header_items preserve Bundle-* headers for --info / i(nfo)
        s1_dir = sessions / "s1"
        meta = self.mod.read_session_meta(s1_dir)
        meta_hdrs = dict(meta["headers"])
        self.assertEqual(meta_hdrs.get("Bundle-Command"), "agents_bundle role=execute task=F55")
        self.assertEqual(meta_hdrs.get("Bundle-Boundary"), "deadbeef55")
        self.assertEqual(meta_hdrs.get("Bundle-Expose"), "Role, Task, Title")
        self.assertEqual(meta_hdrs.get("Bundle-Hide"), "Internal-Flag")
        self.assertEqual(meta_hdrs.get("Bundle-Custom"), "extra-transport")
        self.assertEqual(self.mod.parse_bundle_headers(s1_dir).get("bundle-command"), "agents_bundle role=execute task=F55")
        self.assertNotIn("bundle-command", {k.lower() for k, _ in self.mod.parse_bundle_header_items(s1_dir, include_transport=False)})

        # 2. PLAN, END, NOT RUN, SYNTAX ERROR, and confirmation header lines exclude Bundle-* and clamp Title
        old_base = self.mod.BASE_DIR
        self.mod.BASE_DIR = sessions
        try:
            with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((72, 24))):
                plan_box, _, _ = self.mod.format_safety_box(
                    "s1/1", [], default_yes=True, summary={"work_dir": str(proj.resolve()), "meta": "1 line, bash"}
                )
                end_box, _, _ = self.mod.format_clipboard_box("s1/1", s1_dir / "1" / "out", ok=True, rc=0)
                hdr_confirm = self.mod.format_session_header_lines(label="s1/1", sdir=s1_dir, work_dir=proj)

            for box_name, rendered in (("PLAN", plan_box), ("END", end_box), ("CONFIRM", "\n".join(hdr_confirm))):
                with self.subTest(box=box_name):
                    for hidden_hdr in ("Bundle-Command:", "Bundle-Boundary:", "Bundle-Expose:", "Bundle-Hide:", "Bundle-Custom:"):
                        self.assertNotIn(hidden_hdr, rendered)
                    t_lines = [ln for ln in rendered.splitlines() if "Title:" in ln]
                    self.assertEqual(len(t_lines), 1)
                    self.assertTrue(t_lines[0].endswith("…"))
                    max_row = 70 if box_name == "CONFIRM" else 72
                    self.assertLessEqual(self.mod.display_width(t_lines[0]), max_row)

            # NOT RUN & SYNTAX ERROR via runner
            buf_nr = io.StringIO()
            with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))),                  contextlib.redirect_stdout(buf_nr):
                self.assertEqual(self.mod.cmd_normal("s1/2", "echo skip\n"), 2)
            self.assertIn("╭─ NOT RUN ", buf_nr.getvalue())
            self.assertNotIn("Bundle-Command:", buf_nr.getvalue())
            self.assertEqual(len([ln for ln in buf_nr.getvalue().splitlines() if "Title:" in ln]), 1)

            buf_syn = io.StringIO()
            with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((76, 24))),                  contextlib.redirect_stdout(buf_syn):
                self.assertNotEqual(self.mod.cmd_normal("s1/1", "if true; then\n"), 0)
            self.assertIn("╭─ SYNTAX ERROR ", buf_syn.getvalue())
            self.assertNotIn("Bundle-Command:", buf_syn.getvalue())
            self.assertEqual(len([ln for ln in buf_syn.getvalue().splitlines() if "Title:" in ln]), 1)
        finally:
            self.mod.BASE_DIR = old_base

        # 3. Short Title stays untruncated; wide Unicode Title respects display_width; ASCII uses '...'
        s2_dir = self.tmp / "s_short"
        s2_dir.mkdir()
        (s2_dir / "0").write_text(
            f"Session: s_short\nNext-Block: s_short/1\nWorkdir: {proj}\nSandbox: off\n"
            "Date: 2026-11-18 08:00 UTC\nTitle: Short task\n",
            encoding="utf-8",
        )
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((80, 24))):
            short_lines = self.mod.format_session_header_lines(label="s_short/1", sdir=s2_dir, work_dir=proj)
        self.assertIn("Title:   Short task", short_lines)

        s3_dir = self.tmp / "s_wide"
        s3_dir.mkdir()
        (s3_dir / "0").write_text(
            f"Session: s_wide\nNext-Block: s_wide/1\nWorkdir: {proj}\nSandbox: off\n"
            "Date: 2026-11-18 08:00 UTC\nTitle: " + ("界" * 40) + "\n",
            encoding="utf-8",
        )
        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((60, 24))):
            wide_lines = self.mod.format_session_header_lines(label="s_wide/1", sdir=s3_dir, work_dir=proj, max_width=58)
        wide_title = [ln for ln in wide_lines if "Title:" in ln]
        self.assertEqual(len(wide_title), 1)
        self.assertTrue(wide_title[0].endswith("…"))
        self.assertLessEqual(self.mod.display_width(wide_title[0]), 58)

        with io.TextIOWrapper(io.BytesIO(), encoding="ascii") as ascii_stream:
            with unittest.mock.patch.object(self.mod.sys, "stdout", ascii_stream),                  unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((60, 24))):
                ascii_lines = self.mod.format_session_header_lines(label="s1/1", sdir=s1_dir, work_dir=proj, max_width=58)
        ascii_title = [ln for ln in ascii_lines if "Title:" in ln]
        self.assertEqual(len(ascii_title), 1)
        self.assertTrue(ascii_title[0].endswith("..."))
        self.assertLessEqual(self.mod.display_width(ascii_title[0]), 58)

    def test_f63_unified_chars_chain_hierarchy_tabular_and_preamble(self):
        # 1. count_tokens / format_stats / Script: / format_start_bundle use chars
        sample = "hello мир\n"
        tok = self.mod.count_tokens(sample.encode("utf-8"))
        self.assertEqual(tok["chars"], len(sample))
        self.assertEqual(tok["bytes"], len(sample.encode("utf-8")))
        self.assertIn("10 chars", self.mod.format_stats(sample.encode("utf-8")))
        plan_sum = self.mod.summarize_script_actions("echo hello_f63\n", Path("/tmp"))
        self.assertIn("15 chars", str(plan_sum["meta"]))

        # 2. Standalone ===== Rules ===== outside boundary markers does NOT create [text] Preamble,
        #    whereas real unframed preamble text DOES create [text] Preamble.
        nonce = "f63nonce"
        body_with_section_hdr = (
            "===== Rules =====\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"vitalio/run_block:blocks/bash\", \"chain\": [\"vitalio/run_block\"]}} -->\n"
            "Rule body\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        _, p_clean = self.mod.parse_bundle_fragments(body_with_section_hdr, boundary=nonce)
        self.assertEqual(p_clean["part_count"], 1)
        self.assertEqual([x["kind"] for x in p_clean["parts"]], ["rule"])

        body_with_real_preamble = (
            "===== Rules =====\n"
            "Actual unframed intro\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"prompt\", \"chain\": []}} -->\n"
            "Prompt text\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        _, p_pre = self.mod.parse_bundle_fragments(body_with_real_preamble, boundary=nonce)
        self.assertEqual(p_pre["part_count"], 2)
        self.assertEqual([x["kind"] for x in p_pre["parts"]], ["text", "prompt"])
        self.assertEqual(p_pre["parts"][0]["name"], "Preamble")

        # 3. Neutral chain hierarchy, prefix dedup, legacy fallback, and older meta.json bytes->chars fallback
        nested_body = (
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"vitalio/run_block:blocks/bash\", \"chain\": [\"vitalio/run_block\"]}} -->\n"
            + ("bash rule line\n" * 4)
            + f"<!-- bundle:{nonce}:end -->\n"
            + f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"bundleA:r1\", \"chain\": [\"bundleA\", \"rulesetB\"]}} -->\n"
            + "sub rule 1\n"
            + f"<!-- bundle:{nonce}:end -->\n"
            + f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"bundleA:r2\", \"chain\": [\"bundleA\", \"rulesetB\"]}} -->\n"
            + "sub rule 2\n"
            + f"<!-- bundle:{nonce}:end -->\n"
            + f"<!-- bundle:{nonce}:part {{\"kind\": \"cmd\", \"name\": \"git status -sb\", \"chain\": [], \"rc\": 0, \"ms\": 4}} -->\n"
            + "clean\n"
            + f"<!-- bundle:{nonce}:end -->\n"
            + f"<!-- bundle:{nonce}:part {{\"kind\": \"prompt\", \"name\": \"Prompt\", \"chain\": []}} -->\n"
            + ("very_long_unbroken_token_" * 4)
            + "\n"
            + f"<!-- bundle:{nonce}:end -->\n"
        )
        proj = self.tmp / "f63_proj"
        proj.mkdir()
        sessions = self.tmp / "f63_sessions"
        env = {**os.environ, "RUN_BLOCK_DIR": str(sessions), "RUN_BLOCK_CWD": str(proj)}
        bundle_in = (
            f"Bundle-Boundary: {nonce}\n"
            "Bundle-Expose: Role\n"
            "Role: execute\n\n"
            + nested_body
        )
        r_start = self._run(
            [str(SCRIPT), "--start", "--session", "s1"],
            input=bundle_in,
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_start.returncode, 0, r_start.stderr)
        out_s = r_start.stdout
        self.assertRegex(out_s, r"│ Stats: .*\(5 parts\)\n╰")
        self.assertNotIn("│ Summary:", out_s)

        plan1 = self.mod.load_session_bundle_plan(sessions / "s1")
        assert plan1 is not None
        self.assertFalse(any("vitalio/run_block: vitalio/run_block:" in s for _, s in self.mod.format_bundle_group_items(plan1)))
        self.assertFalse(any("vitalio/run_block: vitalio/run_block:" in s for _, s in self.mod.format_bundle_part_items(plan1)))
        sum1_text = "\n".join(self.mod.format_bundle_summary_lines(plan1, max_width=100))
        self.assertIn("[header]  Headers & spacing", sum1_text)
        self.assertNotIn("vitalio/run_block: vitalio/run_block:", sum1_text)
        self.assertIn("vitalio/run_block:blocks/bash", sum1_text)
        self.assertIn("[bundle]  bundleA (2)", sum1_text)
        self.assertIn("[bundle]  └─ rulesetB (2)", sum1_text)
        self.assertIn("[cmd]     git status -sb", sum1_text)
        self.assertIn("[prompt]  Prompt", sum1_text)

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
            det_box, _, _ = self.mod.format_clipboard_box(
                "s1/0", sessions / "s1" / "0", stats=self.mod.stats_line(sessions / "s1" / "0"), title_kind="START SESSION", bundle_details=True, sdir=sessions / "s1"
            )
        self.assertIn("(5 parts)\n│ Parts:", det_box)
        self.assertIn("├─ bundleA:r1", det_box)
        self.assertIn("└─ bundleA:r2", det_box)

        # Narrow terminal wraps ONLY the description column cleanly
        narrow_lines = self.mod.format_bundle_summary_lines(plan1, max_width=64)
        for ln in narrow_lines:
            self.assertLessEqual(self.mod.display_width(ln), 64, ln)
        self.assertTrue(any(ln.startswith("  " + " " * 30) for ln in narrow_lines))

        with unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))):
            ed_box, _, _ = self.mod.format_clipboard_box(
                "s1/0", sessions / "s1" / "0", stats=self.mod.stats_line(sessions / "s1" / "0"), title_kind="START SESSION", edited=True, sdir=sessions / "s1"
            )
            self.assertRegex(ed_box, r"│ Stats: .*\(5 parts\) \(edited\)\n│\n│ -> Copy to clipboard\?")
            no_tok_box, _, _ = self.mod.format_clipboard_box(
                "s1/0", sessions / "s1" / "0", stats=None, title_kind="START SESSION", edited=False, sdir=sessions / "s1"
            )
            self.assertNotIn("│ Stats:", no_tok_box)
            self.assertNotIn("│ Summary", no_tok_box)

        # Legacy meta.json without chars falls back to bytes; empty group expands at root
        legacy_plan = {
            "protocol": "boundary",
            "part_count": 2,
            "lines": 2,
            "bytes": 40,
            "gpt": 10,
            "claude": 12,
            "parts": [
                {"index": 1, "kind": "cmd", "name": "root_cmd", "group": "", "lines": 1, "bytes": 20, "gpt": 5, "claude": 6, "share_pct": 50.0},
                {"index": 2, "kind": "rule", "id": "g:item", "group": "g", "lines": 1, "bytes": 20, "gpt": 5, "claude": 6, "share_pct": 50.0},
            ],
            "warnings": [],
        }
        enriched = self.mod._enrich_bundle_plan(legacy_plan)
        self.assertEqual(enriched["chars"], 40)
        self.assertEqual(enriched["parts"][0]["chars"], 20)
        leg_sum = "\n".join(self.mod.format_bundle_summary_lines(enriched, max_width=100))
        self.assertIn("[cmd]     root_cmd", leg_sum)
        self.assertIn("[bundle]  g:item", leg_sum)

        r_bp = self._run(
            [str(SCRIPT), "--bundle-plan", "s1"],
            capture_output=True,
            text=True,
            cwd=str(proj),
            env=env,
            check=False,
        )
        self.assertEqual(r_bp.returncode, 0, r_bp.stderr)
        self.assertIn("chars ·", r_bp.stdout)
        self.assertNotIn(" B ·", r_bp.stdout)

    def test_f66_embedded_block_rules_injection_dedup_and_tty_bare_start(self):
        # 1. Built ./run_block embeds bash.md and pwsh.md without '# Description:' lines
        built_text = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn('EMBEDDED_RULE_BASH = "__EMBEDDED_RULE_BASH__"', built_text)
        self.assertNotIn('EMBEDDED_RULE_PWSH = "__EMBEDDED_RULE_PWSH__"', built_text)
        self.assertIn("## Terminal blocks (`{cmd:run_block}`)", self.mod.EMBEDDED_RULE_BASH)
        self.assertIn("## Terminal blocks (`{cmd:run_block}`)", self.mod.EMBEDDED_RULE_PWSH)
        self.assertFalse(self.mod.EMBEDDED_RULE_BASH.startswith("# Description:"))
        self.assertFalse(self.mod.EMBEDDED_RULE_PWSH.startswith("# Description:"))

        # 2. Shell selection (bash vs pwsh) and prog_name() substitution
        saved_shell = os.environ.get("RUN_BLOCK_SHELL")
        saved_argv0 = self.mod.sys.argv[0]
        try:
            self.mod.sys.argv[0] = "/usr/local/bin/rxb"
            os.environ["RUN_BLOCK_SHELL"] = "bash"
            rid_bash, rtxt_bash = self.mod.get_embedded_block_rule()
            self.assertEqual(rid_bash, "run_block:blocks/bash")
            self.assertIn("## Terminal blocks (`rxb`)", rtxt_bash)
            self.assertIn("rxb s1/1 <<'RUN_BLOCK'", rtxt_bash)
            self.assertNotIn("{cmd:run_block}", rtxt_bash)

            os.environ["RUN_BLOCK_SHELL"] = "pwsh"
            rid_pwsh, rtxt_pwsh = self.mod.get_embedded_block_rule()
            self.assertEqual(rid_pwsh, "run_block:blocks/pwsh")
            self.assertIn("## Terminal blocks (`rxb`)", rtxt_pwsh)
            self.assertIn("'@ | rxb s1/1", rtxt_pwsh)
            self.assertNotIn("{cmd:run_block}", rtxt_pwsh)
        finally:
            self.mod.sys.argv[0] = saved_argv0
            if saved_shell is None:
                os.environ.pop("RUN_BLOCK_SHELL", None)
            else:
                os.environ["RUN_BLOCK_SHELL"] = saved_shell

        proj = self.tmp / "f66_proj"
        proj.mkdir()
        nonce = "f66nonce"

        # 3. Bundle-Boundary: ignores decoy '===== Rules =====' inside a part, prepends top-level Rules before first part
        decoy_body = (
            f"<!-- bundle:{nonce}:part {{\"kind\": \"file\", \"name\": \"README.md\", \"chain\": [\"files\"]}} -->\n"
            "===== Rules =====\nDecoy section inside file\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"prompt\", \"chain\": []}} -->\n"
            "===== Prompt =====\nImplement F66\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_prepend = self.mod.format_start_bundle(
            "s1",
            stdin_body=f"Bundle-Boundary: {nonce}\n\n{decoy_body}",
            work_dir=proj,
        )
        full_prepend = str(res_prepend["full"])
        self.assertIn("\n\n===== Rules =====\n## Terminal blocks (`", full_prepend)
        self.assertLess(full_prepend.index("## Terminal blocks (`"), full_prepend.index("Decoy section inside file"))
        plan_prepend = res_prepend["bundle_plan"]
        assert isinstance(plan_prepend, dict)
        p0 = plan_prepend["parts"][0]
        self.assertEqual(p0["kind"], "rule")
        self.assertEqual(p0["id"], "run_block:blocks/bash")
        self.assertEqual(p0["chain"], ["run_block"])

        # 4. Bundle-Boundary: inserts into top-level '===== Rules =====' outside parts
        top_rules_body = (
            "===== Rules =====\n"
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"other:r1\", \"chain\": [\"other\"]}} -->\n"
            "Other project rule\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_top_rules = self.mod.format_start_bundle(
            "s2",
            stdin_body=f"Bundle-Boundary: {nonce}\n\n{top_rules_body}",
            work_dir=proj,
        )
        full_top_rules = str(res_top_rules["full"])
        self.assertEqual(full_top_rules.count("===== Rules ====="), 1)
        self.assertLess(full_top_rules.index("## Terminal blocks (`"), full_top_rules.index("Other project rule"))

        # 5. Fallback mode without Bundle-Boundary: leading Rules vs plain prompt wrapping
        res_fb_rules = self.mod.format_start_bundle(
            "s3",
            stdin_body="===== Rules =====\nCustom rule\n\n===== Prompt =====\nDo task\n",
            work_dir=proj,
        )
        full_fb_rules = str(res_fb_rules["full"])
        self.assertEqual(full_fb_rules.count("===== Rules ====="), 1)
        self.assertLess(full_fb_rules.index("## Terminal blocks (`"), full_fb_rules.index("Custom rule"))
        self.assertIn("===== Prompt =====\nDo task", full_fb_rules)

        res_fb_plain = self.mod.format_start_bundle(
            "s4",
            stdin_body="Unlabeled user request\n",
            work_dir=proj,
        )
        full_fb_plain = str(res_fb_plain["full"])
        self.assertIn("===== Rules =====\n## Terminal blocks (`", full_fb_plain)
        self.assertIn("\n\n===== Prompt =====\nUnlabeled user request\n", full_fb_plain)

        # 6. Deduplication against legacy vitalio/run_block parts and existing '## Terminal blocks (' headings
        legacy_part_body = (
            f"<!-- bundle:{nonce}:part {{\"kind\": \"rule\", \"id\": \"vitalio/run_block:blocks/bash\", \"chain\": [\"vitalio/run_block\"]}} -->\n"
            "Legacy rule without standard heading\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_dedup_part = self.mod.format_start_bundle(
            "s5",
            stdin_body=f"Bundle-Boundary: {nonce}\n\n{legacy_part_body}",
            work_dir=proj,
        )
        self.assertEqual(res_dedup_part["bundle_plan"]["part_count"], 1)
        self.assertEqual(
            [part["id"] for part in res_dedup_part["bundle_plan"]["parts"]],
            ["vitalio/run_block:blocks/bash"],
        )

        res_dedup_heading = self.mod.format_start_bundle(
            "s6",
            stdin_body="===== Rules =====\n## Terminal blocks (`run_block`)\nAlready present\n",
            work_dir=proj,
        )
        self.assertEqual(str(res_dedup_heading["full"]).count("## Terminal blocks ("), 1)

        # 7. Bare main() and --start in TTY stdin start a rule-only session; --sandbox stays on cmd_sandbox()
        sessions = self.tmp / "f66_tty_sessions"
        old_base = self.mod.BASE_DIR
        old_cwd_env = os.environ.get("RUN_BLOCK_CWD")
        self.mod.BASE_DIR = sessions
        os.environ["RUN_BLOCK_CWD"] = str(proj)
        try:
            class _FakeTtyIn(io.StringIO):
                def isatty(self) -> bool:
                    return True

            with unittest.mock.patch.object(self.mod.sys, "stdin", _FakeTtyIn()),                  unittest.mock.patch.object(self.mod, "no_clipboard", return_value=True):
                buf_bare = io.StringIO()
                with contextlib.redirect_stdout(buf_bare):
                    rc_bare = self.mod.main([])
                self.assertEqual(rc_bare, 0)
                self.assertIn("╭─ START SESSION ", buf_bare.getvalue())
                self.assertIn("(1 part)", buf_bare.getvalue())
                self.assertNotIn("│ Summary:", buf_bare.getvalue())
                b0_bare = (sessions / "s1" / "0").read_text(encoding="utf-8")
                self.assertIn("===== Rules =====\n## Terminal blocks (`", b0_bare)
                self.assertNotIn("===== Prompt =====", b0_bare)

                buf_start = io.StringIO()
                with contextlib.redirect_stdout(buf_start):
                    rc_start = self.mod.main(["--start", "--session", "s2", "--sandbox", "strict"])
                self.assertEqual(rc_start, 0)
                self.assertIn("╭─ START SESSION ", buf_start.getvalue())
                b0_start = (sessions / "s2" / "0").read_text(encoding="utf-8")
                self.assertIn("Sandbox: strict", b0_start)
                self.assertIn("===== Rules =====\n## Terminal blocks (`", b0_start)

                buf_sb = io.StringIO()
                with contextlib.redirect_stdout(buf_sb):
                    rc_sb = self.mod.main(["--sandbox", "nonet"])
                self.assertEqual(rc_sb, 0)
                self.assertIn("Updated s2/0 -> Sandbox: nonet", buf_sb.getvalue())
        finally:
            self.mod.BASE_DIR = old_base
            if old_cwd_env is None:
                os.environ.pop("RUN_BLOCK_CWD", None)
            else:
                os.environ["RUN_BLOCK_CWD"] = old_cwd_env

    def test_bundle_part_line_ranges_and_part_option(self):
        import json

        nonce = "abc"
        stdin_text = (
            f"Bundle-Boundary: {nonce}\n\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","name":"r1"}} -->\n'
            "## Rule one\nline a\n\n\nline b\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind":"prompt","name":"p1"}} -->\n'
            "Do the task\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        rule_txt = "## Rule one\nline a\n\nline b\n"
        task_txt = "Do the task\n"

        # 1. Body-relative ranges (stdin mode) with collapsed blank lines
        _, body = self.mod.parse_stdin_preamble(stdin_text)
        clean, plan = self.mod.parse_bundle_fragments(body, boundary=nonce)
        self.assertEqual(plan["line_offset"], 0)
        self.assertEqual(
            [(p["line_start"], p["line_end"]) for p in plan["parts"]],
            [(1, 4), (5, 5)],
        )
        got = {
            p["name"]: self.mod.extract_bundle_part(plan, clean, p["index"])[1]
            for p in plan["parts"]
        }
        self.assertEqual(got, {"r1": rule_txt, "p1": task_txt})
        for p in plan["parts"]:
            self.assertNotIn("text", p)
            self.assertNotIn("body", p)

        # 2. Absolute ranges inside the final <session>/0 (headers + injected rule)
        with tempfile.TemporaryDirectory() as td:
            res = self.mod.format_start_bundle(
                "s1", stdin_body=stdin_text, work_dir=Path(td), sandbox_mode="off"
            )
        full = str(res["full"])
        plan_full = res["bundle_plan"]
        self.assertGreater(plan_full["line_offset"], 0)
        by_name = {p.get("name"): p for p in plan_full["parts"]}
        self.assertEqual(
            self.mod.extract_bundle_part(plan_full, full, by_name["r1"]["index"])[1], rule_txt
        )
        self.assertEqual(
            self.mod.extract_bundle_part(plan_full, full, by_name["p1"]["index"])[1], task_txt
        )
        # Reconciling twice must not shift ranges again
        again = self.mod.reconcile_bundle_plan(plan_full, full)
        self.assertEqual(
            [(p.get("line_start"), p.get("line_end")) for p in again["parts"]],
            [(p.get("line_start"), p.get("line_end")) for p in plan_full["parts"]],
        )
        with self.assertRaises(ValueError):
            self.mod.extract_bundle_part(plan_full, full, 99)

        # 3. Section fallback ranges
        _, plan_fb = self.mod.parse_bundle_fragments("===== A =====\nx\n\n===== B =====\ny\n")
        self.assertEqual(
            [(p["line_start"], p["line_end"]) for p in plan_fb["parts"]],
            [(1, 2), (4, 5)],
        )

        # 4. CLI: --bundle-plan / --show with --part
        with tempfile.TemporaryDirectory() as td:
            env = dict(os.environ)
            env.update({"RUN_BLOCK_DIR": td, "RUN_BLOCK_CLIPBOARD": "never", "RUN_BLOCK_HEADLESS": "1"})
            env.pop("IN_RUN_BLOCK", None)

            def run(*args, stdin=None):
                return self._run(
                    [str(SCRIPT), *args],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    env=env,
                    check=False,
                )

            r_stdin = run("--bundle-plan", "--part", "2", stdin=stdin_text)
            self.assertEqual((r_stdin.returncode, r_stdin.stdout), (0, task_txt), r_stdin.stderr)
            self.assertIn("part 2/2", r_stdin.stderr)
            self.assertIn("(lines 5-5)", r_stdin.stderr)

            r_start = run("--start", "--session", "s1", stdin=stdin_text)
            self.assertEqual(r_start.returncode, 0, r_start.stderr)
            plan_json = json.loads(run("--bundle-plan", "s1", "--json").stdout)
            idx = {p.get("name"): p["index"] for p in plan_json["parts"]}
            for argv in (("--bundle-plan", "s1"), ("--show", "s1"), ("--show", "s1/0")):
                with self.subTest(argv=argv):
                    r = run(*argv, "--part", str(idx["p1"]))
                    self.assertEqual((r.returncode, r.stdout), (0, task_txt), r.stderr)
            r_latest = run("--show", "--part", str(idx["r1"]))
            self.assertEqual((r_latest.returncode, r_latest.stdout), (0, rule_txt), r_latest.stderr)

            for argv in (
                ("--bundle-plan", "s1", "--part", "99"),
                ("--bundle-plan", "s1", "--part", "0"),
                ("--show", "s1/1", "--part", "1"),
                ("--bundle-plan", "s1", "--part", "1", "--json"),
                ("--show", "s1", "--part", "x"),
            ):
                with self.subTest(argv=argv):
                    r = run(*argv)
                    self.assertNotEqual(r.returncode, 0)
                    self.assertEqual(r.stdout, "")

            # 5. Legacy sessions without recorded ranges fail cleanly
            meta_path = Path(td) / "s1" / "meta.json"
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            for p in meta["bundle_plan"]["parts"]:
                p.pop("line_start", None)
                p.pop("line_end", None)
            meta["bundle_plan"].pop("line_offset", None)
            meta_path.write_text(json.dumps(meta), encoding="utf-8")
            r_legacy = run("--show", "s1", "--part", str(idx["p1"]))
            self.assertNotEqual(r_legacy.returncode, 0)
            self.assertEqual(r_legacy.stdout, "")
            self.assertIn("no recorded line range", r_legacy.stderr)

            # 6. Help and docs mention --part
            r_help = run("--help")
            self.assertEqual(r_help.returncode, 0)
            self.assertIn("--part N", r_help.stdout)
        self.assertIn("--part N", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("--part N", (ROOT / "src/rules/blocks/bash.md").read_text(encoding="utf-8"))
        self.assertIn("--part N", (ROOT / "src/rules/blocks/pwsh.md").read_text(encoding="utf-8"))

    def test_info_part_viewer_and_part_prompt(self):
        nonce = "abc"
        stdin_text = (
            f"Bundle-Boundary: {nonce}\n\n"
            f'<!-- bundle:{nonce}:part {{"kind":"rule","name":"r1"}} -->\n'
            "## Rule one\nline a\n\n\nline b\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind":"prompt","name":"p1"}} -->\n'
            "Do the task\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )

        # Prompt parsing without a TTY (readline fallback)
        self.assertEqual(self.mod._read_part_number(io.StringIO("2\n"), io.StringIO(), 3), 2)
        for raw in ("x\n", "0\n", "4\n", "\n"):
            with self.subTest(raw=raw):
                self.assertIsNone(self.mod._read_part_number(io.StringIO(raw), io.StringIO(), 3))

        # Shared scroll helper
        self.assertEqual(self.mod._apply_pager_scroll("down", 3, 10), 4)
        self.assertEqual(self.mod._apply_pager_scroll("up", 0, 10), 0)
        self.assertEqual(self.mod._apply_pager_scroll("pgdn", 0, 10), 9)
        self.assertEqual(self.mod._apply_pager_scroll("top", 7, 10), 0)
        self.assertIsNone(self.mod._apply_pager_scroll("edit", 0, 10))

        with tempfile.TemporaryDirectory() as td:
            sdir = Path(td) / "s1"
            sdir.mkdir()
            res = self.mod.format_start_bundle(
                "s1", stdin_body=stdin_text, work_dir=Path(td), sandbox_mode="off"
            )
            bundle_path = sdir / "0"
            bundle_path.write_text(str(res["full"]), encoding="utf-8")
            self.mod.write_session_meta(sdir, list(res["stdin_headers"]), bundle_plan=res["bundle_plan"])
            idx = {p.get("name"): p["index"] for p in res["bundle_plan"]["parts"]}
            total = len(res["bundle_plan"]["parts"])

            frame0, _, _ = self.mod._build_info_screen(
                "START SESSION", "s1/0", 100, 30, 0,
                sdir=sdir, out_path=bundle_path, edit_target=bundle_path, allow_copy=True,
            )
            self.assertIn("p(art)", frame0)
            frame_step, _, _ = self.mod._build_info_screen(
                "END STEP", "s1/1", 100, 30, 0, sdir=sdir, out_path=bundle_path,
            )
            self.assertNotIn("p(art)", frame_step)

            buf = io.StringIO()
            keys = iter(["part", "next_part", "back", "back"])
            with unittest.mock.patch.object(
                self.mod, "_read_pager_key", side_effect=lambda *a, **k: next(keys)
            ), unittest.mock.patch.object(
                self.mod, "_read_part_number", return_value=idx["r1"]
            ), unittest.mock.patch.object(self.mod, "_term_size", return_value=(100, 30)):
                out = self.mod._show_info_fullscreen(
                    title_kind="START SESSION",
                    label="s1/0",
                    tty_r=io.StringIO(),
                    tty_w=buf,
                    sdir=sdir,
                    out_path=bundle_path,
                    edit_target=bundle_path,
                    allow_copy=True,
                )
            self.assertEqual(out["action"], "back")
            shown = buf.getvalue()
            self.assertIn(f"PART {idx['r1']}/{total}", shown)
            self.assertIn("line a", shown)
            self.assertIn(f"PART {idx['p1']}/{total}", shown)
            self.assertIn("Do the task", shown)

    def test_f73_prompt_flag_embedding_and_cli_validation(self):
        proj = self.tmp / "f73_proj"
        proj.mkdir()
        nonce = "f73nonce"

        # 1. Empty stdin: includes ===== Rules ===== and ===== Prompt ===== with joined repeatable prompts
        res_empty = self.mod.format_start_bundle(
            "s1",
            stdin_body="",
            work_dir=proj,
            prompt=["First prompt", "   \n\t  ", "Second prompt"],
        )
        full_empty = str(res_empty["full"])
        self.assertIn("===== Rules =====\n## Terminal blocks (`", full_empty)
        self.assertIn("\n\n===== Prompt =====\nFirst prompt\n\nSecond prompt\n", full_empty)
        plan_empty = res_empty["bundle_plan"]
        self.assertEqual([p["kind"] for p in plan_empty["parts"]], ["rules", "prompt"])
        self.assertEqual(plan_empty["parts"][1]["name"], "Prompt")
        _, part2_txt = self.mod.extract_bundle_part(plan_empty, full_empty, 2)
        self.assertEqual(part2_txt, "===== Prompt =====\nFirst prompt\n\nSecond prompt\n")

        # Whitespace-only prompts are ignored completely
        res_ws = self.mod.format_start_bundle("s1", stdin_body="", work_dir=proj, prompt=["", "   "])
        self.assertNotIn("===== Prompt =====", str(res_ws["full"]))
        self.assertEqual(len(res_ws["bundle_plan"]["parts"]), 1)

        # 2. Unlabeled plain stdin wrapped as ===== Prompt ===== by F66: appends \n\n<prompt> without duplicate header
        res_plain = self.mod.format_start_bundle(
            "s2",
            stdin_body="Unlabeled base request\n",
            work_dir=proj,
            prompt="Extra instruction",
        )
        full_plain = str(res_plain["full"])
        self.assertEqual(full_plain.count("===== Prompt ====="), 1)
        self.assertIn("===== Prompt =====\nUnlabeled base request\n\nExtra instruction\n", full_plain)
        self.assertEqual([p["kind"] for p in res_plain["bundle_plan"]["parts"]], ["rules", "prompt"])

        # 3. Trailing ===== Prompt ===== section (plain and boundary-marked): appends inside trailing section
        res_trail_plain = self.mod.format_start_bundle(
            "s3",
            stdin_body="===== Rules =====\nRule A\n\n===== Prompt =====\nBase task\n",
            work_dir=proj,
            prompt=["Follow-up 1", "Follow-up 2"],
        )
        full_trail_plain = str(res_trail_plain["full"])
        self.assertEqual(full_trail_plain.count("===== Prompt ====="), 1)
        self.assertIn("===== Prompt =====\nBase task\n\nFollow-up 1\n\nFollow-up 2\n", full_trail_plain)

        boundary_with_prompt = (
            f"Bundle-Boundary: {nonce}\n\n"
            f'<!-- bundle:{nonce}:part {{"kind": "rule", "id": "pkg:r1", "chain": ["pkg"]}} -->\n'
            "Rule content\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind": "prompt", "name": "Prompt", "chain": []}} -->\n'
            "===== Prompt =====\n"
            "Piped bundle prompt\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_trail_bnd = self.mod.format_start_bundle(
            "s4",
            stdin_body=boundary_with_prompt,
            work_dir=proj,
            prompt="CLI extra prompt",
        )
        full_trail_bnd = str(res_trail_bnd["full"])
        raw_trail_bnd = str(res_trail_bnd["raw_body"])
        self.assertEqual(full_trail_bnd.count("===== Prompt ====="), 1)
        self.assertIn("===== Prompt =====\nPiped bundle prompt\n\nCLI extra prompt\n", full_trail_bnd)
        self.assertNotIn(f"bundle:{nonce}", full_trail_bnd)
        self.assertIn(f"Piped bundle prompt\n\nCLI extra prompt\n<!-- bundle:{nonce}:end -->", raw_trail_bnd)
        plan_trail_bnd = res_trail_bnd["bundle_plan"]
        self.assertEqual([p["kind"] for p in plan_trail_bnd["parts"]], ["rule", "rule", "prompt"])
        _, bnd_prompt_chunk = self.mod.extract_bundle_part(plan_trail_bnd, full_trail_bnd, 3)
        self.assertEqual(bnd_prompt_chunk, "===== Prompt =====\nPiped bundle prompt\n\nCLI extra prompt\n")

        # 4. Other sections without trailing ===== Prompt ===== (with and without Bundle-Boundary)
        boundary_no_prompt = (
            f"Bundle-Boundary: {nonce}\n\n"
            f'<!-- bundle:{nonce}:part {{"kind": "rule", "id": "pkg:r1", "chain": ["pkg"]}} -->\n'
            "Rule content\n"
            f"<!-- bundle:{nonce}:end -->\n"
            f'<!-- bundle:{nonce}:part {{"kind": "cmd", "name": "git status", "rc": 0, "ms": 5}} -->\n'
            "===== " + chr(36) + " git status =====\n"
            "===== Prompt =====\n"
            "Decoy prompt header inside cmd output\n"
            f"<!-- bundle:{nonce}:end -->\n"
        )
        res_other_bnd = self.mod.format_start_bundle(
            "s5",
            stdin_body=boundary_no_prompt,
            work_dir=proj,
            prompt="Appended final prompt",
        )
        full_other_bnd = str(res_other_bnd["full"])
        self.assertTrue(full_other_bnd.endswith("===== Prompt =====\nAppended final prompt\n"))
        plan_other_bnd = res_other_bnd["bundle_plan"]
        self.assertEqual([p["kind"] for p in plan_other_bnd["parts"]], ["rule", "rule", "cmd", "prompt"])
        self.assertEqual(plan_other_bnd["parts"][-1]["name"], "Prompt")
        _, bnd_appended_chunk = self.mod.extract_bundle_part(plan_other_bnd, full_other_bnd, 4)
        self.assertEqual(bnd_appended_chunk, "===== Prompt =====\nAppended final prompt\n")

        # 5. CLI modes (TTY and piped, bare and --start, with --session, --sandbox, --force) & incompatible rejections
        sessions = self.tmp / "f73_sessions"
        old_base = self.mod.BASE_DIR
        old_cwd_env = os.environ.get("RUN_BLOCK_CWD")
        self.mod.BASE_DIR = sessions
        os.environ["RUN_BLOCK_CWD"] = str(proj)
        try:
            class _FakeTtyIn(io.StringIO):
                def isatty(self) -> bool:
                    return True

            with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=True):
                # Bare run_block -p in TTY without stdin
                with unittest.mock.patch.object(self.mod.sys, "stdin", _FakeTtyIn()):
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        rc = self.mod.main(["-p", "TTY prompt 1", "-p", "   ", "--prompt", "TTY prompt 2"])
                    self.assertEqual(rc, 0)
                    b_s1 = (sessions / "s1" / "0").read_text(encoding="utf-8")
                    self.assertIn("===== Rules =====\n## Terminal blocks (`", b_s1)
                    self.assertIn("===== Prompt =====\nTTY prompt 1\n\nTTY prompt 2\n", b_s1)

                    # run_block --start -p in TTY with --session, --sandbox, --force
                    buf2 = io.StringIO()
                    with contextlib.redirect_stdout(buf2):
                        rc2 = self.mod.main([
                            "--start", "--session", "s1", "--sandbox", "strict", "--force",
                            "--prompt=Start prompt",
                        ])
                    self.assertEqual(rc2, 0)
                    b_s1_forced = (sessions / "s1" / "0").read_text(encoding="utf-8")
                    self.assertIn("Sandbox: strict", b_s1_forced)
                    self.assertIn("===== Prompt =====\nStart prompt\n", b_s1_forced)

                    # Bare run_block -p with --session, --sandbox, --force in TTY
                    buf3 = io.StringIO()
                    with contextlib.redirect_stdout(buf3):
                        rc3 = self.mod.main([
                            "-p", "Bare combined", "--session", "s2", "--sandbox", "nonet", "--force",
                        ])
                    self.assertEqual(rc3, 0)
                    b_s2 = (sessions / "s2" / "0").read_text(encoding="utf-8")
                    self.assertIn("Sandbox: nonet", b_s2)
                    self.assertIn("===== Prompt =====\nBare combined\n", b_s2)

                # Piped stdin: <cmd> | run_block -p and <cmd> | run_block --start -p
                with unittest.mock.patch.object(
                    self.mod.sys, "stdin", io.StringIO("===== Prompt =====\nFrom pipe\n")
                ):
                    buf4 = io.StringIO()
                    with contextlib.redirect_stdout(buf4):
                        rc4 = self.mod.main(["-p", "From flag", "--session", "s3", "--sandbox", "strict"])
                    self.assertEqual(rc4, 0)
                    b_s3 = (sessions / "s3" / "0").read_text(encoding="utf-8")
                    self.assertEqual(b_s3.count("===== Prompt ====="), 1)
                    self.assertIn("===== Prompt =====\nFrom pipe\n\nFrom flag\n", b_s3)

                with unittest.mock.patch.object(
                    self.mod.sys, "stdin", io.StringIO("===== $ echo hi =====\nhi\n")
                ):
                    buf5 = io.StringIO()
                    with contextlib.redirect_stdout(buf5):
                        rc5 = self.mod.main([
                            "--start", "-p", "After cmd", "--session", "s3", "--force", "--no-sandbox",
                        ])
                    self.assertEqual(rc5, 0)
                    b_s3_f = (sessions / "s3" / "0").read_text(encoding="utf-8")
                    self.assertIn("Sandbox: off", b_s3_f)
                    self.assertIn("===== Prompt =====\nAfter cmd\n", b_s3_f)

                # Missing argument for -p / --prompt
                for bad_argv in (["-p"], ["--start", "--prompt"]):
                    with self.subTest(bad_argv=bad_argv):
                        with self.assertRaises(SystemExit) as cm:
                            self.mod.main(bad_argv)
                        self.assertIn("requires an argument", str(cm.exception))

                # Incompatible commands must reject -p / --prompt
                incompatible_cases = [
                    ["s1/1", "-p", "no"],
                    ["-p", "no", "s1/1"],
                    ["--fix", "s1/1", "-p", "no"],
                    ["--retry", "-p", "no"],
                    ["--retry", "s1/1", "--prompt", "no"],
                    ["--list", "-p", "no"],
                    ["-l", "s1", "-p", "no"],
                    ["--show", "-p", "no"],
                    ["--show", "s1/0", "--prompt=no"],
                    ["--plan", "-p", "no"],
                    ["--bundle-plan", "-p", "no"],
                    ["--bundle-plan", "s1", "-p", "no"],
                    ["--clean", "-p", "no"],
                    ["--sandbox", "-p", "no"],
                    ["--sandbox", "s1", "-p", "no"],
                    ["--sandbox", "strict", "s1", "-p", "no"],
                    ["--update", "-p", "no"],
                    ["--check-update", "-p", "no"],
                ]
                for bad_cmd in incompatible_cases:
                    with self.subTest(bad_cmd=bad_cmd):
                        with self.assertRaises(SystemExit) as cm:
                            self.mod.main(bad_cmd)
                        self.assertIn("-p/--prompt", str(cm.exception))
                        self.assertIn("usage:", str(cm.exception))
        finally:
            self.mod.BASE_DIR = old_base
            if old_cwd_env is None:
                os.environ.pop("RUN_BLOCK_CWD", None)
            else:
                os.environ["RUN_BLOCK_CWD"] = old_cwd_env

    def test_f57_start_session_append_creates_prompt_section_and_backup(self):
        sdir = self.tmp / "s1"
        sdir.mkdir(parents=True, exist_ok=True)
        bundle_file = sdir / "0"
        initial_text = (
            "Session: s1\n"
            "Next-Block: s1/1\n"
            f"Workdir: {self.tmp}\n"
            "Sandbox: off\n"
            "Date: 2026-11-20 13:00 UTC\n\n"
            "Short context\n"
        )
        bundle_file.write_text(initial_text, encoding="utf-8")
        initial_stats = self.mod.stats_line(bundle_file)
        tty_out, mock_copy, refresh_calls = self._f57_offer(
            bundle_file,
            "a\na\n\n",
            ["first note\n", "second note\n"],
            "START SESSION",
            extra_lines=[f"Bundle: {bundle_file}"],
        )
        text = bundle_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("===== Prompt ====="), 1)
        self.assertTrue(text.startswith(initial_text.rstrip("\n")))
        self.assertLess(text.index("first note"), text.index("second note"))
        orig = sdir / "0.orig"
        self.assertEqual(orig.read_text(encoding="utf-8"), initial_text)
        self.assertEqual(refresh_calls, [bundle_file, bundle_file])
        mock_copy.assert_called_once_with(["pbcopy"], bundle_file)
        self.assertIn("a(ppend)", tty_out)
        self.assertIn("(edited)", tty_out)
        self.assertNotEqual(self.mod.stats_line(bundle_file), initial_stats)
        self.assertEqual(tty_out.count("╭─ START SESSION "), 3)

    def test_f57_start_session_append_extends_existing_prompt_section(self):
        sdir = self.tmp / "s1"
        sdir.mkdir(parents=True, exist_ok=True)
        bundle_file = sdir / "0"
        initial_text = (
            "Session: s1\n"
            "Next-Block: s1/1\n\n"
            "===== Rules =====\nsome rule\n\n"
            "===== Prompt =====\nOriginal ask\n"
        )
        bundle_file.write_text(initial_text, encoding="utf-8")
        self._f57_offer(
            bundle_file, "a\n\n", ["follow-up question\n"], "START SESSION", extra_lines=[f"Bundle: {bundle_file}"]
        )
        text = bundle_file.read_text(encoding="utf-8")
        self.assertEqual(text.count("===== Prompt ====="), 1)
        self.assertLess(text.index("Original ask"), text.index("follow-up question"))
        self.assertGreater(text.index("follow-up question"), text.index("===== Prompt ====="))
        self.assertEqual((sdir / "0.orig").read_text(encoding="utf-8"), initial_text)

    def test_f57_start_session_empty_append_leaves_files_untouched(self):
        sdir = self.tmp / "s1"
        sdir.mkdir(parents=True, exist_ok=True)
        bundle_file = sdir / "0"
        initial_text = "Session: s1\nNext-Block: s1/1\n\nShort context\n"
        bundle_file.write_text(initial_text, encoding="utf-8")
        for blank in ("", "  \n\n\t\n"):
            with self.subTest(blank=blank):
                tty_out, mock_copy, refresh_calls = self._f57_offer(
                    bundle_file, "a\n\n", [blank], "START SESSION", extra_lines=[f"Bundle: {bundle_file}"]
                )
                self.assertEqual(bundle_file.read_text(encoding="utf-8"), initial_text)
                self.assertFalse((sdir / "0.orig").exists())
                self.assertEqual(refresh_calls, [])
                self.assertNotIn("(edited)", tty_out)
                mock_copy.assert_called_once_with(["pbcopy"], bundle_file)


if __name__ == "__main__":
    unittest.main()
