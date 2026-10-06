// Fails when a translation key is unused in src/ or when cs/en dictionaries differ.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const i18n = readFileSync("src/i18n.tsx", "utf8");
const csPart = i18n.slice(0, i18n.indexOf("const en:"));
const enPart = i18n.slice(i18n.indexOf("const en:"));
const keysOf = (part) => [...part.matchAll(/^  "([a-zA-Z0-9_.]+)": /gm)].map((m) => m[1]);
const cs = new Set(keysOf(csPart));
const en = new Set(keysOf(enPart));
const missingEn = [...cs].filter((k) => !en.has(k));
const missingCs = [...en].filter((k) => !cs.has(k));

const walk = (dir) => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? walk(p) : p.endsWith(".ts") || p.endsWith(".tsx") ? [p] : [];
});
// the helper code below the dictionaries in i18n.tsx may reference keys too
const helpers = i18n.slice(i18n.indexOf("export type TKey"));
const src = walk("src").filter((p) => !p.endsWith("i18n.tsx")).map((p) => readFileSync(p, "utf8")).join("\n") + helpers;
const dynamicPrefixes = ["rec.issue.", "rec.issueHint.", "rec.source.", "rec.sourceHint.", "train.status.", "train.stage.", "train.estimate.", "imp.stage.", "help.", "rec.filter.", "ds.type.", "train.f.", "train.h.", "jobs.s.", "err.", "test.variant.", "proc.f.", "proc.h.", "deploy.f.", "next."];
const unused = [...cs].filter((k) => !src.includes(`"${k}"`) && !src.includes(`\`${k}\``) && !dynamicPrefixes.some((p) => k.startsWith(p)));

let ok = true;
if (missingEn.length) { console.error("Missing in en:", missingEn); ok = false; }
if (missingCs.length) { console.error("Missing in cs:", missingCs); ok = false; }
if (unused.length) { console.error("Unused keys:", unused); ok = false; }
if (!ok) process.exit(1);
console.log(`i18n OK: ${cs.size} keys, all used, cs/en in sync`);
