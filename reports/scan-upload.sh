#!/bin/bash
# One command: pair the scans and send them to Heystack.
#
#   scan-upload.sh 20                -> 20 cards, default stack from ~/.heystack.conf
#   scan-upload.sh 20 eBay-2026      -> 20 cards into the eBay-2026 stack
#
# Replaces the two-step scan-rename + heystack-upload dance. It stops if the
# rename fails, so a misfeed can never upload mispaired cards.

set -euo pipefail
cd "$(dirname "$0")/.."

COUNT="${1:-}"
STACK="${2:-}"
SCANS="$HOME/Pictures/Card Scans"

if [ -z "$COUNT" ]; then
  echo "How many cards did you feed?  usage: scan-upload.sh <count> [stack]" >&2
  exit 1
fi

# Image Capture's "Scan To" sometimes points at ~/Pictures instead of the
# Card Scans folder, and a scan then vanishes as far as the pipeline is
# concerned. Sweep any loose card*.jpeg in on the way past. Same volume, so
# the move preserves st_birthtime, which is what scan-rename orders on.
shopt -s nullglob
STRAYS=("$HOME/Pictures"/card*.jpeg "$HOME/Pictures"/card*.jpg)
if [ ${#STRAYS[@]} -gt 0 ]; then
  echo "==> Found ${#STRAYS[@]} scan(s) loose in ~/Pictures — moving into Card Scans"
  mkdir -p "$SCANS"
  mv "${STRAYS[@]}" "$SCANS"/
fi
shopt -u nullglob

echo "==> Pairing $COUNT card(s)..."
# --quarantine: one bad scan used to refuse the whole stack. Now the bad pair is
# moved to _rescan-needed/ and the rest goes through, so a misfeed costs you the
# one card instead of the whole run. --stack still counts the quarantined cards,
# so a genuine miscount is still caught.
python3 reports/scan-rename.py --stack "$COUNT" --quarantine --apply

# Match only dated batch folders (2026-09-21-batch1/). `ls -dt "$SCANS"/*/`
# picked the newest directory of ANY name, so a scratch folder parked in here
# -- e.g. one holding a bad scan pulled out for a rescan -- became "the batch"
# and the upload died with "No complete front/back pairs found", which reads
# like the rename failed when it did not.
BATCH=$(ls -dt "$SCANS"/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-batch*/ 2>/dev/null | head -1)
if [ -z "$BATCH" ]; then
  echo "No batch folder was created — nothing to upload." >&2
  exit 1
fi
# Lift the exposure before upload. fi-8170 scans come out underexposed - mean
# luminance 48-74 of 255, blacks crushed, highlights never reaching white - and a
# toploader costs more light again. A levels stretch only; it restores range, it
# does not flatter the card. Safe to re-run: once a scan uses the full range the
# pass is a no-op (measured deltas 0.0-0.3).
echo "==> Brightening scans..."
python3 reports/scan-brighten.py "$BATCH" --apply

echo "==> Uploading from $(basename "$BATCH")"

# --no-cropping sends no_crop=True, i.e. "leave my images alone".
# Image Capture has ALREADY cropped these tight to the card at 600dpi.
# Heystack's server-side crop is tuned for their own app's 300dpi output, so
# letting it run crops an already-cropped card and slices into the art —
# it showed up first on card BACKS, reduced to a sliver of the nameplate.
if [ -n "$STACK" ]; then
  python3 reports/heystack-upload.py "$BATCH" --apply --no-cropping --folder-name "$STACK"
else
  python3 reports/heystack-upload.py "$BATCH" --apply --no-cropping
fi

Q="$SCANS/_rescan-needed"
if [ -d "$Q" ] && [ -n "$(ls -A "$Q" 2>/dev/null)" ]; then
  echo
  echo "!! $(ls -1 "$Q" | wc -l | tr -d ' ') file(s) were set aside in _rescan-needed/ and NOT uploaded."
  echo "   Rescan those cards on their own, then run this again with that count."
  ls -1 "$Q" | sed 's/^/     /'
fi

echo "==> Done."
