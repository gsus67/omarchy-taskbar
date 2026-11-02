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

    def test_no_privilege_commands(self):
        for source in [SOURCE] + [path.read_text() for path in (ROOT / "bin").glob("*.sh")]:
            self.assertNotRegex(source, r"\b(?:s[u](?:do)?|pkex[e]c|do[a]s)\b")

    def test_bash_only_runs_literal_scripts_with_positional_data(self):
        for call in re.finditer(r'"bash",\s*', SOURCE):
            rest = SOURCE[call.end():]
            self.assertRegex(rest, r'^"-c",')

    def test_pin_icon_path_is_positional_data(self):
        self.assertRegex(SOURCE, r"function queuePinChange\(operation, value, path\)")
        command = re.search(
            r"id: pinChangeProc\b.*?command:\s*\[(.*?)\]\s*stdout:", SOURCE, re.S
        )
        self.assertIsNotNone(command)
        self.assertIn('case "$1" in icon)', command.group(1))
        self.assertIn('"$BASH" "$5" "$1" "$2" "$4"', command.group(1))
        self.assertIn('unicon) "$BASH" "$5" "$1" "$2" ""', command.group(1))
        self.assertIn('*) "$BASH" "$5" "$1" "$2" "$3"', command.group(1))
        arguments = command.group(1).split('"omarchy-taskbar",', 1)[1]
        self.assertRegex(
            arguments,
            r'^\s*operation,\s*value,\s*applicationIds,\s*path,\s*'
            r'root\.pluginDirectory \+ "/bin/pin-file\.sh"\s*$',
        )
        self.assertNotRegex(
            command.group(1),
            r'(?:["\'][^"\']*["\']\s*\+\s*(?:operation|value|applicationIds|path)\b|'
            r'(?:operation|value|applicationIds|path)\s*\+\s*["\'])',
        )

    def test_icon_errors_notify_with_an_argument_list_and_fixed_messages(self):
        notification = re.search(
            r'Quickshell\.execDetached\(\["notify-send",(.*?)\]\)', SOURCE, re.S
        )
        self.assertIsNotNone(notification)
        arguments = re.sub(r"\s+", " ", notification.group(1)).strip()
        self.assertEqual(
            arguments,
            'root.t("Icon change failed", "Error al cambiar el icono"), '
            "root.iconErrorMessage(code)",
        )
        self.assertRegex(SOURCE, r'default:\s*return root\.t\(')

    def test_icon_error_messages_cover_every_set_icon_failure_code(self):
        set_icon = (ROOT / "bin/set-icon.sh").read_text()
        failure_codes = set(
            re.findall(r"^\s*fail\s+([A-Za-z0-9_-]+)\s*$", set_icon, re.M)
        )
        message_function = re.search(
            r"function iconErrorMessage\([^\n]*\)\s*\{(.*?)\n\s*\}", SOURCE, re.S
        )
        self.assertTrue(failure_codes, "set-icon.sh has no literal fail codes")
        self.assertIsNotNone(message_function)
        message_codes = set(
            re.findall(r'case "([A-Za-z0-9_-]+)":', message_function.group(1))
        )
        self.assertEqual(set(), failure_codes - message_codes)

    def test_no_other_shells(self):
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
        for source in [SOURCE] + [path.read_text() for path in (ROOT / "bin").glob("*.sh")]:
            self.assertNotIn("/cmdline", source)
            self.assertNotIn("/environ", source)


if __name__ == "__main__":
    unittest.main()
