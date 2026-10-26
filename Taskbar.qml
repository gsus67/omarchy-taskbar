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
  readonly property string pinsPath: configHome + "/omarchy-taskbar/pinned.json"
  readonly property int barSize: Style.bar.sizeHorizontal
  readonly property int iconSize: Math.round(barSize * 0.66)
  readonly property color foreground: Commons.Color.bar.text

  property var pinned: []
  property bool transparent: false

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
    else list.splice(at, 1)
    savePins(list)
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

  function webAppEntry(appId) {
    var match = /^(?:chrome|chromium|brave|msedge|vivaldi)-(.+?)__/.exec(appId)
    return match ? (root.webApps[match[1].toLowerCase()] || null) : null
  }

  function entryFor(appId) {
    if (!appId) return null
    return webAppEntry(appId) || DesktopEntries.heuristicLookup(appId)
  }

  // A window's own entry, or the one of the program behind it (found later
  // through its process), so e.g. a terminal with its own class joins the
  // terminal's button and can be pinned like it.
  function windowEntry(appId) {
    var entry = entryFor(appId)
    if (entry) return entry
    var found = root.fallbacks[appId]
    return found && found.entry !== "" ? DesktopEntries.byId(found.entry) : null
  }

  // The button a window belongs to: its entry id, else the program's path,
  // else its class. Pinned keys are the same ids or paths.
  function keyFor(toplevel) {
    var appId = String(toplevel.appId || "")
    var entry = windowEntry(appId)
    if (entry) return entry.id
    var found = root.fallbacks[appId]
    return found && found.exe !== "" ? found.exe : appId
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
        list.push({ key: id, entry: null, appId: "", exe: id })
        return
      }
      var entry = DesktopEntries.byId(id)
      if (!entry || seen[entry.id]) return
      seen[entry.id] = true
      list.push({ key: entry.id, entry: entry, appId: "", exe: "" })
    })
    ToplevelManager.toplevels.values.forEach(function(toplevel) {
      var key = root.keyFor(toplevel)
      if (key === "" || seen[key]) return
      seen[key] = true
      var appId = String(toplevel.appId || "")
      var found = root.fallbacks[appId]
      list.push({ key: key, entry: root.windowEntry(appId), appId: appId, exe: found ? found.exe : "" })
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
    var found = root.fallbacks[app.appId]
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
    var found = root.fallbacks[app.appId]
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

  function iconFor(app) {
    var found = root.fallbacks[app.appId]
    // A pinned program path: its file name ("/usr/bin/foot" → "foot").
    var own = app.appId !== "" ? app.appId.toLowerCase() : String(app.exe || "").split("/").pop()
    var name = app.entry && app.entry.icon ? app.entry.icon : (found && found.icon) || own
    if (!app.entry && app.appId !== "") Qt.callLater(root.lookupIcon, app.appId)
    var path = Quickshell.iconPath(name, true)
    return path || Quickshell.iconPath("application-x-executable", true)
  }

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
    // Prints the program name, then its executable path.
    command: ["bash", "-c",
      'pid=$(hyprctl clients -j | jq -r --arg c "$1" \'first(.[] | select(.class == $c) | .pid) // empty\'); '
      + '[[ -n $pid ]] && cat "/proc/$pid/comm" && readlink -f "/proc/$pid/exe"', "omarchy-taskbar", appId]
    stdout: StdioCollector {
      onStreamFinished: {
        var lines = text.split("\n")
        var entry = root.entryFor((lines[0] || "").trim())
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

        screen: modelData
        anchors {
          bottom: true
          left: true
          right: true
        }
        implicitHeight: root.barSize
        exclusionMode: ExclusionMode.Auto
        color: root.transparent ? "transparent" : Commons.Color.bar.background
        surfaceFormat.opaque: false
        WlrLayershell.namespace: "omarchy-taskbar"
        WlrLayershell.layer: WlrLayer.Top

        // Empty bar space: double-click toggles transparency, like Omarchy's bar.
        MouseArea {
          anchors.fill: parent
          acceptedButtons: Qt.LeftButton | Qt.RightButton
          onPressed: root.closeMenu()
          onDoubleClicked: function(event) {
            if (event.button === Qt.LeftButton) root.toggleTransparent()
          }
        }

        Row {
          anchors.centerIn: parent
          height: parent.height
          spacing: Style.space(2)

          Repeater {
            model: root.apps

            delegate: AppButton {
              required property var modelData
              app: modelData
            }
          }
        }
      }
    }
  }

  component AppButton: Item {
    id: button

    property var app
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

    MouseArea {
      id: mouse
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
      onClicked: function(event) {
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
      running: mouse.containsMouse && !menu.visible && !windowList.visible
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

        Column {
          id: windowColumn
          anchors.centerIn: parent

          Repeater {
            model: windowList.visible ? button.windows : []
            delegate: WindowRow {
              required property var modelData
              title: modelData.title || button.label
              workspace: root.workspaceOf(modelData)
              current: modelData.activated
              onTriggered: { root.closeMenu(); root.focusWindow(modelData) }
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
      visible: mouse.containsMouse && !menu.visible && !windowList.visible && !tipDelay.running
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

  // A row of the window list: title on the left, workspace on the right.
  component WindowRow: Rectangle {
    id: windowRow

    property string title
    property string workspace
    property bool current: false
    signal triggered()

    width: Math.min(Style.space(420), Math.max(Style.space(220), windowTitle.implicitWidth + windowSpace.implicitWidth + Style.space(40)))
    height: windowTitle.implicitHeight + Style.space(12)
    radius: Style.cornerRadius
    color: windowMouse.containsMouse ? Commons.Color.menu.selectedBackground : "transparent"

    Text {
      id: windowTitle
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
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
      anchors.verticalCenter: parent.verticalCenter
      anchors.right: parent.right
      anchors.rightMargin: Style.space(12)
      text: windowRow.workspace === "" ? "" : root.t("Workspace ", "Escritorio ") + windowRow.workspace
      color: windowMouse.containsMouse ? Commons.Color.menu.selectedText : Commons.Color.accent
      font.family: Style.font.family
      font.pixelSize: Style.font.bodySmall
    }

    MouseArea {
      id: windowMouse
      anchors.fill: parent
      hoverEnabled: true
      onClicked: windowRow.triggered()
    }
  }

  component MenuRow: Rectangle {
    id: row

    property string text
    property bool shown: true
    signal triggered()

    visible: shown
    width: Math.max(Style.space(140), rowLabel.implicitWidth + Style.space(24))
    height: shown ? rowLabel.implicitHeight + Style.space(12) : 0
    radius: Style.cornerRadius
    color: rowMouse.containsMouse ? Commons.Color.menu.selectedBackground : "transparent"

    Text {
      id: rowLabel
      textFormat: Text.PlainText
      anchors.verticalCenter: parent.verticalCenter
      anchors.left: parent.left
      anchors.leftMargin: Style.space(12)
      text: row.text
      color: rowMouse.containsMouse ? Commons.Color.menu.selectedText : Commons.Color.menu.text
      font.family: Style.font.family
      font.pixelSize: Style.font.body
    }

    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      onClicked: {
        menu.visible = false
        row.triggered()
      }
    }
  }
}
