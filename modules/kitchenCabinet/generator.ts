import type {
  BoardGeometry,
  BoardNotch,
  ComputedKitchenColumn,
  ComputedKitchenZone,
  FrontPanelGeometry,
  KitchenGeometryConstants,
  KitchenGeometryResult,
  KitchenLayoutState,
  KitchenZoneType,
  PanelBodyCutout,
  PanelDxfAudit,
  PanelDxfGeometry,
  PanelBodyPlane,
  ResolvedSlot,
  SidePanelOptions,
  SlotRequest,
  VPanelGeometry,
  VPanelMachiningMode,
} from "./types.ts";
import { relationshipDeclarationsForBoards } from "./relationshipDeclarations.ts";

export * from "./types.ts";

const DEFAULT_CONSTANTS: KitchenGeometryConstants = {
  notchAllowanceExtra: 1,
  style1ToeKickY: 70,
  bottomSlotRearY: 80,
  receiverNotchDepth: 85,
  supportStripWidth: 100,
  b3Depth: 150,
  b3InternalNotchDepth: 75,
  supportStripNotchDepth: 20,
  minStripSegmentLength: 30,
};

/** Match General Tall / Fridge LED insert groove (mm). */
const LED_GROOVE_WIDTH = 14.5;
const LED_GROOVE_DEPTH = 6.5;
/** Clear strip from board front edge to near wall of main channel. */
const LED_GROOVE_FRONT_LAND_MM = 18;
/** Centerline from front = land + half groove width (25.25). */
const LED_GROOVE_FRONT_OFFSET = LED_GROOVE_FRONT_LAND_MM + LED_GROOVE_WIDTH / 2;
const LED_GROOVE_BRANCH_END_INSET = 80;

