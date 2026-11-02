"""Static guards for loading and preferring private pinned-app icons."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()


def function(name):
    match = re.search(r"  function " + name + r"\([^\n]*\) \{(.*?)\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"missing function {name}")
    return match.group(1)


def file_view(name):
    match = re.search(r"  FileView \{\s*id: " + name + r"\b(.*?)\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"missing FileView {name}")
    return match.group(1)


def app_menu():
    start = SOURCE.index("      id: menu", SOURCE.index("component AppButton:"))
    end = SOURCE.index("  // A row of the window list:", start)
    return SOURCE[start:end]


class CustomIconsTest(unittest.TestCase):
    def test_private_icon_map_uses_config_home_and_reloads_on_change(self):
        self.assertIn(
            'readonly property string iconsMapPath: configHome + "/omarchy-taskbar/pinned-icons.json"',
            SOURCE,
        )
        self.assertIn(
            'readonly property string iconsDirectory: configHome + "/omarchy-taskbar/icons"',
            SOURCE,
        )
        self.assertIn("property var customIcons: ({})", SOURCE)
        loader = file_view("iconsFile")
        self.assertIn("path: root.iconsMapPath", loader)
        self.assertIn("watchChanges: true", loader)
        self.assertIn("printErrors: false", loader)
        self.assertIn("onFileChanged: reload()", loader)
        self.assertNotIn("Timer", loader)

    def test_loader_defaults_to_empty_and_accepts_only_safe_private_paths(self):
        loader = file_view("iconsFile")
        self.assertIn("JSON.parse(text())", loader)
        self.assertIn('typeof parsed === "object"', loader)
        self.assertIn("!Array.isArray(parsed)", loader)
        self.assertIn('typeof value !== "string"', loader)
        self.assertRegex(loader, r"\^\[0-9a-f\]\{16\}-\[A-Za-z0-9\]\{6\}\\\.png\$")
        self.assertIn('var path = root.iconsDirectory + "/" + value', loader)
        self.assertIn('path.indexOf(root.iconsDirectory + "/") !== 0', loader)
        self.assertGreaterEqual(loader.count("root.customIcons = ({})"), 2)
        self.assertIn("onLoadFailed: root.customIcons = ({})", loader)

    def test_custom_icon_precedes_existing_resolution_as_file_url(self):
        resolver = function("iconFor")
        custom = "var custom = root.customIcons[app.key]"
        fallback = "var found = root.fallbacks[app.lookup]"
        self.assertIn(custom, resolver)
        self.assertIn('if (typeof custom === "string" && custom !== "") return Util.fileUrl(custom)', resolver)
        self.assertIn(fallback, resolver)
        self.assertLess(resolver.index(custom), resolver.index(fallback))

    def test_icon_map_reloads_only_after_successful_icon_changes(self):
        collector = re.search(
            r"id: pinChangeProc\b.*?stdout:\s*StdioCollector\s*\{(.*?)\n\s*\}\n\s*onExited:",
            SOURCE,
            re.S,
        )
        self.assertIsNotNone(collector)
        body = collector.group(1)
        self.assertRegex(body, r'operation === "icon"\s*\|\|\s*operation === "unicon"')
        self.assertRegex(body, r'result === "ok"[^\n]*iconsFile\.reload\(\)')

    def test_stdout_uses_captured_operation_and_scopes_complete_icon_errors(self):
        process = re.search(
            r"Process\s*\{\s*id: pinChangeProc\b(.*?)\n\s*\}\n\n", SOURCE, re.S
        )
        self.assertIsNotNone(process)
        body = process.group(1)
        queue = function("queuePinChange")
        start = function("nextPinChange")
        finish = function("finishPinChange")
        self.assertIn("if (!pinChangeProc.busy) nextPinChange()", queue)
        self.assertIn("pinChangeProc.operation = change.operation", start)
        self.assertIn("pinChangeProc.value = change.value", start)
        self.assertIn("pinChangeProc.path = change.path", start)
        self.assertIn("pinChangeProc.busy = true", start)
        self.assertIn("if (!pinChangeProc.exitSeen || !pinChangeProc.streamSeen) return", finish)
        self.assertIn("pinChangeProc.busy = false", finish)
        self.assertIn("nextPinChange()", finish)
        self.assertIn("var operation = pinChangeProc.operation", body)
        self.assertNotIn("pinChangeProc.change", body)
        self.assertRegex(body, r"split\(/\\r\?\\n/,\s*1\)\[0\]\.trim\(\)")
        self.assertRegex(
            body,
            r'var iconOperation = operation === "icon"\s*\|\|\s*operation === "unicon"',
        )
        self.assertIn(
            "var error = iconOperation ? /^error:([A-Za-z0-9_-]+)$/.exec(result) : null",
            body,
        )
        self.assertIn("pinChangeProc.streamSeen = true", body)
        self.assertIn("pinChangeProc.exitSeen = true", body)
        self.assertGreaterEqual(body.count("root.finishPinChange()"), 2)

    def test_pinned_app_menu_shows_only_applicable_icon_actions(self):
        menu = app_menu()
        self.assertIn('text: root.t("Change icon…", "Cambiar icono…")', menu)
        self.assertIn("shown: root.isPinned(button.app.key)", menu)
        self.assertIn('text: root.t("Restore icon", "Restaurar icono")', menu)
        self.assertIn(
            'shown: typeof root.customIcons[button.app.key] === "string"', menu
        )
        menu_row = SOURCE[SOURCE.index("  component MenuRow:") :]
        self.assertGreaterEqual(menu_row.count("textFormat: Text.PlainText"), 2)

    def test_icon_actions_run_before_the_popup_closes_without_a_shell(self):
        menu = app_menu()
        change = re.search(
            r'text: root\.t\("Change icon…".*?onTriggered:\s*\{(.*?)\}',
            menu,
            re.S,
        )
        restore = re.search(
            r'text: root\.t\("Restore icon".*?onTriggered:\s*\{(.*?)\}',
            menu,
            re.S,
        )
        self.assertIsNotNone(change)
        self.assertIsNotNone(restore)
        self.assertLess(
            change.group(1).index("iconFileDialog.appKey = button.app.key"),
            change.group(1).index("iconFileDialog.open()"),
        )
        self.assertLess(
            change.group(1).index("iconFileDialog.open()"),
            change.group(1).index("root.closeMenu()"),
        )
        self.assertLess(
            restore.group(1).index('root.queuePinChange("unicon", button.app.key, "")'),
            restore.group(1).index("root.closeMenu()"),
        )
        for forbidden in ("Process", "execDetached", "bash", "zenity"):
            self.assertNotIn(forbidden, change.group(1) + restore.group(1))

    def test_root_file_dialog_captures_the_app_key_without_closing_other_menus(self):
        self.assertIn("import QtQuick.Dialogs", SOURCE)
        self.assertIn("import QtCore", SOURCE)
        self.assertEqual(SOURCE.count("FileDialog {"), 1)
        dialog = re.search(r"  FileDialog \{\s*id: iconFileDialog\b(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(dialog)
        body = dialog.group(1)
        for extension in ("*.png", "*.svg", "*.ico", "*.exe"):
            self.assertIn(extension, body)
        self.assertIn(
            "currentFolder: StandardPaths.writableLocation(StandardPaths.PicturesLocation)",
            body,
        )
        self.assertIn('property string appKey: ""', body)
        self.assertIn("var path = root.droppedPath(selectedFile)", body)
        self.assertIn('root.queuePinChange("icon", appKey, path)', body)
        self.assertNotIn("button.app.key", body)
        self.assertNotIn("root.closeMenu()", body)
        self.assertNotIn("onRejected:", body)

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_file_url_conversion_accepts_only_safe_decoded_local_paths(self):
        converter = "function droppedPath(url) {" + function("droppedPath") + "\n}"
        values = [
            "file:///home/user/icon%20one.png",
            "file:///home/user/a+icon.svg",
            "https://example.test/icon.png",
            "file://server/share/icon.png",
            "file:///",
            "file:///tmp/bad%0Aicon.png",
            "file:///tmp/bad%0Dicon.png",
            "file:///tmp/bad%00icon.png",
            "file:///tmp/bad%1Bicon.png",
            "file:///tmp/bad%09icon.png",
            "file:///tmp/bad%7Ficon.png",
            "file:///tmp/%ZZ.png",
            "",
        ]
        code = (
            converter
            + "\nconsole.log(JSON.stringify("
            + json.dumps(values)
            + ".map(droppedPath)));"
        )
        result = subprocess.run(  # noqa: S603
            [shutil.which("node"), "-e", code],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [
                "/home/user/icon one.png",
                "/home/user/a+icon.svg",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
            ],
        )


if __name__ == "__main__":
    unittest.main()
