/**
 * Unit tests for AppData preset library store (no Fusion).
 * Run: node --test fusion360-unified-cabinet-plugin/tests/preset_library_store.test.js
 * Note: Python store is mirrored here for logic checks of normalize shape.
 */
const assert = require("node:assert/strict");
const test = require("node:test");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const PLUGIN = path.join(__dirname, "..");
const STORE = path.join(PLUGIN, "presets", "library_store.py");

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

test("preset library survives save/load roundtrip on disk", () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "uc-presets-"));
  const code = `
import json, os, sys
sys.path.insert(0, r${JSON.stringify(PLUGIN)})
import presets.library_store as store

# Point store at temp dir
store.presets_dir = lambda: __import__("pathlib").Path(r${JSON.stringify(tmp)})
lib = {
  "version": 2,
  "module": "lounge",
  "activeId": "preset-a",
  "items": [{"id": "preset-a", "name": "Sofa A", "savedAt": "2026-01-01T00:00:00Z", "data": {"version": 1}}],
}
saved = store.save_library("lounge", lib)
assert saved["ok"], saved
loaded = store.load_library("lounge")
assert loaded["ok"], loaded
assert loaded["library"]["items"][0]["name"] == "Sofa A"
print("ok")
`;
  const result = runPython(code);
  if (result.status !== 0 && /no python|ENOENT|not recognized|Microsoft Store/i.test(String(result.stderr) + String(result.error || ""))) {
    // Skip when Python isn't on PATH in this environment.
    return;
  }
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.match(result.stdout || "", /ok/);
});