function n(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

const DEFAULT_SIDE_PANEL_OPTIONS: SidePanelOptions = {
  panelType: "carcass",
  frontVisible: false,
  bchNotchEnabled: true,
  grooveVisible: true,
  extendT2T3B4ToOuterFace: true,
  strengtheningStripEnabled: false,
};

function normalizeSidePanelOptions(input: Partial<SidePanelOptions> | undefined): SidePanelOptions {
  return {
    ...DEFAULT_SIDE_PANEL_OPTIONS,
    ...(input || {}),
    panelType: input?.panelType === "door" ? "door" : "carcass",
    frontVisible: input?.frontVisible === true,
    bchNotchEnabled: input?.bchNotchEnabled !== false,
    grooveVisible: input?.grooveVisible !== false,
    extendT2T3B4ToOuterFace: input?.extendT2T3B4ToOuterFace !== false,
    strengtheningStripEnabled: input?.strengtheningStripEnabled === true,
  };
}

function sidePanelThickness(options: SidePanelOptions, cpt: number, fpt: number): number {
  return options.panelType === "door" ? fpt : cpt;
}

function kitchenStructuralDepth(settings: KitchenLayoutState["globalSettings"]): number {
  return Math.max(0, n(settings.depth, 0) - n(settings.frontThickness, 16));
}

function resolveOuterSideOptions(state: KitchenLayoutState, side: "left" | "right", warnings?: string[]): SidePanelOptions {
  const column = side === "left" ? state.columns[0] : state.columns[state.columns.length - 1];
  const key = side === "left" ? "leftSidePanelOptions" : "rightSidePanelOptions";
  const zonesWithOptions = (column?.zones || []).filter((zone) => Boolean(zone[key]));
  const preferredZone = zonesWithOptions.find((zone) => isDoorZone(zone.zoneType))
    || zonesWithOptions.find((zone) => zoneVisible(zone.zoneType))
    || zonesWithOptions[0];
  return normalizeSidePanelOptions(preferredZone?.[key]);
}

function sideReferences(state: KitchenLayoutState, warnings?: string[]) {
  const g = state.globalSettings;
  const cw = n(g.length, 0);
  const cpt = n(g.materialThickness, 15);
  const fpt = n(g.frontThickness, 16);
  const leftOptions = resolveOuterSideOptions(state, "left", warnings);
  const rightOptions = resolveOuterSideOptions(state, "right", warnings);
  const leftThickness = sidePanelThickness(leftOptions, cpt, fpt);
  const rightThickness = sidePanelThickness(rightOptions, cpt, fpt);
  return {
    left: { outerX: 0, innerX: leftThickness, thickness: leftThickness, options: leftOptions },
    right: { outerX: cw, innerX: cw - rightThickness, thickness: rightThickness, options: rightOptions },
    cpt,
    fpt,
  };
}

function intersects(a0: number, a1: number, b0: number, b1: number): boolean {
  return a0 < b1 && b0 < a1;
}

function board(
  id: string,
  name: string,
  type: BoardGeometry["type"],
  category: string,
  materialThickness: number,
  profilePlane: BoardGeometry["profilePlane"],
  thicknessAxis: BoardGeometry["thicknessAxis"],
  bounds: Pick<BoardGeometry, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">,
  notches?: BoardNotch[],
  notes?: string[],
): BoardGeometry {
  return {
    id,
    name,
    type,
    category,
    materialThickness,
    profilePlane,
    thicknessAxis,
    ...bounds,
    ...(notches?.length ? { notches } : {}),
    ...(notes?.length ? { notes } : {}),
  };
}

function functionalProfileXY(
  clearX0: number,
  clearX1: number,
  y0: number,
  y1: number,
  leftTongueLength: number,
  rightTongueLength: number,
  tongueY0: number,
  tongueY1: number,
): Array<[number, number]> {
  const raw: Array<[number, number]> = [
    [clearX0, y0],
    [clearX1, y0],
    [clearX1, tongueY0],
    [clearX1 + rightTongueLength, tongueY0],
    [clearX1 + rightTongueLength, tongueY1],
    [clearX1, tongueY1],
    [clearX1, y1],
    [clearX0, y1],
    [clearX0, tongueY1],
    [clearX0 - leftTongueLength, tongueY1],
    [clearX0 - leftTongueLength, tongueY0],
    [clearX0, tongueY0],
    [clearX0, y0],
  ];
  return trimClosedProfile(raw);
}

function samePoint(a: [number, number], b: [number, number]): boolean {
  return Math.abs(a[0] - b[0]) <= 0.001 && Math.abs(a[1] - b[1]) <= 0.001;
}

function isCollinear(a: [number, number], b: [number, number], c: [number, number]): boolean {
  const sameX = Math.abs(a[0] - b[0]) <= 0.001 && Math.abs(b[0] - c[0]) <= 0.001;
  const sameY = Math.abs(a[1] - b[1]) <= 0.001 && Math.abs(b[1] - c[1]) <= 0.001;
  return sameX || sameY;
}

function trimClosedProfile(points: Array<[number, number]>): Array<[number, number]> {
  const deduped: Array<[number, number]> = [];
  for (const point of points) {
    if (deduped.length && samePoint(deduped[deduped.length - 1], point)) continue;
    deduped.push(point);
  }
  if (deduped.length > 1 && samePoint(deduped[0], deduped[deduped.length - 1])) deduped.pop();
  let changed = true;
  while (changed && deduped.length >= 3) {
    changed = false;
    for (let index = 0; index < deduped.length; index += 1) {
      const prev = deduped[(index - 1 + deduped.length) % deduped.length];
      const current = deduped[index];
      const next = deduped[(index + 1) % deduped.length];
      if (isCollinear(prev, current, next)) {
        deduped.splice(index, 1);
        changed = true;
        break;
      }
    }
  }
  return [...deduped, deduped[0]];
}

function profileArea(points: Array<[number, number]>): number {
  const closed = points.length > 1 && samePoint(points[0], points[points.length - 1]) ? points : [...points, points[0]];
  let area = 0;
  for (let index = 0; index < closed.length - 1; index += 1) {
    area += closed[index][0] * closed[index + 1][1] - closed[index + 1][0] * closed[index][1];
  }
  return area / 2;
}

function auditClosedProfile(raw: Array<[number, number]>, cleaned: Array<[number, number]>): PanelDxfAudit {
  let duplicatePointCount = 0;
  let collinearPointCount = 0;
  for (let index = 1; index < raw.length; index += 1) {
    if (samePoint(raw[index - 1], raw[index])) duplicatePointCount += 1;
  }
  const open = raw.length > 1 && samePoint(raw[0], raw[raw.length - 1]) ? raw.slice(0, -1) : raw;
  for (let index = 0; index < open.length; index += 1) {
    const prev = open[(index - 1 + open.length) % open.length];
    const current = open[index];
    const next = open[(index + 1) % open.length];
    if (isCollinear(prev, current, next)) collinearPointCount += 1;
  }
  const area = profileArea(cleaned);
  const warnings: string[] = [];
  if (!samePoint(cleaned[0], cleaned[cleaned.length - 1])) warnings.push("Profile is not closed.");
  if (Math.abs(area) <= 0.001) warnings.push("Profile area is zero.");
  return {
    closed: cleaned.length > 1 && samePoint(cleaned[0], cleaned[cleaned.length - 1]),
    pointCount: cleaned.length,
    duplicatePointCount,
    collinearPointCount,
    area,
    warnings,
  };
}

function zoneVisible(type: KitchenZoneType | undefined): boolean {
  return isDoorZone(type) || type === "open" || type === "custom";
}

function isDoorZone(type: KitchenZoneType | undefined): boolean {
  return type === "left_door" || type === "right_door" || type === "double_door";
}

function vProfileNoWheel(style: string, cd: number, ch: number, cpt: number, bch: number, c: KitchenGeometryConstants): Array<[number, number]> {
  const na = cpt + c.notchAllowanceExtra;
  const frontY = style === "style_2" ? cpt : c.style1ToeKickY;
  const r = c.receiverNotchDepth;
  return [
    [frontY, 0],
    [frontY, bch],
    [c.bottomSlotRearY, bch],
    [c.bottomSlotRearY, bch + na],
    [0, bch + na],
    [0, ch - na],
    [r, ch - na],
    [r, ch],
    [cd - na - r, ch],
    [cd - na - r, ch - na],
    [cd - na, ch - na],
    [cd - na, ch - r],
    [cd, ch - r],
    [cd, r],
    [cd - na, r],
    [cd - na, 0],
    [frontY, 0],
  ];
}

function vProfileWithWheel(base: Array<[number, number]>, wheel: { height: number; depth: number } | undefined, cd: number, cpt: number, c: KitchenGeometryConstants): Array<[number, number]> {
  if (!wheel) return base;
  const na = cpt + c.notchAllowanceExtra;
  const r = c.receiverNotchDepth;
  const ah = Math.max(0, n(wheel.height, 0));
  const ad = Math.max(0, n(wheel.depth, 0));
  const replacement: Array<[number, number]> = [
    [cd, ah + r],
    [cd - na, ah + r],
    [cd - na, ah],
    [cd - ad, ah],
    [cd - ad, 0],
  ];
  return [...base.slice(0, -4), ...replacement, base[base.length - 1]];
}

/**
 * Outer V beside a stove bay has no T1/T2/T3 receivers to seat — keep toe-kick / B3
 * pocket only and a flat top + full rear so the panel does not show empty 豁口.
 */
function vProfileStoveOuterNoReceivers(
  style: string,
  cd: number,
  ch: number,
  cpt: number,
  bch: number,
  c: KitchenGeometryConstants,
): Array<[number, number]> {
  const na = cpt + c.notchAllowanceExtra;
  const frontY = style === "style_2" ? cpt : c.style1ToeKickY;
  return [
    [frontY, 0],
    [frontY, bch],
    [c.bottomSlotRearY, bch],
    [c.bottomSlotRearY, bch + na],
    [0, bch + na],
    [0, ch],
    [cd, ch],
    [cd, 0],
    [frontY, 0],
  ];
}

function vProfileStoveOuterWithWheel(
  base: Array<[number, number]>,
  wheel: { height: number; depth: number } | undefined,
  cd: number,
  ch: number,
  cpt: number,
  c: KitchenGeometryConstants,
): Array<[number, number]> {
  if (!wheel) return trimClosedProfile(base);
  const na = cpt + c.notchAllowanceExtra;
  const r = c.receiverNotchDepth;
  const ah = Math.max(0, n(wheel.height, 0));
  const ad = Math.max(0, n(wheel.depth, 0));
  const closed = base.length > 1 && samePoint(base[0], base[base.length - 1]) ? base.slice(0, -1) : [...base];
  // Flat stove-outer profile ends [... , [0,ch], [cd,ch], [cd,0]]; replace the rear drop with the wheel pocket.
  const head = closed.filter(([y, z]) => !(Math.abs(y - cd) <= 0.001 && z < ch - 0.001));
  if (!head.length || Math.abs(head[head.length - 1][0] - cd) > 0.001 || Math.abs(head[head.length - 1][1] - ch) > 0.001) {
    head.push([cd, ch]);
  }
  return trimClosedProfile([
    ...head,
    [cd, ah + r],
    [cd - na, ah + r],
    [cd - na, ah],
    [cd - ad, ah],
    [cd - ad, 0],
    closed[0],
  ]);
}

function applySideFrontVisibility(
  profile: Array<[number, number]>,
  options: SidePanelOptions | undefined,
  fpt: number,
  bch: number,
  frontRepairMaxY: number,
  frontRepairMaxZ: number,
  cabinetHeight: number,
): Array<[number, number]> {
  const frontVisible = Boolean(options?.frontVisible);
  if (!frontVisible || profile.length < 2) return profile;
  const notchlessTop = profile.map(([y, z]) => [
    z >= cabinetHeight - frontRepairMaxZ - 0.001 && y >= -0.001 && y <= frontRepairMaxY + 0.001 ? -fpt : y,
    z >= cabinetHeight - frontRepairMaxZ - 0.001 && y >= -0.001 && y <= frontRepairMaxY + 0.001 ? cabinetHeight : z,
  ]);
  const extended = notchlessTop.map(([y, z]) => [
    Math.abs(y) <= 0.001 && z >= frontRepairMaxZ - 0.001 && z < cabinetHeight - 0.001 ? -fpt : y,
    z,
  ]);
  if (options?.bchNotchEnabled !== false) return trimClosedProfile(extended);
  return trimClosedProfile(extended.map(([y, z]) => [
    z <= frontRepairMaxZ + 0.001 && y >= -0.001 && y <= frontRepairMaxY + 0.001 ? -fpt : y,
    z,
  ]));
}

function computeXBoundaries(columns: KitchenLayoutState["columns"]): number[] {
  const boundaries = [0];
  for (const column of columns) {
    boundaries.push(boundaries[boundaries.length - 1] + n(column.width, 0));
  }
  return boundaries;
}

function computeVPanels(state: KitchenLayoutState, constants: KitchenGeometryConstants, warnings: string[]): VPanelGeometry[] {
  const g = state.globalSettings;
  const cw = n(g.length, 0);
  const cd = kitchenStructuralDepth(g);
  const ch = n(g.height, 0);
  const cpt = n(g.materialThickness, 15);
  const fpt = n(g.frontThickness, 16);
  const bch = n(g.bottomClearanceHeight, 70);
  const boundaries = computeXBoundaries(state.columns);
  const refs = sideReferences(state, warnings);
  const panels: VPanelGeometry[] = [];
  for (let i = 0; i < boundaries.length; i += 1) {
    const sideRef = i === 0 ? refs.left : i === boundaries.length - 1 ? refs.right : null;
    const panelThickness = sideRef?.thickness ?? cpt;
    const centerX = i === 0 ? panelThickness / 2 : i === boundaries.length - 1 ? cw - panelThickness / 2 : boundaries[i];
    const x0 = i === 0 ? 0 : i === boundaries.length - 1 ? cw - panelThickness : centerX - cpt / 2;
    const x1 = i === 0 ? panelThickness : i === boundaries.length - 1 ? cw : centerX + cpt / 2;
    const wheel = state.wheelAvoidances.find((avoidance) => intersects(x0, x1, n(avoidance.x0, 0), n(avoidance.x1, 0)));
    const baseProfile = vProfileNoWheel(g.bottomClearanceStyle, cd, ch, panelThickness, bch, constants);
    const visibleProfile = applySideFrontVisibility(
      baseProfile,
      sideRef?.options,
      fpt,
      bch,
      Math.max(constants.bottomSlotRearY, constants.receiverNotchDepth),
      bch + panelThickness + constants.notchAllowanceExtra,
      ch,
    );
    if (wheel && n(wheel.height, 0) < bch) warnings.push(`Wheel avoidance ${wheel.id} height is below bottom clearance; V${i} profile may conflict with bottom system.`);
    panels.push({
      id: `V${i}`,
      index: i,
      x0,
      x1,
      centerX,
      yzProfile: vProfileWithWheel(visibleProfile, wheel, cd, panelThickness, constants),
      hasWheelAvoidance: Boolean(wheel),
      machiningMode: state.vPanelMachiningPreferences?.find((pref) => pref.vPanelIndex === i)?.mode,
      materialThickness: panelThickness,
      sidePanelOptions: sideRef?.options,
    });
  }
  return panels;
}

function computeColumns(state: KitchenLayoutState, vPanels: VPanelGeometry[]): ComputedKitchenColumn[] {
  const boundaries = computeXBoundaries(state.columns);
  return state.columns.map((column, index) => ({
    ...column,
    index,
    logicalX0: boundaries[index],
    logicalX1: boundaries[index + 1],
    clearX0: vPanels[index].x1,
    clearX1: vPanels[index + 1].x0,
  }));
}

function computeZones(state: KitchenLayoutState, columns: ComputedKitchenColumn[]): ComputedKitchenZone[] {
  const ch = n(state.globalSettings.height, 0);
  const zones: ComputedKitchenZone[] = [];
  for (const column of columns) {
    let zCursor = ch;
    column.zones.forEach((zone, zoneIndex) => {
      const height = n(zone.height, 0);
      zones.push({
        ...zone,
        columnId: column.id,
        columnIndex: column.index,
        zoneIndex,
        x0: column.clearX0,
        x1: column.clearX1,
        z0: zCursor - height,
        z1: zCursor,
      });
      zCursor -= height;
    });
  }
  return zones;
}

function rebuildStoveEdgeOuterVPanel(
  panel: VPanelGeometry,
  state: KitchenLayoutState,
  constants: KitchenGeometryConstants,
): void {
  const g = state.globalSettings;
  const cd = kitchenStructuralDepth(g);
  const ch = n(g.height, 0);
  const cpt = n(g.materialThickness, 15);
  const fpt = n(g.frontThickness, 16);
  const bch = n(g.bottomClearanceHeight, 70);
  const panelThickness = panel.materialThickness ?? cpt;
  const baseProfile = vProfileStoveOuterNoReceivers(
    g.bottomClearanceStyle,
    cd,
    ch,
    panelThickness,
    bch,
    constants,
  );
  const visibleProfile = applySideFrontVisibility(
    baseProfile,
    panel.sidePanelOptions,
    fpt,
    bch,
    Math.max(constants.bottomSlotRearY, constants.receiverNotchDepth),
    bch + panelThickness + constants.notchAllowanceExtra,
    ch,
  );
  const wheel = state.wheelAvoidances.find((avoidance) =>
    intersects(panel.x0, panel.x1, n(avoidance.x0, 0), n(avoidance.x1, 0)),
  );
  panel.yzProfile = vProfileStoveOuterWithWheel(visibleProfile, wheel, cd, ch, panelThickness, constants);
  panel.hasWheelAvoidance = Boolean(wheel);
}

function removeUnsupportedEdgeStoveVPanelNotches(
  vPanels: VPanelGeometry[],
  zones: ComputedKitchenZone[],
  state: KitchenLayoutState,
  constants: KitchenGeometryConstants,
): void {
  const lastColumnIndex = state.columns.length - 1;
  const stoveAtLeftEdge = zones.some((zone) => zone.zoneType === "stove" && zone.columnIndex === 0);
  const stoveAtRightEdge = zones.some((zone) => zone.zoneType === "stove" && zone.columnIndex === lastColumnIndex);
  if (stoveAtLeftEdge && vPanels[0]) rebuildStoveEdgeOuterVPanel(vPanels[0], state, constants);
  if (stoveAtRightEdge && vPanels[vPanels.length - 1]) {
    rebuildStoveEdgeOuterVPanel(vPanels[vPanels.length - 1], state, constants);
  }
}

function supportStripNotches(idPrefix: string, strip: Pick<BoardGeometry, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">, vPanels: VPanelGeometry[], cpt: number, c: KitchenGeometryConstants, kind: "T1" | "T2" | "T3" | "B4"): BoardNotch[] {
  const notchDepth = c.supportStripNotchDepth;
  return vPanels
    .filter((v) => v.centerX >= strip.x0 - 0.5 && v.centerX <= strip.x1 + 0.5)
    .map((v) => {
      const x0 = Math.max(strip.x0, v.centerX - cpt / 2 - 0.5);
      const x1 = Math.min(strip.x1, v.centerX + cpt / 2 + 0.5);
      const base = { id: `${idPrefix}-notch-V${v.index}`, x0, x1 };
      if (kind === "T1") return { ...base, y0: strip.y1 - notchDepth, y1: strip.y1, from: "rear" as const };
      if (kind === "T2") return { ...base, y0: strip.y0, y1: strip.y0 + notchDepth, from: "front" as const };
      if (kind === "T3") return { ...base, z0: strip.z0, z1: strip.z0 + notchDepth, from: "bottom" as const };
      return { ...base, z0: strip.z1 - notchDepth, z1: strip.z1, from: "top" as const };
    });
}

function splitStripForStove<T extends Pick<BoardGeometry, "x0" | "x1" | "y0" | "y1">>(strip: T, stoveCuts: Array<{ x0: number; x1: number; y0: number; y1: number }>, constants: KitchenGeometryConstants): Array<T & { segmentIndex: number }> {
  let segments: Array<T & { segmentIndex: number }> = [{ ...strip, segmentIndex: 0 }];
  for (const cut of stoveCuts) {
    if (!intersects(strip.y0, strip.y1, cut.y0, cut.y1)) continue;
    const next: Array<T & { segmentIndex: number }> = [];
    for (const segment of segments) {
      if (!intersects(segment.x0, segment.x1, cut.x0, cut.x1)) {
        next.push(segment);
        continue;
      }
      const left = { ...segment, x1: Math.min(segment.x1, cut.x0) };
      const right = { ...segment, x0: Math.max(segment.x0, cut.x1) };
      if (left.x1 - left.x0 >= constants.minStripSegmentLength) next.push(left);
      if (right.x1 - right.x0 >= constants.minStripSegmentLength) next.push(right);
    }
    segments = next.map((segment, index) => ({ ...segment, segmentIndex: index }));
  }
  return segments;
}

function splitStripByXCuts<T extends Pick<BoardGeometry, "x0" | "x1">>(strip: T, xCuts: Array<{ x0: number; x1: number }>, constants: KitchenGeometryConstants): Array<T & { segmentIndex: number }> {
  let segments: Array<T & { segmentIndex: number }> = [{ ...strip, segmentIndex: 0 }];
  for (const cut of xCuts) {
    const next: Array<T & { segmentIndex: number }> = [];
    for (const segment of segments) {
      if (!intersects(segment.x0, segment.x1, cut.x0, cut.x1)) {
        next.push(segment);
        continue;
      }
      const left = { ...segment, x1: Math.min(segment.x1, cut.x0) };
      const right = { ...segment, x0: Math.max(segment.x0, cut.x1) };
      if (left.x1 - left.x0 >= constants.minStripSegmentLength) next.push(left);
      if (right.x1 - right.x0 >= constants.minStripSegmentLength) next.push(right);
    }
    segments = next.map((segment, index) => ({ ...segment, segmentIndex: index }));
  }
  return segments;
}

function validWheelAvoidances(state: KitchenLayoutState, cd: number, ch: number): Array<{ id: string; x0: number; x1: number; height: number; depth: number }> {
  return (state.wheelAvoidances || [])
    .map((avoidance, index) => {
      const x0 = Math.max(0, n(avoidance.x0, 0));
      const x1 = Math.min(n(state.globalSettings.length, 0), n(avoidance.x1, 0));
      const height = Math.max(0, Math.min(ch, n(avoidance.height, 0)));
      const depth = Math.max(0, Math.min(cd, n(avoidance.depth, 0)));
      return { id: avoidance.id || `wheel-${index + 1}`, x0, x1, height, depth };
    })
    .filter((avoidance) => avoidance.x1 > avoidance.x0 && avoidance.height > 0 && avoidance.depth > 0);
}

function generateBaseBoards(state: KitchenLayoutState, vPanels: VPanelGeometry[], columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], constants: KitchenGeometryConstants, warnings: string[]): BoardGeometry[] {
  const g = state.globalSettings;
  const cw = n(g.length, 0);
  const cd = kitchenStructuralDepth(g);
  const ch = n(g.height, 0);
  const cpt = n(g.materialThickness, 15);
  const fpt = n(g.frontThickness, 16);
  const bch = n(g.bottomClearanceHeight, 70);
  const boards: BoardGeometry[] = [];
  const refs = sideReferences(state, warnings);
  const frontStopX0 = refs.left.options.frontVisible ? refs.left.innerX : 0;
  const frontStopX1 = refs.right.options.frontVisible ? refs.right.innerX : cw;
  const stoveAtLeftEdge = zones.some((zone) => zone.zoneType === "stove" && zone.columnIndex === 0);
  const stoveAtRightEdge = zones.some((zone) => zone.zoneType === "stove" && zone.columnIndex === columns.length - 1);
  // Stove-edge outer V has no strip receivers — keep T2/T3/B4 off that skin thickness.
  let rearSupportX0 = refs.left.options.frontVisible && !refs.left.options.extendT2T3B4ToOuterFace ? refs.left.innerX : 0;
  let rearSupportX1 = refs.right.options.frontVisible && !refs.right.options.extendT2T3B4ToOuterFace ? refs.right.innerX : cw;
  if (stoveAtLeftEdge && vPanels[0]) rearSupportX0 = Math.max(rearSupportX0, vPanels[0].x1);
  if (stoveAtRightEdge && vPanels.length) rearSupportX1 = Math.min(rearSupportX1, vPanels[vPanels.length - 1].x0);
  const wheelAvoidances = validWheelAvoidances(state, cd, ch);

  if (g.bottomClearanceStyle === "style_2") {
    boards.push(board("B1", "Bottom front panel", "B1", "bottom_system", fpt, "XZ", "Y", { x0: frontStopX0, x1: frontStopX1, y0: -fpt, y1: 0, z0: 0, z1: bch }));
    boards.push(board("B2", "Bottom carcass panel", "B2", "bottom_system", cpt, "XZ", "Y", { x0: frontStopX0, x1: frontStopX1, y0: 0, y1: cpt, z0: 0, z1: bch }));
  } else {
    boards.push(board("B1", "Bottom front panel", "B1", "bottom_system", fpt, "XZ", "Y", { x0: frontStopX0, x1: frontStopX1, y0: constants.style1ToeKickY - cpt - fpt, y1: constants.style1ToeKickY - cpt, z0: 0, z1: bch }));
    boards.push(board("B2", "Bottom carcass panel", "B2", "bottom_system", cpt, "XZ", "Y", { x0: frontStopX0, x1: frontStopX1, y0: constants.style1ToeKickY - cpt, y1: constants.style1ToeKickY, z0: 0, z1: bch }));
  }

  const b3Y0 = 0;
  const b3Y1 = constants.supportStripWidth;
  boards.push(board(
    "B3",
    "Bottom horizontal board",
    "B3",
    "bottom_system",
    cpt,
    "XY",
    "Z",
    { x0: frontStopX0, x1: frontStopX1, y0: b3Y0, y1: b3Y1, z0: bch, z1: bch + cpt },
    vPanels.map((v) => ({
      id: `B3-notch-V${v.index}`,
      x0: Math.max(frontStopX0, v.centerX - cpt / 2 - 0.5),
      x1: Math.min(frontStopX1, v.centerX + cpt / 2 + 0.5),
      y0: Math.max(b3Y0, b3Y1 - constants.supportStripNotchDepth),
      y1: b3Y1,
      from: "rear",
    })),
  ));

  const stoveCuts = zones
    .filter((zone) => zone.zoneType === "stove")
    .map((zone) => {
      const column = columns[zone.columnIndex];
      return {
        x0: column.clearX0,
        x1: column.clearX1,
        y0: 0,
        y1: fpt + 100,
      };
    });

  const t1Base = { x0: frontStopX0, x1: frontStopX1, y0: 0, y1: constants.supportStripWidth, z0: ch - cpt, z1: ch };
  splitStripForStove(t1Base, stoveCuts, constants).forEach((segment) => {
    boards.push(board(`T1-${segment.segmentIndex + 1}`, "Top front strip", "T1", "support_strip", cpt, "XY", "Z", segment, supportStripNotches(`T1-${segment.segmentIndex + 1}`, segment, vPanels, cpt, constants, "T1")));
  });

  const t2Base = { x0: rearSupportX0, x1: rearSupportX1, y0: cd - constants.supportStripWidth, y1: cd, z0: ch - cpt, z1: ch };
  splitStripForStove(t2Base, stoveCuts, constants).forEach((segment) => {
    boards.push(board(`T2-${segment.segmentIndex + 1}`, "Top rear strip", "T2", "support_strip", cpt, "XY", "Z", segment, supportStripNotches(`T2-${segment.segmentIndex + 1}`, segment, vPanels, cpt, constants, "T2")));
  });

  const t3Base = { x0: rearSupportX0, x1: rearSupportX1, y0: cd - cpt, y1: cd, z0: ch - constants.supportStripWidth, z1: ch };
  splitStripForStove(t3Base, stoveCuts, constants).forEach((segment) => {
    boards.push(board(`T3-${segment.segmentIndex + 1}`, "Rear top vertical strip", "T3", "support_strip", cpt, "XZ", "Y", segment, supportStripNotches(`T3-${segment.segmentIndex + 1}`, segment, vPanels, cpt, constants, "T3")));
  });

  const b4Base = { x0: rearSupportX0, x1: rearSupportX1, y0: cd - cpt, y1: cd, z0: 0, z1: constants.supportStripWidth };
  splitStripByXCuts(b4Base, wheelAvoidances, constants).forEach((segment) => {
    boards.push(board(
      `B4-${segment.segmentIndex + 1}`,
      "Rear bottom vertical strip",
      "B4",
      "support_strip",
      cpt,
      "XZ",
      "Y",
      segment,
      supportStripNotches(`B4-${segment.segmentIndex + 1}`, segment, vPanels, cpt, constants, "B4"),
      wheelAvoidances.length ? ["Lower B4 kept outside wheel avoidance span."] : undefined,
    ));
  });

  for (const avoidance of wheelAvoidances) {
    const x0 = Math.max(rearSupportX0, avoidance.x0);
    const x1 = Math.min(rearSupportX1, avoidance.x1);
    const y0 = Math.max(0, cd - avoidance.depth);
    const y1 = cd;
    const topZ1 = avoidance.height;
    const topZ0 = topZ1 - cpt;
    if (x1 <= x0 || y1 <= y0 || topZ0 < 0) {
      warnings.push(`Wheel avoidance ${avoidance.id} support boards skipped due to invalid bounds.`);
      continue;
    }
    boards.push(board(
      `${avoidance.id}-avoidance-top`,
      "Wheel avoidance top",
      "avoidance_top",
      "avoidance_support",
      cpt,
      "XY",
      "Z",
      { x0, x1, y0, y1, z0: topZ0, z1: topZ1 },
      undefined,
      ["Avoidance top horizontal board generated from wheel arch settings."],
    ));
    const b4Z0 = topZ1;
    const b4Z1 = topZ1 + constants.supportStripWidth;
    if (b4Z1 <= ch) {
      const avoidanceB4 = { x0, x1, y0: cd - cpt, y1: cd, z0: b4Z0, z1: b4Z1 };
      boards.push(board(
        `${avoidance.id}-B4`,
        "Wheel avoidance raised B4",
        "B4",
        "support_strip",
        cpt,
        "XZ",
        "Y",
        avoidanceB4,
        supportStripNotches(`${avoidance.id}-B4`, avoidanceB4, vPanels, cpt, constants, "B4"),
        ["B4 segment placed directly above wheel avoidance."],
      ));
    } else {
      warnings.push(`Wheel avoidance ${avoidance.id} raised B4 skipped because it exceeds cabinet height.`);
    }
    const frontZ1 = Math.max(0, avoidance.height - cpt);
    if (frontZ1 > 0) {
      boards.push(board(
        `${avoidance.id}-avoidance-front`,
        "Wheel avoidance front",
        "avoidance_front",
        "avoidance_support",
        cpt,
        "XZ",
        "Y",
        { x0, x1, y0, y1: y0 + cpt, z0: 0, z1: frontZ1 },
        undefined,
        ["Avoidance front vertical board generated from wheel arch settings."],
      ));
    } else {
      warnings.push(`Wheel avoidance ${avoidance.id} front board skipped because height is not greater than CPT.`);
    }
  }

  if (stoveCuts.length > 0 && boards.filter((item) => item.type === "T1" || item.type === "T2" || item.type === "T3").length === 0) {
    warnings.push("Stove cuts removed all top support strip segments.");
  }

  return boards;
}

