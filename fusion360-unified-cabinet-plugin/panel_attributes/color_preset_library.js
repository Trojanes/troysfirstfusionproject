(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.CabinetColorPresets = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const DEFAULT_STORAGE_KEY = "cabinetnc.attributeColors.v1";

  function slug(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "_")
      .replace(/[^a-z0-9_]+/g, "_")
      .replace(/_+/g, "_")
      .replace(/^_|_$/g, "")
      .slice(0, 32);
  }

  function normalize(items, nowIso) {
    const now = nowIso || new Date().toISOString();
    const byTag = new Map();
    (Array.isArray(items) ? items : []).forEach((item) => {
      const name = String(item && item.name || "").trim();
      const colorTag = slug(item && (item.colorTag || name));
      if (!name || !colorTag) return;
      byTag.set(colorTag, {
        id: String(item && item.id || `color-${colorTag}`),
        name,
        colorTag,
        createdAt: String(item && item.createdAt || now),
        updatedAt: String(item && (item.updatedAt || item.createdAt) || now),
      });
    });
    return [...byTag.values()].sort((a, b) => a.name.localeCompare(b.name));
  }

  function load(storage, key) {
    if (!storage || typeof storage.getItem !== "function") return [];
    try {
      const raw = storage.getItem(key || DEFAULT_STORAGE_KEY);
      return normalize(raw ? JSON.parse(raw) : []);
    } catch (_error) {
      return [];
    }
  }

  function save(storage, items, key) {
    if (!storage || typeof storage.setItem !== "function") {
      throw new Error("Color preset storage is unavailable.");
    }
    const normalized = normalize(items);
    storage.setItem(key || DEFAULT_STORAGE_KEY, JSON.stringify(normalized));
    return normalized;
  }

  function upsert(items, name, nowIso) {
    const cleanName = String(name || "").trim();
    const colorTag = slug(cleanName);
    if (!cleanName || !colorTag) throw new Error("A valid color name is required.");
    const now = nowIso || new Date().toISOString();
    const result = normalize(items, now);
    const existing = result.find((item) => item.colorTag === colorTag);
    if (existing) {
      existing.name = cleanName;
      existing.updatedAt = now;
    } else {
      result.push({
        id: `color-${Date.now().toString(36)}-${colorTag}`,
        name: cleanName,
        colorTag,
        createdAt: now,
        updatedAt: now,
      });
    }
    return normalize(result, now);
  }

  function remove(items, value) {
    const colorTag = slug(value);
    const current = normalize(items);
    return {
      removed: Boolean(colorTag && current.some((item) => item.colorTag === colorTag)),
      items: current.filter((item) => item.colorTag !== colorTag),
    };
  }

  return {
    DEFAULT_STORAGE_KEY,
    slug,
    normalize,
    load,
    save,
    upsert,
    remove,
  };
});
