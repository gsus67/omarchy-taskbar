#!/usr/bin/env python3
"""Run the actual settings queue and Process against a temporary config only."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "Taskbar.qml").read_text()
functions = "\n".join(re.search(r"  function " + name + r"\([^\n]*\) \{.*?\n  \}", source, re.S).group(0)
                      for name in ("saveConfig", "writeNextConfig"))
scale = re.search(r"  function scaleFor\([^\n]*\) \{[^\n]*\}", source).group(0)
writer = re.search(r"  Process \{\n    id: configWriter\b.*?\n  \}", source, re.S).group(0)
with tempfile.TemporaryDirectory(prefix="taskbar-native-settings-") as directory:
    base = Path(directory)
    (base / "runtime").mkdir(mode=0o700)
    config = base / "config $(touch injected)" / "config.json"
    config.parent.mkdir()
    config.write_text('{"other":"preserved","__proto__":{"sentinel":true}}')
    harness = r'''import QtQuick
import Quickshell
import Quickshell.Io
ShellRoot {
    id: root
    property var configSnapshot: null
    property var configWrites: []
    property bool started: false
    FileView {
        id: configFile
        path: CONFIG_PATH
        watchChanges: true
        printErrors: false
        onLoaded: {
            if (!root.started || configWriter.running || root.configWrites.length) return;
            var value = JSON.parse(text());
            if (value.other !== "preserved" || value.width !== "10%" || value.scale !== 0.75 || value.style !== undefined || value.__proto__.sentinel !== true) {
                console.error("Settings queue did not preserve all choices and unknown keys");
                Qt.exit(1);
                return;
            }
            console.log("TASKBAR_NATIVE_SETTINGS_OK");
            Qt.quit();
        }
    }
    Timer {
        interval: 50
        running: true
        onTriggered: {
            root.started = true;
            root.saveConfig("style", "crystal");
            root.saveConfig("width", "10%");
            root.saveConfig("scale", 0.75);
            root.saveConfig("style", null);
        }
    }
    Timer {
        interval: 5000
        running: true
        onTriggered: { console.error("Settings queue timed out"); Qt.exit(1); }
    }
FUNCTIONS
WRITER
}
'''
    (base / "shell.qml").write_text(harness.replace("CONFIG_PATH", json.dumps(str(config)))
                                  .replace("FUNCTIONS", functions + "\n" + scale).replace("WRITER", writer))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(base / "runtime"),
               DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(base / "no-bus"))
    result = subprocess.run(["quickshell", "--no-color", "-p", str(base)],
                            env=env, text=True, capture_output=True, timeout=10)
    output = result.stdout + result.stderr
    if result.returncode or "TASKBAR_NATIVE_SETTINGS_OK" not in output:
        raise SystemExit(output)
    if (base / "injected").exists():
        raise SystemExit("Config path was evaluated as a command")
    print("OK: actual Quickshell Process serializes settings, preserves unknown keys and treats the config path as data")