function boundaryBoardType(zoneType: KitchenZoneType, isBottomZone: boolean): "drawer_divider" | "full_depth_shelf" | null {
  if (isBottomZone) return null;
  if (zoneType === "drawer" || zoneType === "down_flap") return "drawer_divider";
  if (isDoorZone(zoneType) || zoneType === "open" || zoneType === "stove" || zoneType === "custom") {
    return "full_depth_shelf";
  }
  return null;
}

function addFunctionalBoard(boards: BoardGeometry[], id: string, type: "drawer_divider" | "full_depth_shelf" | "door_shelf", column: ComputedKitchenColumn, centerZ: number, cpt: number, cd: number, constants: KitchenGeometryConstants, notes?: string[]): void {
  const isDrawer = type === "drawer_divider";
  const y0 = 0;
  const y1 = isDrawer ? constants.b3Depth : cd;
  const leftTongueLength = cpt / 2;
  const rightTongueLength = cpt / 2;
  const tongueY0 = isDrawer ? 50 : (cd - cd / 3) / 2;
  const tongueY1 = isDrawer ? constants.b3Depth : tongueY0 + cd / 3;
  const item = board(
    id,
    type.replace(/_/g, " "),
    type,
    "functional",
    cpt,
    "XY",
    "Z",
    {
      x0: column.clearX0 - leftTongueLength,
      x1: column.clearX1 + rightTongueLength,
      y0,
      y1,
      z0: centerZ - cpt / 2,
      z1: centerZ + cpt / 2,
    },
    undefined,
    notes,
  );
  item.profileXY = functionalProfileXY(
    column.clearX0,
    column.clearX1,
    y0,
    y1,
    leftTongueLength,
    rightTongueLength,
    tongueY0,
    tongueY1,
  );
  boards.push(item);
}

