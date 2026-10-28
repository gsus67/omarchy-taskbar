#!/usr/bin/env python3
"""Check the actual QML debounce under a burst and while idle, without a desktop."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / "Taskbar.qml").read_text()
refresh = re.search(r"  function refreshIcons\([^\n]*\) \{.*?\n  \}", source, re.S).group(0)
debounce = re.search(r"  Timer \{\n    id: iconIndexDebounce\b.*?\n  \}", source, re.S).group(0)
harness = r'''import QtQuick
import Quickshell
ShellRoot {
    id: root
    property int scans: 0
    property int events: 0
    QtObject {
        id: iconIndexScan
        property bool running: false
        onRunningChanged: {
            if (running) {
                root.scans += 1;
                Qt.callLater(function() { iconIndexScan.running = false; });
            }
        }
    }
    Timer {
        interval: 10
        running: true
        repeat: true
        onTriggered: {
            iconIndexDebounce.restart();
            root.events += 1;
            if (root.events === 20) stop();
        }
    }
    Timer {
        interval: 2300
        running: true
        onTriggered: {
            if (root.events !== 20 || root.scans !== 1) {
                console.error("Expected one icon scan after the burst and no idle polling; got", root.events, root.scans);
                Qt.exit(1);
                return;
            }
            console.log("TASKBAR_NATIVE_RUNTIME_OK");
            Qt.quit();
        }
    }
REFRESH
DEBOUNCE
}
'''
with tempfile.TemporaryDirectory(prefix="taskbar-native-runtime-") as directory:
    base = Path(directory)
    (base / "runtime").mkdir(mode=0o700)
    (base / "shell.qml").write_text(harness.replace("REFRESH", refresh).replace("DEBOUNCE", debounce))
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", XDG_RUNTIME_DIR=str(base / "runtime"),
               DBUS_SESSION_BUS_ADDRESS="unix:path=" + str(base / "no-bus"))
    result = subprocess.run(["quickshell", "--no-color", "-p", str(base)],
                            env=env, text=True, capture_output=True, timeout=10)
    output = result.stdout + result.stderr
    if result.returncode or "TASKBAR_NATIVE_RUNTIME_OK" not in output:
        raise SystemExit(output)
    print("OK: the actual QML debounce coalesces 20 events into one scan and does not poll while idle")
