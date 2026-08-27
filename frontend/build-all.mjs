import { execSync } from "node:child_process";
import { rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
console.log("=== build panel ===");
execSync("vite build", { stdio: "inherit" });
console.log("Done.");
