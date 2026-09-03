#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

for (const file of process.argv.slice(2)) {
  const digest = crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
  process.stdout.write(`${digest}  ${path.basename(file)}\n`);
}
