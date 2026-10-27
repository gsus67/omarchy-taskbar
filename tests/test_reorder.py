"""Static guards for app dragging; the layer windows need a Wayland session."""
import re
import unittest
from pathlib import Path

SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()
BAR = SOURCE[SOURCE.index("id: barWindow"):SOURCE.index("component DragGhostPanel:")]
GHOST = SOURCE[SOURCE.index("component DragGhostPanel:"):SOURCE.index("component AppButton:")]
BUTTON = SOURCE[SOURCE.index("component AppButton:"):SOURCE.index("component WindowRow:")]
POINTER = BUTTON[BUTTON.index("id: mouse"):BUTTON.index("// Its own popup")]


class ReorderTest(unittest.TestCase):
    def test_reordering_and_new_pins_use_the_existing_writer(self):
        match = re.search(r"function movePin\(app, index\) \{(.*?)\n  \}", SOURCE, re.S)
        self.assertIsNotNone(match)
        move = match.group(1)
        self.assertIn("var list = root.pinned.slice()", move)
        self.assertIn("var at = list.indexOf(app.key)", move)
        self.assertIn("if (at !== -1)", move)
        self.assertIn("list.splice(at, 1)", move)
        self.assertIn("if (at < index) index -= 1", move)
        self.assertIn("list.splice(index, 0, app.key)", move)
        self.assertIn("if (JSON.stringify(list) !== JSON.stringify(root.pinned)) root.savePins(list)", move)
        self.assertNotIn("execDetached", move)
        self.assertNotIn("queuePinChange", move)
        self.assertIn("if (wasDragging && index >= 0) root.movePin(button.app, index)", POINTER)

    def test_unpinned_apps_can_start_a_drag_and_be_inserted(self):
        self.assertIn("(!root.isPinned(button.app.key) && !root.canPin(button.app))", POINTER)
        self.assertIn("(!root.isPinned(app.key) && !root.canPin(app))", SOURCE)
        self.assertIn("barDragIndex = pinIndex < 0 ? root.pinned.length : pinIndex + (after ? 1 : 0)", BAR)
        # A drop past the pins uses their end, including when there are no pins.
        self.assertIn("if (pinIndex < 0) break", BAR)

    def test_same_threshold_as_omarchy_and_clicks_are_suppressed_only_for_drags(self):
        self.assertIn("readonly property real dragThreshold: Style.space(4)", POINTER)
        self.assertIn("Math.abs(event.x - pressedX) + Math.abs(event.y - pressedY)", POINTER)
        self.assertIn("if (!dragging && distance >= dragThreshold)", POINTER)
        self.assertIn("if (!pressed || !(event.buttons & Qt.LeftButton)", POINTER)
        self.assertIn("suppressClick = wasDragging", POINTER)
        clicked = POINTER[POINTER.index("onClicked:"):]
        self.assertLess(clicked.index("if (suppressClick)"), clicked.index("root.activate(button.app)"))
        self.assertIn("event.button === Qt.RightButton", clicked)
        self.assertIn("root.showMenu(menu)", clicked)
        self.assertIn("root.showMenu(windowList)", clicked)
        self.assertIn("else root.launch(button.app)", clicked)
        self.assertNotIn("drag.target:", POINTER)

    def test_escape_and_pointer_cancellation_clear_the_drag(self):
        self.assertIn("Keys.onEscapePressed: barWindow.clearBarDrag()", BAR)
        self.assertIn("barDragSource ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None", BAR)
        self.assertIn("onBarDragSourceChanged: if (barDragSource) dragKeys.forceActiveFocus()", BAR)
        self.assertIn("if (dragging && bar.barDragSource === button) bar.updateBarDrag", POINTER)
        self.assertRegex(POINTER, r"onCanceled: \{\s*dragging = false\s*suppressClick = true\s*bar.clearBarDrag\(\)")
        clear = BAR[BAR.index("function clearBarDrag()"):BAR.index("function captureBarDragGhost(")]
        for assignment in ("barDragSource = null", "barDragTarget = null", "barDragAfter = false",
                           "barDragIndex = -1", "barDragTargetGeometry = null", 'barDragImageUrl = ""'):
            self.assertIn(assignment, clear)
        self.assertIn("Component.onDestruction: if (bar.barDragSource === button) bar.clearBarDrag()", BUTTON)

    def test_outside_and_self_drops_do_nothing_and_release_rechecks_position(self):
        update = BAR[BAR.index("function updateBarDrag("):BAR.index("screen: modelData")]
        self.assertIn("barDragIndex = -1", update)
        outside = "if (point.x < 0 || point.x >= width || point.y < 0 || point.y >= height) return"
        itself = "if (x >= 0 && x < button.width && y >= 0 && y < button.height) return"
        self.assertIn(outside, update)
        self.assertIn(itself, update)
        self.assertLess(update.index("barDragIndex = -1"), update.index(outside))
        self.assertLess(update.index(itself), update.index("for (var i = 0;"))
        release = POINTER[POINTER.index("onReleased:"):POINTER.index("onCanceled:")]
        self.assertIn("if (wasDragging && bar.barDragSource === button) bar.updateBarDrag(button, event.x, event.y)", release)
        self.assertLess(release.index("bar.updateBarDrag"), release.index("var index = bar.barDragIndex"))
        self.assertLess(release.index("bar.clearBarDrag()"), release.index("root.movePin"))

    def test_captured_ghost_and_marker_reuse_bar_visuals(self):
        self.assertIn("item.grabToImage(function(result)", BAR)
        self.assertIn("barWindow.barDragSource === button && result && result.url", BAR)
        self.assertIn("mask: Region {}", GHOST)
        self.assertIn("WlrLayershell.layer: WlrLayer.Overlay", GHOST)
        self.assertIn("WlrLayershell.keyboardFocus: WlrKeyboardFocus.None", GHOST)
        self.assertIn("exclusionMode: ExclusionMode.Ignore", GHOST)
        self.assertIn("source: bar.barDragImageUrl", GHOST)
        self.assertIn("borderSpec: Border.flat(root.foreground, 1)", GHOST)
        self.assertIn("opacity: root.transparent ? 0.45 : 0.94", GHOST)
        self.assertIn("opacity: 0.84", GHOST)
        self.assertIn("color: Commons.Color.accent", GHOST)
        self.assertIn("var thickness = Style.spacing.xs", BAR)
        self.assertIn("opacity: button.dragSource ? 0.22 : 1.0", BUTTON)

    def test_each_screen_uses_its_own_scaled_geometry(self):
        self.assertIn("property var barDragSource: null", BAR)
        self.assertIn("screen: bar.screen", GHOST)
        self.assertIn("DragGhostPanel { bar: barWindow }", BAR)
        self.assertIn("bar: barWindow", BAR)
        self.assertIn("point.x + margins.left, point.y + screen.height - height", BAR)
        self.assertIn("var point = button.mapToItem(null, x, y)", BAR)
        self.assertIn("appButtons.itemAt(i)", BAR)
        self.assertIn("width: thickness, height: slot.height", BAR)
        self.assertIn("onWidthChanged: clearBarDrag()", BAR)
        self.assertIn("onHeightChanged: clearBarDrag()", BAR)
        self.assertIn("height: root.barSize", BUTTON)


if __name__ == "__main__":
    unittest.main()
