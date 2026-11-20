#!/usr/bin/env python3
# run_block-repo: vitalio/run_block
"""Usage:
  {prog}                           Start a rule-only session on TTY stdin (or read bundle from piped stdin)
  <command> | {prog}                 Start a new session from stdin context bundle into {base_dir}/<session>/0
  {prog} [-y] <session>/<step>       Run block from stdin (-y/--yes: non-interactive headless mode, also reopens a completed session)
  {prog} --plan                      Analyze script from stdin and print JSON execution & safety plan
  {prog} --bundle-plan [opts] [sess] Summarize bundle parts/warnings from stdin or session (--json, --full, --part N)
  {prog} --fix [-y] <session>/<ref>  Patch <ref> script via Python on stdin and run as <ref>_N
  {prog} --retry [-y] [session/step] Re-run the last (or specified) block
  {prog} --list | -l [session]       List sessions or blocks in a session ([DONE] marks completed sessions)
  {prog} --done [session] [-m NOTE]  Mark session completed and print END SESSION summary (later blocks ask to reopen)
  {prog} --show [session/step]       Show script, output, and (edited) backup notes of a block or <session>/0
  {prog} --show [session] --part N   Print only part N of <session>/0 (1-based part index, see --bundle-plan --json)
  {prog} --sandbox [MODE] [session]  Show or set session sandbox mode (off, strict, nonet)
  {prog} --clean [opts] [session...] Prune sessions in {base_dir} (--keep N, --older-than DAYS, --max-size MB, --all)
  {prog} -p | --prompt TEXT          Embed repeatable prompt text into the started session bundle (===== Prompt =====)
  {prog} --start [opts]              Start session from stdin or rule-only on TTY (--session NAME, --sandbox MODE, --force, -p/--prompt TEXT)
  {prog} --update [--force]          Self-update {prog} from GitHub (vitalio/run_block)
  {prog} --check-update              Check if a newer version is available
  {prog} -V | --version              Print version and exit 0
  {prog} -h | --help                 Print this usage and exit 0

Environment:
  RUN_BLOCK_CWD=auto|cwd|PATH        Working directory (auto prefers piped/session Workdir, project root, or $PWD)
  RUN_BLOCK_PROGRESS=0               Disable live step progress markers during interactive runs
  RUN_BLOCK_BUNDLE_MAX_TOKENS=100000 Warn when total bundle exceeds token budget (0 disables)
  RUN_BLOCK_FRAGMENT_MAX_TOKENS=20000 Warn when a single bundle part exceeds token limit (0 disables)
  VISUAL / EDITOR                    Editor/viewer for e(dit), s(cript), o(utput), and v(iew) inside i(nfo) (keeps *.orig backups)
"""
from __future__ import annotations

if __doc__ is None:
    raise SystemExit("missing usage documentation")

import ast
import difflib
import json
import math
import os
import queue
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

try:
    import pty
    import termios
    import tty
    HAS_PTY = True
except ImportError:
    pty = None  # type: ignore[assignment]
    termios = None  # type: ignore[assignment]
    tty = None  # type: ignore[assignment]
    HAS_PTY = False

VERSION = "__VERSION__"
REPO_MARKER = "run_block-repo: vitalio/run_block"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/vitalio/run_block/main/run_block"
EMBEDDED_RULE_BASH = "__EMBEDDED_RULE_BASH__"
EMBEDDED_RULE_PWSH = "__EMBEDDED_RULE_PWSH__"
