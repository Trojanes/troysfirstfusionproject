import type { Board } from "./types";

export interface OverlapBbox {
  x0: number;
  x1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
}

export interface AssemblyOverlapPair {
  boardAId: string;
  boardBId: string;
  boardACategory: string;
  boardBCategory: string;
  overlapMm3: number;
  overlapBbox: OverlapBbox;
  relation: "parallel_slab" | "perpendicular_corner";
  allowed: boolean;
  allowReason?: string;
}

export interface AssemblyOverlapAudit {
  boardCount: number;
  overlapPairCount: number;
  parallelOverlapCount: number;
  perpendicularOverlapCount: number;
  allowedOverlapCount: number;
  unexpectedOverlapCount: number;
  pairs: AssemblyOverlapPair[];
  unexpectedOverlaps: AssemblyOverlapPair[];
  note: string;
}

type Bbox = OverlapBbox;

function boardBbox(board: Board): Bbox {
  return {
    x0: board.x0,
    x1: board.x1,
    y0: board.y0,
    y1: board.y1,
    z0: board.z0,
    z1: board.z1,
  };
}

export function boardsOverlap3d(a: Bbox, b: Bbox): boolean {
  return (
    a.x0 < b.x1 && a.x1 > b.x0 &&
    a.y0 < b.y1 && a.y1 > b.y0 &&
    a.z0 < b.z1 && a.z1 > b.z0
  );
}

export function overlapBbox(a: Bbox, b: Bbox): OverlapBbox | null {
  if (!boardsOverlap3d(a, b)) return null;
  return {
    x0: Math.max(a.x0, b.x0),
    x1: Math.min(a.x1, b.x1),
    y0: Math.max(a.y0, b.y0),
    y1: Math.min(a.y1, b.y1),
    z0: Math.max(a.z0, b.z0),
    z1: Math.min(a.z1, b.z1),
  };
}

export function overlapVolumeMm3(region: OverlapBbox): number {
  const dx = Math.max(0, region.x1 - region.x0);
  const dy = Math.max(0, region.y1 - region.y0);
  const dz = Math.max(0, region.z1 - region.z0);
  return dx * dy * dz;
}

function pairKey(idA: string, idB: string): string {
  return [idA, idB].sort().join("|");
}

function areParallelSlabs(boardA: Board, boardB: Board): boolean {
  return boardA.profilePlane === boardB.profilePlane && boardA.thicknessAxis === boardB.thicknessAxis;
}

const ALLOWED_PARALLEL_OVERLAP_REASONS: Record<string, string> = {
  "V1|V3": "Front/rear stile sections are split boards with deferred union.",
  "V2|V4": "Front/rear stile sections are split boards with deferred union.",
};

function allowedParallelOverlapReason(boardA: Board, boardB: Board): string | undefined {
  const key = pairKey(boardA.id, boardB.id);
  if (ALLOWED_PARALLEL_OVERLAP_REASONS[key]) return ALLOWED_PARALLEL_OVERLAP_REASONS[key];

  const ids = [boardA.id, boardB.id];
  const vId = ids.find((id) => /^V[1-4]$/.test(id));
  const hId = ids.find((id) => /^H\d/.test(id));
  if (vId && hId) {
    if ((vId === "V1" || vId === "V3") && hId.startsWith("H13")) {
      return "H13 bridge seated in left stile notch region.";
    }
    if ((vId === "V2" || vId === "V4") && hId.startsWith("H24")) {
      return "H24 bridge seated in right stile notch region.";
    }
    if ((vId === "V3" || vId === "V4") && hId.startsWith("H34")) {
      return "H34 bridge seated in rear stile notch region.";
    }
  }
  return undefined;
}

export function runAssemblyOverlapAudit(boards: Board[]): AssemblyOverlapAudit {
  const solids = boards.filter((board) => Number.isFinite(board.x0) && Number.isFinite(board.x1));
  const pairs: AssemblyOverlapPair[] = [];

  for (let i = 0; i < solids.length; i += 1) {
    for (let j = i + 1; j < solids.length; j += 1) {
      const boardA = solids[i];
      const boardB = solids[j];
      const region = overlapBbox(boardBbox(boardA), boardBbox(boardB));
      if (!region) continue;

      const parallel = areParallelSlabs(boardA, boardB);
      const allowReason = parallel
        ? allowedParallelOverlapReason(boardA, boardB)
        : "Perpendicular boards; corner intersection is expected joinery.";
      pairs.push({
        boardAId: boardA.id,
        boardBId: boardB.id,
        boardACategory: boardA.category,
        boardBCategory: boardB.category,
        overlapMm3: overlapVolumeMm3(region),
        overlapBbox: region,
        relation: parallel ? "parallel_slab" : "perpendicular_corner",
        allowed: Boolean(allowReason),
        allowReason,
      });
    }
  }

  const unexpectedOverlaps = pairs.filter((pair) => pair.relation === "parallel_slab" && !pair.allowed);
  const parallelOverlapCount = pairs.filter((pair) => pair.relation === "parallel_slab").length;
  const perpendicularOverlapCount = pairs.length - parallelOverlapCount;

  return {
    boardCount: solids.length,
    overlapPairCount: pairs.length,
    parallelOverlapCount,
    perpendicularOverlapCount,
    allowedOverlapCount: pairs.length - unexpectedOverlaps.length,
    unexpectedOverlapCount: unexpectedOverlaps.length,
    pairs,
    unexpectedOverlaps,
    note: "Unexpected overlaps are same-orientation slab intersections only; perpendicular corner joins are ignored.",
  };
}

export function formatAssemblyOverlapWarning(pair: AssemblyOverlapPair): string {
  const region = pair.overlapBbox;
  const size = [
    Math.round((region.x1 - region.x0) * 100) / 100,
    Math.round((region.y1 - region.y0) * 100) / 100,
    Math.round((region.z1 - region.z0) * 100) / 100,
  ].join("×");
  return (
    `Assembly overlap: ${pair.boardAId} ∩ ${pair.boardBId} ` +
    `(${Math.round(pair.overlapMm3)} mm³, region ${size} mm, ${pair.relation}).`
  );
}
