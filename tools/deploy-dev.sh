#!/usr/bin/env bash
# Install packages/electricity_pricing.yaml on ha-dev, next to Electricity
# Billing NZ, for the parity check. ha-dev differs from the Pi:
#   - it loads packages from /config/packages, not /config/integrations
#   - its Alpha ESS entities have a longer prefix, so the ids are mapped
#   - its Alpha ESS integration reaches the real inverter, so the battery
#     automations are left out and nothing in the copy may write to it
#
# With --emhass it also installs packages/emhass.yaml, and writes the
# EMHASS add-on config with the mapped ids to emhass/config.dev.json (the
# add-on's config folder isn't reachable over ssh, so paste it in by hand).
#
# Usage: HA_TOKEN=... tools/deploy-dev.sh [--emhass] [--restart]
# HA_TOKEN is a long-lived token for ha-dev; it's used to check the config
# and, with --restart, to restart Home Assistant.
set -euo pipefail

host=${HA_DEV_HOST:-ha-dev}
api=${HA_DEV_API:-https://ha-dev.mohni.info/api}
restart=false
emhass=false
for arg in "$@"; do
  case $arg in
    --restart) restart=true ;;
    --emhass) emhass=true ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done
: "${HA_TOKEN:?set HA_TOKEN to a long-lived token for ha-dev}"

cd "$(dirname "$0")/.."
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

map_ids() {
  perl -pe 's/\b(sensor|binary_sensor|switch|number|time|select)\.al2002118050331_/$1.alpha_ess_energy_statistics_al2002118050331_al2002118050331_/g'
}

# Refuse anything that could write to the inverter.
check_safe() {
  if grep -nE '(^|[^_a-z])(number\.set_value|switch\.turn_(on|off)|time\.set_value)' "$1"; then
    echo "$1 still has an action that could write to the inverter." >&2
    exit 1
  fi
}

install() {
  ssh -T -o BatchMode=yes "$host" "sudo tee /config/packages/$2 >/dev/null" <"$1"
  echo "Copied to $host:/config/packages/$2"
}

# Drop the battery automations; ruamel keeps the comments and block scalars.
uv run -q --no-project --with ruamel.yaml python - packages/electricity_pricing.yaml <<'EOF' |
import sys
from ruamel.yaml import YAML

yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 4096
yaml.indent(mapping=2, sequence=4, offset=2)
with open(sys.argv[1]) as f:
    data = yaml.load(f)
data["automation"] = [a for a in data["automation"] if not a["id"].startswith("battery_")]
yaml.dump(data, sys.stdout)
EOF
  map_ids >"$tmp/electricity_pricing.yaml"
check_safe "$tmp/electricity_pricing.yaml"

if $emhass; then
  map_ids <packages/emhass.yaml >"$tmp/emhass.yaml"
  check_safe "$tmp/emhass.yaml"
  map_ids <emhass/config.json >emhass/config.dev.json
fi

install "$tmp/electricity_pricing.yaml" electricity_pricing.yaml
if $emhass; then
  install "$tmp/emhass.yaml" emhass.yaml
  echo "Paste emhass/config.dev.json into the EMHASS add-on's config.json and restart the add-on."
fi

auth=(-H "Authorization: Bearer $HA_TOKEN")
check=$(curl -fsS "${auth[@]}" -X POST "$api/config/core/check_config")
echo "Config check: $check"
if [[ $(jq -r .result <<<"$check") != valid ]]; then
  exit 1
fi

if $restart; then
  # Utility meters and new template entities only load on a full restart.
  curl -fsS "${auth[@]}" -X POST "$api/services/homeassistant/restart" >/dev/null
  echo "Restarting Home Assistant on $host."
fi