function generateFunctionalBoards(columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], state: KitchenLayoutState, constants: KitchenGeometryConstants, warnings: string[]): BoardGeometry[] {
  const cpt = n(state.globalSettings.materialThickness, 15);
  const cd = kitchenStructuralDepth(state.globalSettings);
  const boards: BoardGeometry[] = [];
  for (const column of columns) {
    const columnZones = zones.filter((zone) => zone.columnId === column.id);
    columnZones.forEach((zone, index) => {
      const type = boundaryBoardType(zone.zoneType, index === columnZones.length - 1);
      if (type) addFunctionalBoard(boards, `${column.id}-${zone.id}-bottom`, type, column, zone.z0, cpt, cd, constants);
      if (isDoorZone(zone.zoneType) && zone.shelfEnabled !== false) {
        const shelfTopHeight = zone.shelfHeight == null ? Math.round(zone.height / 2) : n(zone.shelfHeight, 0);
        const shelfTopZ = zone.z0 + shelfTopHeight;
        if (zone.height < 350) {
          warnings.push(`Door shelf skipped in ${zone.id}: zone height ${zone.height} < 350.`);
        } else if (shelfTopZ <= zone.z0 || shelfTopZ >= zone.z1) {
          warnings.push(`Door shelf skipped in ${zone.id}: shelf top Z ${shelfTopZ} is outside zone range ${zone.z0}-${zone.z1}.`);
        } else {
          const centerZ = shelfTopZ - cpt / 2;
          addFunctionalBoard(boards, `${zone.id}-door-shelf`, "door_shelf", column, centerZ, cpt, cd, constants, ["Shelf top height is user input; centerZ = shelfTopZ - CPT/2."]);
        }
      }
    });
  }
  return boards;
}

function shortenHorizontalBoardsForWheelAvoidance(boards: BoardGeometry[], state: KitchenLayoutState, warnings: string[]): void {
  const g = state.globalSettings;
  const cd = kitchenStructuralDepth(g);
  const ch = n(g.height, 0);
  const wheelAvoidances = validWheelAvoidances(state, cd, ch);
  if (!wheelAvoidances.length) return;
  const candidates = boards.filter((item) =>
    (item.type === "drawer_divider" || item.type === "full_depth_shelf" || item.type === "door_shelf") &&
    item.profilePlane === "XY"
  );
  for (const boardItem of candidates) {
    let newY1 = boardItem.y1;
    const applied: string[] = [];
    for (const avoidance of wheelAvoidances) {
      const frontY = cd - avoidance.depth;
      const raisedB4Z0 = avoidance.height;
      const raisedB4Z1 = avoidance.height + 100;
      if (!intersects(boardItem.x0, boardItem.x1, avoidance.x0, avoidance.x1)) continue;
      if (intersects(boardItem.z0, boardItem.z1, 0, avoidance.height)) {
        const clearanceY = Math.max(boardItem.y0, frontY - n(g.materialThickness, 15));
        if (boardItem.y1 > clearanceY + 0.001) {
          newY1 = Math.min(newY1, clearanceY);
          applied.push(`${avoidance.id}:front`);
        }
      }
      if (intersects(boardItem.z0, boardItem.z1, raisedB4Z0, raisedB4Z1)) {
        const clearanceY = Math.max(boardItem.y0, cd - n(g.materialThickness, 15));
        if (boardItem.y1 > clearanceY + 0.001) {
          newY1 = Math.min(newY1, clearanceY);
          applied.push(`${avoidance.id}:raised-B4`);
        }
      }
    }
    if (newY1 < boardItem.y1 - 0.001) {
      boardItem.y1 = Math.max(boardItem.y0, newY1);
      boardItem.notes = [
        ...(boardItem.notes || []),
        `Rear shortened to avoid wheel arch front board (${applied.join(", ")}).`,
      ];
      warnings.push(`${boardItem.id} shortened at rear for wheel avoidance ${applied.join(", ")}.`);
    }
  }
}

function addSideStrengtheningStrips(boards: BoardGeometry[], columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], state: KitchenLayoutState, warnings: string[]): void {
  const g = state.globalSettings;
  const cpt = n(g.materialThickness, 15);
  const bch = n(g.bottomClearanceHeight, 0);
  const ch = n(g.height, 0);
  const refs = sideReferences(state, warnings);
  const addStrip = (side: "left" | "right", columnIndex: number, zone: ComputedKitchenZone): void => {
    const options = side === "left" ? refs.left.options : refs.right.options;
    if (!options.frontVisible || !options.strengtheningStripEnabled) return;
    if (!isDoorZone(zone.zoneType)) {
      return;
    }
    const columnZones = zones.filter((item) => item.columnIndex === columnIndex);
    const belowZone = columnZones.find((candidate) => Math.abs(candidate.z1 - zone.z0) <= 0.001);
    const aboveZone = columnZones.find((candidate) => Math.abs(candidate.z0 - zone.z1) <= 0.001);
    const lowerLimit = Math.max(
      bch + cpt,
      belowZone ? belowZone.z1 + cpt / 2 : -Infinity,
    );
    const upperLimit = Math.min(
      ch - cpt,
      aboveZone ? aboveZone.z0 - cpt / 2 : Infinity,
    );
    const stripZ0 = Math.max(zone.z0, lowerLimit);
    const stripZ1 = Math.min(zone.z1, upperLimit);
    if (stripZ1 <= stripZ0) {
      warnings.push(`${side} side strengthening strip skipped for ${zone.id}: invalid Z range ${stripZ0}-${stripZ1}.`);
      return;
    }
    const x0 = side === "left" ? refs.left.innerX : refs.right.innerX - cpt;
    const x1 = side === "left" ? refs.left.innerX + cpt : refs.right.innerX;
    boards.push(board(
      `${side}-side-strengthening-strip-${zone.id}`,
      `${side === "left" ? "Left" : "Right"} side strengthening strip`,
      "side_strengthening_strip",
      "support_strip",
      cpt,
      "YZ",
      "X",
      { x0, x1, y0: 0, y1: 100, z0: stripZ0, z1: stripZ1 },
      undefined,
      ["Side strengthening strip: no notch, groove, or tongue."],
    ));
  };
  zones.filter((zone) => zone.columnIndex === 0).forEach((zone) => addStrip("left", 0, zone));
  const rightIndex = columns.length - 1;
  zones.filter((zone) => zone.columnIndex === rightIndex).forEach((zone) => addStrip("right", rightIndex, zone));
}

