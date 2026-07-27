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
  profileFeatures?: Array<Record<string, unknown>>;
}

export interface OverheadCabinetParams {
  style?: "style_1" | "style_2" | string;
  cabinetWidth: number;
  cabinetDepth: number;
  cabinetHeight?: number;
  /** Carcass / structural board colour. Default White Stipple (double-sided). */
  carcassColor?: string;
  carcassColorName?: string;
  /** T3 top-face LED T-groove (opens upward). Default on when omitted. */
  ledGroove?: boolean;
  topClearanceHeight?: number;
  frontPanelThickness?: number;
  clearance?: number;
  hingeHoleDiameter?: number;
  hingeHoleDepth?: number;
  hingeHoleFromTop?: number;
  hingeHoleFromSide?: number;
  selectedZoneIndex?: number;
  /** Rangehood carcass insert. Only one contiguous rangehood group is allowed per OHC. */
  rangehoodPreset?: "NCE" | string;
  /** Clear distance from BP top face to RGHD_TOP bottom face. */
  rangehoodClearHeight?: number;
  rangehoodAlignment?: "left" | "right" | string;
  /** Cutout distance from the selected outer D inner face. Minimum 40 mm for NCE. */
  rangehoodEdgeOffsetX?: number;
  // Legacy aliases kept for bridge/backwards compatibility.
  bottomThickness?: number;
  dividerTongueHeight?: number;
  routerDiameter?: number;
  featureWidth?: number;
  internalDividerCenterlines?: number[];
  zones?: Array<{
    id?: string;
    type: "up_flap" | "rangehood_flap" | "fixed_panel" | "open" | string;
    width: number;
  }>;
}

export interface OverheadValidation {
  errors: string[];
  warnings: string[];
}

export interface RelationshipDeclaration {
  declarationId: string;
  generator: "overhead";
  panelAId: string;
  panelBId: string;
  relationshipType: "structural_butt_joint" | "face_contact";
  geometryType: "edge_to_surface" | "surface_to_surface";
  hostPanelId: string;
  targetPanelId: string;
  ruleId: string;
  allowedHardware: string[];
}

export interface OverheadCabinetResult {
  params: Required<
    Pick<OverheadCabinetParams, "cabinetWidth" | "cabinetDepth"> & {
      cabinetHeight: number;
      style: string;
      topClearanceHeight: number;
      frontPanelThickness: number;
      clearance: number;
              hingeHoleDiameter: number;
              hingeHoleDepth: number;
              hingeHoleFromTop: number;
              hingeHoleFromSide: number;
      bottomThickness: number;
      dividerTongueHeight: number;
      routerDiameter: number;
      featureWidth: number;
      internalDividerCenterlines: number[];
      carcassColor: string;
      carcassColorName: string;
      rangehoodPreset: string;
      rangehoodClearHeight: number;
      rangehoodAlignment: string;
      rangehoodEdgeOffsetX: number;
    }
  >;
  boards: Board[];
  features: unknown[];
  relationshipDeclarations: RelationshipDeclaration[];
  validation: OverheadValidation;
  debug: {
    phase: "geometry_v1" | "skeleton_v0";
    legacyReference: string;
    dividerCenterlines: number[];
    legacyGeometry?: unknown;
    svgPreview?: string;
  };
}
