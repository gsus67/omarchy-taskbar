import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import qs.Commons
import qs.Commons as Commons
import qs.Ui

// A second bar along the bottom edge of every screen, built from the same
// theme tokens as Omarchy's own bar (size, colors, font, transparency).
// Pinned apps come first, then every other open app, all centered. A mark
// under an icon means the app has windows; the focused app gets a wider mark
// in the accent color.
Item {
  id: root

  property var shell
  property var manifest
  property string omarchyPath: ""

  readonly property bool spanish: Qt.locale().name.indexOf("es") === 0
  function t(english, spanishText) { return spanish ? spanishText : english }

  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")
  readonly property string pluginDirectory: decodeURIComponent(
    Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "").replace(/\/$/, ""))
  readonly property string pinsPath: configHome + "/omarchy-taskbar/pinned.json"
  readonly property int barSize: Math.round(Style.bar.sizeHorizontal * configuredScale)
  readonly property int iconSize: Math.round(barSize * 0.66)
  readonly property color foreground: Commons.Color.bar.text

  property var pinned: []
  property bool transparent: false
  property var configuredWidth: null
  property real configuredScale: 1

  // The one right-click menu open, if any. Opening another or clicking the
  // bar closes it.
  property var openMenu: null

  function showMenu(menu) {
    if (root.openMenu && root.openMenu !== menu) root.openMenu.visible = false
    root.openMenu = menu
    menu.visible = true
  }

  function closeMenu() {
    if (root.openMenu) root.openMenu.visible = false
    root.openMenu = null
  }

  // ------------------------------------------------------------ transparency

  // Same switch as Omarchy's bar: `bar.transparent` in shell.json. Watching
  // the file keeps both bars in step whichever one was double-clicked.
  FileView {
    id: shellFile
    path: root.configHome + "/omarchy/shell.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var config = JSON.parse(text())
        root.transparent = !!(config.bar && config.bar.transparent === true)
      } catch (e) {}
    }
  }

  function toggleTransparent() {
    Quickshell.execDetached(["omarchy", "bar", "transparent", "toggle"])
  }

  // ------------------------------------------------------------ bar size

  // Optional settings. Missing or invalid config keeps the
  // full-width bar; each screen resolves percentages against its own width.
  FileView {
    id: configFile
    path: root.configHome + "/omarchy-taskbar/config.json"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var config = JSON.parse(text())
        root.configuredWidth = config && typeof config === "object" && !Array.isArray(config) ? config.width : null
        root.configuredScale = root.scaleFor(config && config.scale)
      } catch (e) {
        root.configuredWidth = null
        root.configuredScale = 1
      }
    }
    onLoadFailed: {
      root.configuredWidth = null
      root.configuredScale = 1
    }
  }

  function scaleFor(value) { return [1, 1.25, 1.5, 2].indexOf(value) !== -1 ? value : 1 }

  function widthFor(value, screenWidth, barSize) {
    var width = typeof value === "number" ? value : NaN
    if (typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)%$/.test(value.trim()))
      width = screenWidth * (parseFloat(value) / 100)
    if (!isFinite(width)) return screenWidth
    return Math.min(screenWidth, Math.max(barSize * 2, Math.round(width)))
  }

  function saveConfig(key, value) {
    var config = {}
    try {
      var parsed = JSON.parse(configFile.text())
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) config = parsed
    } catch (e) {}
    if (value === null) delete config[key]
    else config[key] = value
    Quickshell.execDetached(["bash", "-c",
      'if [[ -z $2 ]]; then rm -f -- "$1"; else '
      + 'mkdir -p -- "${1%/*}" || exit; tmp=$(mktemp -- "$1.XXXXXX") || exit; '
      + 'trap \'rm -f -- "$tmp"\' EXIT; printf "%s\\n" "$2" >"$tmp" && mv -f -- "$tmp" "$1"; fi',
      "omarchy-taskbar", configFile.path, Object.keys(config).length ? JSON.stringify(config, null, 2) : ""])
  }

  // ------------------------------------------------------------ pinned apps

  FileView {
    id: pinsFile
    path: root.pinsPath
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: {
      try {
        var list = JSON.parse(text())
        root.pinned = Array.isArray(list) ? list.map(String) : []
      } catch (e) {
        root.pinned = []
      }
    }
    onLoadFailed: function(error) {
      if (error === FileViewError.FileNotFound) seedProc.running = true
    }
  }

  // First run: pin the default browser (the real one behind Omarchy's
  // launcher), file manager and terminal.
  Process {
    id: seedProc
    command: ["bash", "-c",
      'term=$(grep -v "^#" "${XDG_CONFIG_HOME:-$HOME/.config}/xdg-terminals.list" 2>/dev/null | head -n1); '
      + 'printf "%s\\n" "$(omarchy-cmd-default-browser 2>/dev/null)" '
      + '"$(xdg-mime query default inode/directory 2>/dev/null)" "$term"']
    stdout: StdioCollector {
      onStreamFinished: {
        var ids = []
        text.split("\n").forEach(function(line) {
          var id = line.trim().replace(/\.desktop$/, "")
          if (id !== "" && ids.indexOf(id) === -1 && DesktopEntries.byId(id)) ids.push(id)
        })
        root.savePins(ids)
      }
    }
  }

  function savePins(list) {
    root.pinned = list
    Quickshell.execDetached(["bash", "-c", 'mkdir -p -- "${1%/*}" && printf "%s\\n" "$2" >"$1"',
      "omarchy-taskbar", root.pinsPath, JSON.stringify(list, null, 2)])
  }

  function isPinned(key) { return root.pinned.indexOf(key) !== -1 }

  function togglePin(key) {
    var list = root.pinned.slice()
    var at = list.indexOf(key)
    if (at === -1) list.push(key)
    else {
      list.splice(at, 1)
      root.queuePinChange("remove", key)
    }
    savePins(list)
  }

  function movePin(app, index) {
    if (!app || index < 0 || (!root.isPinned(app.key) && !root.canPin(app))) return
    var list = root.pinned.slice()
    var at = list.indexOf(app.key)
    if (at !== -1) {
      list.splice(at, 1)
      if (at < index) index -= 1
    }
    list.splice(index, 0, app.key)
    if (JSON.stringify(list) !== JSON.stringify(root.pinned)) root.savePins(list)
  }

  // File operations run in order, including removal, so a quick unpin cannot
  // race a drop that is still creating its desktop entry.
  property var pinChanges: []

  function queuePinChange(operation, value) {
    root.pinChanges = root.pinChanges.concat([{ operation: operation, value: value }])
    if (!pinChangeProc.running) nextPinChange()
  }

  function nextPinChange() {
    if (root.pinChanges.length === 0) return
    pinChangeProc.change = root.pinChanges[0]
    root.pinChanges = root.pinChanges.slice(1)
    pinChangeProc.running = true
  }

  function droppedPath(url) {
    var match = /^file:\/\/(?:localhost)?(\/[^?#]*)$/.exec(String(url))
    if (!match) return ""
    try {
      var path = decodeURIComponent(match[1])
      return /[\x00-\x1f\x7f-\x9f]/.test(path) ? "" : path
    } catch (e) { return "" }
  }

  Process {
    id: pinChangeProc
    property var change: ({ operation: "", value: "" })
    command: ["bash", root.pluginDirectory + "/bin/pin-file.sh", change.operation, change.value,
      JSON.stringify(DesktopEntries.applications.values.map(function(entry) { return String(entry.id) }))]
    stdout: StdioCollector {
      onStreamFinished: {
        var id = text.replace(/\n$/, "")
        if (pinChangeProc.change.operation === "add" && id !== "" && !/[\x00-\x1f\x7f-\x9f]/.test(id)
            && !root.isPinned(id)) root.savePins(root.pinned.concat([id]))
      }
    }
    onExited: root.nextPinChange()
  }

  // ------------------------------------------------------------ apps model

  // Omarchy web apps run as Chromium --app windows named
  // "chrome-<host>__<path>-<profile>"; the heuristic lookup would match the
  // browser. Their desktop entries launch omarchy-launch-webapp (or --app=)
  // with the URL, so the host links each window to its own entry and icon.
  readonly property var webApps: {
    var map = ({})
    DesktopEntries.applications.values.forEach(function(entry) {
      var exec = String(entry.execString || "")
      if (exec.indexOf("omarchy-launch-webapp") === -1 && exec.indexOf("--app=") === -1) return
      var match = /https?:\/\/([^\/\s"':]+)/.exec(exec)
      if (match && !(match[1].toLowerCase() in map)) map[match[1].toLowerCase()] = entry
    })
    return map
  }

  // Omarchy's own web app handlers (omarchy-webapp-handler-hey, -zoom…) keep
  // the URL in the script: their name is matched against the host's labels.
  readonly property var webHandlers: {
    var map = ({})
    DesktopEntries.applications.values.forEach(function(entry) {
      var first = String((entry.command || [])[0] || "").split("/").pop()
      if (first.indexOf("omarchy-webapp-handler-") === 0) map[first.slice(23).toLowerCase()] = entry
    })
    return map
  }

  function webAppEntry(appId) {
    var match = /^(?:chrome|chromium|brave|msedge|vivaldi)-(.+?)__/.exec(appId)
    if (!match) return null
    var host = match[1].toLowerCase()
    if (root.webApps[host]) return root.webApps[host]
    var labels = host.split(".")
    for (var i = 0; i < labels.length; i++)
      if (labels[i].length >= 3 && root.webHandlers[labels[i]]) return root.webHandlers[labels[i]]
    return null
  }

  // Desktop entries by the program they run (first word of Exec after
  // launchers like uwsm/setsid/env), cut to 15 characters like a process name.
  // Used to find the entry of a script that opened a window under another
  // program (e.g. omarchy-windows-vm opening xfreerdp).
  readonly property var programs: {
    var map = ({})
    DesktopEntries.applications.values.forEach(function(entry) {
      var words = (entry.command || []).map(String)
      // Skip launchers, their options (env --unset=X) and VAR=value pairs.
      while (words.length > 0 && (/^(uwsm|uwsm-app|app|--|setsid|env)$/.test(words[0].split("/").pop())
                                  || /^[A-Za-z_]+=/.test(words[0]) || /^-/.test(words[0])))
        words.shift()
      if (words.length === 0) return
      var key = words[0].split("/").pop().slice(0, 15)
      if (key !== "" && !(key in map)) map[key] = entry
    })
    return map
  }

  // Entries that open a program inside a terminal ("-e prog" or
  // "-e bash -c 'prog …'"), by that program, plus their names and icons,
  // to recognise Omarchy's TUI windows (class TUI.tile/TUI.float) by what
  // runs inside them.
  readonly property var terminalApps: {
    var list = []
    DesktopEntries.applications.values.forEach(function(entry) {
      var words = (entry.command || []).map(String)
      var at = words.indexOf("-e")
      if (at === -1 || at + 1 >= words.length) return
      var program = words[at + 1].split("/").pop()
      if (/^(ba)?sh$/.test(program) && words[at + 2] === "-c" && words[at + 3])
        program = words[at + 3].trim().split(/\s+/)[0].split("/").pop()
      list.push({ entry: entry, program: program.slice(0, 15),
                  hints: [String(entry.icon || "").toLowerCase(), String(entry.name || "").toLowerCase().replace(/\s+/g, "")]
                           .filter(function(hint) { return hint.length >= 4 }) })
    })
    return list
  }

  function isTerminal(entry) {
    return !!entry && (entry.categories || []).map(String).indexOf("TerminalEmulator") !== -1
  }

  // Shells and multiplexers inside a terminal: still just a terminal.
  readonly property var shellNames: /^((ba|z|da)?sh|fish|nu|tmux|zellij|screen|ssh|s[u](do)?|do[a]s|login|env)$/

  // The app running inside a terminal window, from one process name: a
  // terminal app ("-e prog"), an entry that runs it (e.g. cliamp), or an entry
  // whose program or name contains it (e.g. voxtype → voxtype-configure).
  function appInside(processName) {
    if (processName === "" || root.shellNames.test(processName)) return null
    var entry = terminalAppFor(processName)
    if (entry) return entry
    entry = root.programs[processName]
    if (entry && !isTerminal(entry)) return entry
    if (processName.length < 4) return null
    var all = DesktopEntries.applications.values
    for (var i = 0; i < all.length; i++) {
      if (isTerminal(all[i])) continue
      var words = (all[i].command || []).map(String)
      var program = String(words[0] || "").split("/").pop().toLowerCase()
      var name = String(all[i].name || "").toLowerCase().replace(/\s+/g, "")
      if (program.indexOf(processName) === 0 || name.indexOf(processName) === 0) return all[i]
    }
    return null
  }

  // The terminal app whose program is (or whose name/icon appears in) a
  // process name running inside the window.
  function terminalAppFor(processName) {
    var name = processName.toLowerCase()
    for (var i = 0; i < root.terminalApps.length; i++)
      if (root.terminalApps[i].program === processName) return root.terminalApps[i].entry
    for (var j = 0; j < root.terminalApps.length; j++)
      if (root.terminalApps[j].hints.some(function(hint) { return name.indexOf(hint) !== -1 })) return root.terminalApps[j].entry
    return null
  }

  // How a window is looked up: by class, except Omarchy's TUI windows, which
  // share a class and are told apart one by one (by Hyprland address).
  function lookupFor(toplevel) {
    var appId = String(toplevel.appId || "")
    // Terminals too: each window may be running a different app.
    if (appId.indexOf("TUI.") !== 0 && !isTerminal(entryFor(appId))) return appId
    var hypr = hyprlandOf(toplevel)
    var address = hypr ? String(hypr.address) : ""
    if (address !== "" && !/^0x/.test(address)) address = "0x" + address
    return /^0x[0-9a-fA-F]+$/.test(address) ? "@" + address : appId
  }

  function entryFor(appId) {
    if (!appId) return null
    return webAppEntry(appId) || DesktopEntries.heuristicLookup(appId)
  }

  // A window's own entry, or the one of the program behind it (found later
  // through its process), so e.g. a terminal with its own class joins the
  // terminal's button and can be pinned like it.
  function windowEntry(appId, lookup) {
    var entry = lookup.charAt(0) === "@" ? null : entryFor(appId)
    if (entry) return entry
    var found = root.fallbacks[lookup]
    // A terminal window with nothing but a shell inside stays the terminal.
    if (lookup.charAt(0) === "@" && !(found && found.entry !== "")) return entryFor(appId)
    return found && found.entry !== "" ? DesktopEntries.byId(found.entry) : null
  }

  // The button a window belongs to: its entry id, else the program's path,
  // else its class. Pinned keys are the same ids or paths.
  function keyFor(toplevel) {
    var appId = String(toplevel.appId || "")
    var lookup = lookupFor(toplevel)
    var entry = windowEntry(appId, lookup)
    if (entry) return entry.id
    var found = root.fallbacks[lookup]
    return found && found.exe !== "" && lookup.charAt(0) !== "@" ? found.exe : lookup
  }

  readonly property var apps: {
    var list = []
    var seen = ({})
    DesktopEntries.applications.values // re-evaluate when apps are installed
    root.pinned.forEach(function(id) {
      // A pinned program without a desktop entry is kept as its path.
      if (id.charAt(0) === "/") {
        if (seen[id]) return
        seen[id] = true
        list.push({ key: id, entry: null, appId: "", lookup: "", exe: id })
        return
      }
      var entry = DesktopEntries.byId(id)
      if (!entry || seen[entry.id]) return
      seen[entry.id] = true
      list.push({ key: entry.id, entry: entry, appId: "", lookup: "", exe: "" })
    })
    ToplevelManager.toplevels.values.forEach(function(toplevel) {
      var appId = String(toplevel.appId || "")
      var lookup = root.lookupFor(toplevel)
      var found = root.fallbacks[lookup]
      // Every terminal window is asked once what runs inside it, even when it
      // is grouped under the terminal's button for now.
      if (lookup.charAt(0) === "@" && !found) Qt.callLater(root.lookupIcon, lookup)
      var key = root.keyFor(toplevel)
      if (key === "" || seen[key]) return
      seen[key] = true
      list.push({ key: key, entry: root.windowEntry(appId, lookup), appId: appId, lookup: lookup, exe: found ? found.exe : "" })
    })
    return list
  }

  function windowsFor(key) {
    return ToplevelManager.toplevels.values.filter(function(toplevel) {
      return root.keyFor(toplevel) === key
    })
  }

  // From the desktop entry; for a window without one (e.g. a terminal started
  // with its own class), the entry or program found behind its process.
  function launch(app) {
    if (app.entry) { launchEntry(app.entry); return }
    if (app.exe) { Quickshell.execDetached(["uwsm-app", "--", app.exe]); return }
    var found = root.fallbacks[app.lookup]
    if (!found) return
    if (found.entry !== "") launchEntry(DesktopEntries.byId(found.entry))
    else if (found.exe !== "") Quickshell.execDetached(["uwsm-app", "--", found.exe])
  }

  // uwsm-app rejects desktop ids that are not valid ids, such as web apps
  // named "Google Maps.desktop"; those run the entry's own command instead.
  function launchEntry(entry) {
    if (!entry) return
    if (/^[A-Za-z0-9._-]+$/.test(entry.id)) Quickshell.execDetached(["uwsm-app", "--", entry.id + ".desktop"])
    else if (entry.command && entry.command.length > 0) Quickshell.execDetached(["uwsm-app", "--"].concat(entry.command))
  }

  function canLaunch(app) {
    var found = root.fallbacks[app.lookup]
    return !!app.entry || !!app.exe || !!(found && (found.entry !== "" || found.exe !== ""))
  }

  // Anything the bar can start again can be pinned: an entry or a program path.
  function canPin(app) { return !!app.entry || (app.key.charAt(0) === "/" && !!app.exe) }

  // Not running: start it. Running elsewhere: bring its window up. Already
  // focused with several windows: step to the next one.
  function activate(app) {
    var windows = windowsFor(app.key)
    if (windows.length === 0) {
      launch(app)
      return
    }
    var current = -1
    for (var i = 0; i < windows.length; i++)
      if (windows[i].activated) current = i
    if (current === -1) windows[0].activate()
    else if (windows.length > 1) windows[(current + 1) % windows.length].activate()
  }

  // Hyprland's view of a window: its workspace and address.
  function hyprlandOf(toplevel) {
    var all = Hyprland.toplevels.values
    for (var i = 0; i < all.length; i++) if (all[i].wayland === toplevel) return all[i]
    return null
  }

  function workspaceOf(toplevel) {
    var hypr = hyprlandOf(toplevel)
    return hypr && hypr.workspace ? String(hypr.workspace.name) : ""
  }

  // Jumps to one window, switching to its workspace. The address comes from
  // Hyprland and is checked to be hex before it goes into the dispatch.
  function focusWindow(toplevel) {
    var hypr = hyprlandOf(toplevel)
    var address = hypr ? String(hypr.address) : ""
    if (!/^0x/.test(address)) address = "0x" + address
    if (/^0x[0-9a-fA-F]+$/.test(address))
      Quickshell.execDetached(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "address:' + address + '" })'])
    else toplevel.activate()
  }

  function closeAll(app) {
    windowsFor(app.key).forEach(function(toplevel) { toplevel.close() })
  }

  // ------------------------------------------------------------ icons

  // Ported from Omarchy's shell/services/AppLibrary.qml: panel plugins do
  // not receive shell.appLibrary. The index bypasses stale theme caches.
  property var iconIndex: ({})
  property var pendingIconIndex: ({})

  function iconSource(icon) {
    var value = String(icon || "")
    if (value.length === 0) return Quickshell.iconPath("application-x-executable", true)
    if (value.indexOf("file://") === 0 || value.indexOf("image://") === 0) return value
    if (value.charAt(0) === "/") return Util.fileUrl(value)
    // Prefer app/device icons: a themed lookup can pick an action such as zoom.
    var found = root.iconIndex[value]
    if (found) return Util.fileUrl(found)
    var themed = Quickshell.iconPath(value, true)
    if (themed.length > 0) return themed
    return Quickshell.iconPath("application-x-executable", true)
  }

  function iconFor(app) {
    var found = root.fallbacks[app.lookup]
    // A pinned program path: its file name ("/usr/bin/foot" → "foot").
    var own = app.appId !== "" ? app.appId.toLowerCase() : String(app.exe || "").split("/").pop()
    var name = app.entry && app.entry.icon ? app.entry.icon : (found && found.icon) || own
    if (!app.entry && app.lookup !== "") Qt.callLater(root.lookupIcon, app.lookup)
    return root.iconSource(name)
  }

  function refreshIcons() {
    if (!iconIndexScan.running) iconIndexScan.running = true
  }

  function indexIconLine(path) {
    var value = String(path || "").trim()
    if (value.length === 0) return
    var slash = value.lastIndexOf("/")
    var file = slash >= 0 ? value.slice(slash + 1) : value
    var dot = file.lastIndexOf(".")
    var name = dot > 0 ? file.slice(0, dot) : file
    if (name.length > 0 && root.pendingIconIndex[name] === undefined)
      root.pendingIconIndex[name] = value
  }

  Process {
    id: iconIndexScan
    // Non-login shell: profile activation can touch the watched desktop-entry
    // dirs and trigger an endless rescan. $1: home, $2: XDG dirs, $3: pixmaps.
    // Match Omarchy's dirs and app/device contexts, emitting SVGs before PNGs
    // so the first hit per name prefers a scalable icon. Arrays preserve spaces.
    command: ["bash", "-c",
      'bases=("$1/.icons" "$1/.local/share/icons"); '
      + 'IFS=: read -r -a data_dirs <<< "$2"; '
      + 'for d in "${data_dirs[@]}"; do bases+=("$d/icons"); done; '
      + 'for ext in svg png; do for base in "${bases[@]}"; do '
      + '[[ -d $base ]] && find "$base" \\( -path "*/apps/*" -o -path "*/devices/*" \\) -name "*.$ext" 2>/dev/null; '
      + 'done; find "$3" -maxdepth 1 -name "*.$ext" 2>/dev/null; done', "omarchy-taskbar",
      Quickshell.env("HOME"), Quickshell.env("XDG_DATA_DIRS") || "/usr/local/share:/usr/share", "/usr/share/pixmaps"]
    stdout: SplitParser { onRead: function(line) { root.indexIconLine(line) } }
    onStarted: root.pendingIconIndex = ({})
    // Replace the property only when complete, re-evaluating icon bindings.
    onExited: root.iconIndex = root.pendingIconIndex
  }

  Timer {
    id: iconIndexDebounce
    interval: 750
    onTriggered: root.refreshIcons()
  }

  Connections {
    target: DesktopEntries.applications
    function onValuesChanged() { iconIndexDebounce.restart() }
  }

  Component.onCompleted: root.refreshIcons()

  // A window whose class has no desktop entry (e.g. `foot --app-id=x`) borrows
  // the icon, entry and program of the process behind it: { icon, entry, exe }.
  // Asked once per class.
  property var fallbacks: ({})
  property var iconQueue: []

  function lookupIcon(appId) {
    if (appId === "" || appId in root.fallbacks || root.iconQueue.indexOf(appId) !== -1) return
    root.iconQueue = root.iconQueue.concat([appId])
    if (!iconProc.running) nextIcon()
  }

  function nextIcon() {
    if (root.iconQueue.length === 0) return
    iconProc.appId = root.iconQueue[0]
    root.iconQueue = root.iconQueue.slice(1)
    iconProc.running = true
  }

  Process {
    id: iconProc
    property string appId: ""
    // $1 is a class, or "@0x…" for one window by address. Prints the program
    // name, its executable path, the names of up to four parent processes,
    // "--", then the names of the processes running inside it (two levels).
    // Only process names (comm) and the executable path are read: never a
    // command line, which can hold secrets (e.g. the Windows VM password
    // passed to xfreerdp).
    command: ["bash", "-c",
      'if [[ $1 == @* ]]; then f=\'.address == $c\'; c=${1#@}; else f=\'.class == $c\'; c=$1; fi; '
      + 'pid=$(hyprctl clients -j | jq -r --arg c "$c" "first(.[] | select($f) | .pid) // empty"); '
      + '[[ $pid =~ ^[0-9]+$ ]] || exit 0; cat "/proc/$pid/comm"; readlink -f "/proc/$pid/exe"; p=$pid; '
      + 'for _ in 1 2 3 4; do p=$(sed "s/.*) //" "/proc/$p/stat" 2>/dev/null | cut -d" " -f2); '
      + '[[ $p =~ ^[0-9]+$ && $p -gt 1 ]] || break; cat "/proc/$p/comm"; done; echo --; '
      + 'for c in $(cat /proc/"$pid"/task/*/children 2>/dev/null); do cat "/proc/$c/comm"; '
      + 'for g in $(cat /proc/"$c"/task/*/children 2>/dev/null); do cat "/proc/$g/comm"; done; done', "omarchy-taskbar", appId]
    stdout: StdioCollector {
      onStreamFinished: {
        var lines = text.split("\n").map(function(line) { return line.trim() })
        var split = lines.indexOf("--")
        var parents = lines.slice(2, split === -1 ? lines.length : split)
        var children = split === -1 ? [] : lines.slice(split + 1).filter(function(line) { return line !== "" })
        var own = lines[0] || ""
        var entry = null
        if (iconProc.appId.charAt(0) === "@") {
          // A terminal window: the app is what runs inside it.
          for (var c = 0; !entry && c < children.length; c++) entry = root.appInside(children[c])
        } else {
          entry = root.entryFor(own) || root.programs[own] || null
          // Not found: the entry of a parent (the script that opened it).
          for (var i = 0; !entry && i < parents.length; i++)
            if (parents[i] in root.programs) entry = root.programs[parents[i]]
        }
        var exe = (lines[1] || "").trim()
        var known = Object.assign({}, root.fallbacks)
        known[iconProc.appId] = {
          icon: entry && entry.icon ? entry.icon : "",
          entry: entry ? entry.id : "",
          // Only an absolute path to a real program; nothing else is run.
          exe: /^\/[^\0\n]+$/.test(exe) ? exe : ""
        }
        root.fallbacks = known
      }
    }
    onExited: root.nextIcon()
  }

  // ------------------------------------------------------------ the bar

  Variants {
    model: Quickshell.screens

    delegate: Component {
      PanelWindow {
        id: barWindow
        required property var modelData
        readonly property int targetWidth: root.widthFor(root.configuredWidth, modelData.width, root.barSize)

        // Reuse Omarchy's Bar.qml drag threshold, captured ghost and marker.
        // Each screen owns its gesture; only the saved pins are shared.
        property var barDragSource: null
        property var barDragTarget: null
        property bool barDragAfter: false
        property int barDragIndex: -1
        property var barDragTargetGeometry: null
        property url barDragImageUrl: ""
        property point barDragScreenPoint: Qt.point(0, 0)
        property point barDragOffset: Qt.point(0, 0)

        function clearBarDrag() {
          barDragSource = null
          barDragTarget = null
          barDragAfter = false
          barDragIndex = -1
          barDragTargetGeometry = null
          barDragImageUrl = ""
          barDragScreenPoint = Qt.point(0, 0)
          barDragOffset = Qt.point(0, 0)
        }

        function captureBarDragGhost(button) {
          var item = button.activeItem
          item.grabToImage(function(result) {
            if (barWindow.barDragSource === button && result && result.url)
              barWindow.barDragImageUrl = result.url
          }, Qt.size(Math.max(1, Math.ceil(item.width)), Math.max(1, Math.ceil(item.height))))
        }

        function screenPoint(point) {
          return Qt.point(point.x + margins.left, point.y + screen.height - height)
        }

        function updateBarDrag(button, x, y) {
          var point = button.mapToItem(null, x, y)
          barDragScreenPoint = screenPoint(point)
          barDragTarget = null
          barDragAfter = false
          barDragIndex = -1
          barDragTargetGeometry = null
          if (point.x < 0 || point.x >= width || point.y < 0 || point.y >= height) return
          // Returning to the source icon is a no-op, including an unpinned app.
          if (x >= 0 && x < button.width && y >= 0 && y < button.height) return

          var bestDistance = Infinity
          for (var i = 0; i < appButtons.count; i++) {
            var slot = appButtons.itemAt(i)
            if (!slot) continue
            var start = slot.mapToItem(null, 0, 0)
            var pinIndex = root.pinned.indexOf(slot.app.key)
            var beforeDistance = Math.abs(point.x - start.x)
            var afterDistance = pinIndex < 0 ? Infinity : Math.abs(point.x - start.x - slot.width)
            var after = afterDistance < beforeDistance
            var distance = Math.min(beforeDistance, afterDistance)
            if (distance < bestDistance) {
              bestDistance = distance
              barDragTarget = slot
              barDragAfter = after
              barDragIndex = pinIndex < 0 ? root.pinned.length : pinIndex + (after ? 1 : 0)
              var marker = screenPoint(Qt.point(start.x + (after ? slot.width : 0), start.y))
              var thickness = Style.spacing.xs
              barDragTargetGeometry = { x: marker.x - thickness / 2, y: marker.y,
                width: thickness, height: slot.height }
            }
            // Pins stay first; the first running icon marks the end of them.
            if (pinIndex < 0) break
          }
        }

        screen: modelData
        anchors {
          bottom: true
          left: true
          right: true
        }
        // Keep three anchors so Auto still reserves the bar's height.
        margins.left: Math.floor((modelData.width - targetWidth) / 2)
        margins.right: Math.ceil((modelData.width - targetWidth) / 2)
        implicitHeight: root.barSize
        exclusionMode: ExclusionMode.Auto
        color: root.transparent ? "transparent" : Commons.Color.bar.background
        surfaceFormat.opaque: false
        WlrLayershell.namespace: "omarchy-taskbar"
        WlrLayershell.layer: WlrLayer.Top
        onWidthChanged: clearBarDrag()
        onHeightChanged: clearBarDrag()

        DragGhostPanel { bar: barWindow }

        DropArea {
          anchors.fill: parent
          keys: ["text/uri-list"]
          onDropped: function(drop) {
            if (!drop.hasUrls) return
            var accepted = false
            drop.urls.forEach(function(url) {
              var path = root.droppedPath(url)
              if (path === "") return
              root.queuePinChange("add", path)
              accepted = true
            })
            if (accepted) drop.accept(Qt.CopyAction)
          }
        }

        // Empty bar space: size menu and double-click transparency.
        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.LeftButton | Qt.RightButton
          onPressed: root.closeMenu()
          onClicked: function(event) {
            if (event.button === Qt.RightButton) {
              sizeMenu.anchor.rect.x = event.x
              sizeMenu.anchor.rect.y = event.y
              root.showMenu(sizeMenu)
            }
          }
          onDoubleClicked: function(event) {
            if (event.button === Qt.LeftButton) root.toggleTransparent()
          }
        }

        Row {
          anchors.centerIn: parent
          height: parent.height
          spacing: Style.space(2)

          Repeater {
            id: appButtons
            model: root.apps

            delegate: AppButton {
              required property var modelData
              app: modelData
              bar: barWindow
            }
          }
        }

        PopupWindow {
          id: sizeMenu
          visible: false
          anchor.window: barWindow
          anchor.rect.width: 1
          anchor.rect.height: 1
          anchor.edges: Edges.Top
          anchor.gravity: Edges.Top
          anchor.margins.top: -Style.space(4)
          implicitWidth: sizeColumn.implicitWidth + Style.space(8)
          implicitHeight: sizeColumn.implicitHeight + Style.space(8)
          color: "transparent"

          Rectangle {
            anchors.fill: parent
            focus: true
            Keys.onEscapePressed: root.closeMenu()
            color: Commons.Color.menu.background
            border.color: Commons.Color.menu.border
            border.width: Style.normalBorderWidth
            radius: Style.cornerRadius

            Column {
              id: sizeColumn
              anchors.centerIn: parent

              Repeater {
                model: [1, 1.25, 1.5, 2]
                delegate: MenuRow {
                  required property var modelData
                  text: modelData + "x"
                  checkable: true
                  checked: root.configuredScale === modelData
                  onTriggered: { root.closeMenu(); root.saveConfig("scale", modelData === 1 ? null : modelData) }
                }
              }
            }
          }

          onVisibleChanged: {
            if (visible) Qt.callLater(function() { sizeGrab.active = sizeMenu.visible })
            else sizeGrab.active = false
          }

          HyprlandFocusGrab {
            id: sizeGrab
            windows: [sizeMenu, barWindow]
            onCleared: if (root.openMenu === sizeMenu) root.closeMenu()
          }
        }
      }
    }
  }

  component DragGhostPanel: PanelWindow {
    id: ghostWindow
    required property var bar
    readonly property var sourceItem: bar.barDragSource ? bar.barDragSource.activeItem : null
    readonly property int ghostPadding: Style.space(1)

    screen: bar.screen
    visible: sourceItem !== null
    color: "transparent"
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.namespace: "omarchy-taskbar-drag-ghost"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    anchors { top: true; bottom: true; left: true; right: true }
    // Keep the pointer grab on the source icon, as in Omarchy's bar.
    mask: Region {}

    Item {
      x: Math.round(bar.barDragScreenPoint.x - bar.barDragOffset.x - ghostWindow.ghostPadding)
      y: Math.round(bar.barDragScreenPoint.y - bar.barDragOffset.y - ghostWindow.ghostPadding)
      width: (ghostWindow.sourceItem ? ghostWindow.sourceItem.width : 1) + ghostWindow.ghostPadding * 2
      height: (ghostWindow.sourceItem ? ghostWindow.sourceItem.height : 1) + ghostWindow.ghostPadding * 2

      BorderSurface {
        anchors.fill: parent
        color: root.transparent ? "transparent" : Commons.Color.bar.background
        borderSpec: Border.flat(root.foreground, 1)
        radius: Math.min(Style.cornerRadius, height / 2)
        opacity: root.transparent ? 0.45 : 0.94
      }

      Image {
        anchors.fill: parent
        anchors.margins: ghostWindow.ghostPadding
        source: bar.barDragImageUrl
        fillMode: Image.Stretch
        smooth: true
        opacity: 0.84
      }
    }

    Rectangle {
      readonly property var targetRect: bar.barDragTargetGeometry
      visible: ghostWindow.visible && targetRect !== null
      x: targetRect ? Math.round(targetRect.x) : 0
      y: targetRect ? Math.round(targetRect.y) : 0
      width: targetRect ? targetRect.width : 0
      height: targetRect ? targetRect.height : 0
      color: Commons.Color.accent
      radius: Math.min(width, height) / 2
    }
  }

  component AppButton: Item {
    id: button

    property var app
    required property var bar
    readonly property var activeItem: appVisual
    readonly property bool dragSource: bar.barDragSource === button
    readonly property var windows: root.windowsFor(app.key)
    readonly property bool running: windows.length > 0
    readonly property bool focused: windows.some(function(toplevel) { return toplevel.activated })
    // App name; a window without a desktop entry uses its own title.
    // Several windows: "Name (3)".
    readonly property string label: {
      var name = app.entry ? app.entry.name : ""
      if (name === "" && windows.length > 0) name = windows[0].title || ""
      if (name === "") name = app.appId || String(app.exe || "").split("/").pop()
      return windows.length > 1 ? name + " (" + windows.length + ")" : name
    }

    width: root.barSize + Style.space(8)
    height: root.barSize

    Component.onDestruction: if (bar.barDragSource === button) bar.clearBarDrag()

    BorderSurface {
      visible: button.dragSource
      anchors.fill: parent
      anchors.margins: Style.space(1)
      color: root.transparent ? "transparent" : Commons.Color.bar.background
      borderSpec: Border.flat(root.foreground, 1)
      radius: Math.min(Style.cornerRadius, height / 2)
      opacity: root.transparent ? 0.22 : 0.32
    }

    Item {
      id: appVisual
      anchors.fill: parent
      opacity: button.dragSource ? 0.22 : 1.0

      Rectangle {
        anchors.fill: parent
        anchors.topMargin: Style.space(2)
        anchors.bottomMargin: Style.space(2)
        radius: Style.cornerRadius
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
        visible: mouse.containsMouse || menu.visible
      }

      Image {
        anchors.centerIn: parent
        anchors.verticalCenterOffset: -1
        width: root.iconSize
        height: root.iconSize
        sourceSize.width: root.iconSize * 2
        sourceSize.height: root.iconSize * 2
        source: root.iconFor(button.app)
        fillMode: Image.PreserveAspectFit
        smooth: true
        mipmap: true
      }

      Rectangle {
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 1
        anchors.horizontalCenter: parent.horizontalCenter
        height: 2
        radius: 1
        width: button.focused ? Style.space(12) : Style.space(4)
        visible: button.running
        color: button.focused ? Commons.Color.accent : root.foreground
        Behavior on width { NumberAnimation { duration: 120 } }
      }
    }

    MouseArea {
      id: mouse
      property bool dragging: false
      property bool suppressClick: false
      property real pressedX: 0
      property real pressedY: 0
      readonly property real dragThreshold: Style.space(4)

      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
      cursorShape: dragging ? Qt.ClosedHandCursor : Qt.ArrowCursor
      // Row owns the button's position. Move only the overlay ghost.
      onPressed: function(event) {
        dragging = false
        suppressClick = false
        pressedX = event.x
        pressedY = event.y
        bar.clearBarDrag()
      }
      onPositionChanged: function(event) {
        if (!pressed || !(event.buttons & Qt.LeftButton) || (!root.isPinned(button.app.key) && !root.canPin(button.app))) return
        var distance = Math.abs(event.x - pressedX) + Math.abs(event.y - pressedY)
        if (!dragging && distance >= dragThreshold) {
          root.closeMenu()
          bar.barDragOffset = Qt.point(pressedX, pressedY)
          bar.captureBarDragGhost(button)
          bar.barDragSource = button
          dragging = true
        }
        if (dragging && bar.barDragSource === button) bar.updateBarDrag(button, event.x, event.y)
      }
      onReleased: function(event) {
        var wasDragging = dragging
        if (wasDragging && bar.barDragSource === button) bar.updateBarDrag(button, event.x, event.y)
        var index = bar.barDragIndex
        suppressClick = wasDragging
        dragging = false
        bar.clearBarDrag()
        if (wasDragging && index >= 0) root.movePin(button.app, index)
      }
      onCanceled: {
        dragging = false
        suppressClick = true
        bar.clearBarDrag()
      }
      onClicked: function(event) {
        if (suppressClick) {
          suppressClick = false
          return
        }
        if (event.button === Qt.RightButton) {
          if (menu.visible) root.closeMenu()
          else root.showMenu(menu)
          return
        }
        // Several windows: pick one from the list (it may be on another workspace).
        if (event.button === Qt.LeftButton && button.windows.length > 1) {
          if (windowList.visible) root.closeMenu()
          else root.showMenu(windowList)
          return
        }
        root.closeMenu()
        if (event.button === Qt.LeftButton) root.activate(button.app)
        else root.launch(button.app)
      }
    }

    // Its own popup above the icon: a tooltip inside the bar window would be
    // clipped to the bar's height.
    Timer {
      id: tipDelay
      interval: 400
      running: mouse.containsMouse && !mouse.dragging && !menu.visible && !windowList.visible
    }

    // The app's windows, each with its workspace; a click jumps to it.
    PopupWindow {
      id: windowList
      visible: false
      anchor.item: button
      anchor.edges: Edges.Top
      anchor.gravity: Edges.Top
      anchor.margins.top: -Style.space(4)
      implicitWidth: windowColumn.implicitWidth + Style.space(8)
      implicitHeight: windowColumn.implicitHeight + Style.space(8)
      color: "transparent"

      Rectangle {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: root.closeMenu()
        color: Commons.Color.menu.background
        border.color: Commons.Color.menu.border
        border.width: Style.normalBorderWidth
        radius: Style.cornerRadius

        // Side by side, like other taskbars' window previews.
        Row {
          id: windowColumn
          anchors.centerIn: parent
          spacing: Style.space(2)

          Repeater {
            model: button.windows
            delegate: WindowRow {
              required property var modelData
              toplevel: modelData
              capture: windowList.visible
              icon: root.iconFor(button.app)
              title: modelData.title || button.label
              workspace: windowList.visible ? root.workspaceOf(modelData) : ""
              current: modelData.activated
              // Jump first: closing the list can tear the row down.
              onTriggered: {
                var target = modelData
                root.focusWindow(target)
                root.closeMenu()
              }
              // Close just this window; the list follows it, or goes when
              // it was the last one.
              onCloseRequested: {
                var last = button.windows.length <= 1
                modelData.close()
                if (last) root.closeMenu()
              }
            }
          }
        }
      }

      onVisibleChanged: {
        if (visible) Qt.callLater(function() { listGrab.active = windowList.visible })
        else listGrab.active = false
      }

      HyprlandFocusGrab {
        id: listGrab
        windows: [windowList, button.QsWindow.window]
        onCleared: if (root.openMenu === windowList) root.closeMenu()
      }
    }

    PopupWindow {
      id: tip
      visible: mouse.containsMouse && !mouse.dragging && !menu.visible && !windowList.visible && !tipDelay.running
      anchor.item: button
      anchor.edges: Edges.Top
      anchor.gravity: Edges.Top
      anchor.margins.top: -Style.space(6)
      implicitWidth: tipLabel.implicitWidth + Style.space(16)
      implicitHeight: tipLabel.implicitHeight + Style.space(10)
      color: "transparent"

      BorderSurface {
        anchors.fill: parent
        color: Commons.Color.tooltip.background
        borderSpec: Border.surfaceSpec("tooltip", "border", Commons.Color.tooltip.border, Style.normalBorderWidth)
        radius: Style.cornerRadius

        Text {
          id: tipLabel
          anchors.centerIn: parent
          textFormat: Text.PlainText
          text: button.label
          color: Commons.Color.tooltip.text
          font.family: Style.font.family
          font.pixelSize: Style.font.bodySmall
        }
      }
    }

    PopupWindow {
      id: menu
      visible: false
      anchor.item: button
      anchor.edges: Edges.Top
      anchor.gravity: Edges.Top
      anchor.margins.top: -Style.space(4)
      implicitWidth: menuColumn.implicitWidth + Style.space(8)
      implicitHeight: menuColumn.implicitHeight + Style.space(8)
      color: "transparent"

      Rectangle {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: root.closeMenu()
        color: Commons.Color.menu.background
        border.color: Commons.Color.menu.border
        border.width: Style.normalBorderWidth
        radius: Style.cornerRadius

        Column {
          id: menuColumn
          anchors.centerIn: parent

          MenuRow {
            text: root.isPinned(button.app.key) ? root.t("Unpin", "Desanclar") : root.t("Pin", "Anclar")
            shown: root.canPin(button.app) || root.isPinned(button.app.key)
            onTriggered: { root.closeMenu(); root.togglePin(button.app.key) }
          }
          MenuRow {
            text: root.t("New window", "Nueva ventana")
            shown: root.canLaunch(button.app)
            onTriggered: { root.closeMenu(); root.launch(button.app) }
          }
          MenuRow {
            text: button.windows.length > 1 ? root.t("Close all", "Cerrar todas") : root.t("Close", "Cerrar")
            shown: button.running
            onTriggered: { root.closeMenu(); root.closeAll(button.app) }
          }
        }
      }

      // Outside-click dismissal, as in Omarchy's PopupCard: while the grab is
      // active input only reaches the menu and the bar; a click anywhere else
      // clears it. Armed once the menu is mapped, or Hyprland ignores it.
      onVisibleChanged: {
        if (visible) Qt.callLater(function() { grab.active = menu.visible })
        else grab.active = false
      }

      HyprlandFocusGrab {
        id: grab
        windows: [menu, button.QsWindow.window]
        onCleared: if (root.openMenu === menu) root.closeMenu()
      }
    }
  }

  // A row of the window list: a thumbnail, then the title on the left and the
  // workspace on the right. The thumbnail is one frame taken while the list
  // is open (not live, never stored); without one the app icon stands in.
  component WindowRow: Rectangle {
    id: windowRow

    property var toplevel
    property bool capture: false
    property string icon
    property string title
    property string workspace
    property bool current: false
    signal triggered()
    signal closeRequested()

    readonly property int thumbWidth: Style.space(220)
    readonly property int thumbHeight: Math.round(thumbWidth * 9 / 16)

    width: thumbWidth + Style.space(24)
    height: thumbHeight + windowTitle.implicitHeight + Style.space(24)
    radius: Style.cornerRadius
    color: windowMouse.containsMouse ? Commons.Color.menu.selectedBackground : "transparent"

    Rectangle {
      id: thumbFrame
      anchors.top: parent.top
      anchors.topMargin: Style.space(8)
      anchors.horizontalCenter: parent.horizontalCenter
      width: windowRow.thumbWidth
      height: windowRow.thumbHeight
      radius: Style.cornerRadius
      color: Qt.rgba(0, 0, 0, 0.25)
      border.width: windowRow.current ? Style.normalBorderWidth : 0
      border.color: Commons.Color.accent
      clip: true

      Loader {
        id: thumbLoader
        anchors.fill: parent
        anchors.margins: Style.space(2)
        active: windowRow.capture && !!windowRow.toplevel
        sourceComponent: ScreencopyView {
          captureSource: windowRow.toplevel
          live: false
          paintCursor: false
          constraintSize: Qt.size(thumbLoader.width, thumbLoader.height)
        }
      }

      Image {
        anchors.centerIn: parent
        width: windowRow.thumbHeight / 2
        height: width
        visible: !(thumbLoader.item && thumbLoader.item.hasContent)
        source: windowRow.icon
        sourceSize.width: width * 2
        sourceSize.height: height * 2
        fillMode: Image.PreserveAspectFit
      }
    }

    Text {
      id: windowTitle
      textFormat: Text.PlainText
      anchors.top: thumbFrame.bottom
      anchors.topMargin: Style.space(6)
      anchors.left: parent.left
      anchors.leftMargin: Style.space(12)
      width: Math.min(implicitWidth, windowRow.width - windowSpace.implicitWidth - Style.space(36))
      elide: Text.ElideRight
      text: windowRow.title
      font.bold: windowRow.current
      color: windowMouse.containsMouse ? Commons.Color.menu.selectedText : Commons.Color.menu.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    Text {
      id: windowSpace
      textFormat: Text.PlainText
      anchors.verticalCenter: windowTitle.verticalCenter
      anchors.right: parent.right
      anchors.rightMargin: Style.space(12)
      text: windowRow.workspace === "" ? "" : root.t("Workspace ", "Escritorio ") + windowRow.workspace
      color: windowMouse.containsMouse ? Commons.Color.menu.selectedText : Commons.Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    // Middle click closes the window too, as on other taskbars.
    MouseArea {
      id: windowMouse
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton
      onClicked: function(event) {
        if (event.button === Qt.MiddleButton) windowRow.closeRequested()
        else windowRow.triggered()
      }
    }

    // Close button in the thumbnail's corner, like a window's own, shown while
    // hovering the row. Follows the theme's rounding and turns urgent on hover.
    Rectangle {
      anchors.top: thumbFrame.top
      anchors.right: thumbFrame.right
      width: closeGlyph.implicitHeight + Style.space(8)
      height: width
      radius: Style.cornerRadius
      visible: windowMouse.containsMouse || closeMouse.containsMouse
      color: closeMouse.containsMouse ? Commons.Color.urgent : Commons.Color.menu.background

      Text {
        id: closeGlyph
        anchors.centerIn: parent
        textFormat: Text.PlainText
        text: "\u{F0156}"
        color: closeMouse.containsMouse ? Commons.Color.background : Commons.Color.menu.text
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
      }

      MouseArea {
        id: closeMouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: windowRow.closeRequested()
      }
    }
  }

  component MenuRow: Rectangle {
    id: row

    property string text
    property bool shown: true
    property bool checkable: false
    property bool checked: false
    readonly property int checkWidth: checkable ? Style.space(20) : 0
    signal triggered()

    visible: shown
    width: Math.max(Style.space(140), rowLabel.implicitWidth + Style.space(24) + checkWidth)
    height: shown ? rowLabel.implicitHeight + Style.space(12) : 0
    radius: Style.cornerRadius
    color: rowMouse.containsMouse ? Commons.Color.menu.selectedBackground : "transparent"

    Text {
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.space(12)
      width: row.checkWidth
      text: row.checked ? "✓" : ""
      visible: row.checkable
      color: rowLabel.color
      font: rowLabel.font
    }

    Text {
      id: rowLabel
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.space(12) + row.checkWidth
      text: row.text
      color: rowMouse.containsMouse ? Commons.Color.menu.selectedText : Commons.Color.menu.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      onClicked: row.triggered()
    }
  }
}