function applySideStrengtheningStripShelfJoinery(boards: BoardGeometry[], cpt: number): void {
  const notchY0 = 0;
  const notchY1 = 85;
  const stripSlotY0 = 80;
  const stripSlotY1 = 100;
  const clearance = 1;
  const halfClearance = clearance / 2;
  for (const strip of boards.filter((item) => item.type === "side_strengthening_strip")) {
    const side = strip.id.startsWith("left-") ? "left" : strip.id.startsWith("right-") ? "right" : null;
    if (!side) continue;
    const zoneId = strip.id.replace(/^left-side-strengthening-strip-/, "").replace(/^right-side-strengthening-strip-/, "");
    const shelf = boards.find((item) => item.id === `${zoneId}-door-shelf`);
    if (!shelf) continue;
    const shelfBodyX0 = shelf.profileXY?.[0]?.[0] ?? shelf.x0;
    const shelfBodyX1 = shelf.profileXY?.[1]?.[0] ?? shelf.x1;
    const notchWidth = cpt + clearance;
    const shelfNotch: BoardNotch = side === "left"
      ? {
          id: `${shelf.id}-${strip.id}-clearance`,
          x0: shelfBodyX0,
          x1: shelfBodyX0 + cpt + clearance,
          y0: notchY0,
          y1: notchY1,
          from: "front",
        }
      : {
          id: `${shelf.id}-${strip.id}-clearance`,
          x0: shelfBodyX1 - cpt - clearance,
          x1: shelfBodyX1,
          y0: notchY0,
          y1: notchY1,
          from: "front",
        };
    shelf.notches = [...(shelf.notches || []), shelfNotch];
    strip.profileXY = trimClosedProfile([
      [strip.y0, strip.z0],
      [strip.y1, strip.z0],
      [strip.y1, shelf.z0 - halfClearance],
      [stripSlotY0, shelf.z0 - halfClearance],
      [stripSlotY0, shelf.z1 + halfClearance],
      [strip.y1, shelf.z1 + halfClearance],
      [strip.y1, strip.z1],
      [strip.y0, strip.z1],
      [strip.y0, strip.z0],
    ]);
  }
}

function slotRequestForBoardEnd(boardItem: BoardGeometry, vPanel: VPanelGeometry, side: "left" | "right", oppositeVisible: boolean, cpt: number, constants: KitchenGeometryConstants): SlotRequest {
  const isDrawer = boardItem.type === "drawer_divider";
  const y0 = isDrawer ? 45 : ((boardItem.y1 - boardItem.y0) - (boardItem.y1 - boardItem.y0) / 3) / 2 - 6;
  const drawerSlotLength = 110;
  const y1 = isDrawer ? y0 + drawerSlotLength : y0 + (boardItem.y1 - boardItem.y0) / 3 + 12;
  const slotY1 = isDrawer ? y1 : Math.min(boardItem.y1, y1);
  const panelThickness = vPanel.materialThickness ?? cpt;
  const hiddenOuterGroove = Boolean(vPanel.sidePanelOptions && vPanel.sidePanelOptions.grooveVisible === false);
  const slotType: SlotType = hiddenOuterGroove ? "half" : oppositeVisible ? "half" : "through";
  const tongueLength = slotType === "through" ? panelThickness : panelThickness / 2;
  return {
    id: `${boardItem.id}-${vPanel.id}-${side}`,
    boardId: boardItem.id,
    vPanelIndex: vPanel.index,
    side,
    slotType,
    tongueLength,
    grooveDepth: slotType === "half" ? panelThickness / 2 : undefined,
    x0: vPanel.x0,
    x1: vPanel.x1,
    y0: Math.max(0, y0),
    y1: slotY1,
    z0: boardItem.z0 - constants.notchAllowanceExtra / 2,
    z1: boardItem.z1 + constants.notchAllowanceExtra / 2,
    visibleOppositeSide: oppositeVisible || hiddenOuterGroove,
  };
}

function generateSlotRequests(boards: BoardGeometry[], columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], vPanels: VPanelGeometry[], state: KitchenLayoutState, constants: KitchenGeometryConstants): SlotRequest[] {
  const cpt = n(state.globalSettings.materialThickness, 15);
  const requests: SlotRequest[] = [];
  for (const boardItem of boards.filter((item) => item.type === "drawer_divider" || item.type === "full_depth_shelf" || item.type === "door_shelf")) {
    const column = columns.find((item) => boardItem.x0 <= item.clearX0 + 0.1 && boardItem.x1 >= item.clearX1 - 0.1);
    if (!column) continue;
    const leftZone = zones.find((zone) => zone.columnIndex === column.index - 1 && zone.z0 < boardItem.z1 && zone.z1 > boardItem.z0);
    const rightZone = zones.find((zone) => zone.columnIndex === column.index + 1 && zone.z0 < boardItem.z1 && zone.z1 > boardItem.z0);
    requests.push(slotRequestForBoardEnd(boardItem, vPanels[column.index], "right", zoneVisible(leftZone?.zoneType), cpt, constants));
    requests.push(slotRequestForBoardEnd(boardItem, vPanels[column.index + 1], "left", zoneVisible(rightZone?.zoneType), cpt, constants));
  }
  return requests;
}

function slotRangesOverlap(a: Pick<SlotRequest, "y0" | "y1" | "z0" | "z1">, b: Pick<SlotRequest, "y0" | "y1" | "z0" | "z1">): boolean {
  return a.y0 < b.y1 - 0.001 && b.y0 < a.y1 - 0.001 && a.z0 < b.z1 - 0.001 && b.z0 < a.z1 - 0.001;
}

function resolveSlots(requests: SlotRequest[], preferences: KitchenLayoutState["vPanelMachiningPreferences"], warnings: string[], _errors: string[]): ResolvedSlot[] {
  const resolved: ResolvedSlot[] = requests.map((request) => ({ ...request, resolvedSlotType: request.slotType }));
  const resolvedTypeForMode = (mode: VPanelMachiningMode, side: SlotSide): SlotType | "none" => {
    if (mode === "left_half_right_none") return side === "left" ? "half" : "none";
    if (mode === "right_half_left_none") return side === "right" ? "half" : "none";
    if (mode === "right_half_left_through" || mode === "right_half" || mode === "left_through" || mode === "right_face_half_allowed") return side === "right" ? "half" : "through";
    if (mode === "left_half_right_through" || mode === "left_half" || mode === "right_through" || mode === "left_face_half_allowed") return side === "left" ? "half" : "through";
    if (mode === "through_only") return "through";
    return "half";
  };
  const panelIndexes = [...new Set(requests.map((request) => request.vPanelIndex))];
  for (const panelIndex of panelIndexes) {
    const panelRequests = resolved.filter((request) =>
      request.vPanelIndex === panelIndex &&
      request.slotType === "half"
    );
    if (!panelRequests.length) continue;
    const preference = preferences?.find((pref) => pref.vPanelIndex === panelIndex)?.mode;

    // Default: opposing same-height half requests share one through groove; both tongues stay half.
    // Explicit V machining preference still wins and can force through/none arbitration.
    if (!preference) {
      const leftHalves = panelRequests.filter((request) => request.side === "left");
      const rightHalves = panelRequests.filter((request) => request.side === "right");
      const sharedIds = new Set<string>();
      for (const left of leftHalves) {
        for (const right of rightHalves) {
          if (!slotRangesOverlap(left, right)) continue;
          sharedIds.add(left.id);
          sharedIds.add(right.id);
        }
      }
      for (const request of panelRequests) {
        if (sharedIds.has(request.id)) {
          request.resolvedSlotType = "half";
          request.sharedOpposingGroove = true;
          request.tongueLength = request.tongueLength ?? Math.max(0, (request.x1 - request.x0) / 2);
          continue;
        }
        request.machiningMode = request.side === "left" ? "left_face_half_allowed" : "right_face_half_allowed";
        request.resolvedSlotType = "half";
      }
      continue;
    }

    const mode = preference;
    for (const request of panelRequests) {
      request.machiningMode = mode;
      request.resolvedSlotType = resolvedTypeForMode(mode, request.side);
      if (request.resolvedSlotType === "through" && request.visibleOppositeSide) {
        warnings.push(`Through slot may appear on visible side: ${request.id}.`);
      }
    }
  }
  return resolved;
}

function updateFunctionalBoardProfilesFromSlots(boards: BoardGeometry[], resolvedSlots: ResolvedSlot[], cpt: number, cd: number, constants: KitchenGeometryConstants): void {
  const tongueForSlot = (slot: ResolvedSlot | undefined): number => {
    if (!slot) return 0;
    if (slot.resolvedSlotType === "none") return 0;
    if (slot.resolvedSlotType === "through") return cpt;
    if (typeof slot.tongueLength === "number" && Number.isFinite(slot.tongueLength)) return Math.max(0, slot.tongueLength);
    return Math.max(0, cpt / 2 - 0.5);
  };
  for (const boardItem of boards.filter((item) => item.type === "drawer_divider" || item.type === "full_depth_shelf" || item.type === "door_shelf")) {
    const boardSlots = resolvedSlots.filter((slot) => slot.boardId === boardItem.id);
    const leftSlot = boardSlots.find((slot) => slot.side === "right");
    const rightSlot = boardSlots.find((slot) => slot.side === "left");
    const leftTongueLength = tongueForSlot(leftSlot);
    const rightTongueLength = tongueForSlot(rightSlot);
    const isDrawer = boardItem.type === "drawer_divider";
    const bodyX0 = boardItem.profileXY?.[0]?.[0] ?? boardItem.x0 + cpt / 2;
    const bodyX1 = boardItem.profileXY?.[1]?.[0] ?? boardItem.x1 - cpt / 2;
    const tongueY0 = isDrawer ? 50 : (cd - cd / 3) / 2;
    const tongueY1 = isDrawer ? constants.b3Depth : tongueY0 + cd / 3;
    boardItem.x0 = bodyX0 - leftTongueLength;
    boardItem.x1 = bodyX1 + rightTongueLength;
    boardItem.profileXY = functionalProfileXY(
      bodyX0,
      bodyX1,
      boardItem.y0,
      boardItem.y1,
      leftTongueLength,
      rightTongueLength,
      tongueY0,
      tongueY1,
    );
  }
}

