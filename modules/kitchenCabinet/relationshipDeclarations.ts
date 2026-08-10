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

function applianceFloorRelationships(boards: BoardGeometry[]): RelationshipDeclaration[] {
  const boardIds = new Set(boards.map((board) => board.id));
  const decls: RelationshipDeclaration[] = [];
  for (const floor of boards.filter((board) => board.type === "appliance_floor")) {
    if (boardIds.has("B3")) {
      decls.push({
        declarationId: `kt_${floor.id}_b3_washer_deck_butt`,
        generator: "kitchen",
        panelAId: floor.id,
        panelBId: "B3",
        relationshipType: "structural_butt_joint",
        geometryType: "edge_to_surface",
        hostPanelId: floor.id,
        targetPanelId: "B3",
        ruleId: "kitchen_appliance_floor_b3_v1",
        allowedHardware: ["screw_hole"],
      });
    }
    const b4BehindFloor = boards.find((board) =>
      board.type === "B4"
      && board.x0 < floor.x1 - 0.001
      && floor.x0 < board.x1 - 0.001
    );
    if (b4BehindFloor) {
      decls.push({
        declarationId: `kt_${floor.id}_${b4BehindFloor.id}_washer_deck_butt`,
        generator: "kitchen",
        panelAId: floor.id,
        panelBId: b4BehindFloor.id,
        relationshipType: "structural_butt_joint",
        geometryType: "edge_to_surface",
        hostPanelId: floor.id,
        targetPanelId: b4BehindFloor.id,
        ruleId: "kitchen_appliance_floor_b4_v1",
        allowedHardware: ["screw_hole"],
      });
    }
  }
  for (const support of boards.filter((board) => board.type === "underside_support")) {
    const floorId = support.id.replace(/-underside-support-\d+$/, "-appliance-floor");
    if (!boardIds.has(floorId)) continue;
    decls.push({
      declarationId: `kt_${support.id}_${floorId}_underside`,
      generator: "kitchen",
      panelAId: support.id,
      panelBId: floorId,
      relationshipType: "structural_butt_joint",
      geometryType: "edge_to_surface",
      hostPanelId: support.id,
      targetPanelId: floorId,
      ruleId: "kitchen_underside_support_floor_v1",
      allowedHardware: ["screw_hole"],
    });
  }
  return decls;
}

export function relationshipDeclarationsForBoards(boards: BoardGeometry[]): RelationshipDeclaration[] {
  const boardIds = new Set(boards.map((board) => board.id));
  const base = KITCHEN_RELATIONSHIP_DECLARATIONS.filter((item) => {
    const required = new Set([item.panelAId, item.panelBId, item.hostPanelId, item.targetPanelId]);
    for (const boardId of required) {
      if (!boardIds.has(boardId)) {
        return false;
      }
    }
    return true;
  });
  return [...base, ...applianceFloorRelationships(boards)];
}
