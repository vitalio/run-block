#!/usr/bin/env sh
# Usage: install.sh [-h|--help] [--name CMD] [--dir DIR] [--yes] [--uninstall [--purge]]
#
# Installs, updates, or uninstalls run (https://github.com/vitalio/run-block).
# Checks for command name conflicts in PATH, offers an alternative name if
# 'run' is already taken by another program, installs into ~/.local/bin
# (or --dir). --uninstall removes installed binaries (--purge also removes state).
# -h / --help prints this usage and exits 0 doing nothing.
set -eu

REPO_MARKER="run-block-repo: vitalio/run-block"
LEGACY_REPO_MARKER="run_block-repo: vitalio/run_block"
RAW_URL="${RUN_BLOCK_UPDATE_URL:-https://raw.githubusercontent.com/vitalio/run-block/main/run}"
CMD_NAME="${RUN_BLOCK_NAME:-}"
INSTALL_DIR="${RUN_BLOCK_INSTALL_DIR:-}"
ASSUME_YES=0
UNINSTALL=0
PURGE=0

usage() {
    sed -n '2,8s/^# \?//p' "$0"
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --name)
            if [ "$#" -lt 2 ]; then
                echo "install.sh: --name requires an argument" >&2
                exit 2
            fi
            CMD_NAME="$2"
            shift 2
            ;;
        --dir)
            if [ "$#" -lt 2 ]; then
                echo "install.sh: --dir requires an argument" >&2
                exit 2
            fi
            INSTALL_DIR="$2"
            shift 2
            ;;
        -y|--yes)
            ASSUME_YES=1
            shift
            ;;
        --uninstall)
            UNINSTALL=1
            shift
            ;;
        --purge)
            PURGE=1
            shift
            ;;
        *)
            echo "install.sh: unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ "$PURGE" -eq 1 ] && [ "$UNINSTALL" -eq 0 ]; then
    echo "install.sh: --purge requires --uninstall" >&2
    usage >&2
    exit 2
fi

is_our_binary() {
    [ -f "$1" ] && (grep -q "$REPO_MARKER" "$1" 2>/dev/null || grep -q "$LEGACY_REPO_MARKER" "$1" 2>/dev/null)
}

if [ "$UNINSTALL" -eq 1 ]; then
    if [ -z "$INSTALL_DIR" ]; then
        INSTALL_DIR="$HOME/.local/bin"
    fi
    REMOVED=0
    for NAME in ${CMD_NAME:+"$CMD_NAME"} run run_block; do
        CAND="$INSTALL_DIR/$NAME"
        if is_our_binary "$CAND"; then
            rm -f "$CAND"
            echo "Removed: $CAND"
            REMOVED=1
        fi
    done
    if [ "$REMOVED" -eq 0 ]; then
        echo "No installed run/run_block binary found in $INSTALL_DIR."
    fi
    if [ "$PURGE" -eq 1 ]; then
        if [ -n "${RUN_BLOCK_DIR:-}" ]; then
            if [ -e "$RUN_BLOCK_DIR" ] || [ -L "$RUN_BLOCK_DIR" ]; then
                rm -rf "$RUN_BLOCK_DIR"
                echo "Purged state: $RUN_BLOCK_DIR"
            fi
        else
            STATE_BASE="${XDG_STATE_HOME:-$HOME/.local/state}"
            for SNAME in run-block run_block; do
                SDIR="$STATE_BASE/$SNAME"
                if [ -e "$SDIR" ] || [ -L "$SDIR" ]; then
                    rm -rf "$SDIR"
                    echo "Purged state: $SDIR"
                fi
            done
        fi
    fi
    exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but was not found in PATH." >&2
    exit 1
fi
if ! command -v bash >/dev/null 2>&1; then
    echo "Error: bash is required but was not found in PATH." >&2
    exit 1
fi

