/** Small Cabinet v1 — simple floor box, side doors / drawers only. */

export type SmallCabinetZoneType = "left_door" | "right_door" | "drawer";

export type ProfilePoint =
  | { x: number; y: number }
  | { y: number; z: number }
  | { x: number; z: number };

export interface SmallCabinetZone {
  id?: string;
  type: SmallCabinetZoneType | string;
  /** Logical zone height (mm). Zones stack top→bottom; sum must equal interior height. */
  height: number;
  /** Side-door zones: enable door lock cutout (default true for doors). */
  lockEnabled?: boolean;
  /** Distance from handle-side edge / top for lock center (mm). */
  lockSideDistance?: number;
}

export interface SmallCabinetParams {
  cabinetWidth: number;
  cabinetDepth: number;
  cabinetHeight: number;
  /** Carcass panel thickness (CPT). */
  panelThickness?: number;
  /** Front panel / drawer face thickness (FPT). */
  frontPanelThickness?: number;
  /** Door / drawer face clearance (门缝). */
  frontClearance?: number;
  /** Global door-lock toggle (side doors only). Default true. */
  locksEnabled?: boolean;
  /** Default lock inset from handle edge / top (mm). */
  lockSideDistance?: number;
  carcassColor?: string;
  carcassColorName?: string;
  /** When true, left side panel uses door color slot. */
  leftSideDoorColor?: boolean;
  /** When true, right side panel uses door color slot. */
  rightSideDoorColor?: boolean;
  zones?: SmallCabinetZone[];
}

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
  /** Attribute hint: side panel should use door color. */
  useDoorColor?: boolean;
  hingeSide?: "left" | "right";
  zoneId?: string;
  profileVector?: ProfilePoint[];
  profileFeatures?: Array<Record<string, unknown>>;
  cutProfileVector?: Array<{ y: number; z: number }>;
  /** Door lock pocket on front panel (XZ local / world). */
  lockCutout?: LockCutout;
}

export interface LockCutout {
  x0: number;
  x1: number;
  z0: number;
  z1: number;
  radius: number;
  orientation: "vertical" | "horizontal";
}

export interface SmallCabinetFeature {
  id: string;
  type: "shelf_tongue" | "back_tongue" | "side_groove" | "door_lock";
  targetBoardId: string;
  relatedBoardId?: string;
  side?: "left" | "right";
  y0?: number;
  y1?: number;
  z0?: number;
  z1?: number;
  x0?: number;
  x1?: number;
  depth?: number;
  insertionDepth?: number;
  source?: string;
}

export interface SmallCabinetValidation {
  errors: string[];
  warnings: string[];
}

export interface ResolvedZone {
  id: string;
  type: SmallCabinetZoneType;
  height: number;
  /** Logical top Z (underside of board above / top of interior). */
  zTop: number;
  /** Logical bottom Z (top of board below / bottom of interior). */
  zBottom: number;
  /** Clear opening after half-middle / top-bottom faces. */
  clearZ0: number;
  clearZ1: number;
  lockEnabled: boolean;
  lockSideDistance: number;
}

export interface SmallCabinetResult {
  params: {
    cabinetWidth: number;
    cabinetDepth: number;
    cabinetHeight: number;
    panelThickness: number;
    frontPanelThickness: number;
    frontClearance: number;
    locksEnabled: boolean;
    lockSideDistance: number;
    carcassColor: string;
    carcassColorName: string;
    leftSideDoorColor: boolean;
    rightSideDoorColor: boolean;
  };
  zones: ResolvedZone[];
  boards: Board[];
  features: SmallCabinetFeature[];
  validation: SmallCabinetValidation;
  debug?: Record<string, unknown>;
}
