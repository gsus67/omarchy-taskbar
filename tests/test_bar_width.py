"""Guards for bar size, hand-edited width and safe configuration writes."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from extract_shell import CALL, scripts

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()
CONFIG_WRITER = re.search(r"Process \{\s*id: configWriter\b(.*?)\n  \}", SOURCE, re.S)
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
        self.assertIn("config = Object.assign(Object.create(null), parsed)", writer)
        self.assertIn("if (value === null) delete config[key]", writer)
        self.assertIn("else config[key] = value", writer)
        self.assertIn('Object.keys(config).length ? JSON.stringify(config, null, 2) : ""', writer)

    def test_config_script_is_literal_with_positional_data(self):
        self.assertIsNotNone(SAVE_CONFIG)
        writer = CONFIG_WRITER.group(1)
        call = CALL.search(writer)
        self.assertIsNotNone(call, "missing literal bash -c script")
        self.assertRegex(writer[call.end():], r'^,\s*"omarchy-taskbar", configFile\.path,')
        script = list(scripts(writer))[0][1]
        self.assertIn('mktemp -- "$1.XXXXXX"', script)
        self.assertIn('>"$tmp" && mv -f -- "$tmp" "$1"', script)
        self.assertNotIn('>"$1"', script)

    def test_config_script_replaces_atomically_and_removes_empty_config(self):
        self.assertIsNotNone(SAVE_CONFIG)
        script = list(scripts(CONFIG_WRITER.group(1)))[0][1]
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

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_rapid_setting_changes_are_serialized_and_preserve_other_keys(self):
        functions = "\n".join(re.search(r"  function " + name + r"\([^\n]*\) \{.*?\n  \}", SOURCE, re.S).group(0)
                              for name in ("saveConfig", "writeNextConfig"))
        code = functions + "\n" + r'''
const configFile={text:()=>JSON.stringify({other:"preserved"})};
const configWriter={running:false,payload:""};
const root={configSnapshot:null,configWrites:[],writeNextConfig,scaleFor:v=>[0.75,0.9,1,1.25,1.5,2].includes(v)?v:1};
saveConfig("style","crystal");
saveConfig("width","10%");
saveConfig("scale",0.75);
saveConfig("style",null);
saveConfig("__proto__",{});
saveConfig("width","$(touch injected)");
const writes=[];
while(configWriter.running) {
  writes.push(JSON.parse(configWriter.payload));
  configWriter.running=false;
  writeNextConfig();
}
console.log(JSON.stringify(writes));
'''
        result = subprocess.run(["node", "-e", code], text=True, capture_output=True, timeout=5, check=True)
        writes = json.loads(result.stdout)
        self.assertEqual(len(writes), 4)
        self.assertEqual(writes[-1], {"other":"preserved", "width":"10%", "scale":0.75})
        self.assertEqual(writes[1], {"other":"preserved", "style":"crystal", "width":"10%"})

    def test_empty_space_menu_dismissal_and_keyboard(self):
        mouse = SOURCE[SOURCE.index("// Empty bar space:"):SOURCE.index("id: appViewport")]
        self.assertIn("event.button === Qt.LeftButton && !root.crystal) root.toggleTransparent()", mouse)
        self.assertIn("event.button === Qt.RightButton", mouse)
        self.assertIn("root.showMenu(barMenu)", mouse)
        menu = SOURCE[SOURCE.index("id: barMenu"):SOURCE.index("component DragGhostPanel:")]
        for action in ("Keys.onEscapePressed", "Keys.onUpPressed", "Keys.onDownPressed", "Keys.onReturnPressed"):
            self.assertIn(action, menu)
        self.assertIn("windows: bar.sharedSurface ? [barMenu] : [barMenu, bar.surface]", menu)
        self.assertIn("onCleared: if (root.openMenu === barMenu) root.closeMenu()", menu)

    def test_check_mark_has_a_fixed_leading_column(self):
        row = SOURCE[SOURCE.index("component MenuRow:"):]
        self.assertIn("readonly property int checkWidth: checkable ? Style.space(20) : 0", row)
        self.assertIn("width: row.checkWidth", row)
        self.assertIn('text: row.checked ? "✓" : ""', row)
        self.assertIn("anchors.leftMargin: Style.space(12) + row.checkWidth", row)
        self.assertNotIn('"✓ "', SOURCE)
        self.assertNotIn('"    "', SOURCE)

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_scale_and_style_accept_only_supported_values(self):
        result = self.evaluate('[0.75, 0.9, 1, 1.25, 1.5, 2, 0, -1, 99, "0.75", null, {}, "$(touch injected)"].map(scaleFor)')
        self.assertEqual(result, [0.75, 0.9, 1, 1.25, 1.5, 2, 1, 1, 1, 1, 1, 1, 1])
        self.assertEqual(self.evaluate('["crystal", "default", null, {}, "__proto__", "$(touch injected)"].map(styleFor)'),
                         ["crystal", "default", "default", "default", "default", "default"])
        self.assertIn('root.configuredStyle = root.styleFor(config && config.style)', SOURCE)

    def evaluate(self, expression, spanish=False, style="default", scale=1, width=None, position="bottom"):
        names = ("widthFor", "barMenuItems")
        functions = []
        for name in names:
            match = re.search(r"  function " + name + r"\([^\n]*\) \{.*?\n  \}", SOURCE, re.S)
            self.assertIsNotNone(match)
            functions.append(match.group(0))
        for name in ("scaleFor", "styleFor"):
            functions.append(re.search(r"  function " + name + r"\([^\n]*\) \{[^\n]*\}", SOURCE).group(0))
        code = "\n".join(functions) + "\n" + (
            "const spanish=" + json.dumps(spanish) + ";"
            "const configuredStyle=" + json.dumps(style) + ";"
            "const configuredScale=" + json.dumps(scale) + ";"
            "const configuredWidth=" + json.dumps(width) + ";"
            "const configuredPosition=" + json.dumps(position) + ";"
            'const crystal=configuredStyle === "crystal";'
            'const Qt={locale:()=>({decimalPoint: spanish ? "," : "."})};'
            'function t(en, es) {return spanish ? es : en;}\n'
            "console.log(JSON.stringify(" + expression + "));"
        )
        result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=5, check=True)
        return json.loads(result.stdout)

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_menu_language_choices_and_active_values(self):
        self.assertEqual([row["label"] for row in self.evaluate('barMenuItems("root")')], ["Style  ›", "Position  ›", "Size  ›"])
        self.assertEqual([row["label"] for row in self.evaluate('barMenuItems("root")', spanish=True)], ["Estilo  ›", "Posición  ›", "Tamaño  ›"])
        self.assertEqual([row.get("page") for row in self.evaluate('barMenuItems("size")')], ["root", "length", "scale"])
        self.assertEqual([row.get("page") for row in self.evaluate('barMenuItems("size")', style="crystal")], ["root", "length", "scale"])
        self.assertEqual([row["label"] for row in self.evaluate('barMenuItems("size")', spanish=True)[1:]], ["Largo  ›", "Ancho  ›"])
        self.assertEqual([row["label"] for row in self.evaluate('barMenuItems("size")')[1:]], ["Length  ›", "Width  ›"])
        styles = self.evaluate('barMenuItems("style")', spanish=True, style="crystal")
        self.assertEqual([row.get("checked") for row in styles[1:]], [False, True])
        self.assertIsNone(styles[1]["value"])
        scales = self.evaluate('barMenuItems("scale")', spanish=True, scale=0.75)
        self.assertEqual([row["value"] for row in scales[1:]], [0.75, 0.9, None, 1.25, 1.5, 2])
        self.assertEqual(scales[1]["label"], "0,75x")
        lengths = self.evaluate('barMenuItems("length")', width="20%")
        self.assertEqual([row["value"] for row in lengths[1:]], [None, "90%", "80%", "70%", "60%", "50%", "40%", "30%", "20%", "10%"])
        self.assertTrue(lengths[-2]["checked"])
        self.assertTrue(self.evaluate('barMenuItems("length")', width="10%")[-1]["checked"])

    def test_scale_multiplies_bar_height_and_icons(self):
        self.assertIn("readonly property int barSize: Math.round(Style.bar.sizeHorizontal * (combined ? 1 : configuredScale))", SOURCE)
        self.assertIn("readonly property int iconSize: Math.round(barSize * 0.66)", SOURCE)
        self.assertIn("implicitHeight: root.barSize", SOURCE)

    def test_missing_or_invalid_config_resets_width(self):
        self.assertIn("property var configuredWidth: null", SOURCE)
        self.assertRegex(SOURCE, r"catch \(e\) \{\s*root.configuredWidth = null")
        self.assertRegex(SOURCE, r"onLoadFailed: \{\s*root.configuredWidth = null")

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
    def test_width_tracks_icons_and_stays_inside_each_screen(self):
        result = self.evaluate('[widthFor(null, 1000, 40, false, 200), '
            'widthFor("20%", 1000, 40, false, 100), '
            'widthFor("20%", 1000, 40, false, 450), '
            'widthFor("20%", 1000, 40, false, 100), '
            'widthFor("20%", 1000, 40, false, 2000), '
            'widthFor(null, 1000, 40, true, 100), '
            'widthFor("20%", 1000, 40, true, 450), '
            'widthFor("100%", 1000, 40, true, 2000), '
            'widthFor("$(touch injected)", 1000, 40, false, 100), '
            'widthFor(-100, 1000, 40, false, 0), '
            'widthFor("20%", 50, 40, true, 100), '
            'widthFor("10%", 1000, 40, false, 50), '
            'widthFor("10%", 1000, 40, false, 400)]')
        self.assertEqual(result, [1000, 200, 450, 200, 1000, 968, 450, 968, 1000, 80, 18, 100, 400])
        self.assertIn("appRow.implicitWidth", SOURCE)
        self.assertIn("modelData.height - barWindow.height - barWindow.margins.bottom", SOURCE)
        self.assertIn("appViewport.contentX", SOURCE)


if __name__ == "__main__":
    unittest.main()
