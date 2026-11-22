#!/usr/bin/env python3
# run_block-repo: vitalio/run_block
"""Safe, sequential terminal block execution protocol for AI coding agents."""
from __future__ import annotations

if __doc__ is None:
    raise SystemExit("missing usage documentation")

import ast
import difflib
import json
import math
import os
import re
import select
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
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


HELP_USAGE = (
    "{prog} [options] [<session>/<step>]",
    "<command> | {prog} [options]",
)

HELP_COMMANDS = (
    ("{prog}", "Start a rule-only session on TTY stdin (or read a bundle from piped stdin)"),
    ("<command> | {prog}", "Start a new session from a stdin context bundle into {base_dir}/<session>/0"),
    ("{prog} [-y] <session>/<step>", "Run the block from stdin (-y/--yes: non-interactive headless mode, also reopens a completed session)"),
    ("{prog} --plan", "Analyze the script from stdin and print the JSON execution and safety plan"),
    ("{prog} --bundle-plan [sess]", "Print the Parts table and warnings of a bundle from stdin or session (--json, --part N)"),
    ("{prog} --fix [-y] <session>/<ref>", "Patch <ref> script via Python on stdin and run as <ref>_N"),
    ("{prog} --retry [-y] [session/step]", "Re-run the last block of a session or <session>/<step>"),
    ("{prog} --list | -l [session]", "List sessions/blocks: last step, next free step ([DONE] = completed)"),
    ("{prog} --list --filter TEXT", "List only sessions whose name or headers contain TEXT"),
    ("{prog} --done [session] [-m NOTE]", "Mark session completed and print END SESSION summary (later blocks ask to reopen)"),
    ("{prog} --show [session/step]", "Show script, output, and (edited) backup notes of a block or <session>/0"),
    ("{prog} --show <session> --part N", "Print only part N of <session>/0 (1-based part index, see --bundle-plan --json)"),
    ("{prog} --show <ref> --script|--out", "Print only a block's script or only its output"),
    ("{prog} --info [session]", "Show path, size, headers, and all blocks of a session"),
    ("{prog} --sandbox [MODE] [session]", "Show or set session sandbox mode (off, strict, nonet)"),
    ("{prog} --clean [opts] [session...]", "Prune sessions in {base_dir} (--keep N, --older-than DAYS, --max-size MB, --all)"),
    ("{prog} --start [opts]", "Start a session from stdin or rule-only on TTY (--session NAME, --force)"),
    ("{prog} --update [--force]", "Self-update {prog} from GitHub (vitalio/run_block)"),
    ("{prog} --check-update", "Check if a newer version is available"),
)

HELP_OPTIONS = (
    ("-y, --yes, --headless", "Non-interactive headless mode without prompts; also reopens a completed session"),
    ("-p, --prompt TEXT", "Embed repeatable prompt text into the started session bundle (===== Prompt =====)"),
    ("--sandbox [MODE]", "Set the sandbox mode for the run or started session (off, strict, nonet); bare flag means strict"),
    ("--no-sandbox", "Same as --sandbox off"),
    ("-V, --version", "Print version and exit 0"),
    ("-h, --help", "Print this usage and exit 0"),
)

HELP_ENV = (
    ("RUN_BLOCK_CWD=auto|cwd|PATH", "Working directory (auto prefers piped/session Workdir, project root, or $PWD)"),
    ("RUN_BLOCK_PROGRESS=0", "Disable live step progress markers during interactive runs"),
    ("RUN_BLOCK_BUNDLE_MAX_TOKENS=100000", "Warn when total bundle exceeds token budget (0 disables)"),
    ("RUN_BLOCK_FRAGMENT_MAX_TOKENS=20000", "Warn when a single bundle part exceeds token limit (0 disables)"),
    ("VISUAL / EDITOR", "Editor/viewer for e(dit), s(cript), o(utput), and v(iew) inside i(nfo) (keeps *.orig backups)"),
)
