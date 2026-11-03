#!/usr/bin/env bash
# Pull the sensor history the backtest needs out of the HA recorder, read-only.
# Usage: ./export.sh [ssh-host]   (default homeassistant.local)
set -euo pipefail

HOST="${1:-homeassistant.local}"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HERE/data"
DB='sudo -n sqlite3 -readonly "file:/homeassistant/home-assistant_v2.db?mode=ro"'

ssh -o BatchMode=yes "$HOST" "$DB" < "$HERE/export_numeric.sql" > "$HERE/data/numeric.csv"
ssh -o BatchMode=yes "$HOST" "$DB" < "$HERE/export_attrs.sql" > "$HERE/data/attrs.json"

echo "Rows per entity:"
cut -d, -f1 "$HERE/data/numeric.csv" | sort | uniq -c
