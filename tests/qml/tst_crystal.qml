import QtQuick
import QtTest
import "../.." as Taskbar

Rectangle {
  id: scene
  width: 480
  height: 140
  color: "black"

  Taskbar.CrystalSurface {
    id: glass
    x: 30
    y: 40
    width: 420
    height: 48
  }

  TestCase {
    name: "CrystalSurface"
    when: windowShown

    function test_translucent_body_and_clear_corners_data() {
      return [{tag: "dark", tint: "#16202c"}, {tag: "light", tint: "#f1f5fb"}]
    }
    function test_translucent_body_and_clear_corners(data) {
      glass.tint = data.tint
      scene.color = "black"
      waitForRendering(scene)
      var onDark = grabImage(scene)
      compare(onDark.pixel(30, 40), scene.color, "Rounded corners must reveal the background")
      scene.color = "white"
      waitForRendering(scene)
      var onLight = grabImage(scene)
      compare(onLight.pixel(30, 40), scene.color, "Rounded corners must reveal the background")
      var difference = onLight.red(240, 64) - onDark.red(240, 64)
      verify(difference > 190, "The background must show through the glass")
      verify(difference < 250, "The glass tint must remain visible")
      compare(glass.radius, 18)
    }
  }
}