function rectangleOuter(x0: number, x1: number, y0: number, y1: number): Array<[number, number]> {
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
}

function boardPlaneAxes(plane: PanelBodyPlane): { hKey: "x" | "y"; vKey: "y" | "z" } {
  return plane === "YZ" ? { hKey: "y", vKey: "z" } : plane === "XZ" ? { hKey: "x", vKey: "z" } : { hKey: "x", vKey: "y" };
}

function notchCutoutForBoard(boardItem: BoardGeometry, notch: BoardNotch): PanelBodyCutout | null {
  const { hKey, vKey } = boardPlaneAxes(boardItem.profilePlane);
  const h0 = notch[`${hKey}0`] == null ? boardItem[`${hKey}0`] : Number(notch[`${hKey}0`]);
  const h1 = notch[`${hKey}1`] == null ? h0 : Number(notch[`${hKey}1`]);
  const v0 = notch[`${vKey}0`] == null ? boardItem[`${vKey}0`] : Number(notch[`${vKey}0`]);
  const v1 = notch[`${vKey}1`] == null ? v0 : Number(notch[`${vKey}1`]);
  if (![h0, h1, v0, v1].every(Number.isFinite) || h1 <= h0 || v1 <= v0) return null;
  return { id: notch.id, kind: "notch", sourceId: notch.id, x0: h0, x1: h1, y0: v0, y1: v1 };
}

function edgeForCutout(cutout: PanelBodyCutout, v0: number, v1: number): "min" | "max" | null {
  if (Math.abs(cutout.y0 - v0) <= 0.001 && cutout.y1 > v0) return "min";
  if (Math.abs(cutout.y1 - v1) <= 0.001 && cutout.y0 < v1) return "max";
  return null;
}

function outerWithEdgeNotches(h0: number, h1: number, v0: number, v1: number, cutouts: PanelBodyCutout[]): { outer: Array<[number, number]>; remainingCutouts: PanelBodyCutout[] } {
  const edgeNotches = cutouts
    .map((cutout) => ({ cutout, edge: edgeForCutout(cutout, v0, v1) }))
    .filter((item): item is { cutout: PanelBodyCutout; edge: "min" | "max" } => Boolean(item.edge));
  if (!edgeNotches.length) return { outer: rectangleOuter(h0, h1, v0, v1), remainingCutouts: cutouts };
  const edges = [...new Set(edgeNotches.map((item) => item.edge))];
  if (edges.length !== 1) return { outer: rectangleOuter(h0, h1, v0, v1), remainingCutouts: cutouts };

  const edge = edges[0];
  const notches = edgeNotches
    .map(({ cutout }) => ({
      x0: Math.max(h0, cutout.x0),
      x1: Math.min(h1, cutout.x1),
      y0: Math.max(v0, cutout.y0),
      y1: Math.min(v1, cutout.y1),
      id: cutout.id,
    }))
    .filter((notch) => notch.x1 > notch.x0 && notch.y1 > notch.y0)
    .sort((a, b) => a.x0 - b.x0);
  if (!notches.length) return { outer: rectangleOuter(h0, h1, v0, v1), remainingCutouts: cutouts };

  const outer: Array<[number, number]> = [];
  if (edge === "min") {
    outer.push([h0, v0]);
    for (const notch of notches) {
      outer.push([notch.x0, v0], [notch.x0, notch.y1], [notch.x1, notch.y1], [notch.x1, v0]);
    }
    outer.push([h1, v0], [h1, v1], [h0, v1], [h0, v0]);
  } else {
    outer.push([h0, v0], [h1, v0], [h1, v1]);
    for (const notch of [...notches].reverse()) {
      outer.push([notch.x1, v1], [notch.x1, notch.y0], [notch.x0, notch.y0], [notch.x0, v1]);
    }
    outer.push([h0, v1], [h0, v0]);
  }
  const foldedIds = new Set(notches.map((notch) => notch.id));
  return {
    outer: trimClosedProfile(outer),
    remainingCutouts: cutouts.filter((cutout) => !foldedIds.has(cutout.id)),
  };
}

function slotCutoutForBoard(boardItem: BoardGeometry, slot: ResolvedSlot): PanelBodyCutout | null {
  // Functional boards form tongues through their outer profile. The matching machining
  // happens on V panels, so cutting the same slot on the board removes the tongue.
  if (boardItem.type === "drawer_divider" || boardItem.type === "full_depth_shelf" || boardItem.type === "door_shelf") return null;
  if (slot.resolvedSlotType === "none") return null;
  if (boardItem.profilePlane !== "XY") return null;
  const isBoardLeftEnd = slot.side === "right";
  const x0 = isBoardLeftEnd ? boardItem.x0 : boardItem.x1 - boardItem.materialThickness;
  const x1 = isBoardLeftEnd ? boardItem.x0 + boardItem.materialThickness : boardItem.x1;
  const y0 = Math.max(boardItem.y0, slot.y0);
  const y1 = Math.min(boardItem.y1, slot.y1);
  if (x1 <= x0 || y1 <= y0) return null;
  return { id: `${slot.id}-body-cutout`, kind: "slot", sourceId: slot.id, x0, x1, y0, y1, slotType: slot.resolvedSlotType, side: slot.side };
}

function buildBoardBodies(boards: BoardGeometry[], resolvedSlots: ResolvedSlot[]): void {
  for (const boardItem of boards) {
    const { hKey, vKey } = boardPlaneAxes(boardItem.profilePlane);
    const h0 = Number(boardItem[`${hKey}0`]);
    const h1 = Number(boardItem[`${hKey}1`]);
    const v0 = Number(boardItem[`${vKey}0`]);
    const v1 = Number(boardItem[`${vKey}1`]);
    const notchCutouts = (boardItem.notches || [])
      .map((notch) => notchCutoutForBoard(boardItem, notch))
      .filter((cutout): cutout is PanelBodyCutout => Boolean(cutout));
    const usesCustomOuter = Array.isArray(boardItem.profileXY) && boardItem.profileXY.length > 0;
    const edgeProfile = outerWithEdgeNotches(h0, h1, v0, v1, notchCutouts);
    const outer = usesCustomOuter
      ? boardItem.profileXY
      : edgeProfile.outer;
    const slotCutouts = resolvedSlots
      .filter((slot) => slot.boardId === boardItem.id)
      .map((slot) => slotCutoutForBoard(boardItem, slot))
      .filter((cutout): cutout is PanelBodyCutout => Boolean(cutout));
    boardItem.body = {
      plane: boardItem.profilePlane,
      outer,
      cutouts: [...(usesCustomOuter ? notchCutouts : edgeProfile.remainingCutouts), ...slotCutouts],
    };
  }
}

function buildVPanelBodies(vPanels: VPanelGeometry[], resolvedSlots: ResolvedSlot[]): void {
  for (const panel of vPanels) {
    const panelSlots = resolvedSlots.filter((slot) => slot.vPanelIndex === panel.index && slot.resolvedSlotType !== "none");
    const cutouts: PanelBodyCutout[] = [];
    const consumedShared = new Set<string>();
    for (const slot of panelSlots) {
      if (!slot.sharedOpposingGroove) continue;
      if (consumedShared.has(slot.id)) continue;
      const group = panelSlots.filter((other) =>
        other.sharedOpposingGroove &&
        !consumedShared.has(other.id) &&
        slotRangesOverlap(slot, other),
      );
      for (const member of group) consumedShared.add(member.id);
      cutouts.push({
        id: `V${panel.index}-shared-${cutouts.length}-body-cutout`,
        kind: "slot",
        sourceId: group.map((member) => member.id).join("+"),
        x0: Math.min(...group.map((member) => member.y0)),
        x1: Math.max(...group.map((member) => member.y1)),
        y0: Math.min(...group.map((member) => member.z0)),
        y1: Math.max(...group.map((member) => member.z1)),
        slotType: "through",
        side: "left",
      });
    }
    for (const slot of panelSlots) {
      if (slot.sharedOpposingGroove) continue;
      cutouts.push({
        id: `${slot.id}-body-cutout`,
        kind: "slot",
        sourceId: slot.id,
        x0: slot.y0,
        x1: slot.y1,
        y0: slot.z0,
        y1: slot.z1,
        slotType: slot.resolvedSlotType === "half" ? "half" : "through",
        side: slot.side,
      });
    }
    panel.body = {
      plane: "YZ",
      outer: panel.yzProfile,
      cutouts,
    };
  }
}

function buildPanelBodies(boards: BoardGeometry[], vPanels: VPanelGeometry[], resolvedSlots: ResolvedSlot[]): void {
  buildBoardBodies(boards, resolvedSlots);
  buildVPanelBodies(vPanels, resolvedSlots);
}

/**
 * Style 1 B3 LED T-groove on the bottom face (opens downward / −Z).
 * Emitted as half-groove rectangles so the kitchen Fusion flat cutter can cut
 * them with participantBodies isolation (same path as other half grooves).
 */
