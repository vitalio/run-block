#!/usr/bin/env python3
"""Shared test helpers and base class for run-block unit tests."""

from __future__ import annotations

import contextlib
import importlib.machinery
import importlib.util
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run"
INSTALL_SH = ROOT / "install.sh"

_CACHED_MOD: ModuleType | None = None
_CACHED_MTIME_NS: int = -1

_TRACKED_ENV_KEYS = (
    "RUN_BLOCK_NO_CLIPBOARD",
    "RUN_BLOCK_CLIPBOARD",
    "RUN_BLOCK_CONFIRM",
    "RUN_BLOCK_CONFIG",
    "RUN_BLOCK_DIR",
    "RUN_BLOCK_CWD",
    "IN_RUN_BLOCK",
    "RUN_BLOCK_PARENT_SESSION",
    "RUN_BLOCK_PARENT_STEP",
    "RUN_BLOCK_UPDATE_URL",
    "RUN_BLOCK_SHELL",
    "RUN_BLOCK_EDITOR",
    "RUN_BLOCK_SAFETY_DISABLE",
    "RUN_BLOCK_SAFETY_RULES",
    "RUN_BLOCK_APPROVE_CMD",
    "RUN_BLOCK_HEADLESS",
    "RUN_BLOCK_SANDBOX",
    "RUN_BLOCK_MAX_FIX_ATTEMPTS",
    "RUN_BLOCK_MAX_STATE_MB",
    "RUN_BLOCK_BUNDLE_MAX_TOKENS",
    "RUN_BLOCK_FRAGMENT_MAX_TOKENS",
    "RUN_BLOCK_TOKEN_STATS",
    "RUN_BLOCK_PROGRESS",
    "XDG_STATE_HOME",
    "NO_COLOR",
)


def load_module() -> ModuleType:
    global _CACHED_MOD, _CACHED_MTIME_NS
    mtime_ns = SCRIPT.stat().st_mtime_ns
    if _CACHED_MOD is None or mtime_ns != _CACHED_MTIME_NS:
        loader = importlib.machinery.SourceFileLoader("run_block", str(SCRIPT))
        spec = importlib.util.spec_from_loader("run_block", loader)
        assert spec is not None
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        _CACHED_MOD = mod
        _CACHED_MTIME_NS = mtime_ns
    return _CACHED_MOD


