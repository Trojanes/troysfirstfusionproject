import type { BoardGeometry } from "./types.ts";

/** Design-intent structural joints for Kitchen style_1 bottom skeleton. */
export interface RelationshipDeclaration {
  declarationId: string;
  generator: "kitchen";
  panelAId: string;
  panelBId: string;
  relationshipType: "structural_butt_joint" | "face_contact";
  geometryType: "edge_to_surface" | "surface_to_surface";
  hostPanelId: string;
  targetPanelId: string;
  ruleId: string;
  allowedHardware: string[];
}

/** v1: bottom rail-to-deck only. Top strip-to-deck is not edge_to_surface on kitchen_base. */
export const KITCHEN_RELATIONSHIP_DECLARATIONS: RelationshipDeclaration[] = [
  {
    declarationId: "kt_b1_b3_bottom_rail_to_deck",
    generator: "kitchen",
    panelAId: "B1",
    panelBId: "B3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "B1",
    targetPanelId: "B3",
    ruleId: "kitchen_bottom_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "kt_b2_b3_carcass_rail_to_deck",
    generator: "kitchen",
    panelAId: "B2",
    panelBId: "B3",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "B2",
    targetPanelId: "B3",
    ruleId: "kitchen_carcass_rail_deck_v1",
    allowedHardware: ["screw_hole"],
  },
];

export function relationshipDeclarationsForBoards(boards: BoardGeometry[]): RelationshipDeclaration[] {
  const boardIds = new Set(boards.map((board) => board.id));
  return KITCHEN_RELATIONSHIP_DECLARATIONS.filter((item) => {
    const required = new Set([item.panelAId, item.panelBId, item.hostPanelId, item.targetPanelId]);
    for (const boardId of required) {
      if (!boardIds.has(boardId)) {
        return false;
      }
    }
    return true;
  });
}
