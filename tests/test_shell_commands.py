"""Guards for the commands the taskbar runs.

Window classes and titles come from any program, so they must never be pasted
into a shell script: every `bash -c` script is made only of string literals and
receives data as positional arguments ("$1", "$2"), after the fixed $0 name.
Other programs are started with an argument list, never through a shell.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "Taskbar.qml").read_text()
LITERALS = r"(?:'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\s|\+)+"


class ShellCommandTest(unittest.TestCase):
    def test_bash_scripts_are_literals_followed_by_the_fixed_name(self):
        calls = list(re.finditer(r'"bash",\s*"-c",', SOURCE))
        self.assertTrue(calls, "no bash -c calls found")
        for call in calls:
            rest = SOURCE[call.end():]
            # Literals only; then either the end of the list (no data) or the
            # fixed $0 name followed by the data as "$1", "$2"...
            match = re.match(LITERALS + r"(?:\]|,\s*\"omarchy-taskbar\")", rest, re.S)
            line = SOURCE.count("\n", 0, call.start()) + 1
            self.assertIsNotNone(match, f"line {line}: bash -c script must be literals only, data only after \"omarchy-taskbar\" ($0)")

    def test_no_shell_other_than_bash_c(self):
        for shell in ('"sh"', '"/bin/sh"', '"zsh"', '"eval"'):
            self.assertNotIn(shell, SOURCE)

    def test_programs_start_from_argument_lists(self):
        # execDetached and Process commands always take a JS array.
        for match in re.finditer(r"execDetached\(\s*([^\s])", SOURCE):
            self.assertEqual(match.group(1), "[", "execDetached must get an argument list")


    def test_focus_dispatch_only_takes_a_checked_hex_address(self):
        # The window address is placed inside a Hyprland Lua dispatch, so it
        # must be validated as hex right before it is used.
        dispatch = SOURCE.find('"hyprctl", "dispatch"')
        self.assertNotEqual(dispatch, -1)
        guard = SOURCE.rfind("/^0x[0-9a-fA-F]+$/.test(address)", 0, dispatch)
        self.assertNotEqual(guard, -1, "hyprctl dispatch without the hex address check")
        self.assertLess(dispatch - guard, 200, "the address check must sit right before the dispatch")


    def test_never_reads_command_lines(self):
        # Command lines can hold secrets (passwords passed to xfreerdp, tokens);
        # only process names and executable paths may be read.
        self.assertNotIn("/cmdline", SOURCE)
        self.assertNotIn("/environ", SOURCE)


if __name__ == "__main__":
    unittest.main()
