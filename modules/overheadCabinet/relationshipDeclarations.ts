import type { Board } from "./types.ts";

/** M6 design-intent structural joints for standard OHC skeleton boards. */
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

export const OVERHEAD_RELATIONSHIP_DECLARATIONS: RelationshipDeclaration[] = [
  {
    declarationId: "oh_bp_d0_back_to_divider",
    generator: "overhead",
    panelAId: "BP",
    panelBId: "D0",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "BP",
    targetPanelId: "D0",
    ruleId: "overhead_back_divider_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "oh_bp_fp0_back_to_front",
    generator: "overhead",
    panelAId: "BP",
    panelBId: "FP0",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "BP",
    targetPanelId: "FP0",
    ruleId: "overhead_back_front_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "oh_d0_fp0_divider_to_front",
    generator: "overhead",
    panelAId: "D0",
    panelBId: "FP0",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "D0",
    targetPanelId: "FP0",
    ruleId: "overhead_divider_front_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "oh_t1_t2_top_rail_stack",
    generator: "overhead",
    panelAId: "T1",
    panelBId: "T2",
    relationshipType: "face_contact",
    geometryType: "surface_to_surface",
    hostPanelId: "T1",
    targetPanelId: "T2",
    ruleId: "overhead_top_rail_stack_v1",
    allowedHardware: [],
  },
];

export function relationshipDeclarationsForBoards(boards: Board[]): RelationshipDeclaration[] {
  const boardIds = new Set(boards.map((board) => board.id));
  return OVERHEAD_RELATIONSHIP_DECLARATIONS.filter((item) => {
    const required = new Set([item.panelAId, item.panelBId, item.hostPanelId, item.targetPanelId]);
    for (const boardId of required) {
      if (!boardIds.has(boardId)) {
        return false;
      }
    }
    return true;
  });
}
