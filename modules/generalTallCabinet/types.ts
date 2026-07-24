export type BoundaryType = "none" | "full_zi" | "half_zi";

export type ZoneType =
  | "side_door"
  | "left_side_door"
  | "right_side_door"
  | "double_door"
  | "drawer"
  | "open_space"
  | "open_appliance"
  | "fridge"
  | "top_flap"
  | "bottom_flap"
  | "blank_panel";

export type SystemZoneType = "top_system" | "bottom_system";

export interface GtHingeSettings {
  sideDistance: number | "auto";
  cupDiameter: number;
  cupDepth: number;
  cupCenterFromEdge: number;
  useThreeHinges: boolean;
}

export type GtLockPosition = "top" | "bottom" | "side" | "shelf_top" | "shelf_bottom";

export interface FunctionalZone {
  id: string;
  type: ZoneType;
  height: number;
  verticalDivider?: boolean;
  dividerCenterX?: number;
  /** Door zones only: opt-in horizontal shelf inside the zone (kitchen-style). */
  shelfEnabled?: boolean;
  /** Shelf TOP height measured from the zone bottom (mm). Default: zone height / 2. */
  shelfHeight?: number;
  frontPanelEnabled?: boolean;
  lockEnabled?: boolean;
  lockPosition?: GtLockPosition;
  lockSideDistance?: number;
  /** Side locks only: lock slot center Z measured from the zone bottom (mm). Default: panel top - lockSideDistance. */
  lockHeight?: number;
  hingeEnabled?: boolean;
  hingeSettings?: Partial<GtHingeSettings>;
  /** Fridge cavity: appliance envelope (mm). Height overrides zone.height when set. */
  applianceWidthMm?: number;
  applianceDepthMm?: number;
  applianceHeightMm?: number;
}

export interface SystemZone {
  id: SystemZoneType;
  type: SystemZoneType;
}

export type ZoneLike = FunctionalZone | SystemZone;

export interface BoundaryResult {
  index: number;
  aboveZoneId: string;
  belowZoneId: string;
  boundaryType: BoundaryType;
  reason: string;
  upgradedByDoubleDoorDivider?: boolean;
}

export interface BoundaryValidation {
  errors: string[];
  warnings: string[];
}

export interface ZoneBoundaryResolution extends BoundaryValidation {
  boundaries: BoundaryResult[];
  debugBoundaries: BoundaryResult[];
}

export type TopBottomStyle = "style_1" | "style_2";

export interface Style1SystemConfig {
  style: "style_1";
  frontRailHeight?: number;
  insertSlotThickness?: number;
  /** When true, cut LED T-slot on the Style 1 insert board (T3 top / B3 bottom). */
  ledGroove?: boolean;
}

export interface Style2SystemConfig {
  style: "style_2";
  height: number;
}

export type TopBottomSystemConfig = Style1SystemConfig | Style2SystemConfig;

export interface StackingCalculatorInput {
  cabinetHeight: number;
  topSystem: TopBottomSystemConfig;
  bottomSystem: TopBottomSystemConfig;
  zones: FunctionalZone[];
  ziThickness?: number;
}

export type StackingItemType = "bottom_system" | "functional_zone" | "boundary_panel" | "top_system";

export interface StackingItem {
  id: string;
  type: StackingItemType;
  z0: number;
  z1: number;
  height: number;
  zoneId?: string;
  boundaryType?: BoundaryType;
  centerZ?: number;
  notes?: string;
}

export interface SystemHeights {
  topSystemHeight: number;
  bottomSystemHeight: number;
}

export interface StackingCalculationResult {
  items: StackingItem[];
  boundaryResolution: ZoneBoundaryResolution;
  validation: BoundaryValidation;
  topSystemHeight: number;
  bottomSystemHeight: number;
  boundaryPanelTotal: number;
  functionalZoneTotal: number;
  calculatedHeight: number;
  expectedCabinetHeight: number;
  difference: number;
  ziThickness: number;
}

export type ProfilePoint =
  | { x: number; y: number }
  | { y: number; z: number }
  | { x: number; z: number };

export interface Board {
  id: string;
  name: string;
  category: string;
  boardType: string;
  materialThickness: number;
  profilePlane: "XY" | "XZ" | "YZ";
  thicknessAxis: "X" | "Y" | "Z";
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  source?: string;
  notes?: string[];
  profileVector?: ProfilePoint[];
  cutProfileVector?: Array<{ y: number; z: number }>;
  profileFeatures?: Array<{
    type: string;
    y0: number;
    y1: number;
    z0: number;
    z1: number;
    source?: string;
    notes?: string[];
    boundaryId?: string;
    boundaryType?: string;
    h34BoardId?: string;
  }>;
}

