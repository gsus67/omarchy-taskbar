"""Execute the QML window-focus path with Hyprland state fixtures."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import unittest


SOURCE = (Path(__file__).resolve().parent.parent / "Taskbar.qml").read_text()


def qml_function(name):
    match = re.search(r"  function " + name + r"\([^\n]*\) \{.*?\n  \}", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"QML function not found: {name}")
    return match.group()


def qml_object(kind, object_id):
    match = re.search(
        rf"  {kind} \{{\s*id: {re.escape(object_id)}\b.*?\n  \}}",
        SOURCE,
        re.S,
    )
    if match is None:
        raise AssertionError(f"QML object not found: {object_id}")
    return match.group()


@unittest.skipUnless(shutil.which("node"), "Node is needed to run the QML JavaScript")
class FocusWindowTest(unittest.TestCase):
    def run_special_workspace(self, monitors, target_monitor):
        code = qml_function("specialWorkspaceForMonitor") + r'''
const monitors = JSON.parse(process.argv[1]);
console.log(JSON.stringify(specialWorkspaceForMonitor(monitors, process.argv[2])));
'''
        result = subprocess.run(  # noqa: S603 -- fixed local Node binary, no shell
            [shutil.which("node"), "-e", code, json.dumps(monitors), target_monitor],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return json.loads(result.stdout)

    def run_live_focus(
        self,
        monitors,
        target_workspace,
        target_monitor="DP-1",
        cached_special=None,
        focused_monitor_present=True,
        through_activate=False,
        address="abc123",
        hypr_present=True,
        query_succeeded=True,
        query_output=None,
        workspace_present=True,
        queued_requests=None,
        failed_starts=0,
    ):
        functions = [
            qml_function("hyprlandOf"),
            qml_function("specialWorkspaceForMonitor"),
            qml_function("dispatchFocus"),
            qml_function("startNextFocus"),
            qml_function("finishFocus"),
            qml_function("completeFocusQuery"),
            qml_function("timeoutFocusQuery"),
            qml_function("focusWindow"),
        ]
        if through_activate:
            functions.insert(0, qml_function("activate"))
        code = "\n".join(functions) + r'''
const fixture = JSON.parse(process.argv[1]);
const calls = [];
const requests = fixture.queuedRequests || [{
  address: fixture.address,
  workspace: fixture.targetWorkspace,
  workspacePresent: fixture.workspacePresent,
  monitor: fixture.targetMonitor,
}];
const targets = requests.map(() => ({
  activated: false,
  activate: () => calls.push(["direct-activate"]),
}));
const hyprs = requests.map((request, index) => ({
  wayland: targets[index],
  address: request.address,
  workspace: request.workspacePresent ? {name: request.workspace} : null,
  monitor: request.monitor === "" ? null : {name: request.monitor},
}));
const Hyprland = {
  toplevels: {values: fixture.hyprPresent ? hyprs : []},
  focusedMonitor: fixture.focusedMonitorPresent
    ? {lastIpcObject: {specialWorkspace: fixture.cachedSpecial}}
    : null,
  dispatch: request => calls.push(["dispatch", request]),
};
let queryStartCount = 0;
const focusQueryTimeout = {
  requestId: 0,
  running: false,
  restart() { this.running = true; },
  stop() { this.running = false; },
};
function makeQuery(requestId) {
  const query = {
    requestId: requestId || 0,
    hasExited: false, streamFinished: false, querySucceeded: false,
    output: "", _running: false, destroyed: false,
    destroy() { this.destroyed = true; this._running = false; },
    emitComplete() { root.completeFocusQuery(this.requestId, this); },
  };
  Object.defineProperty(query, "running", {
    get() { return query._running; },
    set(value) {
      if (!value) { query._running = false; return; }
      queryStartCount += 1;
      if (fixture.failedStarts > 0) {
        fixture.failedStarts -= 1;
        query._running = false;
        query.emitComplete();
        return;
      }
      query._running = true;
    },
  });
  return query;
}
const focusMonitorQuery = makeQuery(0);
const createdQueries = [];
const focusMonitorQueryComponent = {
  createObject(parent, props) {
    const query = makeQuery(props && props.requestId);
    createdQueries.push(query);
    return query;
  },
};
function currentQuery() { return root.activeFocusQuery || focusMonitorQuery; }
const root = {
  focusRequests: [],
  activeFocusRequest: null,
  activeFocusQuery: null,
  focusRequestSeq: 0,
  activeFocusRequestId: 0,
  startNextFocus,
  finishFocus,
  completeFocusQuery: typeof completeFocusQuery === "undefined" ? null : completeFocusQuery,
  timeoutFocusQuery: typeof timeoutFocusQuery === "undefined" ? null : timeoutFocusQuery,
  dispatchFocus,
  specialWorkspaceForMonitor,
};
function windowsFor() { return [target]; }
function launch() { calls.push(["launch"]); }
const target = targets[0];
if (fixture.throughActivate) {
  activate({key: "app"});
} else {
  targets.forEach(focusWindow);
}
let cycles = 0;
while ((root.activeFocusRequest !== null || root.focusRequests.length > 0)
       && cycles < 20) {
  cycles += 1;
  const query = currentQuery();
  if (!query.running) {
    query.emitComplete();
    continue;
  }
  // Exercise the risky ordering: Process stops before the collector exposes
  // its final text. The active request must wait for streamFinished.
  query.hasExited = true;
  query.querySucceeded = fixture.querySucceeded;
  query.emitComplete();
  query._running = false;
  query.emitComplete();
  query.output = fixture.queryOutput;
  query.streamFinished = true;
  query.emitComplete();
}
console.log(JSON.stringify({
  calls,
  queryStarted: queryStartCount > 0,
  queryStartCount,
  pending: root.focusRequests.length,
  active: root.activeFocusRequest !== null,
}));
'''
        fixture = {
            "monitors": monitors,
            "targetWorkspace": target_workspace,
            "targetMonitor": target_monitor,
            "cachedSpecial": cached_special,
            "focusedMonitorPresent": focused_monitor_present,
            "throughActivate": through_activate,
            "address": address,
            "hyprPresent": hypr_present,
            "querySucceeded": query_succeeded,
            "queryOutput": json.dumps(monitors) if query_output is None else query_output,
            "workspacePresent": workspace_present,
            "queuedRequests": queued_requests,
            "failedStarts": failed_starts,
        }
        result = subprocess.run(  # noqa: S603 -- fixed local Node binary, no shell
            [shutil.which("node"), "-e", code, json.dumps(fixture)],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return json.loads(result.stdout)

    def run_focus_events(self, scenario, monitors):
        functions = [
            qml_function("hyprlandOf"),
            qml_function("specialWorkspaceForMonitor"),
            qml_function("dispatchFocus"),
            qml_function("startNextFocus"),
            qml_function("finishFocus"),
            qml_function("completeFocusQuery"),
            qml_function("timeoutFocusQuery"),
            qml_function("focusWindow"),
        ]
        code = "\n".join(functions) + r'''
const fixture = JSON.parse(process.argv[1]);
const calls = [];
const snapshots = {};
const targets = [0, 1].map(() => ({
  activated: false,
  activate: () => calls.push(["direct-activate"]),
}));
const hyprs = [
  {wayland: targets[0], address: "aaa111", workspace: {name: "2"}, monitor: {name: "DP-1"}},
  {wayland: targets[1], address: "bbb222", workspace: {name: "3"}, monitor: {name: "DP-1"}},
];
const Hyprland = {
  toplevels: {values: hyprs},
  dispatch: request => calls.push(["dispatch", request]),
};
const focusQueryTimeout = {
  requestId: 0, running: false,
  restart() { this.running = true; },
  stop() { this.running = false; },
};
function makeQuery(requestId) {
  const query = {
    requestId: requestId || 0,
    hasExited: false, streamFinished: false, querySucceeded: false,
    output: "", _running: false, destroyed: false,
    destroy() { this.destroyed = true; this._running = false; },
    // Simulates the QML handlers of this process instance: they close over
    // this instance and its captured requestId, never a caller-supplied id.
    emitComplete() { root.completeFocusQuery(this.requestId, this); },
    emitLate(output) {
      this.hasExited = true; this.streamFinished = true;
      this.querySucceeded = true; this.output = output;
      this._running = false; this.emitComplete();
    },
    deliver(output) { this.emitLate(output); },
  };
  Object.defineProperty(query, "running", {
    get() { return query._running; },
    set(value) { query._running = !!value; },
  });
  return query;
}
const focusMonitorQuery = makeQuery(0);
const createdQueries = [];
const focusMonitorQueryComponent = {
  createObject(parent, props) {
    const query = makeQuery(props && props.requestId);
    createdQueries.push(query);
    return query;
  },
};
const root = {
  focusRequests: [], activeFocusRequest: null, activeFocusQuery: null,
  focusRequestSeq: 0, activeFocusRequestId: 0,
  startNextFocus, finishFocus, completeFocusQuery, timeoutFocusQuery,
  dispatchFocus, specialWorkspaceForMonitor,
};
function currentQuery() { return root.activeFocusQuery || focusMonitorQuery; }
function deliverCurrent() { currentQuery().deliver(fixture.queryOutput); }
focusWindow(targets[0]);
if (fixture.scenario === "early") {
  // runningChanged(false) arrives before exited/streamFinished.
  const query = currentQuery();
  query._running = false;
  query.emitComplete();
  snapshots.afterEarly = calls.slice();
  deliverCurrent();
  snapshots.afterDeliver = calls.slice();
} else {
  focusWindow(targets[1]);
  if (fixture.scenario === "late") {
    const oldQuery = currentQuery();
    deliverCurrent();
    snapshots.afterFirst = calls.slice();
    // Late events from the old process: invoke its own handlers only.
    oldQuery.emitLate(fixture.queryOutput);
    snapshots.afterLate = calls.slice();
    deliverCurrent();
    snapshots.afterDeliver = calls.slice();
  } else if (fixture.scenario === "hung") {
    const oldQuery = currentQuery();
    snapshots.beforeTimeout = calls.slice();
    root.timeoutFocusQuery();
    snapshots.afterTimeout = calls.slice();
    // Late events from the killed old process must not complete the new one.
    oldQuery.emitLate(fixture.queryOutput);
    snapshots.afterLate = calls.slice();
    deliverCurrent();
    snapshots.afterDeliver = calls.slice();
  }
}
console.log(JSON.stringify({
  snapshots, pending: root.focusRequests.length,
  active: root.activeFocusRequest !== null,
}));
'''
        fixture = {"scenario": scenario, "queryOutput": json.dumps(monitors)}
        result = subprocess.run(  # noqa: S603 -- fixed local Node binary, no shell
            [shutil.which("node"), "-e", code, json.dumps(fixture)],
            capture_output=True, text=True, check=True, timeout=5,
        )
        return json.loads(result.stdout)

    def test_live_closed_state_does_not_reopen_stale_cached_special(self):
        monitors = [{
            "name": "DP-1",
            "focused": True,
            "specialWorkspace": {"id": 0, "name": ""},
        }]
        result = self.run_live_focus(
            monitors,
            "2",
            cached_special={"id": -99, "name": "special:stale"},
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])
        self.assertTrue(result["queryStarted"])

    def test_monitor_state_query_uses_direct_hyprctl_process(self):
        process = qml_object("Process", "focusQueryProcess")
        self.assertIn("focusMonitorQueryComponent", SOURCE)
        self.assertIn('command: ["hyprctl", "monitors", "-j"]', process)
        self.assertNotIn('"bash"', process)

    def test_monitor_query_completion_is_wired_to_stream_and_start_failure(self):
        process = qml_object("Process", "focusQueryProcess")
        self.assertIn("onStreamFinished:", process)
        self.assertIn("focusQueryProcess.output = text", process)
        self.assertIn(
            "onRunningChanged: root.completeFocusQuery("
            "focusQueryProcess.requestId, focusQueryProcess)",
            process,
        )
        self.assertNotIn("focusMonitorQuery.requestId", process)
        self.assertNotIn("focusMonitorOutput.text", process)

    def test_special_workspace_comes_from_target_windows_monitor(self):
        monitors = [
            {
                "name": "DP-1",
                "focused": True,
                "specialWorkspace": {"id": -98, "name": "special:left"},
            },
            {
                "name": "HDMI-A-1",
                "focused": False,
                "specialWorkspace": {"id": -99, "name": "special:right"},
            },
        ]
        self.assertEqual(
            self.run_special_workspace(monitors, "HDMI-A-1"),
            "special:right",
        )

    def test_multiple_monitors_hide_only_target_windows_special_workspace(self):
        monitors = [
            {
                "name": "DP-1",
                "focused": True,
                "specialWorkspace": {"id": -98, "name": "special:left"},
            },
            {
                "name": "HDMI-A-1",
                "focused": False,
                "specialWorkspace": {"id": -99, "name": "special:right"},
            },
        ]
        result = self.run_live_focus(monitors, "2", target_monitor="HDMI-A-1")
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.focus({ monitor = "HDMI-A-1" })'],
            ["dispatch", 'hl.dsp.workspace.toggle_special("right")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xabc123" })'],
        ])

    def test_null_focused_monitor_falls_back_to_live_focused_monitor(self):
        monitors = [{
            "name": "DP-1",
            "focused": True,
            "specialWorkspace": {"id": -99, "name": "special:scratchpad"},
        }]
        result = self.run_live_focus(
            monitors,
            "2",
            target_monitor="",
            focused_monitor_present=False,
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xabc123" })'],
        ])
        self.assertTrue(result["queryStarted"])

    def test_invalid_hyprland_address_activates_directly_without_hiding(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "2",
            address="not-an-address",
        )
        self.assertEqual(result["calls"], [["direct-activate"]])
        self.assertFalse(result["queryStarted"])

    def test_window_missing_from_hyprland_activates_directly_without_hiding(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "2",
            hypr_present=False,
        )
        self.assertEqual(result["calls"], [["direct-activate"]])
        self.assertFalse(result["queryStarted"])

    def test_app_click_hides_open_special_workspace_before_focusing_normal_window(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "2",
            through_activate=True,
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xabc123" })'],
        ])

    def test_focus_leaves_workspace_alone_without_an_open_scratchpad(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": 0, "name": ""}}],
            "2",
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])

    def test_focus_leaves_open_scratchpad_alone_for_its_own_window(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "special:scratchpad",
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])

    def test_focus_hides_a_different_open_special_workspace(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "special:other",
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xabc123" })'],
        ])

    def test_focus_does_not_toggle_when_other_special_workspace_is_closed(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": 0, "name": ""}}],
            "special:other",
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])

    def test_failed_monitor_query_focuses_without_toggling_cached_state(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "2",
            cached_special={"id": -98, "name": "special:stale"},
            query_succeeded=False,
            query_output="not json",
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])

    def test_null_workspace_is_treated_as_outside_the_open_scratchpad(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "ignored",
            workspace_present=False,
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xabc123" })'],
        ])

    def test_multiple_focus_requests_are_completed_in_click_order(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": 0, "name": ""}}],
            "1",
            queued_requests=[
                {"address": "111", "workspace": "1", "workspacePresent": True,
                 "monitor": "DP-1"},
                {"address": "222", "workspace": "2", "workspacePresent": True,
                 "monitor": "DP-1"},
                {"address": "333", "workspace": "3", "workspacePresent": True,
                 "monitor": "DP-1"},
            ],
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.focus({ window = "address:0x111" })'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0x222" })'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0x333" })'],
        ])
        self.assertEqual(result["queryStartCount"], 3)
        self.assertEqual(result["pending"], 0)
        self.assertFalse(result["active"])

    def test_failed_process_start_releases_request_and_continues_queue(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}],
            "1",
            queued_requests=[
                {"address": "111", "workspace": "1", "workspacePresent": True,
                 "monitor": "DP-1"},
                {"address": "222", "workspace": "2", "workspacePresent": True,
                 "monitor": "DP-1"},
            ],
            failed_starts=1,
        )
        self.assertEqual(result["calls"], [
            ["dispatch", 'hl.dsp.focus({ window = "address:0x111" })'],
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0x222" })'],
        ])
        self.assertEqual(result["queryStartCount"], 2)
        self.assertEqual(result["pending"], 0)
        self.assertFalse(result["active"])

    def test_running_changed_before_exited_waits_for_query_data(self):
        monitors = [{"name": "DP-1", "focused": True,
                     "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}]
        result = self.run_focus_events("early", monitors)
        self.assertEqual(result["snapshots"]["afterEarly"], [])
        self.assertEqual(result["snapshots"]["afterDeliver"], [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xaaa111" })'],
        ])
        self.assertFalse(result["active"])

    def test_late_events_from_previous_request_are_ignored(self):
        monitors = [{"name": "DP-1", "focused": True,
                     "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}]
        result = self.run_focus_events("late", monitors)
        first = [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xaaa111" })'],
        ]
        self.assertEqual(result["snapshots"]["afterFirst"], first)
        self.assertEqual(result["snapshots"]["afterLate"], first)
        self.assertEqual(result["snapshots"]["afterDeliver"], first + [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xbbb222" })'],
        ])
        self.assertEqual(result["pending"], 0)
        self.assertFalse(result["active"])

    def test_hung_hyprctl_times_out_and_focuses_without_toggling(self):
        monitors = [{"name": "DP-1", "focused": True,
                     "specialWorkspace": {"id": -99, "name": "special:scratchpad"}}]
        result = self.run_focus_events("hung", monitors)
        self.assertEqual(result["snapshots"]["beforeTimeout"], [])
        timed_out = [["dispatch", 'hl.dsp.focus({ window = "address:0xaaa111" })']]
        self.assertEqual(result["snapshots"]["afterTimeout"], timed_out)
        self.assertEqual(result["snapshots"]["afterLate"], timed_out)
        self.assertEqual(result["snapshots"]["afterDeliver"], timed_out + [
            ["dispatch", 'hl.dsp.workspace.toggle_special("scratchpad")'],
            ["dispatch", 'hl.dsp.focus({ window = "address:0xbbb222" })'],
        ])
        self.assertEqual(result["pending"], 0)
        self.assertFalse(result["active"])

    def test_focus_query_has_a_timeout_timer(self):
        timer = qml_object("Timer", "focusQueryTimeout")
        self.assertIn("interval: 2000", timer)
        self.assertIn("onTriggered: root.timeoutFocusQuery(", timer)
        process = qml_object("Process", "focusQueryProcess")
        self.assertIn("property int requestId: 0", process)

    def test_special_workspace_name_cannot_inject_a_dispatch(self):
        result = self.run_live_focus(
            [{"name": "DP-1", "focused": True,
              "specialWorkspace": {
                  "id": -99,
                  "name": 'special:scratchpad"); hl.dsp.exec("bad',
              }}],
            "2",
        )
        self.assertEqual(result["calls"], [[
            "dispatch",
            'hl.dsp.focus({ window = "address:0xabc123" })',
        ]])


if __name__ == "__main__":
    unittest.main()
