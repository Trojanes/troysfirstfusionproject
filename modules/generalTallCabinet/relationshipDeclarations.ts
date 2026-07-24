import type { Board } from "./types.ts";

/** Design-intent structural joints for General Tall style_1 skeleton boards. */
export interface RelationshipDeclaration {
  declarationId: string;
  generator: "general_tall";
  panelAId: string;
  panelBId: string;
  relationshipType: "structural_butt_joint" | "face_contact";
  geometryType: "edge_to_surface" | "surface_to_surface";
  hostPanelId: string;
  targetPanelId: string;
  ruleId: string;
  allowedHardware: string[];
}

export const GENERAL_TALL_RELATIONSHIP_DECLARATIONS: RelationshipDeclaration[] = [
  {
    declarationId: "gt_b1_b3_bottom_rail_to_deck",
    generator: "general_tall",
    panelAId: "B1",
    panelBId: "B3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "B1",
    targetPanelId: "B3",
    ruleId: "general_tall_bottom_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "gt_t1_t3_top_rail_to_deck",
    generator: "general_tall",
    panelAId: "T1",
    panelBId: "T3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "T1",
    targetPanelId: "T3",
    ruleId: "general_tall_top_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "gt_b2_b3_mid_rail_to_deck",
    generator: "general_tall",
    panelAId: "B2",
    panelBId: "B3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "B2",
    targetPanelId: "B3",
    ruleId: "general_tall_mid_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "gt_t2_t3_mid_rail_to_deck",
    generator: "general_tall",
    panelAId: "T2",
    panelBId: "T3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "T2",
    targetPanelId: "T3",
    ruleId: "general_tall_mid_top_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
];

/** Fridge stack extras: SidePanel↔stile face joints + V5↔opposite stile. */
const FRIDGE_SIDE_PANEL_L_V1: RelationshipDeclaration = {
  declarationId: "gt_sidepanel_l_v1",
  generator: "general_tall",
  panelAId: "SidePanel_L",
  panelBId: "V1",
  relationshipType: "face_contact",
  geometryType: "surface_to_surface",
  hostPanelId: "SidePanel_L",
  targetPanelId: "V1",
  ruleId: "general_tall_fridge_sidepanel_l_v1",
  allowedHardware: ["screw_hole"],
};

const FRIDGE_SIDE_PANEL_R_V2: RelationshipDeclaration = {
  declarationId: "gt_sidepanel_r_v2",
  generator: "general_tall",
  panelAId: "SidePanel_R",
  panelBId: "V2",
  relationshipType: "face_contact",
  geometryType: "surface_to_surface",
  hostPanelId: "SidePanel_R",
  targetPanelId: "V2",
  ruleId: "general_tall_fridge_sidepanel_r_v2",
  allowedHardware: ["screw_hole"],
};

function fridgeV5Declaration(mateId: "V1" | "V2"): RelationshipDeclaration {
  return {
    declarationId: mateId === "V1" ? "gt_v5_v1" : "gt_v5_v2",
    generator: "general_tall",
    panelAId: "V5",
    panelBId: mateId,
    relationshipType: "face_contact",
    geometryType: "surface_to_surface",
    hostPanelId: "V5",
    targetPanelId: mateId,
    ruleId: mateId === "V1" ? "general_tall_fridge_v5_v1" : "general_tall_fridge_v5_v2",
    allowedHardware: ["screw_hole"],
  };
}

function declarationPresent(item: RelationshipDeclaration, boardIds: Set<string>): boolean {
  const required = new Set([item.panelAId, item.panelBId, item.hostPanelId, item.targetPanelId]);
  for (const boardId of required) {
    if (!boardIds.has(boardId)) {
      return false;
    }
  }
  return true;
}

/**
 * Fridge V5 sits opposite exterior:
 * SidePanel_L → V5 mates V2; SidePanel_R → V5 mates V1; neither → V5 mates V1 (exterior none).
 */
function fridgeExtrasForBoards(boardIds: Set<string>): RelationshipDeclaration[] {
  const extras: RelationshipDeclaration[] = [];
  if (declarationPresent(FRIDGE_SIDE_PANEL_L_V1, boardIds)) {
    extras.push(FRIDGE_SIDE_PANEL_L_V1);
  }
  if (declarationPresent(FRIDGE_SIDE_PANEL_R_V2, boardIds)) {
    extras.push(FRIDGE_SIDE_PANEL_R_V2);
  }
  if (!boardIds.has("V5")) {
    return extras;
  }
  // ponytail: SidePanel presence encodes exterior side; upgrade if multi-fridge / dual side panels appear.
  const mateId: "V1" | "V2" = boardIds.has("SidePanel_L") ? "V2" : "V1";
  const v5Decl = fridgeV5Declaration(mateId);
  if (declarationPresent(v5Decl, boardIds)) {
    extras.push(v5Decl);
  }
  return extras;
}

export function relationshipDeclarationsForBoards(boards: Board[]): RelationshipDeclaration[] {
  const boardIds = new Set(boards.map((board) => board.id));
  const skeleton = GENERAL_TALL_RELATIONSHIP_DECLARATIONS.filter((item) =>
    declarationPresent(item, boardIds),
  );
  return [...skeleton, ...fridgeExtrasForBoards(boardIds)];
}
