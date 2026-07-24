export type KitchenFunctionType =
  | "left_door"
  | "right_door"
  | "double_door"
  | "drawer"
  | "open"
  | "down_flap"
  | "stove"
  | "custom";

export type KitchenColumnType = KitchenFunctionType;
export type KitchenZoneType = KitchenFunctionType | "unassigned";

export interface KitchenGlobalSettings {
  length: number;
  depth: number;
  height: number;
  materialThickness: number;
  frontThickness: number;
  bottomClearanceHeight: number;
  bottomClearanceStyle: "style_1" | "style_2" | string;
  /** Style 1 B3 bottom-face LED T-groove. Default on when omitted. */
  ledGroove?: boolean;
}

export interface KitchenZone {
  id: string;
  height: number;
  zoneType: KitchenZoneType;
  shelfEnabled?: boolean;
  shelfHeight?: number;
  leftSidePanelOptions?: SidePanelOptions;
  rightSidePanelOptions?: SidePanelOptions;
}

export interface SidePanelOptions {
  panelType: "carcass" | "door";
  frontVisible: boolean;
  bchNotchEnabled: boolean;
  grooveVisible: boolean;
  extendT2T3B4ToOuterFace: boolean;
  strengtheningStripEnabled: boolean;
}

export interface KitchenColumn {
  id: string;
  width: number;
  columnType: KitchenColumnType;
  zones: KitchenZone[];
}

export interface WheelAvoidance {
  id: string;
  x0: number;
  x1: number;
  height: number;
  depth: number;
}

export type VPanelMachiningMode =
  | "left_half_right_none"
  | "right_half_left_none"
  | "right_half_left_through"
  | "left_half_right_through"
  | "left_half"
  | "right_half"
  | "left_through"
  | "right_through"
  | "left_face_half_allowed"
  | "right_face_half_allowed"
  | "through_only";

export interface VPanelMachiningPreference {
  vPanelIndex: number;
  mode: VPanelMachiningMode;
}

export interface KitchenLayoutState {
  globalSettings: KitchenGlobalSettings;
  columns: KitchenColumn[];
  wheelAvoidances: WheelAvoidance[];
  vPanelMachiningPreferences?: VPanelMachiningPreference[];
}

export interface KitchenGeometryConstants {
  notchAllowanceExtra: number;
  style1ToeKickY: number;
  bottomSlotRearY: number;
  receiverNotchDepth: number;
  supportStripWidth: number;
  b3Depth: number;
  b3InternalNotchDepth: number;
  supportStripNotchDepth: number;
  minStripSegmentLength: number;
}

export interface ComputedKitchenColumn extends KitchenColumn {
  index: number;
  logicalX0: number;
  logicalX1: number;
  clearX0: number;
  clearX1: number;
}

export interface ComputedKitchenZone extends KitchenZone {
  columnId: string;
  columnIndex: number;
  zoneIndex: number;
  x0: number;
  x1: number;
  z0: number;
  z1: number;
}

export interface BoardNotch {
  id: string;
  x0?: number;
  x1?: number;
  y0?: number;
  y1?: number;
  z0?: number;
  z1?: number;
  from: "front" | "rear" | "top" | "bottom";
}

export type PanelBodyPlane = "XY" | "XZ" | "YZ";

export interface PanelBodyCutout {
  id: string;
  kind: "slot" | "notch";
  sourceId: string;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  slotType?: SlotType;
  side?: SlotSide;
  grooveDepth?: number;
}

export interface PanelBodyGeometry {
  plane: PanelBodyPlane;
  outer: Array<[number, number]>;
  cutouts: PanelBodyCutout[];
}

export interface PanelDxfAudit {
  closed: boolean;
  pointCount: number;
  duplicatePointCount: number;
  collinearPointCount: number;
  area: number;
  warnings: string[];
}

export interface PanelDxfGeometry {
  panelId: string;
  panelKind: "board" | "vPanel";
  panelType: string;
  plane: PanelBodyPlane;
  thicknessAxis: "X" | "Y" | "Z";
  materialThickness: number;
  bbox: {
    x0: number;
    x1: number;
    y0: number;
    y1: number;
    z0: number;
    z1: number;
  };
  outer: Array<[number, number]>;
  notchVectors?: PanelBodyCutout[];
  throughVectors: PanelBodyCutout[];
  halfGrooveVectors: PanelBodyCutout[];
  audit: PanelDxfAudit;
}

export interface BoardGeometry {
  id: string;
  name: string;
  type:
    | "B1"
    | "B2"
    | "B3"
    | "B4"
    | "T1"
    | "T2"
    | "T3"
    | "drawer_divider"
    | "full_depth_shelf"
    | "door_shelf"
    | "avoidance_top"
    | "avoidance_front"
    | "side_strengthening_strip";
  category: string;
  materialThickness: number;
  profilePlane: "XY" | "XZ" | "YZ";
  thicknessAxis: "X" | "Y" | "Z";
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  profileXY?: Array<[number, number]>;
  body?: PanelBodyGeometry;
  notches?: BoardNotch[];
  notes?: string[];
}

export interface VPanelGeometry {
  id: string;
  index: number;
  x0: number;
  x1: number;
  centerX: number;
  yzProfile: Array<[number, number]>;
  body?: PanelBodyGeometry;
  hasWheelAvoidance: boolean;
  machiningMode?: VPanelMachiningMode;
  materialThickness?: number;
  sidePanelOptions?: SidePanelOptions;
}

export type SlotSide = "left" | "right";
export type SlotType = "through" | "half";

export interface SlotRequest {
  id: string;
  boardId: string;
  vPanelIndex: number;
  side: SlotSide;
  slotType: SlotType;
  tongueLength?: number;
  grooveDepth?: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  visibleOppositeSide: boolean;
}

export interface ResolvedSlot extends SlotRequest {
  resolvedSlotType: SlotType | "none";
  machiningMode?: VPanelMachiningMode;
  /** Opposing same-height half tongues share one through groove on the V panel. */
  sharedOpposingGroove?: boolean;
}

export interface HingeCupHole {
  id: string;
  centerX: number;
  centerZ: number;
  diameter: number;
  depth: number;
}

export interface PushButtonLockCutout {
  id: string;
  presetId: string;
  shape: "rounded_slot";
  centerX: number;
  centerZ: number;
  x0: number;
  x1: number;
  z0: number;
  z1: number;
  width: number;
  height: number;
  radius: number;
}

export interface FrontPanelGeometry {
  id: string;
  columnId: string;
  zoneId: string;
  type: "left_door" | "right_door" | "drawer" | "down_flap";
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  width: number;
  height: number;
  thickness: number;
  hingeHoles?: HingeCupHole[];
  lockCutout?: PushButtonLockCutout;
}

export interface KitchenGeometryResult {
  params: KitchenLayoutState;
  constants: KitchenGeometryConstants;
  computedColumns: ComputedKitchenColumn[];
  computedZones: ComputedKitchenZone[];
  vPanels: VPanelGeometry[];
  boards: BoardGeometry[];
  frontPanels: FrontPanelGeometry[];
  panelDxf: PanelDxfGeometry[];
  slotRequests: SlotRequest[];
  resolvedSlots: ResolvedSlot[];
  relationshipDeclarations?: import("./relationshipDeclarations.ts").RelationshipDeclaration[];
  warnings: string[];
  errors: string[];
  debug: {
    phase: "kitchen_geometry_v0";
    xBoundaries: number[];
    svgFrontElevation: string;
    svgVPanelProfile: string;
    svgBoardTopView: string;
  };
}
