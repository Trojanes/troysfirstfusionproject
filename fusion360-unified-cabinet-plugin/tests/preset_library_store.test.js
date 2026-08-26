/**
 * Unit tests for local-file preset library store (no Fusion).
 * Run: node --test fusion360-unified-cabinet-plugin/tests/preset_library_store.test.js
 */
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PLUGIN = path.join(__dirname, "..");

function runPython(code) {
  const candidates = ["python", "python3", "py"];
  for (const exe of candidates) {
    const args = exe === "py" ? ["-3", "-c", code] : ["-c", code];
    const result = spawnSync(exe, args, {
      cwd: PLUGIN,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: PLUGIN },
    });
    if (result.error && result.error.code === "ENOENT") continue;
    return result;
  }
  return { status: 1, stdout: "", stderr: "no python" };
}

function skipIfNoPython(result) {
  if (result.status !== 0 && /no python|ENOENT|not recognized|Microsoft Store/i.test(String(result.stderr) + String(result.error || ""))) {
    return true;
  }
  return false;
}

test("preset library survives save/load roundtrip on disk", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "uc-presets-"));
  const code = `
import json, sys
sys.path.insert(0, r${JSON.stringify(PLUGIN)})
import presets.library_store as store
from pathlib import Path
store.STORE_DIRS = [lambda: Path(r${JSON.stringify(tmp)})]
lib = {
  "version": 2,
  "module": "lounge",
  "activeId": "preset-a",
  "items": [{"id": "preset-a", "name": "Sofa A", "savedAt": "2026-01-01T00:00:00Z", "data": {"version": 1}}],
}
saved = store.save_library("lounge", lib)
assert saved["ok"], saved
assert saved["path"].endswith("lounge.json"), saved
loaded = store.load_library("lounge")
assert loaded["ok"], loaded
assert loaded["exists"] is True
assert loaded["library"]["items"][0]["name"] == "Sofa A"
print("ok")
`;
  const result = runPython(code);
  if (skipIfNoPython(result)) return;
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout || "", /ok/);
});

test("save writes plugin folder and AppData backup, load merges both", () => {
  const pluginDir = fs.mkdtempSync(path.join(os.tmpdir(), "uc-presets-plugin-"));
  const roamingDir = fs.mkdtempSync(path.join(os.tmpdir(), "uc-presets-roam-"));
  const code = `
import sys
sys.path.insert(0, r${JSON.stringify(PLUGIN)})
import presets.library_store as store
from pathlib import Path
plugin = Path(r${JSON.stringify(pluginDir)})
roam = Path(r${JSON.stringify(roamingDir)})
store.STORE_DIRS = [lambda: plugin, lambda: roam]
saved = store.save_library("kitchen", {
  "version": 2,
  "module": "kitchen",
  "activeId": "preset-k",
  "items": [{"id": "preset-k", "name": "Galley", "savedAt": "2026-02-01T00:00:00Z", "data": {"version": 1}}],
})
assert saved["ok"], saved
assert len(saved["paths"]) == 2, saved
assert (plugin / "kitchen.json").is_file()
assert (roam / "kitchen.json").is_file()
# Older roaming-only preset should merge in after plugin file is removed.
(plugin / "kitchen.json").unlink()
(roam / "kitchen.json").write_text(
  '{"version":2,"module":"kitchen","activeId":"preset-old","items":['
  '{"id":"preset-old","name":"Legacy","savedAt":"2026-01-01T00:00:00Z","data":{}}]}',
  encoding="utf-8",
)
loaded = store.load_library("kitchen")
assert loaded["ok"], loaded
names = {item["name"] for item in loaded["library"]["items"]}
assert names == {"Legacy"}, names
print("ok")
`;
  const result = runPython(code);
  if (skipIfNoPython(result)) return;
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout || "", /ok/);
});

test("load_all_libraries returns every requested module", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "uc-presets-all-"));
  const code = `
import sys
sys.path.insert(0, r${JSON.stringify(PLUGIN)})
import presets.library_store as store
from pathlib import Path
store.STORE_DIRS = [lambda: Path(r${JSON.stringify(tmp)})]
store.save_library("lounge", {
  "version": 2,
  "module": "lounge",
  "activeId": "p1",
  "items": [{"id": "p1", "name": "19ft", "savedAt": "2026-01-01T00:00:00Z", "data": {}}],
})
bundle = store.load_all_libraries(["lounge", "kitchen", "not valid!"])
assert bundle["ok"], bundle
assert bundle["itemCount"] == 1, bundle
keys = [entry["moduleKey"] for entry in bundle["libraries"]]
assert keys == ["lounge", "kitchen"], keys
print("ok")
`;
  const result = runPython(code);
  if (skipIfNoPython(result)) return;
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout || "", /ok/);
});
