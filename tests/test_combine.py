"""Guards for the Combine style: the taskbar as a module of Omarchy's bar."""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "Taskbar.qml").read_text()
WIDGET = (ROOT / "BarWidget.qml").read_text()
MANIFEST = json.loads((ROOT / "manifest.json").read_text())


def qml_function(name):
    match = re.search(r"  function " + name + r"\([^\n]*\) \{.*?\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError("missing function " + name)
    return match.group(0)


def evaluate(names, prelude, expression):
    code = "\n".join(qml_function(name) for name in names) + "\n" + prelude + (
        "console.log(JSON.stringify(" + expression + "));")
    result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=5, check=True)
    return json.loads(result.stdout)


class ManifestTest(unittest.TestCase):
    def test_plugin_is_both_panel_and_bar_widget(self):
        self.assertIn("panel", MANIFEST["kinds"])
        self.assertIn("bar-widget", MANIFEST["kinds"])
        self.assertEqual(MANIFEST["entryPoints"]["barWidget"], "BarWidget.qml")
        self.assertEqual(MANIFEST["entryPoints"]["panel"], "Taskbar.qml")

    def test_bridge_is_a_singleton_and_local_types_stay_importable(self):
        qmldir = (ROOT / "qmldir").read_text()
        self.assertIn("singleton Bridge 1.0 Bridge.qml", qmldir)
        self.assertIn("CrystalSurface 1.0 CrystalSurface.qml", qmldir)


class SwitchingTest(unittest.TestCase):
    def test_styles_still_apply_as_a_module(self):
        module = SOURCE[SOURCE.index("readonly property Component combinedModule"):SOURCE.index("component PinDropArea")]
        self.assertIn("Local.CrystalSurface", module)
        self.assertIn("visible: root.crystal", module)

    def test_own_bar_stays_until_a_module_is_really_on_omarchys_bar(self):
        self.assertIn("model: root.combined && Local.Bridge.modules > 0 ? [] : Quickshell.screens", SOURCE)
        self.assertIn("Component.onCompleted: Local.Bridge.modules += 1", SOURCE)
        self.assertIn("Component.onDestruction: Local.Bridge.modules -= 1", SOURCE)
        self.assertIn('root.combined ? "bottom" : root.configuredPosition', SOURCE)

    def test_dragging_outside_the_module_does_not_reorder(self):
        self.assertIn("bounds: module\n", SOURCE)
        self.assertIn("inside.x >= bounds.width", SOURCE)

    def test_widget_takes_no_space_outside_combine(self):
        self.assertIn("visible: widget.combined", WIDGET)
        self.assertIn("active: widget.combined", WIDGET)
        self.assertRegex(WIDGET, r"implicitWidth: content\.item \? content\.item\.implicitWidth : 0")

    def test_entering_combine_places_the_widget_without_moving_it(self):
        place = qml_function("placeBarWidget")
        self.assertIn('omarchy bar put "$1"', place)
        self.assertIn("root.onOmarchyBar", place)
        self.assertIn("!root.shellConfigLoaded", place)
        self.assertIn("root.placingBarWidget", place)
        self.assertIn('"omarchy-taskbar", root.pluginId]', place)
        self.assertNotIn('"move"', place)
        self.assertIn("onCombinedChanged: root.placeBarWidget()", SOURCE)

    def test_a_click_anywhere_on_omarchys_bar_closes_the_menus(self):
        self.assertRegex(SOURCE, r"bar: module\b|bounds: module\n")
        self.assertIn("sharedSurface: true", SOURCE)
        for popup in ("barMenu", "windowList", "menu"):
            self.assertIn("windows: bar.sharedSurface ? [%s] : [%s, " % (popup, popup), SOURCE)

    def test_clicking_the_icon_that_opened_a_menu_does_not_reopen_it(self):
        self.assertIn("else if (!bar.sharedSurface || !root.justClosed(menu)) root.showMenu(menu)", SOURCE)
        self.assertIn("else if (!bar.sharedSurface || !root.justClosed(windowList)) root.showMenu(windowList)", SOURCE)
        self.assertIn("root.closedMenu = root.openMenu", SOURCE)

    def test_failed_placement_turns_the_plugin_back_on(self):
        self.assertIn('|| omarchy plugin enable "$1"', qml_function("placeBarWidget"))

    def test_widget_is_raised_so_icons_get_the_press_and_the_margin_moves_it(self):
        self.assertIn("parent.z = 1", WIDGET)
        margin = SOURCE[SOURCE.index("// Margin around the icons:"):SOURCE.index("id: moduleViewport")]
        self.assertIn("acceptedButtons: Qt.RightButton", margin)
        self.assertNotIn("Qt.LeftButton", margin)

    def test_save_config_accepts_only_known_values(self):
        save = qml_function("saveConfig")
        self.assertIn('key === "position" && value !== null && root.positionFor(value) !== value', save)
        self.assertIn('key === "style" && value !== null && value !== "crystal"', save)


@unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
class MenuTest(unittest.TestCase):
    PRELUDE = (
        'const Qt={locale:()=>({decimalPoint:"."})};function t(en, es) {return en;}'
        'const configuredScale=1;const configuredWidth=null;const configuredStyle="default";'
        'const crystal=false;const configuredPosition=%s;\n')

    def items(self, position, page):
        return evaluate(["barMenuItems"], self.PRELUDE % json.dumps(position), 'barMenuItems("%s")' % page)

    def test_position_page_lists_every_place_and_checks_the_current_one(self):
        rows = self.items("combined", "position")
        self.assertEqual([row["label"] for row in rows[1:]], ["Top", "Right", "Left", "Bottom", "Combine"])
        self.assertEqual([row["checked"] for row in rows[1:]], [False, False, False, False, True])
        self.assertEqual([row["value"] for row in rows[1:]], ["top", "right", "left", None, "combined"])
        self.assertEqual(rows[0]["page"], "root")

    def test_size_menu_disappears_in_combine_and_style_stays(self):
        self.assertEqual([row["page"] for row in self.items("combined", "root")], ["style", "position"])
        self.assertEqual([row["page"] for row in self.items("bottom", "root")], ["style", "position", "size"])

    def test_invalid_position_is_bottom(self):
        function = re.search(r"  function positionFor\([^\n]*\) \{[^\n]*\}", SOURCE).group(0)
        code = function + 'console.log(JSON.stringify([positionFor("left"), positionFor("combined"), positionFor("x"), positionFor(null)]));'
        result = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(json.loads(result.stdout), ["left", "combined", "bottom", "bottom"])


@unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
class LayoutHasTest(unittest.TestCase):
    def has(self, layout):
        return evaluate(["layoutHas"], 'const root={pluginId:"me"};\n', "layoutHas(%s)" % json.dumps(layout))

    def test_finds_the_plugin_in_any_section(self):
        self.assertTrue(self.has({"right": [{"id": "x"}, {"id": "me"}]}))
        self.assertTrue(self.has({"center": ["me"]}))

    def test_finds_the_plugin_in_every_section_of_omarchy_4_5(self):
        for section in ("left", "centerBegin", "center", "centerEnd", "right", "tray"):
            with self.subTest(section=section):
                self.assertTrue(self.has({section: ["me"]}))
                self.assertTrue(self.has({section: [{"id": "me"}]}))

    def test_a_section_added_later_still_counts(self):
        self.assertTrue(self.has({"futureSection": ["me"]}))

    def test_a_setting_beside_the_sections_is_not_a_place_on_the_bar(self):
        self.assertFalse(self.has({"centerAnchor": "me"}))

    def test_missing_or_malformed_layout_is_not_on_the_bar(self):
        self.assertFalse(self.has({"left": [{"id": "x"}]}))
        self.assertFalse(self.has(None))
        self.assertFalse(self.has({"left": "me"}))


@unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
class GrowthLimitTest(unittest.TestCase):
    def free(self, own, slots):
        return evaluate(["freeLength"], "", "freeLength(%s, %s, 1000)" % (json.dumps(own), json.dumps(slots)))

    @staticmethod
    def slot(region, start, end):
        return {"region": region, "start": start, "end": end}

    def test_left_module_grows_until_the_center_section(self):
        own = self.slot("left", 100, 200)
        slots = [self.slot("left", 0, 100), own, self.slot("center", 400, 600), self.slot("right", 900, 1000)]
        self.assertEqual(self.free(own, slots), 200)

    def test_modules_of_the_same_section_move_along_and_count_as_used(self):
        own = self.slot("left", 0, 100)
        slots = [own, self.slot("left", 100, 300), self.slot("center", 400, 600)]
        self.assertEqual(self.free(own, slots), 100)

    def test_right_module_grows_until_the_center_section(self):
        own = self.slot("right", 800, 900)
        slots = [self.slot("center", 400, 600), own, self.slot("right", 900, 1000)]
        self.assertEqual(self.free(own, slots), 200)

    def test_center_module_uses_the_tighter_side(self):
        own = self.slot("center", 400, 600)
        slots = [self.slot("left", 0, 350), own, self.slot("right", 800, 1000)]
        self.assertEqual(self.free(own, slots), 50)

    def test_center_module_uses_the_tighter_side_when_that_is_the_far_end(self):
        own = self.slot("center", 400, 600)
        slots = [self.slot("centerBegin", 100, 200), own, self.slot("centerEnd", 650, 700)]
        self.assertEqual(self.free(own, slots), 50)

    def test_unknown_section_uses_the_tighter_side(self):
        own = self.slot("futureSection", 400, 600)
        slots = [self.slot("left", 0, 100), own, self.slot("right", 650, 1000)]
        self.assertEqual(self.free(own, slots), 50)

    def test_center_end_module_grows_away_from_the_clock_beside_it(self):
        own = self.slot("centerEnd", 600, 700)
        slots = [self.slot("center", 400, 600), own, self.slot("right", 900, 1000)]
        self.assertEqual(self.free(own, slots), 200)

    def test_center_begin_module_grows_away_from_the_clock_beside_it(self):
        own = self.slot("centerBegin", 300, 400)
        slots = [self.slot("left", 0, 100), own, self.slot("center", 400, 600)]
        self.assertEqual(self.free(own, slots), 200)

    def test_without_neighbours_it_reaches_the_bar_end(self):
        own = self.slot("left", 0, 100)
        self.assertEqual(self.free(own, [own]), 900)

    def test_overlap_is_negative_so_the_module_can_yield(self):
        own = self.slot("left", 0, 500)
        self.assertEqual(self.free(own, [own, self.slot("center", 400, 600)]), -100)


@unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
class MaxLengthTest(unittest.TestCase):
    MARGIN = 4
    FLOOR = 40

    def limit(self, current, free):
        return evaluate(["moduleMaxLength"], "", "moduleMaxLength(%s, %s, %s, %s)" % (current, free, self.MARGIN, self.FLOOR))

    def settle(self, content, length, free_after, ticks=120):
        """Run the 1 s timer: the module takes min(content, limit), the bar reports the gap."""
        code = "let content=%s, length=%s, seen=[];const freeAfter=%s;" % (content, length, free_after)
        code += "for(let i=0;i<%d;i++){const limit=moduleMaxLength(length,freeAfter(length),%s,%s);" % (ticks, self.MARGIN, self.FLOOR)
        code += "length=Math.max(%s,Math.min(content,limit));seen.push(length);}" % self.FLOOR
        return evaluate(["moduleMaxLength"], code, "seen")

    def test_no_gap_keeps_the_limit_where_it_is(self):
        self.assertEqual(self.limit(300, 0), 300)

    def test_gap_inside_the_margin_keeps_the_limit_where_it_is(self):
        self.assertEqual(self.limit(300, 3), 300)
        self.assertEqual(self.limit(300, 4), 300)

    def test_margin_comes_out_of_the_gap_only(self):
        self.assertEqual(self.limit(300, 100), 396)

    def test_overlap_gives_back_exactly_the_overlap(self):
        self.assertEqual(self.limit(300, -50), 250)

    def test_never_below_the_floor(self):
        self.assertEqual(self.limit(50, -500), 40)

    def test_module_does_not_shrink_when_the_gap_stays_at_zero(self):
        # The neighbour follows the module, so shrinking never opens a gap.
        seen = self.settle(600, 300, "() => 0")
        self.assertEqual(set(seen), {300})

    def test_module_settles_beside_a_fixed_neighbour(self):
        # Neighbour fixed at 500, module starting at 0.
        seen = self.settle(600, 300, "length => 500 - length")
        self.assertEqual(seen[0], 496)
        self.assertEqual(set(seen), {496})

    def test_module_yields_to_a_neighbour_that_overlaps_it_then_holds(self):
        seen = self.settle(600, 300, "length => 250 - length")
        self.assertEqual(seen[0], 250)
        self.assertEqual(set(seen), {250})

    def test_centered_module_converges_without_oscillating(self):
        # Neighbour ends at 100 and the section stays centered on 500.
        seen = self.settle(1000, 900, "length => (500 - length / 2) - 100")
        self.assertEqual(seen, sorted(seen, reverse=True))
        self.assertEqual(seen[-1], seen[-2])
        self.assertAlmostEqual(seen[-1], 800)


@unittest.skipUnless(shutil.which("node"), "Node is needed to run QML JavaScript")
class SlotLookupTest(unittest.TestCase):
    """Omarchy 4.5 wraps modules in a WidgetHost with activeItem but no region."""

    CHAIN = """
const slot = {name: "slot", activeItem: {}, region: "left", parent: {name: "bar", parent: null}};
const area = {name: "area", parent: slot};
const holder = {name: "holder", parent: area};
const host = {name: "host", activeItem: {}, parent: holder};
const loader = {name: "loader", parent: host};
const widget = {name: "widget", parent: loader};
const inner = {name: "inner", parent: widget};
const start = {name: "module", parent: inner};
"""

    def test_skips_a_host_that_has_active_item_but_no_region(self):
        self.assertEqual(evaluate(["slotOf"], self.CHAIN, "slotOf(start).name"), "slot")

    def test_returns_null_without_a_slot(self):
        prelude = """
const host = {activeItem: {}, parent: {parent: null}};
const start = {parent: {parent: host}};
"""
        self.assertIsNone(evaluate(["slotOf"], prelude, "slotOf(start)"))

    def test_real_omarchy_geometry_leaves_the_module_room_to_grow(self):
        prelude = """
const own = {region: "left", start: 128, end: 152};
const slots = [
  {region: "left", start: 7, end: 32},
  {region: "left", start: 32, end: 127},
  own,
  {region: "centerBegin", start: 1159, end: 1197},
];
const free = freeLength(own, slots, 1920);
"""
        result = evaluate(
            ["slotOf", "freeLength", "moduleMaxLength"],
            prelude,
            "[free, moduleMaxLength(24, free, 4, 24)]",
        )
        self.assertEqual(result, [1007, 1027])

    def test_limit_does_not_move_as_the_module_grows(self):
        self.assertEqual(
            evaluate(["slotOf", "freeLength", "moduleMaxLength"], "", "moduleMaxLength(231, 800, 4, 24)"),
            1027,
        )

    def test_module_finds_its_slot_through_the_shared_lookup(self):
        match = re.search(r"      function updateMaxLength\(\) \{.*?\n      \}", SOURCE, re.S)
        self.assertIsNotNone(match)
        self.assertIn("root.slotOf(module)", match.group(0))


if __name__ == "__main__":
    unittest.main()
