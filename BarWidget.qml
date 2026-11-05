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

  // Older bars stack their drag area beside the widget parent, so raising it
  // keeps the icons left press. Omarchy 4.5 loads the widget inside a Loader
  // and its drag area covers the whole module: this has no effect there, and a
  // left press anywhere on the module drags it.
  Component.onCompleted: if (parent) parent.z = 1

  Loader {
    id: content
    anchors.fill: parent
    active: widget.combined
    sourceComponent: widget.taskbar ? widget.taskbar.combinedModule : null
    onLoaded: item.widget = widget
  }
}
