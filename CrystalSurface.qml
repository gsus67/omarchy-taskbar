import QtQuick

// Translucent glass, rendered locally. No screen capture or compositor changes.
Rectangle {
  id: glass
  property color tint: "#202832"
  radius: Math.round(Math.min(22, height * 0.38))
  antialiasing: true
  gradient: Gradient {
    GradientStop { position: 0; color: Qt.tint(Qt.rgba(glass.tint.r, glass.tint.g, glass.tint.b, 0.15), "#06ffffff") }
    GradientStop { position: 0.46; color: Qt.rgba(glass.tint.r, glass.tint.g, glass.tint.b, 0.05) }
    GradientStop { position: 1; color: Qt.tint(Qt.rgba(glass.tint.r, glass.tint.g, glass.tint.b, 0.09), "#0c000000") }
  }
  border.width: 1
  border.color: "#28ffffff"

  Rectangle {
    anchors.fill: parent
    anchors.margins: 1
    radius: Math.max(0, glass.radius - 1)
    color: "transparent"
    border.width: 1
    border.color: "#24000000"
    antialiasing: true
  }

  Rectangle {
    anchors.top: parent.top
    anchors.topMargin: 2
    anchors.horizontalCenter: parent.horizontalCenter
    width: Math.max(0, parent.width - glass.radius * 2)
    height: 1
    radius: 0.5
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0; color: "#00ffffff" }
      GradientStop { position: 0.5; color: "#2cffffff" }
      GradientStop { position: 1; color: "#00ffffff" }
    }
  }
}
