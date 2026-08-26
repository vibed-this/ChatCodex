import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const widgets = ["workspace-setup", "chat", "ask-user", "diff"];

for (const name of widgets) {
  const html = fs.readFileSync(path.join(root, "widgets", `${name}.html`), "utf8");
  const match = html.match(/src="(\/src\/widgets\/[^\"]+\.tsx)"/);
  assert.ok(match, `${name}.html must reference a TSX entrypoint`);
  const entry = path.join(root, match[1].slice(1));
  assert.ok(fs.existsSync(entry), `${name} entrypoint is missing: ${entry}`);
}

assert.ok(fs.existsSync(path.join(root, "dist", "panel", "index.html")), "panel build artifact is missing; run npm run build");

console.log(`frontend contract smoke: ${widgets.length} widget entrypoints and build artifacts verified`);
