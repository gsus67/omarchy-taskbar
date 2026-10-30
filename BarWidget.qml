import QtQuick
import "." as Local

// The Combine style's slot in Omarchy's bar. Everything it shows comes from
// Taskbar.qml; outside Combine it stays in the layout, keeping its place, but
// takes no space.
Item {
  id: widget

  property var bar
  property string moduleName
  property var settings

  readonly property var taskbar: Local.Bridge.taskbar
  readonly property bool combined: !!taskbar && taskbar.combined

  visible: widget.combined
  implicitWidth: content.item ? content.item.implicitWidth : 0
  implicitHeight: content.item ? content.item.implicitHeight : 0

  // The bar's own drag area sits above its modules and would take every left
  // press. Above it, icons keep theirs; the margin has no left-button handler,
  // so a press there still reaches the bar, which moves the whole module.
  Component.onCompleted: if (parent) parent.z = 1

  Loader {
    id: content
    anchors.fill: parent
    active: widget.combined
    sourceComponent: widget.taskbar ? widget.taskbar.combinedModule : null
    onLoaded: item.widget = widget
  }
}
