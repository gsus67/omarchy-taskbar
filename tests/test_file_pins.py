"""Run the file-pin script against fake files in an isolated home."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
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
        self.private_applications = self.applications / "omarchy-taskbar"
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
        return self.private_applications / (key.removeprefix("omarchy-taskbar-") + ".desktop")

    def legacy_entry(self, key):
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
                self.assertIn(f'Exec=gio open "{self.base}/{expected}.exe"\n',
                              self.entry(key).read_text())

    def test_windows_files_use_default_handler_without_execute_permission(self):
        for name in ("Game.exe", "Setup.MSI"):
            with self.subTest(name=name):
                path = self.file(name)
                key = self.run_script("add", path)
                digest = hashlib.sha256(str(path).encode()).hexdigest()[:16]
                self.assertEqual(key, "omarchy-taskbar-" + digest)
                text = self.entry(key).read_text()
                self.assertIn(f'Exec=gio open "{path}"\n', text)
                self.assertIn(f'Name={path.stem}\n', text)
                self.assertIn("Icon=application-x-executable\n", text)
                self.assertEqual(self.run_script("add", path), key)
        self.assertEqual(len(list(self.private_applications.glob("*.desktop"))), 2)
        self.assertFalse(self.icons.exists())
        for entry in self.private_applications.glob("*.desktop"):
            self.assertEqual(entry.stat().st_mode & 0o777, 0o600)

    def test_executable_and_appimage_run_directly(self):
        for name in ("program", "Program.AppImage"):
            with self.subTest(name=name):
                path = self.file(name, executable=True)
                key = self.run_script("add", path)
                self.assertIn(f'Exec="{path}"\n', self.entry(key).read_text())

    def test_existing_windows_pins_are_repaired_without_changing_other_fields(self):
        for name in ("Game.exe", "Setup.MSI"):
            with self.subTest(name=name):
                key = self.run_script("add", self.file(name))
                old = self.entry(key).read_text().replace("Exec=gio open ", "Exec=xdg-open ")
                self.entry(key).write_text(old)
                self.assertEqual(self.run_script("repair", key), "")
                expected = old.replace("Exec=xdg-open ", "Exec=gio open ")
                self.assertEqual(self.entry(key).read_text(), expected)
                before = self.entry(key).stat().st_mtime_ns
                self.run_script("repair", key)
                self.assertEqual(self.entry(key).stat().st_mtime_ns, before)
        self.assertFalse(list(self.applications.glob(".omarchy-taskbar-*")))

    def test_repair_does_not_touch_unrelated_launchers_or_symlinks(self):
        path = self.file("external.desktop", DESKTOP)
        key = self.run_script("add", path)
        self.run_script("repair", key)
        self.assertEqual(self.entry(key).read_text(), DESKTOP)
        self.entry(key).unlink()
        self.entry(key).symlink_to(path)
        self.run_script("repair", key)
        self.assertTrue(self.entry(key).is_symlink())
        self.assertEqual(path.read_text(), DESKTOP)
        self.run_script("repair", "../../external")

    @unittest.skipUnless(shutil.which("gio"), "GIO is needed for a real desktop launch")
    def test_real_default_handler_with_quoted_runner_path(self):
        path = self.file('Game with spaces.exe', "MZ" + "\x00" * 128)
        result_path = self.base / "launch-result"
        runner = self.file("runner with spaces", '#!/bin/bash\nprintf "%s\\n" "$@" > "$LAUNCH_RESULT"\n')
        key = self.run_script("add", path)
        self.file("handler.desktop", '[Desktop Entry]\nType=Application\nName=Test handler\n'
                  f'Exec={BASH} "{runner}" %f\nNoDisplay=true\n', parent=self.applications)
        config = self.base / "config"
        config.mkdir()
        (config / "mimeapps.list").write_text("[Default Applications]\n" + "".join(
            f"{mime}=handler.desktop;\n" for mime in (
                "application/x-ms-dos-executable", "application/vnd.microsoft.portable-executable",
                "application/x-msdownload", "application/octet-stream")))
        (self.bin / "gio").symlink_to(shutil.which("gio"))
        env = dict(self.env, XDG_CONFIG_HOME=str(config), LAUNCH_RESULT=str(result_path),
                   XDG_CURRENT_DESKTOP="", DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(self.base / "no-bus"))
        result = subprocess.run([shutil.which("gio"), "launch", str(self.entry(key))],
                                env=env, cwd=self.base, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        deadline = time.monotonic() + 3
        while not result_path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(result_path.exists(), "Default handler did not run")
        self.assertEqual(result_path.read_text(), str(path) + "\n")

    def test_hostile_filename_stays_data_in_exec_and_name(self):
        name = 'a "quote" `touch injected` $(touch injected) \\.exe'
        path = self.file(name)
        key = self.run_script("add", path)
        text = self.entry(key).read_text()
        expected = (str(self.base) + '/a \\\\"quote\\\\" \\\\`touch injected\\\\` '
                    '\\\\$(touch injected) \\\\\\\\.exe')
        self.assertIn('Exec=gio open "' + expected + '"\n', text)
        self.assertIn(r'Name=a\s"quote"\s`touch\sinjected`\s$(touch\sinjected)\s\\' + '\n', text)
        self.assertFalse((self.base / "injected").exists())

    @unittest.skipUnless(shutil.which("gio"), "GIO is needed for a real desktop launch")
    def test_desktop_launcher_preserves_the_actual_argument(self):
        name = 'a "quote" `literal` $literal \\.exe'
        path = self.file(name)
        result_path = self.base / "launch-result"
        self.file("gio", "#!/bin/bash\nprintf '%s\\n' \"$@\" > \"$LAUNCH_RESULT\"\n",
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
        self.assertEqual(result_path.read_text(), "open\n" + str(path) + "\n")

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

    def test_private_external_desktop_stays_private_when_copied(self):
        sentinel = "REMOTE_PASSWORD=sentinel-secret"
        path = self.file("private.desktop", DESKTOP.replace("Exec=/bin/true", "Exec=/bin/true " + sentinel))
        path.chmod(0o600)
        key = self.run_script("add", path)
        imported = self.entry(key)
        self.assertEqual(imported.read_text(), path.read_text())
        self.assertIn(sentinel, imported.read_text())
        self.assertEqual(imported.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.private_applications.stat().st_mode & 0o777, 0o700)

    def test_repair_preserves_restrictive_launcher_permissions(self):
        path = self.file("Game.exe")
        key = self.run_script("add", path)
        entry = self.entry(key)
        entry.write_text(entry.read_text().replace("Exec=gio open ", "Exec=xdg-open "))
        entry.chmod(0o600)
        self.private_applications.chmod(0o755)
        self.assertEqual(self.run_script("repair", key), "")
        self.assertIn("Exec=gio open ", entry.read_text())
        self.assertEqual(entry.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.private_applications.stat().st_mode & 0o777, 0o700)

    def test_legacy_launcher_is_migrated_into_private_directory_on_repair(self):
        path = self.file("Game.exe")
        key = self.run_script("add", path)
        private_entry = self.entry(key)
        legacy = self.legacy_entry(key)
        legacy.write_text(private_entry.read_text().replace("Exec=gio open ", "Exec=xdg-open "))
        legacy.chmod(0o644)
        private_entry.unlink()

        self.assertEqual(self.run_script("repair", key), "")
        self.assertFalse(legacy.exists())
        self.assertIn("Exec=gio open ", private_entry.read_text())
        self.assertEqual(private_entry.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.private_applications.stat().st_mode & 0o777, 0o700)

    def test_repair_preserves_owner_read_only_legacy_launchers(self):
        key = "omarchy-taskbar-0123456789abcdef"
        old = DESKTOP.replace("Exec=/bin/true", 'Exec=xdg-open "/tmp/Game.exe"')
        legacy = self.file(key + ".desktop", old, parent=self.applications)
        legacy.chmod(0o400)
        self.run_script("repair", key)
        self.assertFalse(legacy.exists())
        self.assertEqual(self.entry(key).stat().st_mode & 0o777, 0o400)
        self.assertIn('Exec=gio open "/tmp/Game.exe"', self.entry(key).read_text())

    def test_repinning_legacy_source_keeps_one_desktop_id(self):
        path = self.file("external.desktop", DESKTOP)
        key = "omarchy-taskbar-" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        legacy = self.file(key + ".desktop", DESKTOP, parent=self.applications)
        self.assertEqual(self.run_script("add", path, [key]), key)
        self.assertFalse(legacy.exists())
        self.assertEqual(self.entry(key).read_text(), DESKTOP)
        self.assertEqual(self.entry(key).stat().st_mode & 0o777, 0o600)

    def test_conflicting_legacy_launcher_stays_private_without_overwriting_either_copy(self):
        path = self.file("Game.exe")
        key = self.run_script("add", path)
        current = self.entry(key).read_text()
        sentinel = "REMOTE_PASSWORD=conflict-sentinel-secret"
        old = DESKTOP.replace("Exec=/bin/true", "Exec=/bin/true " + sentinel)
        legacy = self.file(key + ".desktop", old, parent=self.applications)
        for operation, argument in (("add", path), ("repair", key)):
            for mode in (0o644, 0o640, 0o444, 0o600, 0o400):
                with self.subTest(operation=operation, mode=oct(mode)):
                    legacy.chmod(mode)
                    self.assertEqual(self.run_script(operation, argument), "")
                    self.assertEqual(legacy.read_text(), old)
                    self.assertIn(sentinel, legacy.read_text())
                    self.assertEqual(legacy.stat().st_mode & 0o777, mode & 0o700)
                    self.assertEqual(self.entry(key).read_text(), current)

    def test_legacy_is_restricted_even_when_private_directory_is_unusable(self):
        path = self.file("Game.exe")
        key = "omarchy-taskbar-" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        secret = DESKTOP.replace("Exec=/bin/true", "Exec=/bin/true conflict-sentinel-secret")
        legacy = self.file(key + ".desktop", secret, parent=self.applications)
        external = self.base / "outside"
        external.mkdir()
        protected = self.file(key.removeprefix("omarchy-taskbar-") + ".desktop", DESKTOP, parent=external)
        for kind in ("symlink", "file"):
            if kind == "symlink":
                self.private_applications.symlink_to(external, target_is_directory=True)
            else:
                self.private_applications.write_text("not a directory")
            for operation, argument in (("add", path), ("repair", key)):
                with self.subTest(kind=kind, operation=operation):
                    legacy.chmod(0o644)
                    self.assertEqual(self.run_script(operation, argument), "")
                    self.assertEqual(legacy.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(legacy.read_text(), secret)
                    self.assertEqual(protected.read_text(), DESKTOP)
            self.private_applications.unlink()

    def test_legacy_symlink_is_not_followed_or_chmodded(self):
        path = self.file("Game.exe")
        key = "omarchy-taskbar-" + hashlib.sha256(str(path).encode()).hexdigest()[:16]
        original = self.file("original.desktop", DESKTOP)
        original.chmod(0o644)
        self.applications.mkdir(parents=True)
        legacy = self.legacy_entry(key)
        legacy.symlink_to(original)
        for operation, argument in (("add", path), ("repair", key)):
            with self.subTest(operation=operation):
                self.assertEqual(self.run_script(operation, argument), "")
                self.assertTrue(legacy.is_symlink())
                self.assertEqual(original.stat().st_mode & 0o777, 0o644)
                self.assertEqual(original.read_text(), DESKTOP)
                self.assertFalse(self.entry(key).exists())

    def test_destination_created_during_migration_is_not_overwritten(self):
        key = "omarchy-taskbar-0123456789abcdef"
        secret = DESKTOP.replace("Exec=/bin/true", "Exec=/bin/true conflict-sentinel-secret")
        legacy = self.file(key + ".desktop", secret, parent=self.applications)
        legacy.chmod(0o644)
        (self.bin / "mv").unlink()
        real_mv = shlex.quote(shutil.which("mv"))
        self.file("mv", '#!/bin/bash\nprintf "%s" "existing-private-copy" > "${@: -1}"\n'
                  + 'exec ' + real_mv + ' "$@"\n', executable=True, parent=self.bin)
        self.run_script("repair", key)
        self.assertEqual(legacy.read_text(), secret)
        self.assertEqual(legacy.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.entry(key).read_text(), "existing-private-copy")

    def test_private_directory_symlink_is_not_followed(self):
        external = self.base / "external-applications"
        external.mkdir()
        key = "omarchy-taskbar-0123456789abcdef"
        protected = self.file("0123456789abcdef.desktop", DESKTOP, parent=external)
        self.applications.mkdir(parents=True)
        self.private_applications.symlink_to(external, target_is_directory=True)
        self.assertEqual(self.run_script("add", self.file("Game.exe")), "")
        self.run_script("repair", key)
        self.run_script("remove", key)
        self.assertEqual(protected.read_text(), DESKTOP)
        self.assertEqual(list(external.iterdir()), [protected])

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
        self.assertIn(f"Icon={key}\n", self.entry(key).read_text())
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
        self.assertEqual(list(self.private_applications.iterdir()), [])
        self.assertEqual(self.private_applications.stat().st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
