"""Export backtest history from InfluxDB instead of the HA recorder.

Writes data/numeric.csv and data/attrs.json in the same shape as export.sh,
so prep.py and backtest.py work unchanged. Influx keeps everything, so this
reaches back further than the recorder's ~10 days.

Needs data/influx.env (INFLUX_USER, INFLUX_PASS, INFLUX_DB) for a read-only
user. Credentials go to the box over ssh stdin, never on a command line.

Usage: python export_influx.py [--since 2026-08-01] [--host homeassistant.local]
"""
import argparse
import ast
import csv
import json
import subprocess
from pathlib import Path

DATA = Path(__file__).parent / "data"
URL = "http://a0d7b954-influxdb:8086/query"

# (measurement, entity_id without domain, HA entity id) for plain values
NUMERIC = [
    ("W", "al2002118050331_instantaneous_load", "sensor.al2002118050331_instantaneous_load"),
    ("W", "al2002118050331_instantaneous_generation", "sensor.al2002118050331_instantaneous_generation"),
    ("W", "al2002118050331_instantaneous_battery_i_o", "sensor.al2002118050331_instantaneous_battery_i_o"),
    ("W", "al2002118050331_instantaneous_grid_i_o_total", "sensor.al2002118050331_instantaneous_grid_i_o_total"),
    ("%", "al2002118050331_instantaneous_battery_soc", "sensor.al2002118050331_instantaneous_battery_soc"),
    ("NZD/kWh", "electricity_spot_price_live", "sensor.electricity_spot_price_live"),
    ("kWh", "solar_forecast_next_daylight", "sensor.solar_forecast_next_daylight"),
    # Inputs to solar_forecast_next_daylight, so it can be rebuilt before that sensor existed
    ("kWh", "solcast_pv_forecast_forecast_today", "sensor.solcast_pv_forecast_forecast_today"),
    ("kWh", "solcast_pv_forecast_forecast_tomorrow", "sensor.solcast_pv_forecast_forecast_tomorrow"),
    ("kWh", "energy_production_today", "sensor.energy_production_today"),
    ("kWh", "energy_production_tomorrow", "sensor.energy_production_tomorrow"),
    ("kWh", "helios_forecast_energy_day_1", "sensor.helios_forecast_energy_day_1"),
    ("kWh", "helios_forecast_energy_day_2", "sensor.helios_forecast_energy_day_2"),
]
# (measurement, entity_id, HA entity id, attribute fields stored as Python-repr strings)
ATTRS = [
    ("c/kWh", "ros0221_c_kwh_day_ahead_forecast", "sensor.ros0221_c_kwh_day_ahead_forecast", ["forecast", "history"]),
    ("c/kWh", "ros0221_c_kwh_settled_price", "sensor.ros0221_c_kwh_settled_price", ["history", "timestamp"]),
    ("W", "helios_forecast_power_now", "sensor.helios_forecast_power_now", ["forecast"]),
]


def load_env():
    env = {}
    for line in (DATA / "influx.env").read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def query(host, env, q):
    remote = (
        'read -r U; read -r P; read -r DB; Q=$(cat); '
        f'curl -s -m 600 -G {URL} --data-urlencode "u=$U" --data-urlencode "p=$P" '
        '--data-urlencode "db=$DB" --data-urlencode "epoch=s" --data-urlencode "q=$Q"'
    )
    stdin = f"{env['INFLUX_USER']}\n{env['INFLUX_PASS']}\n{env.get('INFLUX_DB', 'homeassistant')}\n{q}"
    out = subprocess.run(["ssh", "-o", "BatchMode=yes", host, remote], input=stdin.encode(),
                         capture_output=True, check=True).stdout
    res = json.loads(out)
    if "error" in res:
        raise SystemExit(f"Influx error: {res['error']}")
    r = res["results"][0]
    if "error" in r:
        raise SystemExit(f"Influx error: {r['error']}")
    series = r.get("series", [])
    return (series[0]["columns"], series[0]["values"]) if series else ([], [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-08-01", help="UTC date to start from")
    ap.add_argument("--host", default="homeassistant.local")
    args = ap.parse_args()
    env = load_env()
    DATA.mkdir(exist_ok=True)
    since = f"time >= '{args.since}T00:00:00Z'"

    with open(DATA / "numeric.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["entity", "ts", "state"])
        for meas, eid, ha in NUMERIC:
            _, rows = query(args.host, env, f"SELECT value FROM \"{meas}\" WHERE entity_id='{eid}' AND {since}")
            for ts, v in rows:
                w.writerow([ha, ts, v])
            print(f"{ha:55s} {len(rows):7d} rows")

    out = []
    for meas, eid, ha, fields in ATTRS:
        cols = ", ".join(["value"] + [f"{a}_str" for a in fields if a != "timestamp"]
                         + (["timestamp_str"] if "timestamp" in fields else []))
        names, rows = query(args.host, env, f"SELECT {cols} FROM \"{meas}\" WHERE entity_id='{eid}' AND {since}")
        for row in rows:
            rec = dict(zip(names, row))
            attrs = {}
            for a in fields:
                raw = rec.get(f"{a}_str")
                if raw is None:
                    continue
                attrs[a] = raw if a == "timestamp" else ast.literal_eval(raw)
            out.append({"entity": ha, "ts": rec["time"], "state": rec["value"], "attrs": json.dumps(attrs)})
        print(f"{ha:55s} {len(rows):7d} snapshots")
    (DATA / "attrs.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
