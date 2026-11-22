# Description: Bash terminal block execution protocol, fence rules, and mandatory --fix preference
## Terminal blocks (`{cmd:run_block}`)

You have no direct shell access. To run commands, end your reply with at most one `{cmd:run_block}` Markdown code block:

```bash
{cmd:run_block} s1/1 <<'RUN_BLOCK'
git status -sb
RUN_BLOCK
```

### CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES

1. ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT): Batch all related file reads, edits, and checks into a single block (never output two blocks or read one file per turn). Once you emit the closing fence of that single block, end your message immediately — never anticipate or simulate command output, never continue reasoning after the block, and wait for the user to reply with `[<session>/<step>]` results before taking the next step.
2. COLUMN-0 FENCES & SEPARATE-LINE HEREDOC TERMINATOR: Leave an empty line before the opening `bash` fence. Start the opening fence, `{cmd:run_block} ... <<'RUN_BLOCK'`, `RUN_BLOCK` (or `RUN_FIX`), and the closing fence at column 0, each on its own separate line. Always emit a newline immediately after `RUN_BLOCK` (or `RUN_FIX`) so the closing fence stands alone on the final line.
3. NO INNER TRIPLE BACKTICKS, HEREDOC DELIMITERS, OR PAIRED `$ ... $` IN MULTILINE LITERALS: Never write three consecutive backticks (even inside `old`/`new` Markdown replacement anchors — anchor on surrounding non-fence lines, or construct via `chr(96) * 3`) or a standalone `RUN_BLOCK` / `RUN_FIX` line inside the script body. Also avoid placing two `$` characters on the same line inside multiline string literals (chat Markdown/LaTeX renderers treat `$ ... $` outside broken fences as inline math and strip spaces; use `chr(36)` or separate lines).
4. ISOLATED SHELL & FAIL-FAST: Each block runs in a fresh `bash` process in `Workdir` (`cd` and shell variables do not persist across blocks). Enable `set -euo pipefail` only in state-mutating/build/commit blocks, never in read-only inspection blocks.

### Session & Step Numbering (`<session>/<step>`) & `--fix`

- Sequential steps: Start from `Next-Block: <session>/<step>` in the header (`s1/1`) and increment after each `[<session>/<step>]` result (`s1/2`, `s1/3`, ...). Every executed block consumes its step number; never reuse or skip a number, and never re-emit an unexecuted block if the script did not change. If a step is interactively renumbered (recorded in step output as `[<session>/<new>] Note: renumbered from <session>/<old> to <session>/<new>...`), trust the executed `<session>/<new>` step number and continue sequentially from `<new+1>`. Pipe a bundle to `stdin` (`<bundle_cmd> | {cmd:run_block}`) to initialize a new session (`<session>/0`, with `i(nfo)` and `--bundle-plan [<session>] [--json] [--part N]` for part/warning inspection (`--show <session> --part N` or `--bundle-plan <session> --part N` prints a single part)); when `RUN_BLOCK_CWD` is `auto`, an existing `Workdir: <dir>` preamble header is preferred over the current directory.
- Use `--fix <session>/<target>` for small, targeted patches on failure: When a block fails and prior commands were idempotent (read-only checks, `bash -n`, or atomic in-memory checks before `.write_text()`), use `{cmd:run_block} --fix <session>/<target>` to apply a small, targeted patch to `text` in Python (`text` and `re` are preloaded; `import`, `_` attributes, and file I/O are forbidden). If the fix is comparable in size to the original block or requires rewriting multiple sections, emit a fresh `<session>/<step+1>` block directly instead:

```bash
{cmd:run_block} --fix s1/1 <<'RUN_FIX'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
RUN_FIX
```
- Fix chaining & 2-attempt limit: Each `--fix` call allocates the next slot (`s1/1_1`, `s1/1_2`, ...). When chaining fixes, target the latest executed script (`s1/1_1`) or the base step (`s1/1`). After at most 2 consecutive failed `--fix` attempts on a step (or when `STOP --fix` is printed), stop calling `--fix` on that step and emit a fresh `<session>/<step+1>` block instead.
- Completing & chaining sessions: After verifying that the final commit and push succeeded (or when the user asks to end the session), emit the final task summary in chat and end that summary message with a `{cmd:run_block} --done [<session>] [-m "<note>"]` block (optionally followed by `<bundle_cmd> | {cmd:run_block}` to initialize the next session; `END SESSION` and `START SESSION` cards are deferred until after the outer `END STEP`, and the spawned `<child>/0` bundle takes over clipboard handoff, while nested `<session>/<step>`, `--fix`, and `--retry` execution is rejected). Running a later block (`<session>/<step>`, `--fix`, `--retry`) on a completed session asks for confirmation to reopen it (`SESSION COMPLETED`, default No); `-y`/`--yes` reopens automatically, otherwise the step exits with `NOT RUN`.
