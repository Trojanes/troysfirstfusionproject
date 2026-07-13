import {
  DIVIDER_THICKNESS_MM,
  DEFAULT_ROUTER_DIAMETER_MM,
  boardXRange,
  calculateOverheadGeometry,
  clampRange,
  type OverheadCabinetInputs,
  type OverheadLegacyGeometry,
} from "./geometry.ts";
import { generateOHCSvgPreview } from "./svgPreview.ts";
import type { Board, OverheadCabinetParams, OverheadCabinetResult } from "./types.ts";
import { relationshipDeclarationsForBoards } from "./relationshipDeclarations.ts";

export * from "./geometry.ts";
export * from "./svgPreview.ts";

function toInputs(params: OverheadCabinetParams): OverheadCabinetInputs {
  return {
    cabinetWidth: Number(params.cabinetWidth),
    cabinetDepth: Number(params.cabinetDepth),
    cabinetHeight: params.cabinetHeight,
    style: params.style,
    topClearanceHeight: params.topClearanceHeight ?? 40,
    frontPanelThickness: params.frontPanelThickness ?? 16,
    clearance: params.clearance ?? 2.5,
    hingeHoleDiameter: params.hingeHoleDiameter ?? 35,
    hingeHoleDepth: params.hingeHoleDepth ?? 12,
    hingeHoleFromTop: params.hingeHoleFromTop ?? 22.5,
    hingeHoleFromSide: params.hingeHoleFromSide ?? 100,
    bottomThickness: params.featureWidth ?? params.bottomThickness ?? DIVIDER_THICKNESS_MM,
    dividerTongueHeight: params.dividerTongueHeight ?? (params.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
    routerDiameter: params.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
    featureWidth: params.featureWidth ?? DIVIDER_THICKNESS_MM,
    internalDividerCenterlines: Array.isArray(params.internalDividerCenterlines)
      ? params.internalDividerCenterlines.map(Number)
      : [],
    zones: params.zones,
  };
}

function legacyToBoards(geometry: OverheadLegacyGeometry, inputs: OverheadCabinetInputs): Board[] {
  const { cabinetWidth, cabinetDepth, cabinetHeight, bottomThickness, featureWidth, topClearanceHeight, frontPanelThickness } = {
    cabinetWidth: inputs.cabinetWidth,
    cabinetDepth: inputs.cabinetDepth,
    cabinetHeight: inputs.cabinetHeight,
    bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
    featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
    topClearanceHeight: inputs.topClearanceHeight ?? 40,
    frontPanelThickness: inputs.frontPanelThickness ?? 16,
  };

  const boards: Board[] = [
    {
      id: "BP",
      name: "Bottom Panel",
      category: "panel",
      boardType: "BP",
      materialThickness: bottomThickness,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: 0,
      z1: bottomThickness,
      source: "overhead_geometry",
    },
  ];

  boards.push({
    id: "T1",
    name: "Top Front Rail T1",
    category: "rail",
    boardType: "T1",
    materialThickness: frontPanelThickness,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0: 0,
    x1: cabinetWidth,
    y0: 0,
    y1: frontPanelThickness,
    z0: (cabinetHeight ?? topClearanceHeight) - topClearanceHeight,
    z1: cabinetHeight ?? topClearanceHeight,
    source: "overhead_geometry_v7",
  });

  boards.push({
    id: "T2",
    name: "Top Front Rail T2",
    category: "rail",
    boardType: "T2",
    materialThickness: featureWidth,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0: 0,
    x1: cabinetWidth,
    y0: frontPanelThickness,
    y1: frontPanelThickness + featureWidth,
    z0: (cabinetHeight ?? topClearanceHeight) - topClearanceHeight,
    z1: cabinetHeight ?? topClearanceHeight,
    source: "overhead_geometry_v7",
  });

  if (geometry.trimmed_vectors.T3.length > 0) {
    boards.push({
      id: "T3",
      name: "Top Rear Panel",
      category: "panel",
      boardType: "T3",
      materialThickness: featureWidth,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: cabinetHeight != null ? cabinetHeight - featureWidth : 0,
      z1: cabinetHeight ?? bottomThickness,
      source: "overhead_geometry",
      profileVector: geometry.trimmed_vectors.T3.map(([x, y]) => ({ x, y })),
    });
  }

  if (geometry.trimmed_vectors.T4.length > 0) {
    boards.push({
      id: "T4",
      name: "Top Front Panel",
      category: "panel",
      boardType: "T4",
      materialThickness: featureWidth,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: cabinetHeight != null ? cabinetHeight - featureWidth : 0,
      z1: cabinetHeight ?? bottomThickness,
      source: "overhead_geometry",
      profileVector: geometry.trimmed_vectors.T4.map(([x, y]) => ({ x, y })),
    });
  }

  for (const feature of geometry.divider_features) {
    // Board solid thickness must be featureWidth (CPT), not the BP groove
    // slot width (CPT + clearance). Groove/notch features keep the wider
    // slot range; only the divider body uses boardXRange.
    const [x0, x1] = clampRange(boardXRange(feature.XDi, featureWidth), 0, cabinetWidth);
    // Dividers sit on the shifted bottom panel top at z = 2 * FGw. Fusion
    // postprocess used to apply this as a +2*FGw move; bake it into board Z.
    const dividerZ0 = featureWidth * 2;
    const dividerTopZ = (cabinetHeight ?? bottomThickness + 1) + featureWidth;
    boards.push({
      id: feature.id,
      name: `Divider ${feature.id}`,
      category: "divider",
      boardType: "divider",
      materialThickness: featureWidth,
      profilePlane: "YZ",
      thicknessAxis: "X",
      x0,
      x1,
      y0: 0,
      y1: cabinetDepth,
      z0: dividerZ0,
      z1: dividerTopZ,
      source: "overhead_geometry",
      cutProfileVector:
        geometry.trimmed_vectors.DividerSide.length > 0
          ? geometry.trimmed_vectors.DividerSide.map(([y, z]) => ({ y, z }))
          : undefined,
      profileFeatures: [
        feature.bp_groove,
        feature.divider_tongue,
        feature.t3_notch,
        feature.t4_notch,
      ],
    });
  }

  for (const panel of geometry.front_panels) {
    boards.push({
      id: panel.id,
      name: `Front Panel ${panel.zoneIndex + 1}`,
      category: "front_panel",
      boardType: panel.type,
      materialThickness: panel.thickness,
      profilePlane: "XZ",
      thicknessAxis: "Y",
      x0: panel.x[0],
      x1: panel.x[1],
      y0: panel.y[0],
      y1: panel.y[1],
      z0: panel.z[0],
      z1: panel.z[1],
      source: "overhead_geometry_v7",
      profileVector: [
        { x: 0, z: 0 },
        { x: panel.width, z: 0 },
        { x: panel.width, z: panel.height },
        { x: 0, z: panel.height },
        { x: 0, z: 0 },
      ],
    });
  }

  return boards;
}

export function generateOverheadCabinet(rawParams: OverheadCabinetParams): OverheadCabinetResult {
  const inputs = toInputs(rawParams);
  const validation = { errors: [] as string[], warnings: [] as string[] };

  if (!Number.isFinite(inputs.cabinetWidth) || inputs.cabinetWidth <= 0) {
    validation.errors.push("cabinetWidth must be a positive number.");
  }
  if (!Number.isFinite(inputs.cabinetDepth) || inputs.cabinetDepth <= 0) {
    validation.errors.push("cabinetDepth must be a positive number.");
  }
  if (
    inputs.cabinetHeight != null &&
    (!Number.isFinite(inputs.cabinetHeight) || inputs.cabinetHeight <= 0)
  ) {
    validation.errors.push("cabinetHeight must be a positive number when provided.");
  }

  const centerlines =
    validation.errors.length === 0
      ? calculateOverheadGeometry(inputs).divider_features.map((f) => f.XDi)
      : [];

  if (validation.errors.length > 0) {
    return {
      params: {
        cabinetWidth: inputs.cabinetWidth,
        cabinetDepth: inputs.cabinetDepth,
        cabinetHeight: inputs.cabinetHeight ?? 0,
        style: inputs.style ?? "style_1",
        topClearanceHeight: inputs.topClearanceHeight ?? 40,
        frontPanelThickness: inputs.frontPanelThickness ?? 16,
        clearance: inputs.clearance ?? 2.5,
        hingeHoleDiameter: inputs.hingeHoleDiameter ?? 35,
        hingeHoleDepth: inputs.hingeHoleDepth ?? 12,
        hingeHoleFromTop: inputs.hingeHoleFromTop ?? 22.5,
        hingeHoleFromSide: inputs.hingeHoleFromSide ?? 100,
        bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
        dividerTongueHeight: inputs.dividerTongueHeight ?? (inputs.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
        routerDiameter: inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
        featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
        internalDividerCenterlines: inputs.internalDividerCenterlines ?? [],
      },
      boards: [],
      features: [],
      relationshipDeclarations: [],
      validation,
      debug: {
        phase: "geometry_v1",
        legacyReference: "fusion360-cabinet-generator/core/overhead_geometry.py",
        dividerCenterlines: centerlines,
      },
    };
  }

  const geometry = calculateOverheadGeometry(inputs);
  const boards = legacyToBoards(geometry, inputs);
  const relationshipDeclarations = relationshipDeclarationsForBoards(boards);

  return {
    params: {
      cabinetWidth: inputs.cabinetWidth,
      cabinetDepth: inputs.cabinetDepth,
      cabinetHeight: inputs.cabinetHeight ?? 0,
      style: inputs.style ?? "style_1",
      topClearanceHeight: inputs.topClearanceHeight ?? 40,
      frontPanelThickness: inputs.frontPanelThickness ?? 16,
      clearance: inputs.clearance ?? 2.5,
      hingeHoleDiameter: inputs.hingeHoleDiameter ?? 35,
      hingeHoleDepth: inputs.hingeHoleDepth ?? 12,
      hingeHoleFromTop: inputs.hingeHoleFromTop ?? 22.5,
      hingeHoleFromSide: inputs.hingeHoleFromSide ?? 100,
      bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
      dividerTongueHeight: inputs.dividerTongueHeight ?? (inputs.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
      routerDiameter: inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
      featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
      internalDividerCenterlines: inputs.internalDividerCenterlines ?? [],
    },
    boards,
    features: [
      ...geometry.divider_features,
      ...geometry.front_panels,
      ...geometry.hinge_holes,
    ],
    relationshipDeclarations,
    validation,
    debug: {
      phase: "geometry_v1",
      legacyReference: "fusion360-cabinet-generator/core/overhead_geometry.py",
      dividerCenterlines: centerlines,
      legacyGeometry: geometry,
      svgPreview: generateOHCSvgPreview(geometry, {
        selectedZoneIndex: Number((rawParams as { selectedZoneIndex?: number }).selectedZoneIndex ?? -1),
      }),
    },
  };
}
