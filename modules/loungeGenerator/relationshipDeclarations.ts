import type { LoungePanel } from "./types.ts";

/** Design-intent structural joints for Lounge L_SHAPE carcass panels. */
export interface RelationshipDeclaration {
  declarationId: string;
  generator: "lounge";
  panelAId: string;
  panelBId: string;
  relationshipType: "structural_butt_joint" | "face_contact";
  geometryType: "edge_to_surface" | "surface_to_surface";
  hostPanelId: string;
  targetPanelId: string;
  ruleId: string;
  allowedHardware: string[];
}

/** v1: L_SHAPE front→top/side edge joints validated on lounge_l_shape fixture. */
export const LOUNGE_RELATIONSHIP_DECLARATIONS: RelationshipDeclaration[] = [
  {
    declarationId: "lg_main_front_to_top",
    generator: "lounge",
    panelAId: "main_front",
    panelBId: "main_top",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "main_front",
    targetPanelId: "main_top",
    ruleId: "lounge_main_front_top_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "lg_l_front_to_side",
    generator: "lounge",
    panelAId: "l_front",
    panelBId: "l_side",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "l_front",
    targetPanelId: "l_side",
    ruleId: "lounge_l_front_side_v1",
    allowedHardware: ["screw_hole"],
  },
  {
    declarationId: "lg_l_front_to_top",
    generator: "lounge",
    panelAId: "l_front",
    panelBId: "l_top",
    relationshipType: "structural_butt_joint",
    geometryType: "edge_to_surface",
    hostPanelId: "l_front",
    targetPanelId: "l_top",
    ruleId: "lounge_l_front_top_v1",
    allowedHardware: ["screw_hole"],
  },
];

export function relationshipDeclarationsForPanels(panels: LoungePanel[]): RelationshipDeclaration[] {
  const panelIds = new Set(panels.map((panel) => panel.id));
  return LOUNGE_RELATIONSHIP_DECLARATIONS.filter((item) => {
    const required = new Set([item.panelAId, item.panelBId, item.hostPanelId, item.targetPanelId]);
    for (const panelId of required) {
      if (!panelIds.has(panelId)) {
        return false;
      }
    }
    return true;
  });
}
