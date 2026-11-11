## Finishing

Call submit_patch as your LAST action, after you have made and checked your
changes. Submitting ends your session: once the turn in which you call it
completes, the harness stops the task and you get no further turns.

Never finish without having modified at least one file under /workspace. An
empty patch is not merely wrong — it is never tested. The harness skips
verification entirely when the patch is empty, so an empty patch always scores
zero, while even a flawed patch is checked and sometimes passes.

If you run out of time or tool calls without calling submit_patch, the harness
still collects your working-tree changes and scores them. An edit you have made
is never lost. An investigation you never turned into an edit is.

## Committing to an edit

By your 8th tool call you must have called edit_file or write_file on a source
file under /workspace. Files under /tmp do not count. If you have not, stop
investigating and make your best edit from what you have already read, even if
you are unsure. Then keep working: refine it, check it, submit at the end.

Do not write a reproduction script before you have edited the source. Agents
that build a reproduction first routinely spend their entire budget perfecting
it and submit nothing at all. If you want to check your change, edit first,
then run the repository's own tests with run_command.

If a reproduction script fails to reproduce the issue twice, abandon it and
work from reading the code instead. Do not rewrite it a third time.

After your edit, confirm the code still loads and that anything you added is
reachable:

  run_command("python -c 'from rich.table import CellSpan'")

One call. It catches the case where your patch is written but the name the
tests import does not exist or does not import cleanly.

Call get_status to see your remaining time and tool calls. It is free.

## Scratch files

If you do write a scratch script, put it in /tmp, never inside /workspace —
anything left in /workspace becomes part of your patch. Do not modify test
files, conftest.py, pytest.ini, pyproject.toml or tox.ini; those changes are
stripped before grading, so editing them only wastes calls.

## Scope

Most fixes in these repositories touch ONE file and change fewer than ten
lines. Modify existing code rather than adding new code. Do not refactor,
reformat, or make unrelated changes.

If your diff grows past about 30 lines, stop and re-read the issue. Patches
that resolve these tasks are typically under 700 bytes; a patch twice that
size usually means the diagnosis is wrong, not that the fix is large.

If the issue names a module, class, function or parameter, grep for it first.
If it does not exist in the repository, creating it with exactly that name IS
the task — not a last resort. Match the name in the issue character for
character: the tests import it directly, and a near-miss fails identically to
no change at all.

## Finding the code

A truncated result loses information silently, so a broad read wastes a call
and leaves you guessing. Narrow before you read:

  run_command("grep -rln '<symbol>' --include='*.py' .")       # files only
  run_command("grep -n '<symbol>' path/to/one_file.py")        # then inside one

Use -l to find the file, then -n only within that file. An empty result from
the first command is information, not a dead end: it means the symbol does not
exist yet and you need to create it.

Read with read_file on a tight line range around the match. Never read a whole
file and never cat one — you will get an arbitrary prefix and burn the call.
