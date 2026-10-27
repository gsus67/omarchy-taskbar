"""Run the file-pin script against fake files in an isolated home."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin/pin-file.sh"
BASH = shutil.which("bash")
DESKTOP = "[Desktop Entry]\nType=Application\nName=Example\nExec=/bin/true\nIcon=example\n"


class FilePinTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="taskbar-test-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.home = self.base / "home"
        self.applications = self.home / ".local/share/applications"
        self.icons = self.home / ".local/share/icons/hicolor/256x256/apps"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        # Exclude optional icon tools by default, regardless of the host.
        for name in ("readlink", "jq", "sha256sum", "mkdir", "mktemp", "cp", "mv", "chmod", "rm", "bash"):
            target = shutil.which(name)
            self.assertIsNotNone(target, name)
            (self.bin / name).symlink_to(target)
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin),
                        XDG_DATA_HOME=str(self.home / ".local/share"),
                        XDG_DATA_DIRS=str(self.base / "system"), TMPDIR=str(self.base))

    def run_script(self, operation, value, known=()):
        result = subprocess.run([BASH, str(SCRIPT), operation,
                                 str(value), json.dumps(known)], env=self.env,
                                cwd=self.base, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.removesuffix("\n")

    def file(self, name, contents="", executable=False, parent=None):
        path = (parent or self.base) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
        if executable:
            path.chmod(0o755)
        return path

    def entry(self, key):
        return self.applications / (key + ".desktop")

    def test_exec_argument_escaping(self):
        cases = [
            ("a b'c;()&<>|*?#~", "a b'c;()&<>|*?#~"),
            ('a"b', r'a\\"b'),
            ("a`b", r"a\\`b"),
            ("a$b", r"a\\$b"),
            ("a\\b", r"a\\\\b"),
            ("café 日本語", "café 日本語"),
        ]
        for value, expected in cases:
            with self.subTest(value=value):
                path = self.file(value + ".exe")
                key = self.run_script("add", path)
                self.assertIn(f'Exec=xdg-open "{self.base}/{expected}.exe"\n',
                              self.entry(key).read_text())

    def test_windows_files_use_default_handler_without_execute_permission(self):
        for name in ("Game.exe", "Setup.MSI"):
            with self.subTest(name=name):
                path = self.file(name)
                key = self.run_script("add", path)
                digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
                self.assertEqual(key, "omarchy-taskbar-" + digest)
                text = self.entry(key).read_text()
                self.assertIn(f'Exec=xdg-open "{path}"\n', text)
                self.assertIn(f'Name={path.stem}\n', text)
                self.assertIn("Icon=application-x-executable\n", text)
                self.assertEqual(self.run_script("add", path), key)
        self.assertEqual(len(list(self.applications.glob("*.desktop"))), 2)
        self.assertFalse(self.icons.exists())

    def test_executable_and_appimage_run_directly(self):
        for name in ("program", "Program.AppImage"):
            with self.subTest(name=name):
                path = self.file(name, executable=True)
                key = self.run_script("add", path)
                self.assertIn(f'Exec="{path}"\n', self.entry(key).read_text())

    def test_hostile_filename_stays_data_in_exec_and_name(self):
        name = 'a "quote" `touch injected` $(touch injected) \\.exe'
        path = self.file(name)
        key = self.run_script("add", path)
        text = self.entry(key).read_text()
        expected = (str(self.base) + '/a \\\\"quote\\\\" \\\\`touch injected\\\\` '
                    '\\\\$(touch injected) \\\\\\\\.exe')
        self.assertIn('Exec=xdg-open "' + expected + '"\n', text)
        self.assertIn(r'Name=a\s"quote"\s`touch\sinjected`\s$(touch\sinjected)\s\\' + '\n', text)
        self.assertFalse((self.base / "injected").exists())

    @unittest.skipUnless(shutil.which("gio"), "GIO is needed for a real desktop launch")
    def test_desktop_launcher_preserves_the_actual_argument(self):
        name = 'a "quote" `literal` $literal \\.exe'
        path = self.file(name)
        result_path = self.base / "launch-result"
        self.file("xdg-open", "#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$LAUNCH_RESULT\"\n",
                  executable=True, parent=self.bin)
        key = self.run_script("add", path)
        env = dict(self.env, LAUNCH_RESULT=str(result_path),
                   DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(self.base / "no-bus"))
        result = subprocess.run([shutil.which("gio"), "launch", str(self.entry(key))],
                                env=env, cwd=self.base, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 2
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(result_path.read_text(), str(path) + "\n")

    @unittest.skipUnless(shutil.which("gio"), "GIO is needed for a real desktop launch")
    def test_desktop_launcher_runs_the_exact_executable(self):
        name = 'a="quote" `literal` $literal \\.AppImage'
        path = self.file(name, "#!/bin/bash\nprintf '%s\\n' \"$0\" > \"$LAUNCH_RESULT\"\n",
                         executable=True)
        result_path = self.base / "launch-result"
        key = self.run_script("add", path)
        env = dict(self.env, LAUNCH_RESULT=str(result_path),
                   DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(self.base / "no-bus"))
        result = subprocess.run([shutil.which("gio"), "launch", str(self.entry(key))],
                                env=env, cwd=self.base, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 2
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(result_path.read_text(), str(path) + "\n")

    def test_known_desktop_id_including_nested_directories(self):
        for parent, name, key in ((self.applications, "app.desktop", "app"),
                                  (self.base / "system/applications/vendor", "app.desktop", "vendor-app")):
            with self.subTest(key=key):
                path = self.file(name, DESKTOP, parent=parent)
                before = set(self.applications.glob("*"))
                self.assertEqual(self.run_script("add", path, [key]), key)
                self.assertEqual(set(self.applications.glob("*")), before)
                self.assertEqual(path.read_text(), DESKTOP)

    def test_external_desktop_is_copied_and_its_copy_is_reused(self):
        path = self.file("external.desktop", DESKTOP)
        key = self.run_script("add", path)
        self.assertRegex(key, r"^omarchy-taskbar-[0-9a-f]{16}$")
        self.assertEqual(self.entry(key).read_text(), DESKTOP)
        self.assertEqual(self.run_script("add", self.entry(key), [key]), key)
        self.run_script("remove", key)
        self.assertFalse(self.entry(key).exists())
        self.assertTrue(path.exists())

    def test_only_desktop_ids_known_to_desktop_entries_are_reused(self):
        path = self.file("unknown.desktop", DESKTOP, parent=self.applications)
        key = self.run_script("add", path)
        self.assertNotEqual(key, "unknown")
        self.assertEqual(self.entry(key).read_text(), DESKTOP)

    def test_unsupported_and_unsafe_paths_are_silently_ignored(self):
        paths = [self.base, self.base / "missing.exe", "relative.exe",
                 self.file("notes.txt"), self.file("Program.AppImage"),
                 self.file("newline\nExec=bad.exe"), self.file("tab\t.exe"),
                 self.file("control\x01.exe"), self.file("control\x7f.exe"),
                 self.file("control\x85.exe")]
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.run_script("add", path), "")
        self.assertFalse(self.applications.exists())

    def test_symlink_to_unsafe_path_is_rejected(self):
        for index, name in enumerate(("control\n.exe", "control.exe\n", "control\x85.exe")):
            path = self.file(name)
            link = self.base / f"safe{index}.exe"
            link.symlink_to(path)
            self.assertEqual(self.run_script("add", link), "")
        self.assertFalse(self.applications.exists())

    def test_percent_paths_are_rejected_before_and_after_resolving_links(self):
        for name in ("100%.exe", "100%.msi", "100%.desktop", "100%.AppImage"):
            with self.subTest(name=name):
                path = self.file(name, executable=True)
                link = self.base / "safe-name"
                link.symlink_to(path)
                self.assertEqual(self.run_script("add", path), "")
                self.assertEqual(self.run_script("add", link), "")
                link.unlink()
        path = self.file("Game.exe", parent=self.base / "100%")
        self.assertEqual(self.run_script("add", path), "")
        self.assertFalse(self.applications.exists())

    def test_unicode_paths_work_in_utf8_and_c_locales(self):
        path = self.file("日本語 café.exe")
        for locale in ("C", "C.UTF-8"):
            with self.subTest(locale=locale):
                self.env["LC_ALL"] = locale
                key = self.run_script("add", path)
                self.assertTrue(self.entry(key).is_file())

    def test_unpin_cleans_only_generated_entry_and_icon(self):
        key = self.run_script("add", self.file("Game.exe"))
        icon = self.file(key + ".png", "icon", parent=self.icons)
        original = self.file("original.desktop", DESKTOP, parent=self.applications)
        self.run_script("remove", key)
        self.assertFalse(self.entry(key).exists())
        self.assertFalse(icon.exists())
        for unsafe in ("original", "omarchy-taskbar-../../original", "../original",
                       "omarchy-taskbar-0123456789abcde", "omarchy-taskbar-0123456789abcdef0",
                       "omarchy-taskbar-0123456789abcdeg", "omarchy-taskbar-0123456789ABCDEF",
                       "omarchy-taskbar-0123456789abcdef.desktop", key + "\n"):
            self.assertEqual(self.run_script("remove", unsafe), "")
            if "/" not in unsafe:
                entry = self.file(unsafe + ".desktop", DESKTOP, parent=self.applications)
                icon = self.file(unsafe + ".png", "icon", parent=self.icons)
                self.run_script("remove", unsafe)
                self.assertTrue(entry.exists())
                self.assertTrue(icon.exists())
        self.assertTrue(original.exists())
        self.assertEqual(self.run_script("remove", key), "")

    def test_optional_icon_extraction_and_cleanup(self):
        # Stand-ins exercise the optional tools without requiring icoutils.
        self.file("wrestool", '#!/bin/bash\nprintf ico > "$5/group.ico"\n',
                  executable=True, parent=self.bin)
        self.file("icotool", '#!/bin/bash\nprintf png > "$3/icon.png"\n',
                  executable=True, parent=self.bin)
        key = self.run_script("add", self.file("Game.exe"))
        self.assertIn(f"Icon={self.icons / (key + '.png')}\n", self.entry(key).read_text())
        self.assertEqual((self.icons / (key + ".png")).read_text(), "png")
        self.run_script("remove", key)
        self.assertFalse(self.entry(key).exists())
        self.assertFalse((self.icons / (key + ".png")).exists())
        self.assertFalse(list(self.base.glob("tmp.*")))

    def test_failed_icon_extraction_uses_generic_icon(self):
        for name in ("wrestool", "icotool"):
            self.file(name, "#!/bin/bash\nexit 1\n", executable=True, parent=self.bin)
        key = self.run_script("add", self.file("Game.exe"))
        self.assertIn("Icon=application-x-executable\n", self.entry(key).read_text())
        self.assertFalse(self.icons.exists())
    def test_failed_file_operations_are_silent_and_remove_temporary_entries(self):
        path = self.file("Game.exe")
        self.file("applications", parent=self.applications.parent)
        self.assertEqual(self.run_script("add", path), "")
        self.applications.unlink()

        (self.bin / "mv").unlink()
        self.file("mv", "#!/bin/bash\nexit 1\n", executable=True, parent=self.bin)
        self.assertEqual(self.run_script("add", path), "")
        self.assertEqual(list(self.applications.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