export type VerticalBoardId = "V1" | "V2" | "V3" | "V4";
export type ZiFeatureBoundaryType = Exclude<BoundaryType, "none"> | "shortened_zi";

export interface ZiSlotFeature {
  id: string;
  type: "zi_slot";
  targetBoardId: VerticalBoardId;
  boundaryId: string;
  boundaryType: ZiFeatureBoundaryType;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  centerZ: number;
  source: string;
  notes?: string[];
}

export interface ZiGrooveFeature {
  id: string;
  type: "zi_groove";
  targetBoardId: string;
  dividerBoardId: string;
  zoneId: string;
  boundaryId: string;
  face: "top" | "bottom" | "through";
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  depth: number;
  source: string;
  notes?: string[];
}

export interface H34ClearanceSlotFeature {
  id: string;
  type: "h34_clearance_slot";
  targetBoardId: string;
  h34BoardId: string;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  source: string;
  notes?: string[];
}

export interface T3DrillHoleFeature {
  id: string;
  type: "t3_drill_hole";
  targetBoardId: "T3";
  x: number;
  y: number;
  diameter: number;
  through: boolean;
  source: string;
  notes?: string[];
}

export interface LedGrooveSegment {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface B3GrooveFeature {
  id: string;
  type: "b3_groove";
  targetBoardId: "B3";
  face: "bottom";
  width: number;
  depth: number;
  frontOffset: number;
  branchCount: number;
  /** Length of each rear T-branch along +Y (mm); runs to the board back edge. */
  branchLength: number;
  /** Cross-section width of each T-branch (mm); same as main channel width. */
  branchWidth: number;
  /** Distance from each board X end to branch centerline (mm). */
  branchEndInset: number;
  main: LedGrooveSegment;
  branches: LedGrooveSegment[];
  source: string;
  notes?: string[];
}

export interface T3GrooveFeature {
  id: string;
  type: "t3_groove";
  targetBoardId: "T3";
  face: "top";
  width: number;
  depth: number;
  frontOffset: number;
  branchCount: number;
  branchLength: number;
  branchWidth: number;
  branchEndInset: number;
  main: LedGrooveSegment;
  branches: LedGrooveSegment[];
  source: string;
  notes?: string[];
}

export interface B3DrillHoleFeature {
  id: string;
  type: "b3_drill_hole";
  targetBoardId: "B3";
  x: number;
  y: number;
  diameter: number;
  through: boolean;
  source: string;
  notes?: string[];
}

export interface DividerTongueFeature {
  id: string;
  type: "divider_tongue";
  targetBoardId: string;
  relatedZiBoardId: string;
  relatedGrooveFeatureId: string;
  zoneId: string;
  boundaryId: string;
  position: "top" | "bottom";
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  insertionDepth: number;
  source: string;
  notes?: string[];
}

export type BoardFeature =
  | ZiSlotFeature
  | ZiGrooveFeature
  | H34ClearanceSlotFeature
  | T3DrillHoleFeature
  | B3GrooveFeature
  | T3GrooveFeature
  | B3DrillHoleFeature
  | DividerTongueFeature;

export interface GeneralTallCabinetParams {
  cabinetHeight: number;
  cabinetWidth: number;
  cabinetDepth: number;
  panelThickness?: number;
  leftSidePanelThickness?: number;
  rightSidePanelThickness?: number;
  leftSidePanelAdaptAvoidance?: boolean;
  rightSidePanelAdaptAvoidance?: boolean;
  leftSidePanelIgnoreAvoidance?: boolean;
  rightSidePanelIgnoreAvoidance?: boolean;
  frontFaceAllowance?: number;
  ziThickness?: number;
  hThickness?: number;
  sideClearance?: number;
  doorPanelThickness?: number;
  frontPanelThickness?: number;
  frontClearance?: number;
  frontHardware?: Partial<GtFrontHardwareSettings>;
  dividerThickness?: number;
  avoidance?: {
    enabled: boolean;
    depth: number;
    height?: number;
  };
  topSystem: TopBottomSystemConfig;
  bottomSystem: TopBottomSystemConfig;
  zones: FunctionalZone[];
  /**
   * Fridge stacks only: decorative exterior side panel.
   * Maps to SidePanel_L / SidePanel_R (16mm) and cabinetWidth = applianceWidth + 45|61.
   */
  exteriorSide?: "none" | "left" | "right";
  /** Default true when fridge zones exist: rewrite cabinetWidth from appliance width. */
  syncCabinetWidthFromFridge?: boolean;
}

export interface GeneralTallCabinetDebug {
  midWidth: number;
  midDepth: number;
  leftSidePanelThickness: number;
  rightSidePanelThickness: number;
  panelThickness: number;
  frontFaceAllowance: number;
  ziThickness: number;
  hThickness: number;
  sideClearance: number;
  doorPanelThickness: number;
  fridgeAvoidance?: {
    finalMode: "none" | "normal" | "raised";
    fridgeGap: number;
    fridgeBaseBottomZ: number;
    inputHeight: number;
  };
  mergeAndConflict?: {
    topMergeCandidate: boolean;
    bottomMergeCandidate: boolean;
    depthGap: number;
    topBottomHSystemOverlapExpected: boolean;
    hZiConflicts: Array<{
      hBoardId: string;
      hBoardType: string;
      ziBoardId: string;
      ziBoardType: "full_zi" | "shortened_zi" | "half_zi";
      overlapZ0: number;
      overlapZ1: number;
      action: "movement_applied" | "movement_skipped" | "half_zi_rule_deferred";
      moved: boolean;
      originalZ0: number;
      originalZ1: number;
      newZ0?: number;
      newZ1?: number;
      movementDirection: "below" | "above" | "none";
      skippedReason?: string;
    }>;
  };
  h34Clearance?: Array<{
    dividerBoardId: string;
    h34BoardId: string;
    originalZ0: number;
    originalZ1: number;
    effectiveZ0?: number;
    effectiveZ1?: number;
    action: "placeholder_outside_divider_range" | "cut_kept" | "cut_skipped_no_intersection";
    note: string;
  }>;
  sidePanelOverlapAudit?: {
    sidePanels: Array<{
      boardId: "SidePanel_L" | "SidePanel_R";
      bbox: Pick<Board, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">;
    }>;
    verticalBoards: Array<{
      boardId: VerticalBoardId;
      bbox: Pick<Board, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">;
    }>;
    overlaps: Array<{
      sidePanelId: "SidePanel_L" | "SidePanel_R";
      verticalBoardId: VerticalBoardId;
      overlaps: boolean;
      note: string;
    }>;
    note: string;
  };
  assemblyOverlapAudit?: {
    boardCount: number;
    overlapPairCount: number;
    parallelOverlapCount: number;
    perpendicularOverlapCount: number;
    allowedOverlapCount: number;
    unexpectedOverlapCount: number;
    pairs: Array<{
      boardAId: string;
      boardBId: string;
      boardACategory: string;
      boardBCategory: string;
      overlapMm3: number;
      overlapBbox: Pick<Board, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">;
      relation: "parallel_slab" | "perpendicular_corner";
      allowed: boolean;
      allowReason?: string;
    }>;
    unexpectedOverlaps: Array<{
      boardAId: string;
      boardBId: string;
      boardACategory: string;
      boardBCategory: string;
      overlapMm3: number;
      overlapBbox: Pick<Board, "x0" | "x1" | "y0" | "y1" | "z0" | "z1">;
      relation: "parallel_slab" | "perpendicular_corner";
      allowed: boolean;
      allowReason?: string;
    }>;
    note: string;
  };
}

export type GeneralTallResolvedFrontType =
  | "left_door"
  | "right_door"
  | "drawer"
  | "top_flap"
  | "bottom_flap"
  | "fixed_panel";

export interface GtHingeCupHole {
  id: string;
  diameter: number;
  depth: number;
  centerX: number;
  centerY: number;
  centerZ: number;
  drillFromFace: "rear";
}

export interface GtLockCutout {
  presetId: string;
  shape: "rounded_slot";
  orientation: "horizontal" | "vertical";
  centerX: number;
  centerY: number;
  centerZ: number;
  width: number;
  height: number;
  radius: number;
  x0: number;
  x1: number;
  z0: number;
  z1: number;
  mountingBoardId?: string;
  mountingFace?: "top" | "bottom" | "left" | "right";
  fallbackApplied?: boolean;
}

export interface GeneralTallFrontPanel {
  id: string;
  zoneId: string;
  sourceZoneType: ZoneType;
  resolvedType: GeneralTallResolvedFrontType;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  width: number;
  height: number;
  thickness: number;
  z0Source: string;
  z1Source: string;
  hingeHoles?: GtHingeCupHole[];
  lockCutout?: GtLockCutout;
  warnings: string[];
}

export interface GtFrontHardwareSettings {
  frontPanelsEnabled: boolean;
  frontClearance: number;
  locksEnabled: boolean;
  lockPresetId: string;
  defaultHingeSettings: GtHingeSettings;
}

import type { RelationshipDeclaration } from "./relationshipDeclarations.ts";

export interface GeneralTallCabinetResult {
  boards: Board[];
  features: BoardFeature[];
  frontPanels: GeneralTallFrontPanel[];
  stacking: StackingCalculationResult;
  boundaries: BoundaryResult[];
  validation: BoundaryValidation;
  warnings: string[];
  debug: GeneralTallCabinetDebug;
  relationshipDeclarations: RelationshipDeclaration[];
}
