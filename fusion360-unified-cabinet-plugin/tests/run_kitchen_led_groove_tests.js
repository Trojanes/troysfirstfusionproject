const assert = require("assert");
const path = require("path");
const { spawnSync } = require("child_process");

const bridgeScript = path.resolve(__dirname, "..", "scripts", "kitchen_from_params.js");

function sampleState(overrides = {}) {
  const globalSettings = {
    length: 887,
    depth: 270,
    height: 880,
    materialThickness: 15,
    frontThickness: 16,
    frontClearance: 2.5,
    bottomClearanceHeight: 55,
    bottomClearanceStyle: "style_1",
    ledGroove: true,
    ...(overrides.globalSettings || {}),
  };
  return {
    globalSettings,
    columns: [
      {
        id: "k-col-1",
        width: 887,
        columnType: "left_door",
        zones: [
          {
            id: "k-zone-1",
            height: Math.max(1, globalSettings.height - globalSettings.bottomClearanceHeight),
            zoneType: "left_door",
            shelfEnabled: true,
            shelfHeight: 400,
          },
        ],
      },
    ],
    wheelAvoidances: [],
    vPanelMachiningPreferences: [],
  };
}

function runBridge(params) {
  const proc = spawnSync(process.execPath, [bridgeScript], {
    input: JSON.stringify({ params }),
    encoding: "utf8",
  });
  assert.strictEqual(proc.status, 0, proc.stderr || proc.stdout);
  const data = JSON.parse(proc.stdout);
  assert.strictEqual(data.ok, true, JSON.stringify(data.errors || data));
  return data.result || {};
}

function b3LedHalfGrooves(result) {
  const entry = (result.panelDxf || []).find((panel) => panel.panelId === "B3");
  assert(entry, "B3 panelDxf entry missing");
  return (entry.halfGrooveVectors || []).filter((cutout) => String(cutout.sourceId || "") === "B3_led_groove");
}

const on = runBridge(sampleState());
const onGrooves = b3LedHalfGrooves(on);
assert.strictEqual(onGrooves.length, 3, "Style 1 + ledGroove should emit main + 2 branch half grooves");
assert.ok(onGrooves.every((cutout) => cutout.side === "left"), "LED grooves open on bottom face (side=left)");
assert.ok(onGrooves.every((cutout) => cutout.grooveDepth === 6.5), "LED groove depth should be 6.5 mm");
assert.ok(
  (on.boards || []).find((board) => board.id === "B3")?.notes?.some((note) => /LED groove/i.test(note)),
  "B3 should note LED groove implementation",
);

const off = runBridge(sampleState({ globalSettings: { ledGroove: false } }));
assert.strictEqual(b3LedHalfGrooves(off).length, 0, "ledGroove=false should emit no LED half grooves");

const style2 = runBridge(sampleState({ globalSettings: { bottomClearanceStyle: "style_2" } }));
assert.strictEqual(b3LedHalfGrooves(style2).length, 0, "Style 2 should not emit LED grooves");

const omitted = runBridge(sampleState({
  globalSettings: (() => {
    const gs = { ...sampleState().globalSettings };
    delete gs.ledGroove;
    return gs;
  })(),
}));
assert.strictEqual(b3LedHalfGrooves(omitted).length, 3, "omitted ledGroove defaults to on");

console.log("kitchen LED groove tests passed");