function applyB3LedGrooveCutouts(
  boards: BoardGeometry[],
  state: KitchenLayoutState,
  warnings: string[],
): void {
  const g = state.globalSettings || ({} as KitchenLayoutState["globalSettings"]);
  if (String(g.bottomClearanceStyle || "style_1") === "style_2") return;
  if (g.ledGroove === false) return;

  const b3 = boards.find((item) => item.id === "B3" && item.type === "B3");
  if (!b3?.body) return;

  const boardWidth = b3.x1 - b3.x0;
  const boardDepth = b3.y1 - b3.y0;
  const halfWidth = LED_GROOVE_WIDTH / 2;
  if (boardWidth <= LED_GROOVE_BRANCH_END_INSET * 2 + LED_GROOVE_WIDTH) {
    warnings.push(
      `B3 LED groove skipped: board width ${boardWidth.toFixed(1)} too narrow for 80 mm end insets.`,
    );
    return;
  }

  const mainYCenter = b3.y0 + LED_GROOVE_FRONT_OFFSET;
  const main = {
    x0: b3.x0,
    x1: b3.x1,
    y0: mainYCenter - halfWidth,
    y1: mainYCenter + halfWidth,
  };
  if (main.y0 < b3.y0 - 1e-6 || main.y1 > b3.y1 + 1e-6) {
    warnings.push(
      `B3 LED groove main channel y=${main.y0.toFixed(2)}..${main.y1.toFixed(2)} leaves board depth ${boardDepth.toFixed(1)}.`,
    );
  }

  const branchY0 = main.y1;
  const branchY1 = b3.y1;
  const branchLength = branchY1 - branchY0;
  if (branchLength <= 1e-6) {
    warnings.push(
      `B3 LED groove T-branches skipped: no remaining depth behind main channel (y=${branchY0.toFixed(2)}).`,
    );
    return;
  }

  const branchCenters = [
    b3.x0 + LED_GROOVE_BRANCH_END_INSET,
    b3.x1 - LED_GROOVE_BRANCH_END_INSET,
  ];
  const ledCutouts: PanelBodyCutout[] = [
    {
      id: "B3-led-main",
      kind: "slot",
      sourceId: "B3_led_groove",
      x0: main.x0,
      x1: main.x1,
      y0: main.y0,
      y1: main.y1,
      slotType: "half",
      side: "left",
      grooveDepth: LED_GROOVE_DEPTH,
    },
    ...branchCenters.map((centerX, index) => ({
      id: `B3-led-branch-${index + 1}`,
      kind: "slot" as const,
      sourceId: "B3_led_groove",
      x0: centerX - halfWidth,
      x1: centerX + halfWidth,
      y0: branchY0,
      y1: branchY1,
      slotType: "half" as const,
      side: "left" as const,
      grooveDepth: LED_GROOVE_DEPTH,
    })),
  ];

  b3.body.cutouts = [...(b3.body.cutouts || []), ...ledCutouts];
  b3.notes = [
    ...(b3.notes || []).filter((note) => !note.toLowerCase().includes("led groove")),
    "B3 LED groove path implemented on bottom face",
  ];
}

function boardDxfEntry(boardItem: BoardGeometry): PanelDxfGeometry {
  const rawOuter = boardItem.body?.outer || [];
  const outer = trimClosedProfile(rawOuter);
  const cutouts = boardItem.body?.cutouts || [];
  return {
    panelId: boardItem.id,
    panelKind: "board",
    panelType: boardItem.type,
    plane: boardItem.profilePlane,
    thicknessAxis: boardItem.thicknessAxis,
    materialThickness: boardItem.materialThickness,
    bbox: {
      x0: boardItem.x0,
      x1: boardItem.x1,
      y0: boardItem.y0,
      y1: boardItem.y1,
      z0: boardItem.z0,
      z1: boardItem.z1,
    },
    outer,
    notchVectors: cutouts.filter((cutout) => cutout.kind === "notch"),
    throughVectors: cutouts.filter((cutout) => cutout.kind === "slot" && cutout.slotType === "through"),
    halfGrooveVectors: cutouts.filter((cutout) => cutout.kind === "slot" && cutout.slotType === "half"),
    audit: auditClosedProfile(rawOuter, outer),
  };
}

function vPanelDxfEntry(panel: VPanelGeometry, cpt: number): PanelDxfGeometry {
  const rawOuter = panel.body?.outer || panel.yzProfile || [];
  const outer = trimClosedProfile(rawOuter);
  const cutouts = panel.body?.cutouts || [];
  return {
    panelId: panel.id,
    panelKind: "vPanel",
    panelType: "VPanel",
    plane: "YZ",
    thicknessAxis: "X",
    materialThickness: panel.materialThickness ?? cpt,
    bbox: {
      x0: panel.x0,
      x1: panel.x1,
      y0: Math.min(...outer.map((point) => point[0])),
      y1: Math.max(...outer.map((point) => point[0])),
      z0: Math.min(...outer.map((point) => point[1])),
      z1: Math.max(...outer.map((point) => point[1])),
    },
    outer,
    notchVectors: cutouts.filter((cutout) => cutout.kind === "notch"),
    throughVectors: cutouts.filter((cutout) => cutout.kind === "slot" && cutout.slotType === "through"),
    halfGrooveVectors: cutouts.filter((cutout) => cutout.kind === "slot" && cutout.slotType === "half"),
    audit: auditClosedProfile(rawOuter, outer),
  };
}

function buildPanelDxf(boards: BoardGeometry[], vPanels: VPanelGeometry[], cpt: number): PanelDxfGeometry[] {
  return [
    ...boards.map((boardItem) => boardDxfEntry(boardItem)),
    ...vPanels.map((panel) => vPanelDxfEntry(panel, cpt)),
  ];
}

const FRONT_PANEL_ZONE_TYPES = new Set(["left_door", "right_door", "double_door", "drawer", "down_flap"]);

function isFrontPanelZone(type: string | undefined): boolean {
  return FRONT_PANEL_ZONE_TYPES.has(String(type));
}

function getDefaultHingeSideDistance(longSide: number): number {
  return Math.max(75, Math.min(100, 75 + (longSide - 300) * (25 / 300)));
}

function columnHasAnyFrontPanel(column: ComputedKitchenColumn | undefined): boolean {
  return Boolean(column?.zones?.some((zone) => isFrontPanelZone(zone.zoneType)));
}

function upperDividerCenterZ(zone: ComputedKitchenZone, state: KitchenLayoutState): number {
  const ch = n(state.globalSettings.height, 0);
  return Math.abs(zone.z1 - ch) <= 0.001 ? ch - n(state.globalSettings.materialThickness, 15) / 2 : zone.z1;
}

function buildFrontPanels(columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], state: KitchenLayoutState, warnings: string[]): FrontPanelGeometry[] {
  const g = state.globalSettings;
  const cw = n(g.length, 0);
  const ch = n(g.height, 0);
  const cpt = n(g.materialThickness, 15);
  const fpt = n(g.frontThickness, 16);
  const fc = n((g as { frontClearance?: number }).frontClearance, 2.5);
  const lockGlobalEnabled = (g as { lockEnabled?: boolean }).lockEnabled !== false;
  const bottomZ = g.bottomClearanceStyle === "style_2" ? n(g.bottomClearanceHeight, 0) + fc : n(g.bottomClearanceHeight, 0);
  const refs = sideReferences(state);
  const byColumn = new Map<number, ComputedKitchenZone[]>();
  for (const zone of zones) byColumn.set(zone.columnIndex, [...(byColumn.get(zone.columnIndex) || []), zone]);
  const panels: FrontPanelGeometry[] = [];

  for (const column of columns) {
    const columnZones = byColumn.get(column.index) || [];
    const leftColumn = columns[column.index - 1];
    const rightColumn = columns[column.index + 1];
    const baseX0 = column.index === 0
      ? fc
      : columnHasAnyFrontPanel(leftColumn) ? column.logicalX0 + fc / 2 : column.logicalX0 - cpt / 2;
    const baseX1 = column.index === columns.length - 1
      ? cw - fc
      : columnHasAnyFrontPanel(rightColumn) ? column.logicalX1 - fc / 2 : column.logicalX1 + cpt / 2;
    const x0 = column.index === 0 && refs.left.options.frontVisible ? refs.left.innerX + fc : baseX0;
    const x1 = column.index === columns.length - 1 && refs.right.options.frontVisible ? refs.right.innerX - fc : baseX1;

    for (const zone of columnZones) {
      if (!isFrontPanelZone(zone.zoneType)) continue;
      const aboveZone = columnZones.find((candidate) => Math.abs(candidate.z0 - zone.z1) <= 0.001);
      const belowZone = columnZones.find((candidate) => Math.abs(candidate.z1 - zone.z0) <= 0.001);
      const z1 = Math.abs(zone.z1 - ch) <= 0.001
        ? ch - fc
        : isFrontPanelZone(aboveZone?.zoneType) ? zone.z1 - fc / 2 : zone.z1 + cpt / 2;
      const z0 = Math.abs(zone.z0 - n(g.bottomClearanceHeight, 0)) <= 0.001
        ? bottomZ
        : isFrontPanelZone(belowZone?.zoneType) ? zone.z0 + fc / 2 : zone.z0 - cpt / 2;
      const width = x1 - x0;
      const height = z1 - z0;
      const seamX = (x0 + x1) / 2;
      const leaves: Array<{ idSuffix: string; type: FrontPanelGeometry["type"]; x0: number; x1: number }> = zone.zoneType === "double_door"
        ? [
            { idSuffix: "-left", type: "left_door", x0, x1: seamX - fc / 2 },
            { idSuffix: "-right", type: "right_door", x0: seamX + fc / 2, x1 },
          ]
        : [{ idSuffix: "", type: zone.zoneType as FrontPanelGeometry["type"], x0, x1 }];
      const hingeSettings = (zone as unknown as { hingeSettings?: { sideDistance?: number; cupDiameter?: number; cupDepth?: number; cupCenterFromEdge?: number; useThreeHinges?: boolean } }).hingeSettings || {};
      const sideDistance = n(hingeSettings.sideDistance, getDefaultHingeSideDistance(zone.zoneType === "down_flap" ? width : height));
      const cupDiameter = n(hingeSettings.cupDiameter, 35);
      const cupDepth = n(hingeSettings.cupDepth, 12.5);
      const cupCenterFromEdge = n(hingeSettings.cupCenterFromEdge, 22.5);
      const useThreeHinges = Boolean(hingeSettings.useThreeHinges);
      for (const leaf of leaves) {
        const leafWidth = leaf.x1 - leaf.x0;
        if (leafWidth <= 0 || height <= 0) {
          warnings.push(`Front panel skipped in ${zone.id}: invalid leaf ${leaf.x0}-${leaf.x1}.`);
          continue;
        }
        const panel: FrontPanelGeometry = {
          id: `${zone.id}-front-panel${leaf.idSuffix}`,
          columnId: zone.columnId,
          zoneId: zone.id,
          type: leaf.type,
          x0: leaf.x0,
          x1: leaf.x1,
          y0: -fpt,
          y1: 0,
          z0,
          z1,
          width: leafWidth,
          height,
          thickness: fpt,
        };
        if (leaf.type === "left_door" || leaf.type === "right_door") {
          const centerX = leaf.type === "left_door" ? leaf.x0 + cupCenterFromEdge : leaf.x1 - cupCenterFromEdge;
          const centers = [z1 - sideDistance, z0 + sideDistance, ...(useThreeHinges ? [(z0 + z1) / 2] : [])];
          panel.hingeHoles = centers.map((centerZ, index) => ({ id: `${panel.id}-hinge-${index + 1}`, centerX, centerZ, diameter: cupDiameter, depth: cupDepth }));
        } else if (leaf.type === "down_flap") {
          const centerZ = z0 + cupCenterFromEdge;
          const centers = [leaf.x0 + sideDistance, leaf.x1 - sideDistance, ...(useThreeHinges ? [(leaf.x0 + leaf.x1) / 2] : [])];
          panel.hingeHoles = centers.map((centerX, index) => ({ id: `${panel.id}-hinge-${index + 1}`, centerX, centerZ, diameter: cupDiameter, depth: cupDepth }));
        }
        const zoneLockEnabled = (zone as unknown as { lockEnabled?: boolean }).lockEnabled !== false;
        if (lockGlobalEnabled && zoneLockEnabled) {
          const lockSideCenterOffset = n((zone as unknown as { lockSideCenterOffset?: number }).lockSideCenterOffset, 80);
          const lockCenterX = leaf.type === "left_door"
            ? leaf.x1 - lockSideCenterOffset
            : leaf.type === "right_door"
              ? leaf.x0 + lockSideCenterOffset
              : (leaf.x0 + leaf.x1) / 2;
          const lockCenterZ = upperDividerCenterZ(zone, state) - cpt / 2 - 30.5;
          const lockWidth = 55;
          const lockHeight = 15.5;
          panel.lockCutout = {
            id: `${panel.id}-lock`,
            presetId: "razor_long_rounded_1",
            shape: "rounded_slot",
            centerX: lockCenterX,
            centerZ: lockCenterZ,
            x0: lockCenterX - lockWidth / 2,
            x1: lockCenterX + lockWidth / 2,
            z0: lockCenterZ - lockHeight / 2,
            z1: lockCenterZ + lockHeight / 2,
            width: lockWidth,
            height: lockHeight,
            radius: lockHeight / 2,
          };
        }
        panels.push(panel);
      }
    }
  }
  return panels;
}

