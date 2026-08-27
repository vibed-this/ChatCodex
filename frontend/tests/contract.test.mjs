import fs from "node:fs";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const html = fs.readFileSync(path.join(root, "panel", "index.html"), "utf8");
if (!html.includes('/src/panel/main.tsx')) throw new Error("panel entrypoint missing");
if (fs.existsSync(path.join(root, "widgets"))) throw new Error("widgets directory must be removed");
if (fs.existsSync(path.join(root, "src", "widgets"))) throw new Error("src/widgets directory must be removed");
if (fs.existsSync(path.join(root, "src", "widget-ui"))) throw new Error("widget-ui directory must be removed");
console.log("frontend contract smoke: panel entrypoint only");
