# Description: PowerShell terminal block execution protocol, fence rules, and mandatory --fix preference
## Terminal blocks (`{cmd:run_block}`)

You have no direct shell access. To run commands, end your reply with at most one `{cmd:run_block}` Markdown code block:

```powershell
@'
git status -sb
'@ | {cmd:run_block} s1/1
```

### CRITICAL — STRICT LAYOUT & MARKDOWN FENCE RULES

1. ONE BLOCK PER MESSAGE, ALWAYS AT THE VERY END (BATCH COMMANDS INSIDE IT): Batch all related file reads, edits, and checks into a single block (never output two blocks or read one file per turn). Once you emit the closing fence of that single block, end your message immediately — never anticipate or simulate command output, never continue reasoning after the block, and wait for the user to reply with `[<session>/<step>]` results before taking the next step.
2. COLUMN-0 FENCES & SEPARATE-LINE HEREDOC TERMINATOR: Leave an empty line before the opening `powershell` fence. Start the opening fence, `@'`, `'@ | {cmd:run_block} ...`, and the closing fence at column 0, each on its own separate line.
3. NO INNER TRIPLE BACKTICKS, HEREDOC DELIMITERS, OR PAIRED `$ ... $` IN MULTILINE LITERALS: Never write three consecutive backticks (even inside `old`/`new` Markdown replacement anchors — anchor on surrounding non-fence lines, or construct via `chr(96) * 3`) or `'@` at column 0 inside the script body. Also avoid placing two `$` characters on the same line inside multiline string literals (chat renderers can treat `$ ... $` as inline math; use `chr(36)` or separate lines).
4. ISOLATED SHELL: Each block runs in a fresh `pwsh` process in `Workdir` (`cd` and shell variables do not persist across blocks).

### Session & Step Numbering (`<session>/<step>`) & `--fix`

- Sequential steps: Start from `Next-Block: <session>/<step>` in the header (`s1/1`) and increment after each `[<session>/<step>]` result (`s1/2`, `s1/3`, ...). Every executed block consumes its step number; never reuse or skip a number, and never re-emit an unexecuted block if the script did not change. If a step is interactively renumbered (recorded in step output as `[<session>/<new>] Note: renumbered from <session>/<old> to <session>/<new>...`), trust the executed `<session>/<new>` step number and continue sequentially from `<new+1>`. Pipe a bundle to `stdin` (`<bundle_cmd> | {cmd:run_block}`) to initialize a new session (`<session>/0`, with `i(nfo)` and `--bundle-plan [<session>] [--json] [--full]` for part/warning inspection); when `RUN_BLOCK_CWD` is `auto`, an existing `Workdir: <dir>` preamble header is preferred over the current directory.
- Use `--fix <session>/<target>` for small, targeted patches on failure: When a block fails and prior commands were idempotent (read-only checks, parser check, or atomic in-memory checks before `.write_text()`), use `{cmd:run_block} --fix <session>/<target>` to apply a small, targeted patch to `text` in Python (`text` and `re` are preloaded; `import`, `_` attributes, and file I/O are forbidden). If the fix is comparable in size to the original block or requires rewriting multiple sections, emit a fresh `<session>/<step+1>` block directly instead:

```powershell
@'
old = 'wrong_command'
new = 'right_command'
assert text.count(old) == 1
text = text.replace(old, new, 1)
'@ | {cmd:run_block} --fix s1/1
```
- Fix chaining & 2-attempt limit: Each `--fix` call allocates the next slot (`s1/1_1`, `s1/1_2`, ...). When chaining fixes, target the latest executed script (`s1/1_1`) or the base step (`s1/1`). After at most 2 consecutive failed `--fix` attempts on a step (or when `STOP --fix` is printed), stop calling `--fix` on that step and emit a fresh `<session>/<step+1>` block instead.