function svgFront(columns: ComputedKitchenColumn[], zones: ComputedKitchenZone[], state: KitchenLayoutState, boards: BoardGeometry[], frontPanels: FrontPanelGeometry[]): string {
  const cw = n(state.globalSettings.length, 1);
  const ch = n(state.globalSettings.height, 1);
  const bch = n(state.globalSettings.bottomClearanceHeight, 0);
  const width = 900;
  const height = 360;
  const sx = width / cw;
  const sz = height / ch;
  const yForZ = (z: number) => height - z * sz;
  const zoneRects = zones.map((zone) => `<rect x="${zone.x0 * sx}" y="${yForZ(zone.z1)}" width="${(zone.x1 - zone.x0) * sx}" height="${(zone.z1 - zone.z0) * sz}" fill="#eef6ff" stroke="#344b6a"/><text x="${(zone.x0 + zone.x1) * sx / 2}" y="${yForZ((zone.z0 + zone.z1) / 2)}" font-size="10" text-anchor="middle">${zone.zoneType}</text>`).join("");
  const boardLines = boards.filter((item) => item.category === "functional").map((item) => `<rect x="${item.x0 * sx}" y="${yForZ(item.z1)}" width="${(item.x1 - item.x0) * sx}" height="${Math.max(2, (item.z1 - item.z0) * sz)}" fill="#0f6bff" opacity="0.45"/>`).join("");
  const columnLines = columns.map((column) => `<line x1="${column.logicalX0 * sx}" y1="0" x2="${column.logicalX0 * sx}" y2="${height}" stroke="#111827" stroke-width="1"/>`).join("");
  const panelRects = frontPanels.map((panel) => {
    const panelRect = `<rect x="${panel.x0 * sx}" y="${yForZ(panel.z1)}" width="${panel.width * sx}" height="${panel.height * sz}" fill="#fff4db" stroke="#c87800" stroke-width="2" opacity="0.88"/><text x="${(panel.x0 + panel.x1) * sx / 2}" y="${yForZ((panel.z0 + panel.z1) / 2)}" font-size="9" text-anchor="middle">${panel.type}</text>`;
    const hinges = (panel.hingeHoles || []).map((hole) => `<circle cx="${hole.centerX * sx}" cy="${yForZ(hole.centerZ)}" r="${Math.max(3, hole.diameter * sx / 2)}" fill="none" stroke="#1d4ed8" stroke-width="1.5"/>`).join("");
    const lock = panel.lockCutout ? `<rect x="${panel.lockCutout.x0 * sx}" y="${yForZ(panel.lockCutout.z1)}" width="${panel.lockCutout.width * sx}" height="${panel.lockCutout.height * sz}" rx="${Math.max(2, panel.lockCutout.radius * sx)}" ry="${Math.max(2, panel.lockCutout.radius * sz)}" fill="#111827" opacity="0.8"/>` : "";
    return `${panelRect}${hinges}${lock}`;
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg"><rect width="${width}" height="${height}" fill="#fff"/><rect x="0" y="${yForZ(bch)}" width="${width}" height="${bch * sz}" fill="#c9ced8"/>${zoneRects}${boardLines}${panelRects}${columnLines}<line x1="${width}" y1="0" x2="${width}" y2="${height}" stroke="#111827"/></svg>`;
}

function svgVPanel(panel: VPanelGeometry | undefined): string {
  if (!panel) return "";
  const points = panel.yzProfile.map(([y, z]) => `${y},${900 - z}`).join(" ");
  return `<svg viewBox="-20 0 700 920" xmlns="http://www.w3.org/2000/svg"><polyline points="${points}" fill="#eef6ff" stroke="#344b6a" stroke-width="2"/><text x="0" y="20" font-size="14">${panel.id} YZ profile</text></svg>`;
}

function svgBoardTop(boardItem: BoardGeometry | undefined): string {
  if (!boardItem) return "";
  const width = Math.max(1, boardItem.x1 - boardItem.x0);
  const depth = Math.max(1, boardItem.y1 - boardItem.y0);
  return `<svg viewBox="0 0 ${width} ${depth}" xmlns="http://www.w3.org/2000/svg"><rect x="0" y="0" width="${width}" height="${depth}" fill="#fff7dc" stroke="#344b6a"/><text x="8" y="18" font-size="12">${boardItem.id} ${boardItem.type}</text>${(boardItem.notches || []).map((notch) => `<rect x="${(notch.x0 ?? boardItem.x0) - boardItem.x0}" y="${(notch.y0 ?? boardItem.y0) - boardItem.y0}" width="${(notch.x1 ?? notch.x0 ?? 0) - (notch.x0 ?? 0)}" height="${(notch.y1 ?? notch.y0 ?? 0) - (notch.y0 ?? 0)}" fill="#e5484d" opacity="0.35"/>`).join("")}</svg>`;
}

export function generateKitchenCabinetGeometry(rawState: KitchenLayoutState): KitchenGeometryResult {
  const state = rawState;
  const constants = DEFAULT_CONSTANTS;
  const warnings: string[] = [];
  const errors: string[] = [];
  const g = state.globalSettings || {};
  const cw = n(g.length, 0);
  const cd = kitchenStructuralDepth(g);
  const ch = n(g.height, 0);
  const cpt = n(g.materialThickness, 15);
  const bch = n(g.bottomClearanceHeight, 70);

  if (cw <= 0) errors.push("Kitchen length must be > 0.");
  if (cd <= 0) errors.push("Kitchen depth must be > 0.");
  if (ch <= 0) errors.push("Kitchen height must be > 0.");
  if (cpt <= 0) errors.push("Material thickness must be > 0.");
  if (bch < 0 || bch >= ch) errors.push("Bottom clearance height must be >= 0 and less than kitchen height.");
  if (!Array.isArray(state.columns) || state.columns.length === 0) errors.push("At least one kitchen column is required.");
  state.columns?.forEach((column, columnIndex) => {
    const zoneTotal = (column.zones || []).reduce((sum, zone) => sum + n(zone.height, 0), 0);
    const editable = ch - bch;
    if (Math.abs(zoneTotal - editable) > 0.01) warnings.push(`Column ${columnIndex + 1} zone total ${zoneTotal} != editable height ${editable}.`);
    if ((column.zones || []).some((zone) => zone.zoneType === "unassigned")) errors.push(`Column ${columnIndex + 1} contains unassigned zone.`);
  });

  const vPanels = computeVPanels(state, constants, warnings);
  const columns = computeColumns(state, vPanels);
  columns.forEach((column) => {
    if (column.clearX1 <= column.clearX0) errors.push(`Column ${column.index + 1} has negative or zero clear opening width.`);
  });
  const zones = computeZones(state, columns);
  removeUnsupportedEdgeStoveVPanelNotches(vPanels, zones, state, constants);
  const boards = [
    ...generateBaseBoards(state, vPanels, columns, zones, constants, warnings),
    ...generateFunctionalBoards(columns, zones, state, constants, warnings),
  ];
  shortenHorizontalBoardsForWheelAvoidance(boards, state, warnings);
  addSideStrengtheningStrips(boards, columns, zones, state, warnings);
  const slotRequests = generateSlotRequests(boards, columns, zones, vPanels, state, constants);
  const resolvedSlots = resolveSlots(slotRequests, state.vPanelMachiningPreferences, warnings, errors);
  updateFunctionalBoardProfilesFromSlots(boards, resolvedSlots, cpt, cd, constants);
  applySideStrengtheningStripShelfJoinery(boards, cpt);
  buildPanelBodies(boards, vPanels, resolvedSlots);
  applyB3LedGrooveCutouts(boards, state, warnings);
  const frontPanels = buildFrontPanels(columns, zones, state, warnings);
  const panelDxf = buildPanelDxf(boards, vPanels, cpt);
  const relationshipDeclarations = relationshipDeclarationsForBoards(boards);

  return {
    params: state,
    constants,
    computedColumns: columns,
    computedZones: zones,
    vPanels,
    boards,
    frontPanels,
    panelDxf,
    slotRequests,
    resolvedSlots,
    relationshipDeclarations,
    warnings,
    errors,
    debug: {
      phase: "kitchen_geometry_v0",
      xBoundaries: computeXBoundaries(state.columns),
      svgFrontElevation: svgFront(columns, zones, state, boards, frontPanels),
      svgVPanelProfile: svgVPanel(vPanels[0]),
      svgBoardTopView: svgBoardTop(boards[0]),
    },
  };
}
