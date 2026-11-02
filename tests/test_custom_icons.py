"""Static guards for loading and preferring private pinned-app icons."""
import re
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


if __name__ == "__main__":
    unittest.main()