class RunBlockTestCase(unittest.TestCase):
    mod: ModuleType
    tmp: Path

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.mod = load_module()

    def setUp(self) -> None:
        keys = set(_TRACKED_ENV_KEYS) | {k for k in os.environ if k.startswith("RUN_BLOCK_")}
        self._orig_env = {k: os.environ.get(k) for k in keys}
        self._orig_argv0 = sys.argv[0] if sys.argv else "run"
        if sys.argv:
            sys.argv[0] = str(SCRIPT)
        os.environ["RUN_BLOCK_NO_CLIPBOARD"] = "1"
        os.environ["NO_COLOR"] = "1"
        os.environ.pop("IN_RUN_BLOCK", None)
        os.environ.pop("RUN_BLOCK_PARENT_SESSION", None)
        os.environ.pop("RUN_BLOCK_PARENT_STEP", None)
        self.tmp = Path(tempfile.mkdtemp(prefix="rb_test_"))
        os.environ["XDG_STATE_HOME"] = str(self.tmp / ".xdg_state")
        os.environ["RUN_BLOCK_DIR"] = str(self.tmp)
        self.mod = load_module()
        self.mod.BASE_DIR = self.tmp
        if hasattr(self.mod, "_STATE_WARNED_DIRS"):
            self.mod._STATE_WARNED_DIRS.clear()

    def tearDown(self) -> None:
        if sys.argv:
            sys.argv[0] = self._orig_argv0
        for k in list(os.environ):
            if k.startswith("RUN_BLOCK_") and k not in self._orig_env:
                os.environ.pop(k, None)
        for k, v in self._orig_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _assert_ok(self, proc: subprocess.CompletedProcess[str], expected_rc: int = 0) -> None:
        self.assertEqual(
            proc.returncode,
            expected_rc,
            msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}",
        )

    def _normalize_cmd(self, cmd: list[str] | tuple[str, ...]) -> tuple[str, list[str]]:
        items = [str(x) for x in cmd]
        if items and (items[0] == str(SCRIPT) or Path(items[0]).name in ("run", "run_block", "my_block")):
            return items[0], items[1:]
        return str(SCRIPT), items

    def _run_in_process(
        self,
        cmd: list[str] | tuple[str, ...],
        *,
        input: str | None = None,
        stdin: object = None,
        capture_output: bool = True,
        text: bool = True,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        _ = (stdin, capture_output, text)
        exe_path, argv = self._normalize_cmd(cmd)
        old_env = dict(os.environ)
        old_cwd = os.getcwd()
        old_base = self.mod.BASE_DIR
        old_stdin = self.mod.sys.stdin
        old_argv = list(self.mod.sys.argv)
        old_file = getattr(self.mod, "__file__", str(SCRIPT))
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        rc = 0
        try:
            if env is not None:
                os.environ.clear()
                os.environ.update(env)
            if cwd is not None:
                os.chdir(cwd)
            self.mod.sys.argv = [exe_path, *argv]
            self.mod.__file__ = exe_path
            self.mod.BASE_DIR = self.mod.default_base_dir()
            self.mod.sys.stdin = io.StringIO(input if input is not None else "")
            with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
                try:
                    res = self.mod.main(argv)
                    rc = int(res) if res is not None else 0
                except SystemExit as exc:
                    if exc.code is None:
                        rc = 0
                    elif isinstance(exc.code, int):
                        rc = exc.code
                    else:
                        err_buf.write(f"{exc.code}\n")
                        rc = 1
        finally:
            self.mod.sys.stdin = old_stdin
            self.mod.sys.argv = old_argv
            self.mod.__file__ = old_file
            os.chdir(old_cwd)
            if env is not None:
                os.environ.clear()
                os.environ.update(old_env)
            self.mod.BASE_DIR = old_base
        proc = subprocess.CompletedProcess(
            args=[exe_path, *argv],
            returncode=rc,
            stdout=out_buf.getvalue(),
            stderr=err_buf.getvalue(),
        )
        if check and proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, proc.args, output=proc.stdout, stderr=proc.stderr
            )
        return proc

    def _run_subprocess(
        self,
        cmd: list[str] | tuple[str, ...],
        *,
        input: str | None = None,
        stdin: int | None = None,
        capture_output: bool = True,
        text: bool = True,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        exe_path, argv = self._normalize_cmd(cmd)
        return subprocess.run(
            [exe_path, *argv],
            input=input,
            stdin=stdin,
            capture_output=capture_output,
            text=text,
            cwd=str(cwd) if cwd is not None else None,
            env=env,
            check=check,
        )

    def _run(
        self,
        cmd: list[str] | tuple[str, ...],
        *,
        input: str | None = None,
        stdin: object = None,
        capture_output: bool = True,
        text: bool = True,
        cwd: str | Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_in_process(
            cmd,
            input=input,
            stdin=stdin,
            capture_output=capture_output,
            text=text,
            cwd=cwd,
            env=env,
            check=check,
        )

    def _f57_offer(self, target, keys, notes, title_kind, extra_lines=None, rc=None, ok=True):
        editor_paths: list[Path] = []
        note_iter = iter(notes)

        def stub_editor(p, _r, _w):
            editor_paths.append(p)
            self.assertEqual(p.suffix, ".md")
            self.assertEqual(p.read_text(encoding="utf-8"), "")
            p.write_text(next(note_iter), encoding="utf-8")

        class _KeepOpenStringIO(io.StringIO):
            def close(self) -> None:
                pass

        fake_stdout = io.StringIO()
        fake_stdout.isatty = lambda: True  # type: ignore[method-assign]
        tty_w = _KeepOpenStringIO()
        tty_r = io.StringIO(keys)
        refresh_calls: list[Path] = []
        with unittest.mock.patch.object(self.mod, "no_clipboard", return_value=False), \
             unittest.mock.patch.object(self.mod, "clipboard_mode", return_value="prompt"), \
             unittest.mock.patch.object(self.mod, "clipboard_command", side_effect=lambda p: (["pbcopy"], f"pbcopy < {p}")), \
             unittest.mock.patch.object(self.mod, "open_tty", return_value=(tty_w, tty_r)), \
             unittest.mock.patch.object(self.mod, "open_script_in_editor", side_effect=stub_editor), \
             unittest.mock.patch.object(self.mod, "refresh_bundle_meta", side_effect=lambda p: refresh_calls.append(p)), \
             unittest.mock.patch.object(self.mod, "copy_file_to_clipboard", return_value=True) as mock_copy, \
             unittest.mock.patch.object(self.mod.shutil, "get_terminal_size", return_value=os.terminal_size((100, 24))), \
             unittest.mock.patch.object(self.mod.sys, "stdout", fake_stdout):
            self.mod.offer_clipboard_copy(
                "s1/0" if title_kind == "START SESSION" else "s1/1",
                target,
                ok=ok,
                rc=rc,
                title_kind=title_kind,
                extra_lines=extra_lines,
            )
        for p in editor_paths:
            self.assertFalse(p.exists(), msg="temporary append file must be removed")
        return tty_w.getvalue(), mock_copy, refresh_calls
