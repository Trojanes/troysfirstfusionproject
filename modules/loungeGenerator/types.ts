export type LoungeStyle = "L_SHAPE" | "I_SHAPE" | "PARALLEL" | "U_SHAPE";
export type LoungeLPosition = "LEFT" | "RIGHT";
export type LoungeFrontAccess = "NONE" | "DRAWER" | "FLAP";

export type LoungeDoorLockStyle = "RAZOR_ROUNDED" | "NONE";

export interface MiddleCabinetSettings {
  width: number;
  depth: number;
  height: number;
  startHeight: number;
  doorPanelThickness: number;
  doorClearance: number;
  doorLockStyle: LoungeDoorLockStyle;
  lockSideDistance: number;
  hingeSideDistance: number;
  hingeCupCenterFromEdge: number;
  hingeCupDiameter: number;
  hingeCupDepth: number;
}

/** Which flat face a blind cut starts from: local Z+ (top) or local Z- (bottom). */
export type LoungeCutFace = "top" | "bottom";

export interface LoungeHingeHole {
  id: string;
  centerX: number;
  centerY: number;
  diameter: number;
  depth: number;
  face: LoungeCutFace;
}

export interface LoungeLockCutout {
  id: string;
  presetId: string;
  shape: "rounded_slot";
  centerX: number;
  centerY: number;
  width: number;
  height: number;
  radius: number;
  through: true;
}

export interface LoungeGroove {
  id: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  depth: number;
  face: LoungeCutFace;
}

export interface LoungeSettings {
  style: LoungeStyle;
  height: number;
  partitionPanelThickness: number;
  wheelAvoidanceEnabled?: boolean;
  mainWidth: number;
  mainDepth: number;
  lWidth: number;
  lDepth: number;
  lPosition: LoungeLPosition;
  topLidEnabled: boolean;
  lFrontAccess: LoungeFrontAccess;
  totalWidth: number;
  singleLoungeWidth: number;
  depth: number;
  avoidanceDepth: number;
  avoidanceHeight: number;
  hasMiddleCabinet: boolean;
  middleCabinet: MiddleCabinetSettings;
}

export interface LoungeBounds2D {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

export interface LoungeOpening {
  id: string;
  panelId: string;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  width: number;
  depth: number;
  radius: number;
  stepWidth: number;
  stepHeight: number;
}

export interface LoungeLid {
  id: string;
  name: string;
  kind: "lid";
  profilePlane: "XY";
  width: number;
  depth: number;
  thickness: number;
  radius: number;
  stepWidth: number;
  stepHeight: number;
  fingerHoleDiameter: number;
  fingerHole: {
    diameter: number;
    centerX: number;
    centerY: number;
    through: true;
  };
  placement: {
    x0: number;
    x1: number;
    y0: number;
    y1: number;
    z0: number;
    z1: number;
  };
  outer: number[][];
}

export interface LoungePanel {
  id: string;
  name: string;
  kind:
    | "front_panel"
    | "top_panel"
    | "side_panel"
    | "l_support_profile"
    | "support_strip"
    | "avoidance_top"
    | "avoidance_front"
    | "cabinet_top"
    | "cabinet_bottom"
    | "cabinet_side"
    | "cabinet_divider"
    | "cabinet_door";
  profilePlane: "XY" | "XZ" | "YZ";
  width?: number;
  depth?: number;
  height?: number;
  length?: number;
  thickness: number;
  material?: string;
  placement: {
    x0: number;
    x1: number;
    y0: number;
    y1: number;
    z0: number;
    z1: number;
  };
  outer: number[][];
  opening?: LoungeOpening;
  sourceBounds?: LoungeBounds2D;
  note?: string;
  mirrored?: boolean;
  verticalLegWidth?: number;
  horizontalLegWidth?: number;
  hingeHoles?: LoungeHingeHole[];
  lockCutouts?: LoungeLockCutout[];
  grooves?: LoungeGroove[];
}

export interface LoungeGeometryResult {
  meta: {
    module: "lounge";
    style: LoungeStyle;
    phase: string;
  };
  state: LoungeSettings;
  footprint: {
    main?: LoungeBounds2D;
    i?: LoungeBounds2D;
    l?: LoungeBounds2D;
    lPosition?: LoungeLPosition;
    left?: LoungeBounds2D;
    right?: LoungeBounds2D;
    middleGap?: number;
  };
  panels: LoungePanel[];
  openings: LoungeOpening[];
  lids: LoungeLid[];
  validation: {
    warnings: string[];
    errors: string[];
  };
  relationshipDeclarations?: import("./relationshipDeclarations.ts").RelationshipDeclaration[];
}
