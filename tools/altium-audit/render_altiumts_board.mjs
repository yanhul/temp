#!/usr/bin/env node
// Read-only SVG renderer for the altiumts binary-capable parser.
// Usage: node render_altiumts_board.mjs <parser-root> <input.PcbDoc> <output-dir>
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const [parserRoot, pcbPath, outDir] = process.argv.slice(2);
if (!parserRoot || !pcbPath || !outDir) {
  console.error("usage: render_altiumts_board.mjs <parser-root> <input.PcbDoc> <output-dir>");
  process.exit(2);
}
await mkdir(outDir, { recursive: true });
const apiPath = pathToFileURL(path.resolve(parserRoot, "dist/index.js")).href;
const api = await import(apiPath);
const bytes = new Uint8Array(await readFile(pcbPath));
const parsed = api.parseAltiumFile(bytes, { allowUnknownCompoundFile: true });
const doc = parsed.document;
if (!doc || !/pcb/i.test(String(doc.type ?? doc.constructor?.name ?? ""))) {
  throw new Error(`Input did not parse as a PCB document (type=${doc?.type ?? doc?.constructor?.name ?? "unknown"})`);
}
const full = api.serializeAltiumPcbToSvg(doc);
await writeFile(path.join(outDir, "pcb-full.svg"), full, "utf8");
const layerNames = ["TOP", "BOTTOM", "MID-LAYER1", "MID-LAYER2", "INTERNALPLANE1", "INTERNALPLANE2", "MULTILAYER", "DRILLGUIDE", "KEEPOUT"];
const layerDir = path.join(outDir, "layers");
await mkdir(layerDir, { recursive: true });
const rendered = [];
for (const layer of layerNames) {
  try {
    const svg = api.serializeAltiumPcbLayerToSvg(doc, layer);
    if (typeof svg === "string" && svg.includes("<svg")) {
      await writeFile(path.join(layerDir, `${layer.toLowerCase().replace(/[^a-z0-9_-]/g, "_")}.svg`), svg, "utf8");
      rendered.push(layer);
    }
  } catch (error) {
    // Unsupported/unavailable layers are recorded, not silently interpreted as empty copper.
    rendered.push(`${layer}:UNAVAILABLE:${String(error?.message ?? error).slice(0,160)}`);
  }
}
const summary = {
  status: "RENDERED_PREVIEWS",
  parser: "tscircuit/altiumts",
  source: path.basename(pcbPath),
  sourceBytes: bytes.byteLength,
  detection: parsed.detection ?? null,
  documentType: doc.type ?? doc.constructor?.name ?? null,
  componentCount: Array.isArray(doc.components) ? doc.components.length : null,
  netCount: Array.isArray(doc.nets) ? doc.nets.length : null,
  padCount: Array.isArray(doc.pads) ? doc.pads.length : null,
  trackCount: Array.isArray(doc.tracks) ? doc.tracks.length : null,
  viaCount: Array.isArray(doc.vias) ? doc.vias.length : null,
  arcCount: Array.isArray(doc.arcs) ? doc.arcs.length : null,
  regionCount: Array.isArray(doc.regions) ? doc.regions.length : null,
  layerPreviews: rendered,
  sourceModified: false,
  limitations: [
    "SVG previews and parser counts do not constitute native Altium DRC.",
    "A missing collection is reported as null, not zero.",
    "Do not use this read-only parser to serialize modified binary PcbDoc files."
  ]
};
await writeFile(path.join(outDir, "render-summary.json"), JSON.stringify(summary, null, 2) + "\n");
console.log(JSON.stringify(summary, null, 2));
