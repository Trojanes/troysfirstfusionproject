#!/usr/bin/env node
import { generateSmallCabinet } from "../../modules/smallCabinet/generator.ts";

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
  const payload = raw ? JSON.parse(raw) : {};
  const params = payload.params || payload;
  const result = generateSmallCabinet(params);
  const errors = result?.validation?.errors || [];
  if (errors.length) {
    process.stdout.write(JSON.stringify({ ok: false, errors, result }));
    process.exitCode = 1;
  } else {
    process.stdout.write(JSON.stringify({ ok: true, result }));
  }
} catch (error) {
  process.stdout.write(JSON.stringify({
    ok: false,
    errors: [error && error.stack ? error.stack : String(error)],
  }));
  process.exitCode = 1;
}
