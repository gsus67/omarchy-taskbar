"""Security and lifecycle tests for private pinned-app icons."""
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import struct
import subprocess
import tempfile
import unittest
import zlib


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bin/set-icon.sh"
BASH = shutil.which("bash")


def png_bytes(width=1, height=1, idat_chunks=1):
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    pixels = b"".join(b"\0" + (b"\0\0\0\xff" * width) for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    compressed = zlib.compress(pixels)
    idat = chunk(b"IDAT", compressed) + chunk(b"IDAT", b"") * (idat_chunks - 1)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + idat + chunk(b"IEND", b"")


class SetIconTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="taskbar-icon-test-")
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.home = self.base / "home"
        self.config_home = self.home / ".config"
        self.state = self.config_home / "omarchy-taskbar"
        self.icons = self.state / "icons"
        self.map = self.state / "pinned-icons.json"
        self.lock = self.state / ".lock"
        self.bin = self.base / "bin"
        self.bin.mkdir()
        for name in ("bash", "chmod", "cp", "flock", "grep", "head", "iconv", "jq", "ln",
                     "mkdir", "mktemp", "mv", "od", "rm", "sha256sum", "stat", "timeout", "tr"):
            target = shutil.which(name)
            self.assertIsNotNone(target, name)
            (self.bin / name).symlink_to(target)
        self.png_fixture = self.base / "fixture.png"
        self.png_fixture.write_bytes(png_bytes())
        self.env = dict(os.environ, HOME=str(self.home), XDG_CONFIG_HOME=str(self.config_home),
                        PATH=str(self.bin), TMPDIR=str(self.base), PNG_FIXTURE=str(self.png_fixture))

    def run_script(self, *args, umask=None):
        command = [BASH, str(SCRIPT), *map(str, args)]
        if umask is not None:
            command = [BASH, "-c", 'umask "$1"; shift; exec "$@"', "set-icon-test", umask, *command]
        result = subprocess.run(command, env=self.env, cwd=self.base, text=True,  # noqa: S603
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        return result.stdout.removesuffix("\n")

    def binary_file(self, name, data, parent=None):
        path = (parent or self.base) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def tool(self, name, body):
        path = self.bin / name
        if path.exists() or path.is_symlink():
            path.unlink()
        path.write_text("#!/usr/bin/env bash\n" + body)
        path.chmod(0o755)
        return path

    def map_data(self):
        return json.loads(self.map.read_text())

    def install_slow_jq(self):
        self.tool("jq", f'{shlex.quote(shutil.which("sleep"))} 0.05\n'
                  f'exec {shlex.quote(shutil.which("jq"))} "$@"\n')

    def run_parallel(self, operations):
        processes = [subprocess.Popen([BASH, str(SCRIPT), *map(str, operation)], env=self.env,  # noqa: S603
                                      cwd=self.base, text=True, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE)
                     for operation in operations]
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stderr, "")
            results.append(stdout.removesuffix("\n"))
        return results

    def assert_map_matches_icons(self):
        data = self.map_data()
        self.assertEqual(len(data.values()), len(set(data.values())))
        self.assertEqual({path.name for path in self.icons.glob("*.png")}, set(data.values()))

    def assert_private_state(self):
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.icons.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.map.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.lock.stat().st_mode & 0o777, 0o600)
        for icon in self.icons.iterdir():
            self.assertEqual(icon.stat().st_mode & 0o777, 0o600)

    def install_icotool(self, output=None):
        fixture = output or self.png_fixture
        self.env["TOOL_PNG"] = str(fixture)
        self.tool("icotool", 'out=""\nwhile (($#)); do\n'
                  '  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi\n'
                  'done\nmkdir -p -- "$out"\ncp -- "$TOOL_PNG" "$out/icon.png"\n')

    def install_wrestool(self):
        self.tool("wrestool", 'out=""\nwhile (($#)); do\n'
                  '  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi\n'
                  'done\nmkdir -p -- "$out"\nprintf "\\x00\\x00\\x01\\x00\\x01\\x00" > "$out/group.ico"\n')

    def install_rsvg(self, output=None):
        fixture = output or self.png_fixture
        self.env["TOOL_PNG"] = str(fixture)
        self.env["RENDER_CALLED"] = str(self.base / "render-called")
        self.tool("rsvg-convert", 'out=""\n: > "$RENDER_CALLED"\nwhile (($#)); do\n'
                  '  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi\n'
                  'done\ncp -- "$TOOL_PNG" "$out"\n')

    def pe_file(self, name="Game.exe"):
        data = bytearray(128)
        data[:2] = b"MZ"
        data[0x3C:0x40] = struct.pack("<I", 0x40)
        data[0x40:0x44] = b"PE\0\0"
        return self.binary_file(name, data)

    def test_png_set_replace_and_reset_are_private_atomic_and_orphan_free(self):
        first = self.binary_file("first.png", png_bytes())
        second = self.binary_file("second.data", png_bytes(2, 3))
        key = "org.example.App+stable"

        self.assertEqual(self.run_script("set", key, first, umask="000"), "ok")
        first_name = self.map_data()[key]
        self.assertRegex(first_name, r"^[0-9a-f]{16}-[A-Za-z0-9]{6}\.png$")
        self.assertEqual((self.icons / first_name).read_bytes(), first.read_bytes())
        self.assert_private_state()

        self.assertEqual(self.run_script("set", key, second), "ok")
        second_name = self.map_data()[key]
        self.assertNotEqual(first_name, second_name)
        self.assertFalse((self.icons / first_name).exists())
        self.assertEqual((self.icons / second_name).read_bytes(), second.read_bytes())
        self.assertFalse(list(self.state.glob(".pinned-icons.*")))

        self.assertEqual(self.run_script("reset", key), "ok")
        self.assertEqual(self.map_data(), {})
        self.assertEqual(list(self.icons.iterdir()), [])

    def test_parallel_sets_keep_same_and_different_keys_consistent(self):
        self.install_slow_jq()
        sources = [self.binary_file(f"parallel-{number}.png", png_bytes(number + 1, 1))
                   for number in range(6)]

        self.assertEqual(self.run_parallel([("set", "same-key", source) for source in sources]),
                         ["ok"] * len(sources))
        self.assertEqual(set(self.map_data()), {"same-key"})
        self.assert_map_matches_icons()

        self.assertEqual(self.run_script("reset", "same-key"), "ok")
        operations = [("set", f"key-{number}", source)
                      for number, source in enumerate(sources)]
        self.assertEqual(self.run_parallel(operations), ["ok"] * len(operations))
        self.assertEqual(set(self.map_data()), {f"key-{number}" for number in range(6)})
        self.assert_map_matches_icons()

    def test_parallel_set_and_reset_keep_same_and_different_keys_consistent(self):
        self.install_slow_jq()
        old = self.binary_file("old.png", png_bytes())
        new = self.binary_file("new.png", png_bytes(2, 1))

        for key in ("same-a", "same-b", "same-c"):
            self.assertEqual(self.run_script("set", key, old), "ok")
        operations = []
        for key in ("same-a", "same-b", "same-c"):
            operations.extend((("set", key, new), ("reset", key)))
        self.assertEqual(sorted(self.run_parallel(operations)), sorted(["ok"] * len(operations)))
        self.assert_map_matches_icons()

        self.assertEqual(self.run_script("set", "set-key", old), "ok")
        self.assertEqual(self.run_script("set", "reset-key", old), "ok")
        self.assertEqual(sorted(self.run_parallel((
            ("set", "set-key", new),
            ("reset", "reset-key"),
        ))), ["ok", "ok"])
        self.assertIn("set-key", self.map_data())
        self.assertNotIn("reset-key", self.map_data())
        self.assert_map_matches_icons()

    def test_key_is_validated_and_never_becomes_a_file_name(self):
        source = self.binary_file("$(touch owned)\n.png", png_bytes())
        valid = ["app.desktop", "org.example_App+beta@local", "/opt/My Apps/app"]
        invalid = ["relative/path", "../app", "app..desktop", "/opt/../app", "bad\nkey",
                   "bad\rkey", "/bad\x7fkey", ""]
        for key in valid:
            with self.subTest(valid=key):
                self.assertEqual(self.run_script("set", key, source), "ok")
                name = self.map_data()[key]
                self.assertNotIn("app", name)
                self.assertNotIn("/", name)
                self.assertEqual(self.run_script("reset", key), "ok")
        for key in invalid:
            with self.subTest(invalid=repr(key)):
                self.assertEqual(self.run_script("set", key, source), "error:key")
        self.assertFalse((self.base / "owned").exists())

    def test_source_must_be_regular_not_symlink_and_at_most_20mb(self):
        source = self.binary_file("real.png", png_bytes())
        link = self.base / "link.png"
        link.symlink_to(source)
        directory = self.base / "directory.png"
        directory.mkdir()
        oversized = self.binary_file("oversized.png", png_bytes())
        with oversized.open("r+b") as stream:
            stream.truncate(20 * 1024 * 1024 + 1)

        self.assertEqual(self.run_script("set", "app", link), "error:source")
        self.assertEqual(self.run_script("set", "app", directory), "error:source")
        self.assertEqual(self.run_script("set", "app", self.base / "missing"), "error:source")
        self.assertEqual(self.run_script("set", "app", oversized), "error:size")
        self.assertFalse(self.state.exists())

    def test_source_replaced_by_fifo_during_snapshot_is_bounded(self):
        source = self.binary_file("raced.png", png_bytes())
        marker = self.base / "stat-raced"
        self.env.update(RACE_SOURCE=str(source), RACE_MARKER=str(marker))
        real_stat = shlex.quote(shutil.which("stat"))
        real_rm = shlex.quote(shutil.which("rm"))
        real_mkfifo = shlex.quote(shutil.which("mkfifo"))
        self.tool("stat", f'if [[ ${{@: -1}} == "$RACE_SOURCE" && ! -e $RACE_MARKER ]]; then\n'
                  f'  {real_stat} "$@"\n'
                  '  : > "$RACE_MARKER"\n'
                  f'  {real_rm} -f -- "$RACE_SOURCE"\n'
                  f'  {real_mkfifo} -- "$RACE_SOURCE"\n'
                  '  exit 0\n'
                  'fi\n'
                  f'exec {real_stat} "$@"\n')
        real_timeout = shlex.quote(shutil.which("timeout"))
        self.tool("timeout", f'exec {real_timeout} 0.2 "${{@:2}}"\n')

        process = subprocess.Popen([BASH, str(SCRIPT), "set", "fifo-race", str(source)],  # noqa: S603
                                   env=self.env, cwd=self.base, text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            self.fail("snapshot copy hung after the source became a FIFO")
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout, "error:source\n")
        self.assertFalse(self.state.exists())

    def test_png_type_and_dimensions_come_from_content(self):
        valid_wrong_extension = self.binary_file("image.txt", png_bytes(1024, 1))
        fake = self.binary_file("fake.png", b"not a png")
        too_wide = self.binary_file("wide.png", png_bytes(1025, 1))
        too_tall = self.binary_file("tall.png", png_bytes(1, 1025))
        self.assertEqual(self.run_script("set", "valid", valid_wrong_extension), "ok")
        self.assertEqual(self.run_script("set", "fake", fake), "error:type")
        self.assertEqual(self.run_script("set", "wide", too_wide), "error:dimensions")
        self.assertEqual(self.run_script("set", "tall", too_tall), "error:dimensions")

    def test_png_requires_a_well_formed_header_and_terminal_iend(self):
        valid = png_bytes()
        hostile = {
            "trailing.png": valid + b"untrusted trailing data",
            "bad-ihdr-length.png": valid[:8] + b"\0\0\0\x0c" + valid[12:],
            "missing-iend.png": valid[:-12],
            "bad-format.png": valid[:24] + b"\x01\x06\0\0\0" + valid[29:],
        }
        for name, contents in hostile.items():
            with self.subTest(name=name):
                source = self.binary_file(name, contents)
                self.assertEqual(self.run_script("set", name, source), "error:type")

    def test_png_with_more_than_256_idat_chunks_is_accepted(self):
        source = self.binary_file("many-idat.png", png_bytes(idat_chunks=300))
        self.assertEqual(self.run_script("set", "many-idat", source), "ok")

    def test_ico_is_converted_and_converter_output_is_revalidated(self):
        ico = self.binary_file("icon.bin", b"\0\0\1\0\1\0" + b"x" * 32)
        self.install_icotool()
        self.assertEqual(self.run_script("set", "ico.app", ico), "ok")
        self.assertTrue((self.icons / self.map_data()["ico.app"]).read_bytes().startswith(b"\x89PNG"))

        self.install_icotool(self.binary_file("tool-output.png", png_bytes(1025, 1)))
        self.assertEqual(self.run_script("set", "oversized.ico", ico), "error:dimensions")
        self.assertNotIn("oversized.ico", self.map_data())

        self.env["TOOL_PNG"] = str(self.png_fixture)
        self.tool("icotool", 'out=""\nwhile (($#)); do\n'
                  '  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi\n'
                  'done\nmkdir -p -- "$out"\nln -s -- "$TOOL_PNG" "$out/icon.png"\n')
        self.assertEqual(self.run_script("set", "symlink.ico", ico), "error:extract")
        self.assertNotIn("symlink.ico", self.map_data())

    def test_ico_and_pe_choose_the_largest_extracted_png(self):
        small = self.binary_file("small.png", png_bytes(32, 32))
        large = self.binary_file("large.png", png_bytes(256, 128))
        self.env.update(SMALL_PNG=str(small), LARGE_PNG=str(large))
        self.tool("icotool", 'out=""\nwhile (($#)); do\n'
                  '  if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi\n'
                  'done\nmkdir -p -- "$out"\n'
                  'cp -- "$SMALL_PNG" "$out/100-small.png"\n'
                  'cp -- "$LARGE_PNG" "$out/900-large.png"\n')

        ico = self.binary_file("multi.ico", b"\0\0\1\0\1\0" + b"x" * 32)
        self.assertEqual(self.run_script("set", "multi.ico", ico), "ok")
        stored = (self.icons / self.map_data()["multi.ico"]).read_bytes()
        self.assertEqual(struct.unpack(">II", stored[16:24]), (256, 128))

        self.install_wrestool()
        pe = self.pe_file("multi.exe")
        self.assertEqual(self.run_script("set", "multi.exe", pe), "ok")
        stored = (self.icons / self.map_data()["multi.exe"]).read_bytes()
        self.assertEqual(struct.unpack(">II", stored[16:24]), (256, 128))

    def test_pe_is_validated_extracted_and_never_executed(self):
        self.install_wrestool()
        self.install_icotool()
        marker = self.base / "executed"
        self.env["EXECUTED_MARKER"] = str(marker)
        source = self.pe_file('Game; $(touch executed).exe')
        source.chmod(0o755)
        self.tool("wine", ': > "$EXECUTED_MARKER"\n')
        self.assertEqual(self.run_script("set", "/games/Game.exe", source), "ok")
        self.assertFalse(marker.exists())

        invalid = self.binary_file("invalid.exe", b"MZ" + b"\0" * 126)
        self.assertEqual(self.run_script("set", "invalid.exe", invalid), "error:type")

    def test_safe_svg_is_rasterized_and_active_or_external_content_is_rejected(self):
        self.install_rsvg()
        safe = self.binary_file("safe.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><path id="p"/><use href="#p"/></svg>')
        self.assertEqual(self.run_script("set", "safe.svg", safe), "ok")
        self.assertTrue((self.icons / self.map_data()["safe.svg"]).read_bytes().startswith(b"\x89PNG"))

        hostile = [
            b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.test/x"/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="x"><image xlink:href="file:///etc/passwd"/></svg>',
            b'<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg xmlns="http://www.w3.org/2000/svg"/>',
            b'<?xml-stylesheet href="https://example.test/x"?><svg xmlns="http://www.w3.org/2000/svg"/>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://example.test/x)</style></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:s="urn:test"><s:style>rect{fill:blue}</s:style></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:url(https://example.test/x)"/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href=\n"file:///etc/passwd"/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><script\n>alert(1)</script></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject\n/></svg>',
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect\nstyle="fill:red"/></svg>',
        ]
        for number, contents in enumerate(hostile):
            with self.subTest(number=number):
                called = Path(self.env["RENDER_CALLED"])
                called.unlink(missing_ok=True)
                source = self.binary_file(f"hostile-{number}.svg", contents)
                self.assertEqual(self.run_script("set", f"hostile-{number}", source), "error:svg")
                self.assertFalse(called.exists())

    def test_svg_rejects_ambiguous_or_non_utf8_byte_encodings_before_rendering(self):
        self.install_rsvg()
        safe = b'<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'
        hostile = {
            "utf7": (b'<?xml version="1.0" encoding="UTF-7"?>'
                     b'<svg xmlns="http://www.w3.org/2000/svg">'
                     b'+ADw-style+AD4-rect+AHs-fill:red+AH0-+ADw-/style+AD4-</svg>'),
            "utf16-bom": (b'<!-- <svg -->' +
                           '<svg xmlns="http://www.w3.org/2000/svg"><style>rect{fill:red}</style></svg>'.encode("utf-16")),
            "utf8-bom": b"\xef\xbb\xbf" + safe,
            "nul": safe.replace(b"<path/>", b"<path\x00/>"),
            "invalid-utf8": safe.replace(b"<path/>", b"<path id=\"\xff\"/>"),
            "other-declaration": b'<?xml version="1.0" encoding="ISO-8859-1"?>' + safe,
        }
        for name, contents in hostile.items():
            with self.subTest(name=name):
                called = Path(self.env["RENDER_CALLED"])
                called.unlink(missing_ok=True)
                source = self.binary_file(name + ".svg", contents)
                self.assertEqual(self.run_script("set", name, source), "error:svg")
                self.assertFalse(called.exists())

        for name, declaration in (("utf8", "UTF-8"), ("ascii", "us-ascii")):
            with self.subTest(name=name):
                source = self.binary_file(
                    name + ".svg",
                    f'<?xml version="1.0" encoding="{declaration}"?>'.encode() + safe,
                )
                self.assertEqual(self.run_script("set", name, source), "ok")

    def test_svg_ignores_encoding_text_outside_xml_declaration(self):
        self.install_rsvg()
        source = self.binary_file(
            "encoding-text.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><desc>encoding=base64</desc></svg>',
        )
        self.assertEqual(self.run_script("set", "encoding-text", source), "ok")

    def test_svg_with_attributes_after_root_line_break_is_rasterized(self):
        self.install_rsvg()
        source = self.binary_file(
            "multiline.svg",
            b'<svg\n xmlns="http://www.w3.org/2000/svg"><path id="p"/></svg>',
        )
        self.assertEqual(self.run_script("set", "multiline.svg", source), "ok")
        self.assertTrue((self.icons / self.map_data()["multiline.svg"]).read_bytes().startswith(b"\x89PNG"))

    def test_svg_non_ascii_namespace_script_is_rejected_in_c_locale(self):
        self.install_rsvg()
        self.env["LC_ALL"] = "C"
        source = self.binary_file(
            "non-ascii-prefix.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:n\xc3\xa9="urn:test"><n\xc3\xa9:script/></svg>',
        )
        self.assertEqual(self.run_script("set", "non-ascii-prefix.svg", source), "error:svg")
        self.assertFalse(Path(self.env["RENDER_CALLED"]).exists())

    def test_svg_filter_errors_fail_closed(self):
        self.install_rsvg()
        source = self.binary_file("filter-error.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        counter = self.base / "grep-counter"
        self.env["GREP_COUNTER"] = str(counter)
        real_grep = shlex.quote(shutil.which("grep"))
        self.tool("grep", 'count=0\n[[ ! -f $GREP_COUNTER ]] || read -r count < "$GREP_COUNTER"\n'
                  'count=$((count + 1))\nprintf "%s\\n" "$count" > "$GREP_COUNTER"\n'
                  'if ((count == 3)); then exit 2; fi\n'
                  f'exec {real_grep} "$@"\n')
        self.assertEqual(self.run_script("set", "filter-error", source), "error:svg")
        self.assertFalse(Path(self.env["RENDER_CALLED"]).exists())

    def test_svg_href_is_rejected_when_grep_has_no_pcre_support(self):
        self.install_rsvg()
        source = self.binary_file(
            "no-pcre.svg",
            b'<svg xmlns="http://www.w3.org/2000/svg"><image href=\n"file:///etc/passwd"/></svg>',
        )
        pcre_called = self.base / "grep-pcre-called"
        self.env["GREP_PCRE_CALLED"] = str(pcre_called)
        real_grep = shlex.quote(shutil.which("grep"))
        self.tool("grep", 'for argument in "$@"; do\n'
                  '  if [[ $argument == -* && $argument == *P* ]]; then\n'
                  '    : > "$GREP_PCRE_CALLED"\n'
                  '    exit 2\n'
                  '  fi\n'
                  'done\n'
                  f'exec {real_grep} "$@"\n')
        self.assertEqual(self.run_script("set", "no-pcre", source), "error:svg")
        self.assertFalse(pcre_called.exists())
        self.assertFalse(Path(self.env["RENDER_CALLED"]).exists())

    def test_lock_timeout_reports_busy(self):
        source = self.binary_file("busy.png", png_bytes())
        lock_arguments = self.base / "lock-arguments"
        self.env["LOCK_ARGUMENTS"] = str(lock_arguments)
        real_flock = shlex.quote(shutil.which("flock"))
        self.tool("flock", 'if [[ $1 == -x ]]; then\n'
                  '  printf "%s\\n" "$*" > "$LOCK_ARGUMENTS"\n'
                  '  exit 1\n'
                  'fi\n'
                  f'exec {real_flock} "$@"\n')
        self.assertEqual(self.run_script("set", "busy", source), "error:busy")
        self.assertTrue(lock_arguments.read_text().startswith("-x -w 10 "))

    def test_external_converters_have_kill_timeout_and_memory_limit(self):
        source = self.binary_file("limited.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        limit = self.base / "vm-limit"
        self.env.update(VM_LIMIT=str(limit), TOOL_PNG=str(self.png_fixture))
        self.tool("timeout", '[[ $1 == -k && $2 == 2 && $3 == 5 ]] || exit 125\n'
                  'shift 3\nexec "$@"\n')
        self.tool("rsvg-convert", 'ulimit -v > "$VM_LIMIT"\nout=""\n'
                  'while (($#)); do if [[ $1 == -o ]]; then out=$2; shift 2; else shift; fi; done\n'
                  'cp -- "$TOOL_PNG" "$out"\n')
        self.assertEqual(self.run_script("set", "limited.svg", source), "ok")
        self.assertEqual(int(limit.read_text()), 524288)

    def test_svg_without_renderer_and_converter_calls_without_timeout_are_rejected(self):
        svg = self.binary_file("safe.svg", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual(self.run_script("set", "safe.svg", svg), "error:tool")

        ico = self.binary_file("icon.ico", b"\0\0\1\0\1\0" + b"x" * 32)
        ran = self.base / "converter-ran"
        self.env["CONVERTER_RAN"] = str(ran)
        self.tool("icotool", ': > "$CONVERTER_RAN"\n')
        self.tool("timeout", 'if [[ $4 == head ]]; then shift 3; exec "$@"; fi\nexit 124\n')
        self.assertEqual(self.run_script("set", "timed.ico", ico), "error:extract")
        self.assertFalse(ran.exists())

        source = self.pe_file("timed.exe")
        self.tool("wrestool", ': > "$CONVERTER_RAN"\n')
        self.install_icotool()
        self.assertEqual(self.run_script("set", "timed.exe", source), "error:extract")
        self.assertFalse(ran.exists())

    def test_symlinked_storage_and_map_are_never_followed(self):
        source = self.binary_file("source.png", png_bytes())
        outside = self.base / "outside"
        outside.mkdir()
        self.config_home.mkdir(parents=True)
        self.state.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.run_script("set", "app", source), "error:storage")
        self.assertEqual(list(outside.iterdir()), [])

        self.state.unlink()
        self.state.mkdir(mode=0o700)
        target = self.base / "target.json"
        target.write_text('{"sentinel": true}\n')
        self.map.symlink_to(target)
        self.assertEqual(self.run_script("set", "app", source), "error:map")
        self.assertEqual(target.read_text(), '{"sentinel": true}\n')

    def test_corrupt_map_cannot_delete_foreign_files(self):
        self.icons.mkdir(parents=True, mode=0o700)
        victim = self.base / "victim"
        victim.write_text("keep")
        self.map.write_text(json.dumps({"app": "../../victim"}))
        self.map.chmod(0o600)
        self.assertEqual(self.run_script("reset", "app"), "ok")
        self.assertEqual(victim.read_text(), "keep")
        self.assertEqual(self.map_data(), {})

    def test_icon_map_rejects_entries_beyond_its_fixed_quota(self):
        source = self.binary_file("quota.png", png_bytes())
        self.state.mkdir(parents=True, mode=0o700)
        entries = {f"app-{index}": f"{'0' * 16}-AAAAAA.png" for index in range(1024)}
        self.map.write_text(json.dumps(entries))
        self.map.chmod(0o600)
        self.assertEqual(self.run_script("set", "one-too-many", source), "error:map")
        self.assertEqual(json.loads(self.map.read_text()), entries)

    def test_failed_atomic_map_replace_removes_new_icon_and_temporaries(self):
        source = self.binary_file("source.png", png_bytes())
        self.tool("mv", "exit 1\n")
        self.assertEqual(self.run_script("set", "app", source), "error:map")
        self.assertEqual(list(self.icons.glob("*.png")), [])
        self.assertFalse(list(self.state.glob(".pinned-icons.*")))

    def test_unexpected_mktemp_result_is_never_used_or_removed(self):
        source = self.binary_file("source.png", png_bytes())
        victim = self.base / "victim"
        victim.mkdir()
        sentinel = victim / "keep"
        sentinel.write_text("keep")
        self.env["VICTIM"] = str(victim)
        self.tool("mktemp", 'printf "%s\\n" "$VICTIM"\n')
        self.assertEqual(self.run_script("set", "app", source), "error:temp")
        self.assertEqual(sentinel.read_text(), "keep")

    def test_usage_is_reported_on_stdout_only(self):
        self.assertEqual(self.run_script(), "error:usage")
        self.assertEqual(self.run_script("set", "key"), "error:usage")
        self.assertEqual(self.run_script("reset", "key", "extra"), "error:usage")
        self.assertEqual(self.run_script("unknown", "key"), "error:usage")


if __name__ == "__main__":
    unittest.main()
