import type { OverheadLegacyGeometry } from "./geometry.ts";

export interface OHCSvgPreviewOptions {
  width?: number;
  height?: number;
  selectedZoneIndex?: number;
  showDimensions?: boolean;
}

function esc(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmt(value: number): string {
  return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(2)));
}

function panelFill(type: string): string {
  if (type === "rangehood_flap") return "#f3e8ff";
  if (type === "fixed_panel") return "#eef8ea";
  if (type === "open") return "#fff7dc";
  return "#e5f2ff";
}

export function generateOHCSvgPreview(
  geometry: OverheadLegacyGeometry,
  options: OHCSvgPreviewOptions = {},
): string {
  const width = options.width ?? 760;
  const height = options.height ?? 390;
  const showDimensions = options.showDimensions ?? true;
  const selectedZoneIndex = options.selectedZoneIndex ?? -1;

  const cw = geometry.cabinet.Cw;
  const ch = geometry.cabinet.Ch ?? geometry.manufacturing.TCH;
  const fg = geometry.manufacturing.FGw;
  const fpThickness = geometry.manufacturing.FPt;
  const tch = geometry.manufacturing.TCH;
  const fzh = geometry.manufacturing.FZH;
  const clearance = geometry.front_panels[0]?.clearance ?? 0;

  const padLeft = 46;
  const padTop = 36;
  const scale = Math.min((width - padLeft - 30) / Math.max(cw, 1), (height - padTop - 96) / Math.max(ch, 1));
  const ox = padLeft;
  const oy = padTop;
  const bodyW = cw * scale;
  const bodyH = ch * scale;
  const toX = (x: number) => ox + x * scale;
  const toY = (z: number) => oy + (ch - z) * scale;
  const rectFromXZ = (x0: number, z0: number, x1: number, z1: number) => ({
    x: toX(x0),
    y: toY(z1),
    w: Math.max((x1 - x0) * scale, 1),
    h: Math.max((z1 - z0) * scale, 1),
  });

  const dividerRects = geometry.divider_features.map((feature, index) => {
    const x0 = feature.XDi - fg / 2;
    const x1 = feature.XDi + fg / 2;
    const clampedX0 = Math.max(0, x0);
    const clampedX1 = Math.min(cw, x1);
    const r = rectFromXZ(clampedX0, 0, clampedX1, ch);
    const isEdge = index === 0 || index === geometry.divider_features.length - 1;
    const centerX = toX(feature.XDi);
    const labelY = oy + bodyH + 56 + (index % 2) * 14;
    return `
      <rect x="${fmt(r.x)}" y="${fmt(r.y)}" width="${fmt(r.w)}" height="${fmt(r.h)}" fill="rgba(92,75,55,0.45)" stroke="#6e5a42"></rect>
      ${isEdge ? `<text x="${fmt(centerX)}" y="${fmt(oy - 11)}" text-anchor="middle" fill="#6e5a42" font-size="10">edge divider</text>` : `
        <line x1="${fmt(centerX)}" y1="${fmt(oy - 8)}" x2="${fmt(centerX)}" y2="${fmt(oy + bodyH + 12)}" stroke="#e5484d" stroke-dasharray="5 4"></line>
        <text x="${fmt(centerX)}" y="${fmt(oy - 11)}" text-anchor="middle" fill="#e5484d" font-size="10">drag boundary</text>`}
      ${showDimensions ? `
        <line x1="${fmt(r.x)}" y1="${fmt(labelY)}" x2="${fmt(r.x + r.w)}" y2="${fmt(labelY)}" stroke="#6e5a42"></line>
        <line x1="${fmt(r.x)}" y1="${fmt(labelY - 4)}" x2="${fmt(r.x)}" y2="${fmt(labelY + 4)}" stroke="#6e5a42"></line>
        <line x1="${fmt(r.x + r.w)}" y1="${fmt(labelY - 4)}" x2="${fmt(r.x + r.w)}" y2="${fmt(labelY + 4)}" stroke="#6e5a42"></line>
        <text x="${fmt(r.x + r.w / 2)}" y="${fmt(labelY - 4)}" text-anchor="middle" fill="#6e5a42" font-size="10">D${index} ${fmt(fg)} mm</text>` : ""}
    `;
  }).join("");

  const openingRects = geometry.front_panels.map((panel) => {
    const opening = rectFromXZ(panel.opening.x[0], 0, panel.opening.x[1], fzh);
    const selected = panel.zoneIndex === selectedZoneIndex;
    const dimensionY = oy + bodyH + 20 + (panel.zoneIndex % 2) * 15;
    return `
      <rect x="${fmt(opening.x)}" y="${fmt(opening.y)}" width="${fmt(opening.w)}" height="${fmt(opening.h)}" fill="${panelFill(panel.type)}" stroke="${selected ? "#0f6bff" : "#9db6d5"}" stroke-width="${selected ? 2 : 1}"></rect>
      ${showDimensions ? `
        <line x1="${fmt(opening.x)}" y1="${fmt(dimensionY)}" x2="${fmt(opening.x + opening.w)}" y2="${fmt(dimensionY)}" stroke="#0f6bff"></line>
        <line x1="${fmt(opening.x)}" y1="${fmt(dimensionY - 4)}" x2="${fmt(opening.x)}" y2="${fmt(dimensionY + 4)}" stroke="#0f6bff"></line>
        <line x1="${fmt(opening.x + opening.w)}" y1="${fmt(dimensionY - 4)}" x2="${fmt(opening.x + opening.w)}" y2="${fmt(dimensionY + 4)}" stroke="#0f6bff"></line>
        <text x="${fmt(opening.x + opening.w / 2)}" y="${fmt(dimensionY - 3)}" text-anchor="middle" fill="#0f6bff" font-size="10">opening ${fmt(panel.opening.width)} mm</text>` : ""}
    `;
  }).join("");

  const frontPanelRects = geometry.front_panels.map((panel) => {
    const r = rectFromXZ(panel.x[0], panel.z[0], panel.x[1], panel.z[1]);
    const label = panel.type === "fixed_panel"
      ? "Fixed Panel"
      : panel.type === "rangehood_flap"
        ? "Rangehood Flap"
        : "Up Flap";
    return `
      <rect x="${fmt(r.x)}" y="${fmt(r.y)}" width="${fmt(r.w)}" height="${fmt(r.h)}" fill="none" stroke="#66758a" stroke-width="1.2"></rect>
      <text x="${fmt(r.x + r.w / 2)}" y="${fmt(r.y + r.h / 2 - 4)}" text-anchor="middle" fill="#22344d" font-size="12">${esc(label)}</text>
      <text x="${fmt(r.x + r.w / 2)}" y="${fmt(r.y + r.h / 2 + 13)}" text-anchor="middle" fill="#22344d" font-size="11">${esc(panel.id)}</text>
    `;
  }).join("");

  const hingeHoles = geometry.hinge_holes.map((hole) => {
    const panel = geometry.front_panels.find((candidate) => candidate.id === hole.boardId);
    if (!panel) return "";
    const x = panel.x[0] + hole.center[0];
    const z = panel.z[0] + hole.center[1];
    return `<circle cx="${fmt(toX(x))}" cy="${fmt(toY(z))}" r="${fmt(Math.max(hole.diameter / 2 * scale, 4))}" fill="none" stroke="#66758a" stroke-dasharray="4 2"></circle>`;
  }).join("");

  const bp = rectFromXZ(0, 0, cw, fg);
  const topArea = rectFromXZ(0, ch - tch, cw, ch);

  return `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" role="img" aria-label="OHC front elevation geometry preview">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#f8fbff"></rect>
      ${showDimensions ? `
        <line x1="${fmt(ox)}" y1="${fmt(oy - 14)}" x2="${fmt(ox + bodyW)}" y2="${fmt(oy - 14)}" stroke="#222"></line>
        <text x="${fmt(ox + bodyW / 2)}" y="${fmt(oy - 18)}" text-anchor="middle" fill="#222" font-size="11">${fmt(cw)}</text>
        <line x1="${fmt(ox - 14)}" y1="${fmt(oy)}" x2="${fmt(ox - 14)}" y2="${fmt(oy + bodyH)}" stroke="#222"></line>
        <text x="${fmt(ox - 20)}" y="${fmt(oy + bodyH / 2)}" text-anchor="middle" fill="#222" font-size="11" transform="rotate(-90 ${fmt(ox - 20)} ${fmt(oy + bodyH / 2)})">${fmt(ch)}</text>` : ""}
      <rect x="${fmt(ox)}" y="${fmt(oy)}" width="${fmt(bodyW)}" height="${fmt(bodyH)}" fill="#f4f0e6" stroke="#5c4b37" stroke-width="2"></rect>
      <rect x="${fmt(topArea.x)}" y="${fmt(topArea.y)}" width="${fmt(topArea.w)}" height="${fmt(topArea.h)}" fill="rgba(15,107,255,0.06)" stroke="#85b5ff" stroke-dasharray="5 3"></rect>
      <text x="${fmt(topArea.x + topArea.w - 6)}" y="${fmt(topArea.y + 14)}" text-anchor="end" fill="#0b57d0" font-size="10">T1/T2 / TCH ${fmt(tch)}</text>
      ${openingRects}
      ${frontPanelRects}
      <rect x="${fmt(bp.x)}" y="${fmt(bp.y)}" width="${fmt(bp.w)}" height="${fmt(bp.h)}" fill="#c7b9a2" stroke="#6e5a42"></rect>
      <text x="${fmt(bp.x + 6)}" y="${fmt(bp.y - 4)}" fill="#6e5a42" font-size="10">BP ${fmt(fg)} mm</text>
      ${dividerRects}
      ${hingeHoles}
      <text x="${fmt(ox + 4)}" y="${fmt(oy + bodyH + 18)}" fill="#6d7a8d" font-size="11">FGw ${fmt(fg)} mm, FPt/T1 ${fmt(fpThickness)} mm, clearance ${fmt(clearance)} mm</text>
    </svg>`;
}