if [ -z "$CMD_NAME" ]; then
    CMD_NAME="run"
    EXISTING="$(command -v "$CMD_NAME" 2>/dev/null || true)"
    if [ -n "$EXISTING" ] && ! is_our_binary "$EXISTING"; then
        echo "Notice: '$CMD_NAME' already exists at $EXISTING (another program)." >&2
        ALT_NAME="run_block"
        if [ "$ASSUME_YES" -eq 0 ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
            printf "Enter an alternative command name [%s]: " "$ALT_NAME" >/dev/tty
            IFS= read -r USER_NAME </dev/tty || USER_NAME=""
            if [ -n "$USER_NAME" ]; then
                CMD_NAME="$USER_NAME"
            else
                CMD_NAME="$ALT_NAME"
            fi
        else
            CMD_NAME="$ALT_NAME"
            echo "Using alternative command name: $CMD_NAME" >&2
        fi
    fi
fi

if [ -z "$INSTALL_DIR" ]; then
    EXISTING_OUR="$(command -v "$CMD_NAME" 2>/dev/null || true)"
    if [ -n "$EXISTING_OUR" ] && is_our_binary "$EXISTING_OUR"; then
        INSTALL_DIR="$(dirname "$EXISTING_OUR")"
    else
        EXISTING_LEGACY="$(command -v run_block 2>/dev/null || true)"
        if [ -n "$EXISTING_LEGACY" ] && is_our_binary "$EXISTING_LEGACY"; then
            INSTALL_DIR="$(dirname "$EXISTING_LEGACY")"
        else
            INSTALL_DIR="$HOME/.local/bin"
        fi
    fi
fi

mkdir -p "$INSTALL_DIR"
TARGET="$INSTALL_DIR/$CMD_NAME"

TMP_FILE="$(mktemp "${TMPDIR:-/tmp}/run_block_install.XXXXXX")"
cleanup() {
    rm -f "$TMP_FILE"
}
trap cleanup EXIT INT TERM

SCRIPT_DIR="$(CDPATH='' cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)"
if [ -z "${RUN_BLOCK_UPDATE_URL:-}" ] && [ -f "$SCRIPT_DIR/run" ] && is_our_binary "$SCRIPT_DIR/run"; then
    cp "$SCRIPT_DIR/run" "$TMP_FILE"
elif [ -z "${RUN_BLOCK_UPDATE_URL:-}" ] && [ -f "$SCRIPT_DIR/run_block" ] && is_our_binary "$SCRIPT_DIR/run_block"; then
    cp "$SCRIPT_DIR/run_block" "$TMP_FILE"
else
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$RAW_URL" -o "$TMP_FILE"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$TMP_FILE" "$RAW_URL"
    else
        python3 -c 'import sys, urllib.request; data = urllib.request.urlopen(sys.argv[1], timeout=15).read(); open(sys.argv[2], "wb").write(data)' "$RAW_URL" "$TMP_FILE"
    fi
fi

if ! is_our_binary "$TMP_FILE"; then
    echo "Error: downloaded file is not a valid vitalio/run-block script." >&2
    exit 1
fi

chmod 0755 "$TMP_FILE"
mv "$TMP_FILE" "$TARGET"

if [ "$CMD_NAME" != "run_block" ] && [ -f "$INSTALL_DIR/run_block" ] && is_our_binary "$INSTALL_DIR/run_block"; then
    rm -f "$INSTALL_DIR/run_block"
    echo "Removed legacy binary: $INSTALL_DIR/run_block"
fi

if [ -z "${RUN_BLOCK_DIR:-}" ]; then
    STATE_BASE="${XDG_STATE_HOME:-$HOME/.local/state}"
    LEGACY_STATE="$STATE_BASE/run_block"
    TARGET_STATE="$STATE_BASE/run-block"
    if [ -L "$LEGACY_STATE" ]; then
        if [ "${IN_RUN_BLOCK:-}" != "1" ]; then
            rm -f "$LEGACY_STATE"
        fi
    elif [ -d "$LEGACY_STATE" ] && [ ! -e "$TARGET_STATE" ]; then
        mv "$LEGACY_STATE" "$TARGET_STATE"
        if [ "${IN_RUN_BLOCK:-}" = "1" ]; then
            ln -s "run-block" "$LEGACY_STATE" 2>/dev/null || true
        fi
    fi
fi

VER="$("$TARGET" --version 2>/dev/null || echo "$CMD_NAME")"
echo "============================================================"
echo "Installed: $VER -> $TARGET"
case ":${PATH:-}:" in
    *":$INSTALL_DIR:"*) ;;
    *)
        RC_FILE=""
        case "${SHELL:-}" in
            */zsh) RC_FILE="$HOME/.zshrc" ;;
            */bash)
                if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
                    RC_FILE="$HOME/.bash_profile"
                else
                    RC_FILE="$HOME/.bashrc"
                fi
                ;;
            *)
                if [ "$(uname -s 2>/dev/null || true)" = "Darwin" ]; then
                    RC_FILE="$HOME/.zshrc"
                else
                    RC_FILE="$HOME/.bashrc"
                fi
                ;;
        esac
        EXPORT_LINE="export PATH=\"$INSTALL_DIR:\$PATH\""
        if [ -n "$RC_FILE" ] && [ "$INSTALL_DIR" = "$HOME/.local/bin" ]; then
            if [ ! -f "$RC_FILE" ] || ! grep -Fq "$INSTALL_DIR" "$RC_FILE" 2>/dev/null; then
                printf '\n# Added by %s installer\n%s\n' "$CMD_NAME" "$EXPORT_LINE" >> "$RC_FILE"
                echo "Added $INSTALL_DIR to PATH in $RC_FILE (run 'source $RC_FILE' or open a new terminal)."
            else
                echo "Note: $INSTALL_DIR is in $RC_FILE; run 'source $RC_FILE' or open a new terminal."
            fi
        else
            echo "Note: $INSTALL_DIR is not in your PATH. Add: $EXPORT_LINE"
        fi
        ;;
esac
echo "Tip: run '$CMD_NAME' or pipe a context bundle ('context | $CMD_NAME') to start a session."
echo "============================================================"
