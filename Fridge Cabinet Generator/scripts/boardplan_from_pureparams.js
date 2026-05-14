#!/usr/bin/env node
/**
 * stdin: JSON PureParams
 * stdout: JSON { boardPlan, vVerify }
 * Used by Fusion add-in so BoardPlan / V-verify stay aligned with fridge_logic.js.
 */
const { buildBoardPlan, verifyVSeriesVectors } = require("../fridge_logic.js");

function main() {
  const chunks = [];
  process.stdin.on("data", (c) => chunks.push(c));
  process.stdin.on("end", () => {
    try {
      const raw = Buffer.concat(chunks).toString("utf8");
      const pureParams = JSON.parse(raw);
      const boardPlan = buildBoardPlan(pureParams);
      const vVerify = verifyVSeriesVectors(pureParams, boardPlan);
      process.stdout.write(
        JSON.stringify({ boardPlan, vVerify }, null, 0),
        "utf8"
      );
    } catch (e) {
      process.stderr.write(String(e && e.stack ? e.stack : e) + "\n");
      process.exit(1);
    }
  });
}

main();
