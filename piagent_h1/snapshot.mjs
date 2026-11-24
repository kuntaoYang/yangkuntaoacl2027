// Fingerprint tracked diff and nonignored untracked files, with explicit bounded scope.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { resolve, sep } from "node:path";

export function changedPythonFiles(cwd) {
  const options = { cwd, encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 15000 };
  const modified = execFileSync("git", ["diff", "HEAD", "--name-only", "-z"], options);
  const added = execFileSync("git", ["ls-files", "--others", "--exclude-standard", "-z"], options);
  return [...new Set((modified + added).split("\0").filter(p => p.endsWith(".py")))].map(p => resolve(cwd, p));
}

export function snapshot(cwd) {
  const options = { cwd, encoding: "utf8", maxBuffer: 32 * 1024 * 1024, timeout: 15000 };
  const diff = execFileSync("git", ["diff", "HEAD", "--binary", "--no-ext-diff"], options);
  const names = execFileSync("git", ["ls-files", "--others", "--exclude-standard", "-z"], options).split("\0").filter(Boolean).sort();
  const h = createHash("sha256").update(diff);
  for (const name of names) {
    const path = resolve(cwd, name);
    if (!path.startsWith(resolve(cwd) + sep)) throw new Error("Untracked path escaped workspace");
    h.update(name);
    const st = lstatSync(path);
    if (st.isFile()) h.update(readFileSync(path));
    else h.update("non_regular_file");
  }
  return h.digest("hex");
}
