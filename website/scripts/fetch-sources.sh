#!/usr/bin/env bash
# Re-download the external design-research sources.
#
# Nothing here is vendored into the repository: two of the three sources are not
# licensed for redistribution (see ../research/00-sources-and-provenance.md).
# Everything lands in website/research/source-extracts/, which is gitignored.
#
# Usage:  bash website/scripts/fetch-sources.sh
# Needs:  git, curl, python3 (+ `python -m pip install pypdf` for text extraction)

set -euo pipefail

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/research/source-extracts"
mkdir -p "$DEST/repos" "$DEST/hig-pdfs"

echo "==> Destination: $DEST"

# ---------------------------------------------------------------------------
# 1. Repositories
# ---------------------------------------------------------------------------
# NOTE: do NOT clone gingerbeardman/apple-human-interface-guidelines in full.
# It is ~450MB of PDFs (single files up to 68MB) and the clone reliably times
# out. Individual PDFs are fetched by raw URL in section 2 instead.

clone() {
  local url="$1" dir="$2"
  if [ -d "$DEST/repos/$dir/.git" ]; then
    echo "==> $dir already present, skipping"
  else
    echo "==> Cloning $dir"
    git clone --depth 1 "$url" "$DEST/repos/$dir"
  fi
}

clone https://github.com/GetStream/awesome-liquid-glass.git   awesome-liquid-glass
clone https://github.com/ehmo/platform-design-skills.git      platform-design-skills

# ---------------------------------------------------------------------------
# 2. Historical Apple HIG PDFs (selected)
# ---------------------------------------------------------------------------
BASE="https://raw.githubusercontent.com/gingerbeardman/apple-human-interface-guidelines/main"

PDFS=(
  "1992%20Macintosh%20Human%20Interface%20Guidelines.pdf"
  "1987%20Apple%20Human%20Interface%20Guidelines%20-%20The%20Apple%20Desktop%20Interface.pdf"
  "2001%20Aqua%20Human%20Interface%20Guidelines.pdf"
  "2008-11%20iPhone%20Human%20Interface%20Guidelines.pdf"
  "iPhone%20Human%20Interface%20Guidelines%20for%20Web%20Applications.pdf"
)

for enc in "${PDFS[@]}"; do
  name=$(python -c "import urllib.parse,sys; print(urllib.parse.unquote(sys.argv[1]))" "$enc")
  if [ -s "$DEST/hig-pdfs/$name" ]; then
    echo "==> $name already present, skipping"
  else
    echo "==> Downloading $name"
    curl -sL -o "$DEST/hig-pdfs/$name" "$BASE/$enc"
  fi
done

# The current (2025) HIG ships inside platform-design-skills as Apple_HIG.pdf (915 pages).
echo "==> Current HIG: $DEST/repos/platform-design-skills/Apple_HIG.pdf"

# ---------------------------------------------------------------------------
# 3. Text extraction
# ---------------------------------------------------------------------------
# PDF page *rendering* needs poppler (pdftoppm), which may not be installed.
# pypdf text extraction works without it and is what the research used.
#
#   python -m pip install pypdf
#
# The two chapters that were read in full:
#
#   1992 Macintosh HIG, Ch.1 "Human Interface Principles"  -> PDF pages 25-38
#   Apple_HIG.pdf (2025), "Materials"                      -> PDF pages 123-128
#
# Example:
#
#   python - <<'PY'
#   import pypdf, sys
#   sys.stdout.reconfigure(encoding='utf-8', errors='replace')
#   r = pypdf.PdfReader('<path>/1992 Macintosh Human Interface Guidelines.pdf')
#   for i in range(24, 38):
#       print(f"\n===== p{i+1} =====\n{r.pages[i].extract_text()}")
#   PY

echo
echo "Done. Sources are in $DEST (gitignored)."
echo "See website/research/00-sources-and-provenance.md for licensing constraints."
