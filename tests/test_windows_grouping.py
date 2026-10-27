"""Execute the actual QML matching functions with desktop/window fixtures."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()


@unittest.skipUnless(shutil.which("node"), "Node is needed to run the QML JavaScript")
class WindowsGroupingTest(unittest.TestCase):
    def run_match(self, entries, name):
        functions = []
        for method in ("windowsEntryFor", "entryFor", "windowEntry", "keyFor"):
            match = re.search(r"  function " + method + r"\([^\n]*\) \{.*?\n  \}", SOURCE, re.S)
            self.assertIsNotNone(match)
            functions.append(match.group())
        code = "\n".join(functions) + '''
const entries = JSON.parse(process.argv[1]);
const appId = process.argv[2];
const DesktopEntries = {byId: id => entries.find(e => e.id === id), heuristicLookup: () => null};
const root = {pinned: entries.map(e => e.id), fallbacks: {}, windowsEntryFor,
              windowEntry, lookupFor: () => "@0x1234"};
function webAppEntry() { return null; }
function lookupFor() { return "@0x1234"; }
console.log(JSON.stringify({entry: (entryFor(appId) || {}).id || null,
                           key: keyFor({appId})}));
'''
        result = subprocess.run([shutil.which("node"), "-e", code, json.dumps(entries), name],
                                capture_output=True, text=True, check=True, timeout=5)
        return json.loads(result.stdout)

    def entry(self, digit="1", path="/games/Cities Skylines II/Cities2.exe", old=False):
        return {"id": "omarchy-taskbar-" + digit * 16,
                "command": ["xdg-open", path] if old else ["gio", "open", path]}

    def test_windows_class_joins_the_existing_pin_case_insensitively(self):
        for old in (False, True):
            entry = self.entry(old=old)
            result = self.run_match([entry], "CITIES2.EXE")
            self.assertEqual(result, {"entry": entry["id"], "key": entry["id"]})

    def test_other_games_and_generic_wine_do_not_borrow_the_pin(self):
        for name in ("Other.exe", "wine", "wine64", "Cities2", ""):
            self.assertIsNone(self.run_match([self.entry()], name)["entry"])

    def test_explicit_startup_class_is_supported(self):
        entry = dict(self.entry(), startupClass="CitiesWindow")
        self.assertEqual(self.run_match([entry], "CitiesWindow")["key"], entry["id"])

    def test_same_basename_at_different_paths_is_ambiguous(self):
        entries = [self.entry(), self.entry("2", "/other/Cities2.exe")]
        self.assertIsNone(self.run_match(entries, "Cities2.exe")["entry"])

    def test_unrelated_desktop_entries_are_not_treated_as_file_pins(self):
        entry = dict(self.entry(), command=["other-runner", "/games/Cities2.exe"])
        self.assertIsNone(self.run_match([entry], "Cities2.exe")["entry"])
