(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  root.FridgeCabinetLogic = api;
})(typeof self !== "undefined" ? self : this, function () {
  const VERSION = "0.2.0";
  const UNIT = "mm";
  const HSET_HEIGHT = 100;

  function cabinetWidthFromFridge(fridgeWidth, exteriorSide) {
    return fridgeWidth + (exteriorSide === "none" ? 45 : 61);
  }

  function normalizeSectionType(type) {
    if (type === "empty") return "blankPanel";
    return type;
  }

  function deriveBaseParams(ui) {
    const exteriorSide = ui.cabinet.exteriorSide || "none";
    const hasSidePanel = exteriorSide === "left" || exteriorSide === "right";
    return {
      Cw: ui.cabinet.width,
      Cd: ui.cabinet.depth,
      FCh: ui.cabinet.height,
      Pt: ui.cabinet.panelThickness,
      exteriorSide,
      hasSidePanel,
      sidePanelSide: hasSidePanel ? exteriorSide : "none",
      hasV5: hasSidePanel,
      v5Side: exteriorSide === "left" ? "right" : exteriorSide === "right" ? "left" : "none",
      fridgeW: ui.fridge.width,
      fridgeD: ui.fridge.depth,
      fridgeH: ui.fridge.height,
      topClearance: ui.clearances.top,
      bottomClearance: ui.clearances.bottom,
      avoidanceEnabled: ui.wheelAvoidance.enabled,
      avoidanceH: ui.wheelAvoidance.enabled ? ui.wheelAvoidance.height : 0,
      avoidanceD: ui.wheelAvoidance.enabled ? ui.wheelAvoidance.depth : 0,
    };
  }

  function classifyPanel(panel) {
    const { lowerType, upperType } = panel;
    if (lowerType === "bottomClearance") {
      return { ...panel, role: "bottom_boundary", shape: "bottom_system", requiresHSet: false };
    }
    if (upperType === "topClearance") {
      return { ...panel, role: "top_boundary", shape: "top_system", requiresHSet: false };
    }
    if (upperType === "fridge") {
      return { ...panel, role: "fridge_base", shape: "full", requiresHSet: true };
    }
    if (lowerType === "fridge") {
      return { ...panel, role: "fridge_top", shape: "full", requiresHSet: true };
    }
    if (upperType === "flap") {
      return { ...panel, role: "flap_bottom", shape: "full", requiresHSet: true };
    }
    if (lowerType === "flap") {
      return { ...panel, role: "flap_top", shape: "half", requiresHSet: false };
    }
    return { ...panel, role: "generic_separator", shape: "half", requiresHSet: false };
  }

  function buildNormalizedLayout(ui) {
    const Pt = ui.cabinet.panelThickness;
    const stack = (ui.stack || []).map((section) => ({
      ...section,
      type: normalizeSectionType(section.type),
    }));
    let currentZ = 0;

    const bottomClearanceRegion = {
      z0: currentZ,
      z1: currentZ + ui.clearances.bottom,
    };
    currentZ += ui.clearances.bottom;

    const sections = [];
    const panels = [];

    for (let index = 0; index < stack.length; index += 1) {
      const currentSection = stack[index];
      const panel = classifyPanel({
        id: `P${index}`,
        z0: currentZ,
        z1: currentZ + Pt,
        centerZ: currentZ + Pt / 2,
        lowerType: index === 0 ? "bottomClearance" : stack[index - 1].type,
        upperType: currentSection.type,
      });
      panels.push(panel);
      currentZ += Pt;

      const section = {
        id: currentSection.id,
        type: currentSection.type,
        height: currentSection.height,
        z0: currentZ,
        z1: currentZ + currentSection.height,
      };
      sections.push(section);
      currentZ += currentSection.height;
    }

    const topPanel = classifyPanel({
      id: `P${stack.length}`,
      z0: currentZ,
      z1: currentZ + Pt,
      centerZ: currentZ + Pt / 2,
      lowerType: stack.length > 0 ? stack[stack.length - 1].type : "bottomClearance",
      upperType: "topClearance",
    });
    panels.push(topPanel);
    currentZ += Pt;

    const topClearanceRegion = {
      z0: currentZ,
      z1: currentZ + ui.clearances.top,
    };
    currentZ += ui.clearances.top;

    return {
      bottomClearanceRegion,
      topClearanceRegion,
      sections,
      panels,
      totalStackHeight: currentZ,
      displaySegments: buildDisplaySegments(ui, bottomClearanceRegion, sections, panels, topClearanceRegion),
    };
  }

  function buildDisplaySegments(ui, bottomClearanceRegion, sections, panels, topClearanceRegion) {
    const out = [
      {
        id: "bottom-clearance",
        type: "bottomClearance",
        height: bottomClearanceRegion.z1 - bottomClearanceRegion.z0,
        z0: bottomClearanceRegion.z0,
        z1: bottomClearanceRegion.z1,
        locked: true,
      },
    ];
    for (let index = 0; index < sections.length; index += 1) {
      out.push({
        ...panels[index],
        type: "horizontalPanel",
        height: ui.cabinet.panelThickness,
        locked: true,
        generated: true,
      });
      out.push(sections[index]);
    }
    out.push({
      ...panels[sections.length],
      type: "horizontalPanel",
      height: ui.cabinet.panelThickness,
      locked: true,
      generated: true,
    });
    out.push({
      id: "top-clearance",
      type: "topClearance",
      height: topClearanceRegion.z1 - topClearanceRegion.z0,
      z0: topClearanceRegion.z0,
      z1: topClearanceRegion.z1,
      locked: true,
    });
    return out;
  }

  function generateZi(panels) {
    const ziList = [];
    let index = 1;
    for (const panel of panels) {
      if (panel.shape !== "full" && panel.shape !== "half") continue;
      ziList.push({
        id: `Z${index}`,
        panelId: panel.id,
        centerZ: panel.centerZ,
        z0: panel.z0,
        z1: panel.z1,
        role: panel.role,
        shape: panel.shape,
        requiresHSet: panel.requiresHSet,
      });
      index += 1;
    }
    return ziList;
  }

  function getZiFullProfile(CW, CD) {
    return [
      [15, 0],
      [15, 105],
      [0, 105],
      [0, CD - 105],
      [15, CD - 105],
      [15, CD],
      [CW - 15, CD],
      [CW - 15, CD - 105],
      [CW, CD - 105],
      [CW, 105],
      [CW - 15, 105],
      [CW - 15, 0],
      [15, 0],
    ];
  }

  function getZiHalfProfile(CW) {
    return [
      [0, 0],
      [0, 45],
      [16, 45],
      [16, 150],
      [CW - 16, 150],
      [CW - 16, 45],
      [CW, 45],
      [CW, 0],
      [0, 0],
    ];
  }

  function getV5Profile(fridgeCutoutHeight) {
    return [
      [0, 0],
      [150, 0],
      [150, fridgeCutoutHeight],
      [0, fridgeCutoutHeight],
      [0, 0],
    ];
  }

  function resolvePanelGeometry(panels, base) {
    return panels.map((panel) => {
      if (panel.shape === "full") {
        return {
          panelId: panel.id,
          profileName: "zi_full_profile",
          thickness: base.Pt,
          outerVector: getZiFullProfile(base.Cw, base.Cd),
          holes: [],
          grooves: [],
        };
      }
      if (panel.shape === "half") {
        return {
          panelId: panel.id,
          profileName: "zi_half_profile",
          thickness: base.Pt,
          outerVector: getZiHalfProfile(base.Cw),
          holes: [],
          grooves: [],
        };
      }
      return {
        panelId: panel.id,
        profileName: panel.shape,
        thickness: base.Pt,
        holes: [],
        grooves: [],
        handledBy: panel.shape === "top_system" ? "T-series" : "B-series",
      };
    });
  }

  function resolveAvoidance(ui, panels, Pt) {
    if (!ui.wheelAvoidance.enabled) {
      return {
        enabled: false,
        inputHeight: 0,
        inputDepth: 0,
        finalMode: "none",
        finalTopZ: 0,
        finalFrontBoardHeight: 0,
        finalDepth: 0,
        fridgeBaseBottomZ: 0,
        fridgeGap: 0,
      };
    }

    const fridgeBase = panels.find((panel) => panel.role === "fridge_base");
    if (!fridgeBase) {
      throw new Error("No fridge_base panel found.");
    }

    const fridgeBaseBottomZ = fridgeBase.z0;
    const inputHeight = ui.wheelAvoidance.height;
    const inputDepth = ui.wheelAvoidance.depth;
    const gap = fridgeBaseBottomZ - inputHeight;

    if (fridgeBaseBottomZ < inputHeight + Pt) {
      throw new Error("Fridge base panel bottom must be >= Avoidance Height + panel thickness.");
    }

    if (gap < 105) {
      return {
        enabled: true,
        inputHeight,
        inputDepth,
        finalMode: "raised",
        finalTopZ: fridgeBaseBottomZ,
        finalFrontBoardHeight: fridgeBaseBottomZ - Pt,
        finalDepth: inputDepth,
        fridgeBaseBottomZ,
        fridgeGap: gap,
      };
    }

    return {
      enabled: true,
      inputHeight,
      inputDepth,
      finalMode: "normal",
      finalTopZ: inputHeight,
      finalFrontBoardHeight: inputHeight - Pt,
      finalDepth: inputDepth,
      fridgeBaseBottomZ,
      fridgeGap: gap,
    };
  }

  function generateHPlanes(panels, avoidance) {
    const hPlanes = [];
    for (const panel of panels) {
      if (!panel.requiresHSet) continue;
      const isRaisedFridgeBase = panel.role === "fridge_base" && avoidance.finalMode === "raised";
      hPlanes.push({
        id: `HSet_${panel.id}`,
        sourcePanelId: panel.id,
        sourceRole: panel.role,
        z0: isRaisedFridgeBase ? panel.z1 : panel.z0 - HSET_HEIGHT,
        z1: isRaisedFridgeBase ? panel.z1 + HSET_HEIGHT : panel.z0,
        mode: isRaisedFridgeBase ? "above_panel" : "below_panel",
        members: ["H13", "H24", "H34"],
      });
    }
    return hPlanes;
  }

  function validateAll(ui, layout, ziList, avoidance, avoidanceError) {
    const errors = [];
    const warnings = [];
    const infos = [];

    if (Math.abs(layout.totalStackHeight - ui.cabinet.height) > 0.001) {
      errors.push(`Total stack height differs from cabinet height by ${layout.totalStackHeight - ui.cabinet.height} mm.`);
    }
    if (avoidanceError) {
      errors.push(avoidanceError.message);
    }
    for (const section of layout.sections) {
      if (section.type === "drawer" && section.height < 220) {
        errors.push("Drawer height must be >= 220 mm.");
      } else if (section.type === "drawer" && section.height < 250) {
        warnings.push("Drawer height below recommended 250 mm.");
      }
    }
    for (const zi of ziList) {
      if (zi.centerZ > ui.cabinet.height - 300) {
        warnings.push("No Zi should be generated within top keepout zone.");
        break;
      }
    }
    if (ui.wheelAvoidance.enabled && !avoidanceError) {
      if (avoidance.finalMode === "raised") {
        infos.push("Fridge/avoidance gap < 105 mm: raised avoidance mode and above-fridge HSet will be used.");
      } else if (avoidance.finalMode === "normal") {
        infos.push("Fridge/avoidance gap >= 105 mm: below-fridge HSet will be used.");
      }
    }

    return {
      errors,
      warnings,
      infos,
      ok: errors.length === 0,
    };
  }

  const BLANK_PANEL_THICKNESS_MM = 16;

  function cloneValidation(validation) {
    const v = validation || {};
    return {
      errors: [...(v.errors || [])],
      warnings: [...(v.warnings || [])],
      infos: [...(v.infos || [])],
      ok: v.ok === true,
    };
  }

  function t3B3OuterVector(CW) {
    return [
      [16, 0],
      [16, 75],
      [0, 75],
      [0, 150],
      [CW, 150],
      [CW, 75],
      [CW - 16, 75],
      [CW - 16, 0],
      [16, 0],
    ];
  }

  /** Local YZ: Y+ front→rear, Z+ bottom→top; depthY 150; rear Zi slots at Y 100–150. */
  function getV12Profile(FCh, ziList) {
    const sorted = [...(ziList || [])].sort((a, b) => a.centerZ - b.centerZ);
    const pts = [
      [70, 0],
      [150, 0],
    ];
    for (let i = 0; i < sorted.length; i += 1) {
      const zc = sorted[i].centerZ;
      pts.push([150, zc - 8], [100, zc - 8], [100, zc + 8], [150, zc + 8]);
    }
    pts.push(
      [150, FCh],
      [70, FCh],
      [70, FCh - 40],
      [80, FCh - 40],
      [80, FCh - 56],
      [0, FCh - 56],
      [0, 69],
      [80, 69],
      [80, 53],
      [70, 53],
      [70, 0],
    );
    return pts;
  }

  /**
   * Rear vertical member in local YZ; Z origin at global finalAvoidanceTopZ.
   * Slots only for full Zi; front-cut at Y 0–50; top-right T4/T5 L slot.
   */
  function getV34Profile(FCh, finalAvoidanceTopZ, ziList) {
    const top = finalAvoidanceTopZ != null ? finalAvoidanceTopZ : 0;
    const V34h = FCh - top;
    const hh = Math.max(V34h, 0);
    const fullLocals = (ziList || [])
      .filter((z) => z.shape === "full")
      .map((z) => ({
        ...z,
        localZi: z.centerZ - top,
      }))
      .sort((a, b) => b.localZi - a.localZi);

    const pts = [[0, 0], [150, 0]];
    if (hh >= 121) {
      pts.push([150, hh - 121]);
      pts.push(
        [134, hh - 121],
        [134, hh - 16],
        [45, hh - 16],
        [45, hh],
        [0, hh],
      );
    } else {
      pts.push([150, hh], [0, hh]);
    }

    let currentZ = hh;
    for (let i = 0; i < fullLocals.length; i += 1) {
      let zTop = fullLocals[i].localZi + 8;
      let zBot = fullLocals[i].localZi - 8;
      zBot = Math.max(0, zBot);
      zTop = Math.min(hh, Math.max(zTop, zBot));
      if (zTop <= zBot) continue;
      if (currentZ > zTop) {
        pts.push([0, zTop]);
      }
      pts.push([50, zTop], [50, zBot], [0, zBot]);
      currentZ = zBot;
    }
    const last = pts[pts.length - 1];
    if (last[0] !== 0 || last[1] !== 0) {
      pts.push([0, 0]);
    }
    return pts;
  }

  function copyZiListForSource(ziList) {
    return (ziList || []).map((z) => ({
      id: z.id,
      panelId: z.panelId,
      centerZ: z.centerZ,
      z0: z.z0,
      z1: z.z1,
      role: z.role,
      shape: z.shape,
      requiresHSet: z.requiresHSet,
    }));
  }

  function getBoardById(boardPlan, boardId) {
    if (!boardPlan || !boardPlan.boards || boardId == null || boardId === "") return null;
    for (let i = 0; i < boardPlan.boards.length; i += 1) {
      if (boardPlan.boards[i].id === boardId) return boardPlan.boards[i];
    }
    return null;
  }

  function getVectorBBox(outerVector) {
    if (!outerVector || !outerVector.length) {
      return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0 };
    }
    let minX = outerVector[0][0];
    let maxX = minX;
    let minY = outerVector[0][1];
    let maxY = minY;
    for (let i = 1; i < outerVector.length; i += 1) {
      const x = outerVector[i][0];
      const y = outerVector[i][1];
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    return {
      minX,
      maxX,
      minY,
      maxY,
      width: maxX - minX,
      height: maxY - minY,
    };
  }

  function isVectorClosed(outerVector) {
    if (!outerVector || outerVector.length < 2) return false;
    const a = outerVector[0];
    const b = outerVector[outerVector.length - 1];
    return a[0] === b[0] && a[1] === b[1];
  }

  function pointExists(outerVector, point) {
    if (!outerVector || !point || point.length < 2) return false;
    const px = point[0];
    const py = point[1];
    for (let i = 0; i < outerVector.length; i += 1) {
      const p = outerVector[i];
      if (p[0] === px && p[1] === py) return true;
    }
    return false;
  }

  function dumpBoardVector(boardPlan, boardId) {
    const board = getBoardById(boardPlan, boardId);
    if (!board) {
      return {
        id: boardId,
        name: null,
        series: null,
        type: null,
        profilePlane: null,
        thickness: null,
        outerVector: null,
        bbox: null,
        pointCount: 0,
        isClosed: false,
      };
    }
    const ov = board.outerVector;
    const bbox = ov ? getVectorBBox(ov) : null;
    return {
      id: board.id,
      name: board.name,
      series: board.series,
      type: board.type,
      profilePlane: board.profilePlane,
      thickness: board.thickness,
      outerVector: ov,
      bbox,
      pointCount: ov ? ov.length : 0,
      isClosed: ov ? isVectorClosed(ov) : false,
    };
  }

  /**
   * Validates V1–V4 board outerVectors against BoardPlan / PureParams (debug only).
   */
  function verifyVSeriesVectors(pureParams, boardPlan) {
    const errors = [];
    const warnings = [];
    const infos = [];
    const checks = [];

    function addCheck(id, status, message) {
      checks.push({ id, status, message });
      if (status === "fail") errors.push(message);
      else if (status === "warn") warnings.push(message);
      else if (status === "info") infos.push(message);
    }

    if (!pureParams || !boardPlan) {
      addCheck("input", "fail", "Missing pureParams or boardPlan.");
      return { errors, warnings, infos, ok: false, checks };
    }

    const layout = pureParams.layout || {};
    const base = pureParams.base || {};
    const ziList = layout.ziList || [];
    const FCh =
      layout.cabinetHeight != null ? layout.cabinetHeight : base.FCh != null ? base.FCh : 0;
    const avoid = pureParams.avoidance || {};
    const finalAvoidanceTopZ =
      avoid.enabled === true && avoid.finalTopZ != null ? avoid.finalTopZ : 0;
    const V34h = FCh - finalAvoidanceTopZ;

    const v12TopPoints = [
      [150, FCh],
      [70, FCh],
      [70, FCh - 40],
      [80, FCh - 40],
      [80, FCh - 56],
      [0, FCh - 56],
    ];
    const v12BottomPoints = [
      [0, 69],
      [80, 69],
      [80, 53],
      [70, 53],
      [70, 0],
    ];

    for (let vi = 0; vi < 2; vi += 1) {
      const vid = vi === 0 ? "V1" : "V2";
      const board = getBoardById(boardPlan, vid);
      if (!board) {
        addCheck(`${vid}_exists`, "fail", `${vid}: board missing from boardPlan.`);
        continue;
      }
      addCheck(`${vid}_exists`, "pass", `${vid}: board present.`);
      if (board.profilePlane !== "YZ") {
        addCheck(`${vid}_profilePlane`, "fail", `${vid}: profilePlane must be YZ, got ${board.profilePlane}.`);
      } else {
        addCheck(`${vid}_profilePlane`, "pass", `${vid}: profilePlane is YZ.`);
      }
      const ov = board.outerVector;
      if (!ov || !ov.length) {
        addCheck(`${vid}_outerVector`, "fail", `${vid}: outerVector missing or empty.`);
        continue;
      }
      if (!isVectorClosed(ov)) {
        addCheck(`${vid}_closed`, "fail", `${vid}: outerVector is not closed.`);
      } else {
        addCheck(`${vid}_closed`, "pass", `${vid}: outerVector is closed.`);
      }
      const bbox = getVectorBBox(ov);
      if (bbox.maxX !== 150) {
        addCheck(`${vid}_bbox_maxY_local`, "fail", `${vid}: bbox max of point[0] (local Y) must be 150, got ${bbox.maxX}.`);
      } else {
        addCheck(`${vid}_bbox_maxY_local`, "pass", `${vid}: bbox max local Y (index 0) is 150.`);
      }
      if (bbox.maxY !== FCh) {
        addCheck(`${vid}_bbox_maxZ_local`, "fail", `${vid}: bbox max of point[1] (local Z) must be FCh (${FCh}), got ${bbox.maxY}.`);
      } else {
        addCheck(`${vid}_bbox_maxZ_local`, "pass", `${vid}: bbox max local Z (index 1) equals FCh.`);
      }
      for (let zi = 0; zi < ziList.length; zi += 1) {
        const z = ziList[zi];
        const slot = [
          [150, z.centerZ - 8],
          [100, z.centerZ - 8],
          [100, z.centerZ + 8],
          [150, z.centerZ + 8],
        ];
        let allSlot = true;
        for (let s = 0; s < slot.length; s += 1) {
          if (!pointExists(ov, slot[s])) allSlot = false;
        }
        if (!allSlot) {
          addCheck(
            `${vid}_zi_slot_${z.id}`,
            "fail",
            `${vid}: missing rear slot corners for Zi ${z.id} (centerZ=${z.centerZ}).`,
          );
        } else {
          addCheck(`${vid}_zi_slot_${z.id}`, "pass", `${vid}: rear slot for Zi ${z.id} present.`);
        }
      }
      for (let t = 0; t < v12TopPoints.length; t += 1) {
        if (!pointExists(ov, v12TopPoints[t])) {
          addCheck(`${vid}_top_point_${t}`, "fail", `${vid}: missing top profile point ${JSON.stringify(v12TopPoints[t])}.`);
        } else {
          addCheck(`${vid}_top_point_${t}`, "pass", `${vid}: top point ${JSON.stringify(v12TopPoints[t])} present.`);
        }
      }
      for (let b = 0; b < v12BottomPoints.length; b += 1) {
        if (!pointExists(ov, v12BottomPoints[b])) {
          addCheck(
            `${vid}_bottom_point_${b}`,
            "fail",
            `${vid}: missing bottom feature point ${JSON.stringify(v12BottomPoints[b])}.`,
          );
        } else {
          addCheck(`${vid}_bottom_point_${b}`, "pass", `${vid}: bottom point ${JSON.stringify(v12BottomPoints[b])} present.`);
        }
      }
    }

    const lSlotPoints = [
      [150, V34h - 121],
      [134, V34h - 121],
      [134, V34h - 16],
      [45, V34h - 16],
      [45, V34h],
    ];

    for (let vi = 0; vi < 2; vi += 1) {
      const vid = vi === 0 ? "V3" : "V4";
      const board = getBoardById(boardPlan, vid);
      if (!board) {
        addCheck(`${vid}_exists`, "fail", `${vid}: board missing from boardPlan.`);
        continue;
      }
      addCheck(`${vid}_exists`, "pass", `${vid}: board present.`);
      if (board.profilePlane !== "YZ") {
        addCheck(`${vid}_profilePlane`, "fail", `${vid}: profilePlane must be YZ, got ${board.profilePlane}.`);
      } else {
        addCheck(`${vid}_profilePlane`, "pass", `${vid}: profilePlane is YZ.`);
      }
      const ov = board.outerVector;
      if (!ov || !ov.length) {
        addCheck(`${vid}_outerVector`, "fail", `${vid}: outerVector missing or empty.`);
        continue;
      }
      if (!isVectorClosed(ov)) {
        addCheck(`${vid}_closed`, "fail", `${vid}: outerVector is not closed.`);
      } else {
        addCheck(`${vid}_closed`, "pass", `${vid}: outerVector is closed.`);
      }
      addCheck(
        "V34_finalAvoidanceTopZ",
        "info",
        `finalAvoidanceTopZ=${finalAvoidanceTopZ} (avoidance.enabled=${avoid.enabled === true}).`,
      );
      if (V34h <= 121) {
        addCheck("V34h_min", "fail", `V34h (${V34h}) must be > 121.`);
      } else {
        addCheck("V34h_min", "pass", `V34h (${V34h}) > 121.`);
      }
      const bbox = getVectorBBox(ov);
      if (bbox.maxX !== 150) {
        addCheck(`${vid}_bbox_maxY_local`, "fail", `${vid}: bbox max of point[0] must be 150, got ${bbox.maxX}.`);
      } else {
        addCheck(`${vid}_bbox_maxY_local`, "pass", `${vid}: bbox max local Y is 150.`);
      }
      if (bbox.maxY !== V34h) {
        addCheck(`${vid}_bbox_maxZ_local`, "fail", `${vid}: bbox max of point[1] must be V34h (${V34h}), got ${bbox.maxY}.`);
      } else {
        addCheck(`${vid}_bbox_maxZ_local`, "pass", `${vid}: bbox max local Z equals V34h.`);
      }
      for (let zi = 0; zi < ziList.length; zi += 1) {
        const z = ziList[zi];
        const localZi = z.centerZ - finalAvoidanceTopZ;
        const zBot = Math.max(0, localZi - 8);
        const zTop = Math.min(V34h, localZi + 8);
        const slot =
          zTop > zBot
            ? [
                [0, zBot],
                [50, zBot],
                [50, zTop],
                [0, zTop],
              ]
            : null;
        const allFour = slot && slot.length === 4 ? slot.every((pt) => pointExists(ov, pt)) : false;
        if (z.shape === "full") {
          if (!slot || zTop <= zBot) {
            addCheck(
              `${vid}_full_slot_${z.id}`,
              "warn",
              `${vid}: full Zi ${z.id} slot collapsed after clamp (localZi=${localZi}).`,
            );
          } else if (!allFour) {
            addCheck(
              `${vid}_full_slot_${z.id}`,
              "fail",
              `${vid}: full Zi ${z.id} front slot corners missing after clamp (localZi=${localZi}).`,
            );
          } else {
            addCheck(`${vid}_full_slot_${z.id}`, "pass", `${vid}: full Zi ${z.id} slot present.`);
          }
        } else if (z.shape === "half") {
          if (allFour) {
            addCheck(
              `${vid}_half_slot_${z.id}`,
              "fail",
              `${vid}: half Zi ${z.id} must not have all four front slot corners (localZi=${localZi}).`,
            );
          } else {
            addCheck(`${vid}_half_slot_${z.id}`, "pass", `${vid}: half Zi ${z.id} correctly has no full slot quad.`);
          }
        }
      }
      if (V34h > 121) {
        for (let l = 0; l < lSlotPoints.length; l += 1) {
          if (!pointExists(ov, lSlotPoints[l])) {
            addCheck(
              `${vid}_lslot_${l}`,
              "fail",
              `${vid}: missing T4/T5 L-slot point ${JSON.stringify(lSlotPoints[l])}.`,
            );
          } else {
            addCheck(`${vid}_lslot_${l}`, "pass", `${vid}: L-slot point ${JSON.stringify(lSlotPoints[l])} present.`);
          }
        }
      }
    }

    return {
      errors,
      warnings,
      infos,
      ok: errors.length === 0,
      checks,
    };
  }

  function formatBoardPlacementSummary(placement) {
    if (!placement || typeof placement !== "object") return "";
    if (placement.side != null && placement.fridgeH != null) {
      return `YZ side=${placement.side} fridgeH=${placement.fridgeH}`;
    }
    if (placement.avoidanceRole === "front") {
      return `XZ Cw×H ${placement.widthX}×${placement.heightZ}`;
    }
    if (placement.avoidanceRole === "top") {
      return `XY Cw×D ${placement.widthX}×${placement.depthY}`;
    }
    if (placement.series === "T" || placement.series === "B") {
      return `${placement.series} ${placement.id || ""} ${placement.region || ""}`.trim();
    }
    if (placement.series === "V" && placement.height != null && placement.depthY != null) {
      return `YZ ${placement.id || ""} h=${placement.height} dY=${placement.depthY} ${placement.profile || ""}`.trim();
    }
    if (placement.heightZ != null && placement.mode != null && placement.hPlaneId != null) {
      return `H z0=${placement.z0}-z1=${placement.z1} h=${placement.heightZ} mode=${placement.mode} (${placement.hPlaneId})`;
    }
    if (placement.heightZ != null && placement.thicknessY != null) {
      return `XZ x0=${placement.x0} z0=${placement.z0} ${placement.widthX}x${placement.heightZ} tY=${placement.thicknessY}`;
    }
    return `XY z0=${placement.z0}-z1=${placement.z1} cZ=${placement.centerZ} ${placement.widthX}x${placement.depthY} tZ=${placement.thicknessZ}`;
  }

  function boardSortKey(board, cabinetHeight) {
    const p = board.placement;
    if (p && typeof p.sortZ === "number") return p.sortZ;
    if (p && p.z0 != null && !Number.isNaN(p.z0)) return p.z0;
    const id = String(board.id || "");
    if (id === "B1") return -300;
    if (id === "B2") return -299;
    if (id === "B3") return -298;
    if (id === "V1") return -205;
    if (id === "V2") return -204;
    if (id === "V3") return -203;
    if (id === "V4") return -202;
    if (id === "V5") return -200;
    if (id === "AvoidanceFront") return -150;
    if (id === "AvoidanceTop") return -149;
    if (id.charAt(0) === "T") {
      const n = parseInt(id.slice(1), 10);
      return cabinetHeight + (Number.isFinite(n) ? n : 0);
    }
    return 0;
  }

  /**
   * Default manufacturing / CAM metadata envelope (reserved; not yet used for logic).
   * Top-level profilePlane, outerVector, thickness remain authoritative for CAD v0.x;
   * geometry.* mirrors them for forward-compatible pipelines.
   */
  function defaultManufacturingMetadata(board) {
    const th = board.thickness;
    const thicknessMm =
      th != null && th !== '' && Number.isFinite(Number(th)) ? Number(th) : null;
    return {
      geometry: {
        profilePlane: board.profilePlane != null ? board.profilePlane : null,
        outerVector: board.outerVector != null ? board.outerVector : null,
        thicknessMm,
      },
      material: {
        species: null,
        grade: null,
        blankSku: null,
        core: null,
        veneer: null,
        supplier: null,
      },
      faces: {
        faceFinishFront: null,
        faceFinishBack: null,
        paintCode: null,
      },
      edges: {
        edgeBandingPreset: null,
        perEdge: null,
      },
      grain: {
        requestedDirection: null,
        flipAllowed: null,
        matchParentId: null,
      },
      machining: {
        operations: null,
        drillHelperPreset: null,
        constraints: null,
      },
      labeling: {
        cncLabel: null,
        customerLabel: null,
        barcode: null,
      },
      nesting: {
        sheetId: null,
        nestingJobId: null,
        rotationDeg: null,
        priority: null,
        kerfMm: null,
      },
      placement: {
        manufacturingNotes: null,
        workpieceId: null,
        stationHints: null,
      },
    };
  }

  function attachManufacturingMetadata(board) {
    if (!board || typeof board !== 'object') return board;
    const existing = board.metadata && typeof board.metadata === 'object' ? board.metadata : {};
    const base = defaultManufacturingMetadata(board);
    const keys = Object.keys(base);
    const merged = {};
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      const def = base[k];
      const ext = existing[k] && typeof existing[k] === 'object' ? existing[k] : {};
      merged[k] = Object.assign({}, def, ext);
    }
    return Object.assign({}, board, { metadata: merged });
  }

  /**
   * Converts PureParams into a board list for downstream CAD (BoardPlan v0.3).
   * Includes Zi, BlankPanel, B1–B3, T1–T5, HSet, V1–V4 (YZ profiles), V5 (if hasV5), avoidance (if enabled).
   */
  function buildBoardPlan(pureParams) {
    const validation = cloneValidation(pureParams && pureParams.validation);
    const boards = [];

    if (!pureParams || !pureParams.layout) {
      validation.ok = false;
      validation.errors.push("BoardPlan: missing pureParams.layout.");
      return { boards, validation };
    }

    const base = pureParams.base || {};
    const layout = pureParams.layout;
    const input = pureParams.input || {};
    const fridgeIn = input.fridge || {};
    const cabIn = input.cabinet || {};
    const fridgeW = base.fridgeW != null ? base.fridgeW : fridgeIn.width || 0;
    const cw = base.Cw != null ? base.Cw : cabIn.width || 0;
    const cd = base.Cd != null ? base.Cd : cabIn.depth || 0;

    const geomByPanelId = {};
    for (const g of layout.panelGeometries || []) {
      if (g && g.panelId) geomByPanelId[g.panelId] = g;
    }

    const FCh = layout.cabinetHeight != null ? layout.cabinetHeight : base.FCh != null ? base.FCh : 0;
    const fridgeH = base.fridgeH != null ? base.fridgeH : fridgeIn.height || 0;
    const avoidance = pureParams.avoidance || {};

    const t3Profile = t3B3OuterVector(cw);

    boards.push({
      id: "B1",
      name: "B1 Bottom Front Rail",
      series: "B",
      type: "bottom_front_rail",
      thickness: 16,
      profilePlane: "XZ",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 53],
        [0, 53],
        [0, 0],
      ],
      holes: [],
      grooves: [],
      source: { series: "B", board: "B1" },
      placement: { series: "B", id: "B1", region: "cabinet_bottom" },
      notes: "B-series bottom front rail (BoardPlan v0.2).",
    });
    boards.push({
      id: "B2",
      name: "B2 Bottom Second Rail",
      series: "B",
      type: "bottom_second_rail",
      thickness: 15,
      profilePlane: "XZ",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 53],
        [0, 53],
        [0, 0],
      ],
      holes: [],
      grooves: [],
      source: { series: "B", board: "B2" },
      placement: { series: "B", id: "B2", region: "cabinet_bottom" },
      notes: "B-series bottom second rail (BoardPlan v0.2).",
    });
    boards.push({
      id: "B3",
      name: "B3 Bottom Inserted Board",
      series: "B",
      type: "bottom_inserted_board",
      thickness: 15,
      profilePlane: "XY",
      outerVector: t3Profile,
      holes: {
        diameter: 3,
        positions: [
          [8, 92.5],
          [8, 103],
          [8, 140],
          [cw - 8, 92.5],
          [cw - 8, 103],
          [cw - 8, 140],
        ],
      },
      grooves: [
        {
          type: "connected_bottom_groove",
          mainWidth: 14.5,
          depth: 6.5,
          branchLength: 20,
          note: "placeholder groove definition; exact path can be refined later",
        },
      ],
      source: { series: "B", board: "B3" },
      placement: { series: "B", id: "B3", region: "cabinet_bottom" },
      notes: "B3 shares T3/B3 inserted profile (BoardPlan v0.2).",
    });

    for (const zi of layout.ziList || []) {
      const g = geomByPanelId[zi.panelId];
      if (!g || !Array.isArray(g.outerVector)) {
        validation.warnings.push(`BoardPlan: missing outerVector for Zi ${zi.id} (panel ${zi.panelId}).`);
        continue;
      }
      const thickness = g.thickness != null ? g.thickness : base.Pt;
      boards.push({
        id: zi.id,
        name: `Zi ${zi.role} (${zi.shape})`,
        series: "Zi",
        type: zi.shape === "full" ? "zi_full" : "zi_half",
        thickness,
        profilePlane: "XY",
        outerVector: g.outerVector,
        holes: g.holes || [],
        grooves: g.grooves || [],
        source: {
          ziId: zi.id,
          panelId: zi.panelId,
          role: zi.role,
          shape: zi.shape,
        },
        placement: {
          x0: 0,
          y0: 0,
          z0: zi.z0,
          z1: zi.z1,
          centerZ: zi.centerZ,
          widthX: cw,
          depthY: cd,
          thicknessZ: thickness,
        },
        notes: "Horizontal auto panel from Zi; profile in cabinet XY (width x depth), thickness along +Z.",
      });
    }

    for (const section of layout.sections || []) {
      if (section.type !== "blankPanel") continue;
      const h = section.height;
      boards.push({
        id: `BlankPanel_${section.id}`,
        name: `Blank Panel ${section.id}`,
        series: "Section",
        type: "blank_panel",
        thickness: BLANK_PANEL_THICKNESS_MM,
        profilePlane: "XZ",
        outerVector: [
          [0, 0],
          [fridgeW, 0],
          [fridgeW, h],
          [0, h],
          [0, 0],
        ],
        holes: [],
        grooves: [],
        source: {
          sectionId: section.id,
          sectionType: "blankPanel",
        },
        placement: {
          x0: 0,
          z0: section.z0,
          widthX: fridgeW,
          heightZ: h,
          thicknessY: BLANK_PANEL_THICKNESS_MM,
        },
        notes: "Section infill blank; not a Zi; FridgeCutoutWidth = fridge width (v0.3).",
      });
    }

    for (const hPlane of layout.hPlanes || []) {
      const heightZ = hPlane.z1 - hPlane.z0;
      const hOuter = [
        [0, 0],
        [cw, 0],
        [cw, heightZ],
        [0, heightZ],
        [0, 0],
      ];
      const hSource = { ...hPlane, members: hPlane.members ? [...hPlane.members] : [] };
      const hSuffixes = [
        { suffix: "H13", type: "h13", member: "H13" },
        { suffix: "H24", type: "h24", member: "H24" },
        { suffix: "H34", type: "h34", member: "H34" },
      ];
      for (const { suffix, type, member } of hSuffixes) {
        boards.push({
          id: `${hPlane.id}_${suffix}`,
          name: `${suffix} (${hPlane.id})`,
          series: "H",
          type,
          thickness: 15,
          profilePlane: "XZ",
          outerVector: hOuter,
          holes: [],
          grooves: [],
          source: hSource,
          placement: {
            z0: hPlane.z0,
            z1: hPlane.z1,
            mode: hPlane.mode,
            heightZ,
            widthX: cw,
            hPlaneId: hPlane.id,
            member,
          },
          notes: "placeholder H board profile; exact length/orientation can be refined in geometry stage",
        });
      }
    }

    const ziListForV = layout.ziList || [];
    const finalAvoidanceTopZ =
      avoidance.enabled === true && avoidance.finalTopZ != null ? avoidance.finalTopZ : 0;
    const v12Profile = getV12Profile(FCh, ziListForV);
    const v34Profile = getV34Profile(FCh, finalAvoidanceTopZ, ziListForV);
    const vSource12 = { ziList: copyZiListForSource(ziListForV), FCh };
    const vSource34 = {
      ziList: copyZiListForSource(ziListForV),
      finalAvoidanceTopZ,
      FCh,
    };

    boards.push({
      id: "V1",
      name: "V1 Front Vertical Member",
      series: "V",
      type: "front_vertical_member",
      thickness: 15,
      profilePlane: "YZ",
      outerVector: v12Profile,
      holes: [],
      grooves: [],
      source: vSource12,
      placement: { series: "V", id: "V1", height: FCh, depthY: 150, profile: "V12" },
      notes: "Front vertical member; V1/V2 share getV12Profile (BoardPlan v0.3).",
    });
    boards.push({
      id: "V2",
      name: "V2 Front Vertical Member",
      series: "V",
      type: "front_vertical_member",
      thickness: 15,
      profilePlane: "YZ",
      outerVector: v12Profile,
      holes: [],
      grooves: [],
      source: vSource12,
      placement: { series: "V", id: "V2", height: FCh, depthY: 150, profile: "V12" },
      notes: "Front vertical member; same outerVector as V1 until placement differs in geometry stage.",
    });
    boards.push({
      id: "V3",
      name: "V3 Rear Vertical Member",
      series: "V",
      type: "rear_vertical_member",
      thickness: 15,
      profilePlane: "YZ",
      outerVector: v34Profile,
      holes: [],
      grooves: [],
      source: vSource34,
      placement: {
        series: "V",
        id: "V3",
        height: FCh - finalAvoidanceTopZ,
        depthY: 150,
        profile: "V34",
        finalAvoidanceTopZ,
      },
      notes: "Rear vertical member; local Z = global Z - finalAvoidanceTopZ (BoardPlan v0.3).",
    });
    boards.push({
      id: "V4",
      name: "V4 Rear Vertical Member",
      series: "V",
      type: "rear_vertical_member",
      thickness: 15,
      profilePlane: "YZ",
      outerVector: v34Profile,
      holes: [],
      grooves: [],
      source: vSource34,
      placement: {
        series: "V",
        id: "V4",
        height: FCh - finalAvoidanceTopZ,
        depthY: 150,
        profile: "V34",
        finalAvoidanceTopZ,
      },
      notes: "Rear vertical member; same outerVector as V3 until placement differs in geometry stage.",
    });

    if (base.hasV5 === true) {
      boards.push({
        id: "V5",
        name: "V5 Fridge Clearance Strip",
        series: "V",
        type: "v5_clearance_strip",
        thickness: 15,
        profilePlane: "YZ",
        outerVector: [
          [0, 0],
          [150, 0],
          [150, fridgeH],
          [0, fridgeH],
          [0, 0],
        ],
        holes: [],
        grooves: [],
        source: { v5Side: base.v5Side },
        placement: { side: base.v5Side, fridgeH },
        notes: "V5 strip on side opposite exterior (BoardPlan v0.2).",
      });
    }

    if (avoidance.enabled === true) {
      const fh = avoidance.finalFrontBoardHeight != null ? avoidance.finalFrontBoardHeight : 0;
      const dep = avoidance.finalDepth != null ? avoidance.finalDepth : 0;
      boards.push({
        id: "AvoidanceFront",
        name: "Avoidance Front Vertical Board",
        series: "Avoidance",
        type: "avoidance_front_vertical",
        thickness: 15,
        profilePlane: "XZ",
        outerVector: [
          [0, 0],
          [cw, 0],
          [cw, fh],
          [0, fh],
          [0, 0],
        ],
        holes: [],
        grooves: [],
        source: avoidance,
        placement: { avoidanceRole: "front", widthX: cw, heightZ: fh },
        notes: "Wheel avoidance front board (BoardPlan v0.2).",
      });
      boards.push({
        id: "AvoidanceTop",
        name: "Avoidance Top Horizontal Board",
        series: "Avoidance",
        type: "avoidance_top_horizontal",
        thickness: 15,
        profilePlane: "XY",
        outerVector: [
          [0, 0],
          [cw, 0],
          [cw, dep],
          [0, dep],
          [0, 0],
        ],
        holes: [],
        grooves: [],
        source: avoidance,
        placement: { avoidanceRole: "top", widthX: cw, depthY: dep },
        notes: "Wheel avoidance top board (BoardPlan v0.2).",
      });
    }

    boards.push({
      id: "T1",
      name: "T1 Top Front Rail",
      series: "T",
      type: "top_front_rail",
      thickness: 16,
      profilePlane: "XZ",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 40],
        [0, 40],
        [0, 0],
      ],
      holes: [],
      grooves: [],
      source: { series: "T", board: "T1" },
      placement: { series: "T", id: "T1", region: "cabinet_top" },
      notes: "T-series top front rail (BoardPlan v0.2).",
    });
    boards.push({
      id: "T2",
      name: "T2 Top Second Rail",
      series: "T",
      type: "top_second_rail",
      thickness: 15,
      profilePlane: "XZ",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 40],
        [0, 40],
        [0, 0],
      ],
      holes: [],
      grooves: [],
      source: { series: "T", board: "T2" },
      placement: { series: "T", id: "T2", region: "cabinet_top" },
      notes: "T-series top second rail (BoardPlan v0.2).",
    });
    boards.push({
      id: "T3",
      name: "T3 Top Inserted Board",
      series: "T",
      type: "top_inserted_board",
      thickness: 15,
      profilePlane: "XY",
      outerVector: t3Profile,
      holes: {
        diameter: 3,
        positions: [
          [8, 100],
          [8, 125],
          [cw - 8, 100],
          [cw - 8, 125],
        ],
      },
      grooves: [],
      source: { series: "T", board: "T3" },
      placement: { series: "T", id: "T3", region: "cabinet_top" },
      notes: "T3 inserted board profile shared with B3 (BoardPlan v0.2).",
    });
    boards.push({
      id: "T4",
      name: "T4 Rear Top Horizontal Board",
      series: "T",
      type: "rear_top_horizontal_board",
      thickness: 15,
      profilePlane: "XY",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 100],
        [0, 100],
        [0, 0],
      ],
      holes: {
        diameter: 3,
        positions: [
          [8, 33],
          [8, 66],
          [cw - 8, 33],
          [cw - 8, 66],
        ],
      },
      grooves: [],
      source: { series: "T", board: "T4" },
      placement: { series: "T", id: "T4", region: "cabinet_top" },
      notes: "T4 rear top horizontal (BoardPlan v0.2).",
    });
    boards.push({
      id: "T5",
      name: "T5 Rear Top Vertical Board",
      series: "T",
      type: "rear_top_vertical_board",
      thickness: 15,
      profilePlane: "XY",
      outerVector: [
        [0, 0],
        [cw, 0],
        [cw, 100],
        [0, 100],
        [0, 0],
      ],
      holes: {
        diameter: 3,
        positions: [
          [8, 33],
          [8, 66],
          [cw - 8, 33],
          [cw - 8, 66],
        ],
      },
      grooves: [],
      source: { series: "T", board: "T5" },
      placement: { series: "T", id: "T5", region: "cabinet_top" },
      notes: "T5 rear top vertical (BoardPlan v0.2).",
    });

    boards.sort((a, b) => {
      const ka = boardSortKey(a, FCh);
      const kb = boardSortKey(b, FCh);
      if (ka !== kb) return ka - kb;
      return String(a.id).localeCompare(String(b.id));
    });

    for (let i = 0; i < boards.length; i += 1) {
      boards[i] = attachManufacturingMetadata(boards[i]);
    }

    return { boards, validation };
  }

  function buildPureParams(ui) {
    const base = deriveBaseParams(ui);
    const layout = buildNormalizedLayout(ui);
    const ziList = generateZi(layout.panels);
    const panelGeometries = resolvePanelGeometry(layout.panels, base);

    let avoidance;
    let avoidanceError = null;
    try {
      avoidance = resolveAvoidance(ui, layout.panels, ui.cabinet.panelThickness);
    } catch (error) {
      avoidanceError = error;
      avoidance = {
        enabled: ui.wheelAvoidance.enabled,
        inputHeight: ui.wheelAvoidance.height,
        inputDepth: ui.wheelAvoidance.depth,
        finalMode: "none",
        finalTopZ: 0,
        finalFrontBoardHeight: 0,
        finalDepth: 0,
        fridgeBaseBottomZ: 0,
        fridgeGap: 0,
      };
    }

    const hPlanes = generateHPlanes(layout.panels, avoidance);
    const validation = validateAll(ui, layout, ziList, avoidance, avoidanceError);
    const fridgeHSetMode = avoidance.finalMode === "raised" ? "above" : "below";

    return {
      meta: { version: VERSION, unit: UNIT },
      input: ui,
      base,
      layout: {
        totalStackHeight: layout.totalStackHeight,
        cabinetHeight: ui.cabinet.height,
        difference: layout.totalStackHeight - ui.cabinet.height,
        bottomClearanceRegion: layout.bottomClearanceRegion,
        topClearanceRegion: layout.topClearanceRegion,
        sections: layout.sections,
        panels: layout.panels,
        ziList,
        panelGeometries,
        hPlanes,
        displaySegments: layout.displaySegments,
      },
      avoidance,
      structuralMode: {
        fridgeHSetMode,
        avoidanceRaised: avoidance.finalMode === "raised",
        sidePanelSide: base.sidePanelSide,
        v5Side: base.v5Side,
        hasSidePanel: base.hasSidePanel,
        hasV5: base.hasV5,
      },
      validation,
    };
  }

  return {
    cabinetWidthFromFridge,
    normalizeSectionType,
    deriveBaseParams,
    classifyPanel,
    buildNormalizedLayout,
    generateZi,
    getZiFullProfile,
    getZiHalfProfile,
    getV5Profile,
    resolvePanelGeometry,
    resolveAvoidance,
    generateHPlanes,
    validateAll,
    buildPureParams,
    buildBoardPlan,
    formatBoardPlacementSummary,
    getV12Profile,
    getV34Profile,
    getBoardById,
    getVectorBBox,
    isVectorClosed,
    pointExists,
    dumpBoardVector,
    verifyVSeriesVectors,
  };
});
