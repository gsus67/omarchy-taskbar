"""Static guards for the optional, read-only bar width configuration."""
import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()


class BarWidthTest(unittest.TestCase):
    def test_config_file_is_watched_and_read_only(self):
        match = re.search(r"FileView \{\s*id: configFile\b(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(match, "missing config FileView")
        block = match.group(1)
        self.assertIn('path: root.configHome + "/omarchy-taskbar/config.json"', block)
        self.assertIn("watchChanges: true", block)
        self.assertIn("printErrors: false", block)
        self.assertIn("onFileChanged: reload()", block)
        self.assertIn("JSON.parse(text())", block)
        self.assertNotRegex(SOURCE, r"configFile\.(setText|setData|writeAdapter)\s*\(")

    def test_missing_or_invalid_config_resets_width(self):
        self.assertIn("property var configuredWidth: null", SOURCE)
        self.assertRegex(SOURCE, r"catch \(e\) \{\s*root.configuredWidth = null")
        self.assertIn("onLoadFailed: root.configuredWidth = null", SOURCE)

    def test_invalid_width_falls_back_to_full_screen(self):
        match = re.search(r"function widthFor\(value, screenWidth, barSize\) \{(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(match, "missing pure width function")
        self.assertIn("if (!isFinite(width)) return screenWidth", match.group(1))
        self.assertIn("root.widthFor(root.configuredWidth, modelData.width, root.barSize)", SOURCE)


if __name__ == "__main__":
    unittest.main()
