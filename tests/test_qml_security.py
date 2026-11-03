"""Static guards for the taskbar QML.

The taskbar shows app names and window titles, and a window title can be any
web page's title. Rich text would let such a string load remote images or
links, so every text element must render plain text and the QML must not
reach the network on its own.
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKBAR = (ROOT / "Taskbar.qml").read_text()
QML_FILES = sorted(path for path in ROOT.rglob("*.qml") if ".git" not in path.parts)
# Elements that interpret markup unless told otherwise.
TEXT_ELEMENTS = ("Text", "TextEdit", "Label", "Controls.Label", "Controls.TextArea", "TextArea")
OPENING = re.compile(r"^(\s*)(%s)\s*\{" % "|".join(re.escape(name) for name in TEXT_ELEMENTS))


def text_blocks(source):
    """Yield (line number, element, block text) for each text element."""
    lines = source.splitlines()
    for index, line in enumerate(lines):
        match = OPENING.match(line)
        if not match:
            continue
        depth, block = 0, []
        for current in lines[index:]:
            block.append(current)
            depth += current.count("{") - current.count("}")
            if depth <= 0:
                break
        yield index + 1, match.group(2), "\n".join(block)


class QmlSecurityTest(unittest.TestCase):
    def test_qml_files_found(self):
        self.assertTrue(QML_FILES, "no QML files to check")

    def test_text_elements_are_plain_text(self):
        for path in QML_FILES:
            for line, element, block in text_blocks(path.read_text()):
                with self.subTest(file=path.name, line=line):
                    self.assertIn("textFormat: Text.PlainText", block,
                                  f"{path.name}:{line} {element} must set textFormat: Text.PlainText")

    def test_no_rich_text_formats(self):
        for path in QML_FILES:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=path.name, line=number):
                    self.assertIsNone(re.search(r"\b(RichText|StyledText|AutoText|MarkdownText)\b", line),
                                      f"{path.name}:{number} uses a markup text format")

    def test_no_remote_urls(self):
        for path in QML_FILES:
            for number, line in enumerate(path.read_text().splitlines(), 1):
                with self.subTest(file=path.name, line=number):
                    self.assertNotRegex(line, r"https?://", f"{path.name}:{number} references a remote URL")

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_external_key_dictionaries_have_no_object_prototype(self):
        factory = re.search(r"  function newDictionary\([^\n]*\) \{[^\n]*\}", TASKBAR)
        self.assertIsNotNone(factory, "missing null-prototype dictionary factory")
        code = factory.group(0).strip() + r'''
const map = newDictionary();
["__proto__", "constructor", "toString"].forEach((key, index) => { map[key] = index; });
console.log(JSON.stringify([
  map["__proto__"], map["constructor"], map["toString"],
  Object.getPrototypeOf(map), Object.keys(map)
]));
'''
        result = subprocess.run(  # noqa: S603
            [shutil.which("node"), "-e", code], capture_output=True, text=True,
            timeout=5, check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            [0, 1, 2, None, ["__proto__", "constructor", "toString"]],
        )
        self.assertNotRegex(TASKBAR, r"\(\{\}\)|Object\.assign\(\{\}")
        for assignment in (
            "var map = root.newDictionary()",
            "var seen = root.newDictionary()",
            "var config = root.newDictionary()",
            "var known = root.newDictionary(root.fallbacks)",
            "root.pendingIconIndex = root.newDictionary()",
        ):
            with self.subTest(assignment=assignment):
                self.assertIn(assignment, TASKBAR)


if __name__ == "__main__":
    unittest.main()
