import type {
  Board,
  OverheadCabinetParams,
  OverheadCabinetResult,
  OverheadValidation,
} from "../overheadCabinet/types.ts";

export type UShapeRunId = "LEFT" | "BACK" | "RIGHT";

export interface UShapeZone {
  id?: string;
  /** Rangehood flaps are allowed on LEFT/RIGHT usable spans only — never BACK/corners. */
  type: "up_flap" | "rangehood_flap" | "fixed_panel" | "open" | string;
  width: number;
}

export interface UShapeRunZones {
  LEFT?: UShapeZone[];
  BACK?: UShapeZone[];
  RIGHT?: UShapeZone[];
}

export interface UShapeOverheadParams {
  totalWidth: number;
  leftArmLength: number;
  rightArmLength: number;
  cabinetDepth: number;
  cabinetHeight: number;
  sideClearance?: number;
  style?: "style_1";
  topClearanceHeight?: number;
  frontPanelThickness?: number;
  clearance?: number;
  featureWidth?: number;
  bottomThickness?: number;
  dividerTongueHeight?: number;
  routerDiameter?: number;
  hingeHoleDiameter?: number;
  hingeHoleDepth?: number;
  hingeHoleFromTop?: number;
  hingeHoleFromSide?: number;
  carcassColor?: string;
  carcassColorName?: string;
  ledGroove?: boolean;
  runLedGroove?: Partial<Record<UShapeRunId, boolean>>;
  /** NCE rangehood settings applied to LEFT/RIGHT runs that contain rangehood_flap zones. */
  rangehoodPreset?: "NCE" | string;
  rangehoodClearHeight?: number;
  rangehoodAlignment?: "left" | "right";
  rangehoodEdgeOffsetX?: number;
  zones?: UShapeRunZones;
}

export interface UShapeRunTransform {
  rotationDeg: -90 | 0 | 90 | 180;
  translateX: number;
  translateY: number;
}

export interface UShapeRunResult {
  id: UShapeRunId;
  cabinetWidth: number;
  reservedStart: number;
  usableZoneWidth: number;
  transform: UShapeRunTransform;
  result: OverheadCabinetResult;
}

export interface UShapeWorldBoard extends Board {
  id: string;
  localBoardId: string;
  runId: UShapeRunId;
}

export interface UShapeContactAudit {
  id: string;
  kind: "touch" | "tongue_groove" | "no_overlap" | "dimension";
  ok: boolean;
  detail: string;
}

export interface UShapeOverheadResult {
  meta: {
    module: "u_shape_overhead";
    style: "style_1";
    phase: "u_shape_geometry_v2";
    geometryRevision: "back_owns_corners_v5";
    cornerOwnership: "BACK";
  };
  params: Required<
    Pick<
      UShapeOverheadParams,
      | "totalWidth"
      | "leftArmLength"
      | "rightArmLength"
      | "cabinetDepth"
      | "cabinetHeight"
      | "sideClearance"
      | "style"
      | "topClearanceHeight"
      | "frontPanelThickness"
      | "clearance"
      | "featureWidth"
      | "carcassColor"
      | "carcassColorName"
      | "ledGroove"
      | "rangehoodPreset"
      | "rangehoodClearHeight"
      | "rangehoodAlignment"
      | "rangehoodEdgeOffsetX"
    >
  > & {
    geometryRevision: "back_owns_corners_v5";
    backCabinetWidth: number;
    backFunctionalSpan: number;
    backClearanceWidth: number;
  };
  runs: UShapeRunResult[];
  worldBoards: UShapeWorldBoard[];
  validation: OverheadValidation;
  audit: UShapeContactAudit[];
  debug: {
    planBounds: { x0: number; x1: number; y0: number; y1: number };
    planSvg: string;
  };
}

export interface UShapeRunBuildOptions {
  id: UShapeRunId;
  width: number;
  reservedStart: number;
  endClearance: number;
  zones: UShapeZone[];
  transform: UShapeRunTransform;
  overheadParams: Omit<OverheadCabinetParams, "cabinetWidth" | "zones">;
}
