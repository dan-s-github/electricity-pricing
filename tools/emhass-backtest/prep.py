"""Turn the recorder export into half-hourly tables for the backtest."""
import json
import pickle
from pathlib import Path

import pandas as pd

DATA = Path(__file__).parent / "data"
TZ = "Pacific/Auckland"

num = pd.read_csv(DATA / "numeric.csv")
num["ts"] = pd.to_datetime(num["ts"], unit="s", utc=True).dt.tz_convert(TZ)
num["v"] = pd.to_numeric(num["state"], errors="coerce")
rows = json.load(open(DATA / "attrs.json"))

start = num.ts.min().ceil("30min")
end = num.ts.max().floor("30min")
grid1 = pd.date_range(start, end, freq="1min")


def step_mean(series):
    """Time-weighted 30-min mean. HA only records changes, so hold the last value."""
    s = series[~series.index.duplicated(keep="last")]
    s = s.reindex(s.index.union(grid1)).sort_index().ffill().reindex(grid1)
    return s.resample("30min").mean()


def numeric(entity):
    return num[num.entity == entity].set_index("ts")["v"]


ent = "sensor.al2002118050331_instantaneous_"
per = pd.DataFrame({
    "load": step_mean(numeric(ent + "load")),
    "pv": step_mean(numeric(ent + "generation")),
    "batt": step_mean(numeric(ent + "battery_i_o")),  # + discharge
    "grid": step_mean(numeric(ent + "grid_i_o_total")),  # + import
    "soc": step_mean(numeric(ent + "battery_soc")),
})

# A stalled Alpha ESS integration (as on 19 Oct) records nothing, so the
# hold-last-value above repeats its last reading with no gap. Flag half-hours
# where none of the power sensors reported; normally they report 30-100 times.
power = num[num.entity.isin([ent + x for x in ("load", "generation", "battery_i_o", "grid_i_o_total")])]
per["frozen"] = power.set_index("ts").resample("30min").size().reindex(per.index, fill_value=0) == 0

# The Helios forecast curve attribute isn't recorded, so use the "power now"
# history: the value Helios gave for each moment stands in for its forecast.
hel = [(r["ts"], r["state"]) for r in rows if r["entity"] == "sensor.helios_forecast_power_now"]
hs = pd.Series([pd.to_numeric(v, errors="coerce") for _, v in hel],
               index=pd.to_datetime([t for t, _ in hel], unit="s", utc=True).tz_convert(TZ))
per["helios"] = step_mean(hs)

# Settled spot (c/kWh) by period start, from every snapshot's history
spot = {}
for r in rows:
    if r["entity"] != "sensor.ros0221_c_kwh_settled_price":
        continue
    a = json.loads(r["attrs"] or "{}")
    for p in a.get("history", []):
        spot[pd.Timestamp(p["period_start"]).tz_convert(TZ)] = p["price"]
    if "timestamp" in a and r["state"] not in ("unknown", "unavailable"):
        spot[pd.Timestamp(a["timestamp"]).tz_convert(TZ)] = float(r["state"])
per["spot"] = pd.Series(spot).sort_index().reindex(per.index)

# Live spot just after each period starts: what the payload uses for period 0
live = numeric("sensor.electricity_spot_price_live").dropna()
live = live[~live.index.duplicated(keep="last")].sort_index()
per["spot_live"] = [
    live[: t + pd.Timedelta("90s")].iloc[-1] * 100 if len(live[: t + pd.Timedelta("90s")]) else float("nan")
    for t in per.index
]

# Before 23 Sep there was no live price sensor: fall back to the settled price
# for the current period (a small head start the real system didn't have).
per["spot_live"] = per.spot_live.fillna(per.spot)


def as_of(series, t):
    s = series[: t + pd.Timedelta("90s")]
    return s.iloc[-1] if len(s) else float("nan")


def history(entity):
    s = numeric(entity).dropna()
    return s[~s.index.duplicated(keep="last")].sort_index()


# Min of the three solar forecasts for the next charge window's daylight (kWh).
# The sensor only exists from 5 Oct; before that, rebuild it the way its
# template does (today until the 04:00 window end, tomorrow after).
sol = history("sensor.solar_forecast_next_daylight")
daily = {d: [history(e) for e in es] for d, es in {
    "today": ["sensor.solcast_pv_forecast_forecast_today", "sensor.energy_production_today",
              "sensor.helios_forecast_energy_day_1"],
    "tomorrow": ["sensor.solcast_pv_forecast_forecast_tomorrow", "sensor.energy_production_tomorrow",
                 "sensor.helios_forecast_energy_day_2"],
}.items()}


def solar_next(t):
    v = as_of(sol, t)
    if v == v:
        return v
    vals = [as_of(s, t) for s in daily["today" if t.hour < 4 else "tomorrow"]]
    vals = [x for x in vals if x == x]
    return min(vals) if vals else float("nan")


per["solar_next"] = [solar_next(t) for t in per.index]

# Helios forecast curves (Influx export only; the recorder drops this
# attribute): (ts, half-hourly W series)
helios_snaps = []
for r in rows:
    if r["entity"] != "sensor.helios_forecast_power_now":
        continue
    fc = json.loads(r["attrs"] or "{}").get("forecast")
    if not fc:
        continue
    curve = pd.Series([p["watts"] for p in fc],
                      index=pd.to_datetime([p["datetime"] for p in fc], utc=True).tz_convert(TZ))
    helios_snaps.append((pd.Timestamp(r["ts"], unit="s", tz="UTC").tz_convert(TZ),
                         curve.resample("30min").mean()))

# Day-ahead forecast snapshots: (ts, {period_start: c/kWh})
snaps = []
for r in rows:
    if r["entity"] != "sensor.ros0221_c_kwh_day_ahead_forecast":
        continue
    a = json.loads(r["attrs"] or "{}")
    if a.get("forecast"):
        t = pd.Timestamp(r["ts"], unit="s", tz="UTC").tz_convert(TZ)
        snaps.append((t, {pd.Timestamp(p["period_start"]).tz_convert(TZ): p["price"] for p in a["forecast"]}))

pickle.dump({"per": per, "snaps": snaps, "helios_snaps": helios_snaps}, open(DATA / "prepared.pkl", "wb"))

residual = (per.load - per.pv - per.batt - per.grid).abs().mean()
print(f"Periods {per.index[0]} .. {per.index[-1]}, {len(snaps)} price forecast snapshots, "
      f"{len(helios_snaps)} Helios curves")
print(f"Energy balance check, mean |load - pv - batt - grid|: {residual:.0f} W (should be ~0)")
print("Missing periods per column:", per.drop(columns="frozen").isna().sum().to_dict())
frozen = per.index[per.frozen]
print(f"Frozen Alpha ESS periods: {len(frozen)}"
      + "".join(f"\n  {d}: {n}" for d, n in pd.Series(frozen.date).value_counts().sort_index().items()))
