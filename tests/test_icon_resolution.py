"""Guard Omarchy's icon resolution order and run the embedded filesystem scan."""
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from extract_shell import scripts

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()


def function(name):
    match = re.search(r"  function " + name + r"\([^\n]*\) \{(.*?)\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"missing function {name}")
    return match.group(1)


def block(kind, name):
    match = re.search(kind + r" \{\s*id: " + name + r"\b(.*?)\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"missing {kind} {name}")
    return match.group(1)


class IconResolutionTest(unittest.TestCase):
    def test_resolver_uses_omarchy_order_and_encoded_file_urls(self):
        resolver = function("iconSource")
        steps = [
            'if (value.length === 0) return Quickshell.iconPath("application-x-executable", true)',
            'if (value.indexOf("file://") === 0 || value.indexOf("image://") === 0) return value',
            'if (value.charAt(0) === "/") return Util.fileUrl(value)',
            'var found = root.iconIndex[value]',
            'if (found) return Util.fileUrl(found)',
            'var themed = Quickshell.iconPath(value, true)',
            'if (themed.length > 0) return themed',
            'return Quickshell.iconPath("application-x-executable", true)',
        ]
        # Find each step after the preceding one (the generic fallback occurs twice).
        offset = 0
        for step in steps:
            with self.subTest(step=step):
                offset = resolver.index(step, offset) + len(step)
        self.assertIn('import qs.Commons\n', SOURCE)
        code = "\n".join(line for line in SOURCE.splitlines() if not line.lstrip().startswith("//"))
        self.assertNotIn("shell.appLibrary", code)

    def test_entry_and_window_fallbacks_share_the_resolver(self):
        resolver = function("iconFor")
        self.assertIn('var found = root.fallbacks[app.lookup]', resolver)
        self.assertIn('app.entry && app.entry.icon ? app.entry.icon : (found && found.icon) || own', resolver)
        self.assertIn('if (!app.entry && app.lookup !== "") Qt.callLater(root.lookupIcon, app.lookup)', resolver)
        self.assertIn('return root.iconSource(name)', resolver)
        self.assertNotIn('Quickshell.iconPath', resolver)
        self.assertIn('app.appId.toLowerCase()', resolver)
        self.assertIn('String(app.exe || "").split("/").pop()', resolver)

    def test_index_keeps_first_basename_and_swaps_only_after_scan(self):
        parser = function("indexIconLine")
        self.assertIn('value.lastIndexOf("/")', parser)
        self.assertIn('file.lastIndexOf(".")', parser)
        self.assertIn('root.pendingIconIndex[name] === undefined', parser)
        self.assertIn('root.pendingIconIndex[name] = value', parser)
        scan = block("Process", "iconIndexScan")
        self.assertIn('stdout: SplitParser { onRead: function(line) { root.indexIconLine(line) } }', scan)
        self.assertIn('onStarted: root.pendingIconIndex = ({})', scan)
        self.assertIn('onExited: root.iconIndex = root.pendingIconIndex', scan)
        self.assertEqual(SOURCE.count('root.iconIndex ='), 1)

    def test_scan_starts_once_and_app_changes_are_debounced_without_polling(self):
        self.assertIn('Component.onCompleted: root.refreshIcons()', SOURCE)
        self.assertIn('if (!iconIndexScan.running) iconIndexScan.running = true', function("refreshIcons"))
        timer = block("Timer", "iconIndexDebounce")
        self.assertIn('interval: 750', timer)
        self.assertIn('onTriggered: root.refreshIcons()', timer)
        self.assertNotIn('repeat:', timer)
        self.assertNotIn('running:', timer)
        self.assertRegex(SOURCE, r'Connections \{\s*target: DesktopEntries.applications\s*'
                         r'function onValuesChanged\(\) \{ iconIndexDebounce.restart\(\) \}')
        scan = block("Process", "iconIndexScan")
        self.assertIn('command: ["bash", "-c",', scan)
        self.assertIn('Quickshell.env("HOME"), Quickshell.env("XDG_DATA_DIRS") || "/usr/local/share:/usr/share", "/usr/share/pixmaps"', scan)


class IconScanTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="taskbar-icons-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        # Spaces and shell syntax must remain literal positional data.
        self.home = self.base / "home ' $(touch INJECTED) `touch INJECTED`"
        self.data_dirs = [self.base / "local share", self.base / "system share"]
        self.pixmaps = self.base / "pixmaps"
        self.pixmaps.mkdir()
        self.roots = [self.home / ".icons", self.home / ".local/share/icons"]
        self.roots += [path / "icons" for path in self.data_dirs]
        self.script, = [script for _, script in scripts(block("Process", "iconIndexScan"))]

    def icon(self, root, relative):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return str(path)

    def scan(self):
        result = subprocess.run(
            ["bash", "-c", self.script, "omarchy-taskbar", str(self.home),
             ":".join(map(str, self.data_dirs)), str(self.pixmaps)],
            cwd=self.base, env=dict(os.environ, HOME=str(self.base / "unused")),
            text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertFalse((self.base / "INJECTED").exists())
        return result.stdout.splitlines()

    def test_dirs_contexts_extensions_and_flat_pixmaps_match_omarchy(self):
        expected = set()
        for i, root in enumerate(self.roots):
            expected.add(self.icon(root, f"hicolor/scalable/apps/app{i}.svg"))
            expected.add(self.icon(root, f"hicolor/48x48/devices/device{i}.png"))
            for relative in ("hicolor/scalable/actions/zoom.svg", "hicolor/status/status.png",
                             "loose.svg", "hicolor/apps/ignored.xpm", "hicolor/apps/upper.SVG"):
                self.icon(root, relative)
        expected.add(self.icon(self.pixmaps, "pixmap.svg"))
        expected.add(self.icon(self.pixmaps, "pixmap.png"))
        self.icon(self.pixmaps, "nested/ignored.svg")
        self.icon(self.pixmaps, "ignored.xpm")
        self.assertEqual(set(self.scan()), expected)

    def test_svg_before_png_and_first_hit_directory_precedence(self):
        png = self.icon(self.roots[0], "hicolor/48x48/apps/shared.png")
        svg = self.icon(self.roots[-1], "hicolor/scalable/apps/shared.svg")
        for root in self.roots:
            self.icon(root, "hicolor/scalable/apps/ordered.svg")
        pixmap = self.icon(self.pixmaps, "ordered.svg")
        lines = self.scan()
        self.assertLess(lines.index(svg), lines.index(png))
        ordered = [str(root / "hicolor/scalable/apps/ordered.svg") for root in self.roots]
        self.assertEqual([line for line in lines if Path(line).name == "ordered.svg"], ordered + [pixmap])
        # Apply the same first-basename rule guarded above.
        index = {}
        for line in lines:
            index.setdefault(Path(line).stem, line)
        self.assertEqual(index["shared"], svg)
        self.assertEqual(index["ordered"], ordered[0])

    def test_rescan_sees_changes_without_a_theme_cache_and_missing_dirs_are_quiet(self):
        self.assertEqual(self.scan(), [])
        old = Path(self.icon(self.roots[0], "hicolor/apps/old.svg"))
        self.assertEqual(self.scan(), [str(old)])
        old.unlink()
        new = self.icon(self.roots[1], "hicolor/apps/new.png")
        self.assertEqual(self.scan(), [new])


if __name__ == "__main__":
    unittest.main()
