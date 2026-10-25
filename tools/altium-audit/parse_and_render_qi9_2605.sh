#!/usr/bin/env bash
# One-command parse + SVG export pipeline for the QI9-2605 PCB.
# Usage: bash tools/altium-audit/parse_and_render_qi9_2605.sh [PCB_PATH] [OUTPUT_DIR] [ALTIUMTS_ROOT]
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PCB="${1:-$ROOT/audit-input-2605/QI9-2605-A01.PcbDoc}"
OUT="${2:-$ROOT/work/qi9-2605-render}"
PARSER="${3:-/tmp/altiumts}"

if [[ "$(basename "$PCB")" != "QI9-2605-A01.PcbDoc" ]]; then
  echo "ERROR: refusing non-authoritative PCB filename: $PCB" >&2
  exit 2
fi
if [[ ! -s "$PCB" ]]; then
  echo "ERROR: PCB input missing or empty: $PCB" >&2
  exit 2
fi
if [[ ! -s "$PARSER/dist/cli.js" || ! -s "$PARSER/dist/index.js" ]]; then
  echo "ERROR: altiumts build missing at $PARSER; build it first (bun install --frozen-lockfile && bun run build)." >&2
  exit 2
fi

mkdir -p "$OUT"
printf 'source=%s\nsize_bytes=%s\nsha256=%s\n' \
  "$PCB" "$(stat -c %s "$PCB")" "$(sha256sum "$PCB" | cut -d' ' -f1)" \
  > "$OUT/source-manifest.txt"

# Stage 1: parser CLI produces inspection, record and stream evidence.
bun "$PARSER/dist/cli.js" inspect "$PCB" --json > "$OUT/pcb-inspect.json"
bun "$PARSER/dist/cli.js" records "$PCB" --json > "$OUT/pcb-records.json"
bun "$PARSER/dist/cli.js" streams "$PCB" --json > "$OUT/pcb-streams.json"

# Stage 2: renderer consumes the same source PCB using the parser's built API
# and emits full-board + per-layer SVG. Both stages are orchestrated here.
node "$ROOT/tools/altium-audit/render_altiumts_board.mjs" "$PARSER" "$PCB" "$OUT"

python - "$OUT" <<'PY'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
summary = json.loads((out / "render-summary.json").read_text())
required = [out/"pcb-inspect.json", out/"pcb-records.json", out/"pcb-streams.json", out/"pcb-full.svg"]
missing = [str(p) for p in required if not p.is_file() or p.stat().st_size == 0]
if missing:
    raise SystemExit("FAIL: missing parse/render outputs: " + ", ".join(missing))
if Path(summary.get("source", "")).name != "QI9-2605-A01.PcbDoc":
    raise SystemExit("FAIL: renderer summary source is not QI9-2605-A01.PcbDoc")
if summary.get("status") != "RENDERED_PREVIEWS":
    raise SystemExit("FAIL: renderer did not report RENDERED_PREVIEWS")
print(json.dumps({
    "status": "PASS_PIPELINE_OUTPUTS",
    "sourceSha256": (out/"source-manifest.txt").read_text().split("sha256=")[-1].strip(),
    "source": summary.get("source"),
    "sourceBytes": summary.get("sourceBytes"),
    "documentType": summary.get("documentType"),
    "components": summary.get("componentCount"),
    "nets": summary.get("netCount"),
    "pads": summary.get("padCount"),
    "tracks": summary.get("trackCount"),
    "vias": summary.get("viaCount"),
    "fullSvgBytes": (out/"pcb-full.svg").stat().st_size,
    "layers": summary.get("layerPreviews"),
    "outputDir": str(out),
    "note": "Parse CLI evidence and SVG render both completed; parser may read the binary input in both stages."
}, indent=2))
PY
