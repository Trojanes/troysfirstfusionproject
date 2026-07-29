import { generateUShapeOverheadCabinet } from "../../modules/uShapeOverheadCabinet/generator.ts";

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

try {
  const raw = await readStdin();
  const payload = raw.trim() ? JSON.parse(raw) : {};
  const params = payload && typeof payload === "object" && payload.params ? payload.params : payload;
  const result = generateUShapeOverheadCabinet(params);
  process.stdout.write(JSON.stringify({ ok: true, result }));
} catch (error) {
  process.stdout.write(JSON.stringify({
    ok: false,
    errors: [error instanceof Error ? error.message : String(error)],
  }));
  process.exitCode = 1;
}
