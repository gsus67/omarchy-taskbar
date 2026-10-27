"""Guards for bar size, hand-edited width and safe configuration writes."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from extract_shell import CALL, scripts

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()
SAVE_CONFIG = re.search(r"function saveConfig\(key, value\) \{(.*?)\n  \}", SOURCE, re.S)


class BarWidthTest(unittest.TestCase):
    def test_config_file_is_watched_and_writes_use_the_safe_script(self):
        match = re.search(r"FileView \{\s*id: configFile\b(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(match, "missing config FileView")
        block = match.group(1)
        self.assertIn('path: root.configHome + "/omarchy-taskbar/config.json"', block)
        self.assertIn("watchChanges: true", block)
        self.assertIn("printErrors: false", block)
        self.assertIn("onFileChanged: reload()", block)
        self.assertIn("JSON.parse(text())", block)
        self.assertNotRegex(SOURCE, r"configFile\.(setText|setData|writeAdapter)\s*\(")
        self.assertIsNotNone(SAVE_CONFIG, "missing config writer")
        writer = SAVE_CONFIG.group(1)
        self.assertIn("JSON.parse(configFile.text())", writer)
        self.assertIn('typeof parsed === "object" && !Array.isArray(parsed)', writer)
        self.assertIn("config = parsed", writer)
        self.assertIn("if (value === null) delete config[key]", writer)
        self.assertIn("else config[key] = value", writer)
        self.assertIn('Object.keys(config).length ? JSON.stringify(config, null, 2) : ""', writer)

    def test_config_script_is_literal_with_positional_data(self):
        self.assertIsNotNone(SAVE_CONFIG)
        writer = SAVE_CONFIG.group(1)
        call = CALL.search(writer)
        self.assertIsNotNone(call, "missing literal bash -c script")
        self.assertRegex(writer[call.end():], r'^,\s*"omarchy-taskbar", configFile\.path,')
        script = list(scripts(writer))[0][1]
        self.assertIn('mktemp -- "$1.XXXXXX"', script)
        self.assertIn('>"$tmp" && mv -f -- "$tmp" "$1"', script)
        self.assertNotIn('>"$1"', script)

    def test_config_script_replaces_atomically_and_removes_empty_config(self):
        self.assertIsNotNone(SAVE_CONFIG)
        script = list(scripts(SAVE_CONFIG.group(1)))[0][1]
        with tempfile.TemporaryDirectory(prefix="taskbar-config-") as directory:
            path = Path(directory) / 'config dir $(touch injected)' / 'config.json'
            data = json.dumps({"scale": 1.25, "width": "60%", "other": '$(touch injected) `touch injected` "quote"'})

            def run(value):
                result = subprocess.run(["bash", "-c", script, "omarchy-taskbar", str(path), value],
                                        cwd=directory, text=True, capture_output=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")

            run(data)
            self.assertEqual(path.read_text(), data + "\n")
            original_inode = path.stat().st_ino
            run('{"other": true}')
            self.assertNotEqual(path.stat().st_ino, original_inode)
            self.assertEqual(json.loads(path.read_text()), {"other": True})
            self.assertEqual(list(path.parent.iterdir()), [path])
            run("")
            run("")
            self.assertFalse(path.exists())
            self.assertFalse((Path(directory) / "injected").exists())

    def test_empty_space_menu_options_and_current_check(self):
        mouse = SOURCE[SOURCE.index("// Empty bar space:"):SOURCE.index("\n        Row {")]
        self.assertIn("onDoubleClicked:", mouse)
        self.assertIn("event.button === Qt.LeftButton) root.toggleTransparent()", mouse)
        self.assertIn("event.button === Qt.RightButton", mouse)
        self.assertIn("sizeMenu.anchor.rect.x = event.x", mouse)
        self.assertIn("sizeMenu.anchor.rect.y = event.y", mouse)
        self.assertIn("root.showMenu(sizeMenu)", mouse)
        menu = SOURCE[SOURCE.index("id: sizeMenu"):SOURCE.index("\n  component AppButton:")]
        self.assertIn("anchor.window: barWindow", menu)
        self.assertIn('model: [1, 1.25, 1.5, 2]', menu)
        self.assertIn('text: modelData + "x"', menu)
        self.assertIn("checkable: true", menu)
        self.assertIn("checked: root.configuredScale === modelData", menu)
        self.assertIn('root.saveConfig("scale", modelData === 1 ? null : modelData)', menu)
        self.assertNotIn("configuredWidth", menu)
        self.assertNotIn("saveWidth", SOURCE)
        self.assertIn("Keys.onEscapePressed: root.closeMenu()", menu)
        self.assertIn("Qt.callLater(function() { sizeGrab.active = sizeMenu.visible })", menu)
        self.assertIn("windows: [sizeMenu, barWindow]", menu)
        self.assertIn("onCleared: if (root.openMenu === sizeMenu) root.closeMenu()", menu)

    def test_check_mark_has_a_fixed_leading_column(self):
        row = SOURCE[SOURCE.index("component MenuRow:"):]
        self.assertIn("readonly property int checkWidth: checkable ? Style.space(20) : 0", row)
        self.assertIn("width: row.checkWidth", row)
        self.assertIn('text: row.checked ? "✓" : ""', row)
        self.assertIn("anchors.leftMargin: Style.space(12) + row.checkWidth", row)
        self.assertNotIn('"✓ "', SOURCE)
        self.assertNotIn('"    "', SOURCE)

    def test_scale_defaults_to_one_and_rejects_other_values(self):
        self.assertIn("property real configuredScale: 1", SOURCE)
        self.assertIn("function scaleFor(value) { return [1, 1.25, 1.5, 2].indexOf(value) !== -1 ? value : 1 }", SOURCE)
        self.assertIn("root.configuredScale = root.scaleFor(config && config.scale)", SOURCE)
        self.assertRegex(SOURCE, r"catch \(e\) \{\s*root.configuredWidth = null\s*root.configuredScale = 1")
        self.assertRegex(SOURCE, r"onLoadFailed: \{\s*root.configuredWidth = null\s*root.configuredScale = 1")

    def test_scale_multiplies_bar_height_and_icons(self):
        self.assertIn("readonly property int barSize: Math.round(Style.bar.sizeHorizontal * configuredScale)", SOURCE)
        self.assertIn("readonly property int iconSize: Math.round(barSize * 0.66)", SOURCE)
        self.assertIn("implicitHeight: root.barSize", SOURCE)

    def test_missing_or_invalid_config_resets_width(self):
        self.assertIn("property var configuredWidth: null", SOURCE)
        self.assertRegex(SOURCE, r"catch \(e\) \{\s*root.configuredWidth = null")
        self.assertRegex(SOURCE, r"onLoadFailed: \{\s*root.configuredWidth = null")

    def test_invalid_width_falls_back_to_full_screen(self):
        match = re.search(r"function widthFor\(value, screenWidth, barSize\) \{(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(match, "missing pure width function")
        self.assertIn("if (!isFinite(width)) return screenWidth", match.group(1))
        self.assertIn("root.widthFor(root.configuredWidth, modelData.width, root.barSize)", SOURCE)


if __name__ == "__main__":
    unittest.main()
