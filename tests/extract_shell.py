"""Writes each `"bash", "-c", <script>` from Taskbar.qml to <dir>/N.sh for ShellCheck.

The scripts are QML string literals joined with `+`; they are rebuilt as the
shell will see them. Data (window classes, paths) must arrive as positional
arguments, which tests/test_shell_commands.py enforces.
"""
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CALL = re.compile(r'"bash",\s*"-c",\s*((?:\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*"|\s|\+)+)', re.S)
LITERAL = re.compile(r'\'(?:[^\'\\]|\\.)*\'|"(?:[^"\\]|\\.)*"', re.S)


def scripts(source):
    """Yield (line, script) for every bash -c call."""
    for match in CALL.finditer(source):
        parts = LITERAL.findall(match.group(1))
        # QML/JS string escapes match Python's for these literals.
        yield source.count("\n", 0, match.start()) + 1, "".join(ast.literal_eval(part) for part in parts)


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    found = list(scripts((ROOT / "Taskbar.qml").read_text()))
    for number, (line, script) in enumerate(found):
        (out / f"{number:02d}-line{line}.sh").write_text("#!/usr/bin/env bash\n" + script + "\n")
    print(f"{len(found)} scripts")
