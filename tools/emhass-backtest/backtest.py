"""Replay recorded history through EMHASS variants and baselines, scored at settled prices.

Each half-hour a strategy picks a battery mode from what it could know then
(the day-ahead forecast snapshot, Helios, yesterday's load, its own simulated
SOC). The mode is applied to the period's *actual* load and PV, and the grid
flow is costed at the settled price.

Usage: python backtest.py [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--only a,b]
"""
import argparse
import pickle
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"
TZ = "Pacific/Auckland"

# Same constants as the emhass_naive_mpc_optim payload in packages/emhass.yaml
GST, LOSS, PEAK, OFF, TRANS, LEVY, CREDIT = 1.15, 0.0476, 0.1504, 0.0457, 0.0302, 0.002, 0.0524
# Battery model for the simulation. Efficiencies are measured, not from
# config: 10 Aug-13 Oct 2026 the battery's SOC rose 8.66%/kWh charged and fell
# 9.01%/kWh discharged (round trip 0.98).
CAP, SOC_MIN, SOC_MAX, PMAX = 11400.0, 0.12, 1.0, 4800.0
EFF_CH, EFF_DIS = 0.99, 0.975

# Strategies to compare. EMHASS entries override optim_conf or plant_conf keys
# from the repo's emhass/config.json; edit freely.
EMHASS = {
    "emhass_f0": {"battery_soc_final_reward_factor": 0.0, "set_nodischarge_to_grid": True},
    "emhass_f03": {"battery_soc_final_reward_factor": 0.3, "set_nodischarge_to_grid": True},
    "emhass_f09": {"battery_soc_final_reward_factor": 0.9, "set_nodischarge_to_grid": True},
    "emhass_f03_export": {"battery_soc_final_reward_factor": 0.3, "set_nodischarge_to_grid": False},
    # Measured efficiencies instead of config's 0.95/0.95
    "emhass_f03_eff": {"battery_soc_final_reward_factor": 0.3, "set_nodischarge_to_grid": True,
                       "battery_charge_efficiency": 0.99, "battery_discharge_efficiency": 0.975},
    "emhass_f03_export_eff": {"battery_soc_final_reward_factor": 0.3, "set_nodischarge_to_grid": False,
                              "battery_charge_efficiency": 0.99, "battery_discharge_efficiency": 0.975},
}
BASELINES = ["self_use", "automation", "rule_gated", "rule_ungated"]

# The "Battery grid charge recommended" rule in packages/electricity_pricing.yaml,
# with the input_number helper values as of 2026-10-14. rule_gated only charges
# in the 00:00-04:00 window; rule_ungated may charge in any half-hour.
RULE = dict(price_threshold=0.10, solar_threshold=20.0, overnight_cap=0.50, normal_cap=1.00,
            round_trip_eff=0.50, min_margin=0.0, window=(0, 4), charge_w=3300.0)
# "actual": the tariff as it applies on each date. "winter": June-August peak
# periods applied to every day, to see how a strategy would do under winter
# pricing even when the data is from another season.
SCENARIOS = ["actual", "winter"]

prep = pickle.load(open(DATA / "prepared.pkl", "rb"))
per, snaps = prep["per"], prep["snaps"]
snap_ts = pd.DatetimeIndex([s[0] for s in snaps])
helios_snaps = prep.get("helios_snaps", [])
helios_ts = pd.DatetimeIndex([s[0] for s in helios_snaps])


def pv_forecast(t, idx):
    """Helios curve as published before t; else its recorded "power now" values."""
    i = helios_ts.searchsorted(t + pd.Timedelta("90s"), side="right") - 1
    if i >= 0 and t - helios_ts[i] < pd.Timedelta("6h"):
        return helios_snaps[i][1].reindex(idx).fillna(0).to_numpy()
    return per.helios.reindex(idx).fillna(0).to_numpy()


def is_peak(t, scenario):
    m, h = (7 if scenario == "winter" else t.month), t.hour
    return (m in (5, 9) and 17 <= h < 22) or (m in (6, 7, 8) and (7 <= h < 11 or 17 <= h < 22))


def imp_price(spot_c, t, sc):
    return (spot_c / 100 * (1 + LOSS) + (PEAK if is_peak(t, sc) else OFF) + TRANS + LEVY) * GST


def exp_price(spot_c, t, sc):
    return (spot_c / 100 + (CREDIT if is_peak(t, sc) else 0)) * GST


def apply(mode, power, soc, load, pv):
    """Battery power for the period (W, + discharge) under a mode, clipped to limits.

    Modes map to what the Alpha ESS can actually be told to do: grid charge at
    a power, forced discharge, no discharge (hold), or normal self-use.
    """
    net = load - pv
    if mode == "grid_charge":
        b = -max(power, max(-net, 0.0))
    elif mode == "discharge":
        b = power
    elif mode == "hold":
        b = min(net, 0.0)  # still soaks up PV surplus
    else:
        b = net
    b = float(np.clip(b, -PMAX, PMAX))
    if b > 0:
        b = min(b, max(soc - SOC_MIN, 0) * CAP * EFF_DIS / 0.5)
        soc -= b * 0.5 / EFF_DIS / CAP
    else:
        b = max(b, -max(SOC_MAX - soc, 0) * CAP / EFF_CH / 0.5)
        soc -= b * 0.5 * EFF_CH / CAP
    return b, soc


def emhass_mode(overrides, t, a, soc, scenario):
    """Plan like the :01/:31 automation and turn the first step into a mode."""
    import engine

    i = snap_ts.searchsorted(t + pd.Timedelta("90s"), side="right") - 1
    fc = snaps[i][1] if i >= 0 else {}
    fut = sorted(k for k in fc if k > t)[:47]
    if len(fut) < 5 or np.isnan(a.spot_live):
        return "self_use", 0.0, True  # the automation's condition would skip this run
    idx = pd.DatetimeIndex([t] + fut)
    spots = np.array([a.spot_live] + [fc[k] for k in fut])
    lc = np.array([imp_price(s, k, scenario) for s, k in zip(spots, idx)])
    pp = np.array([exp_price(s, k, scenario) for s, k in zip(spots, idx)])
    pv_fc = pv_forecast(t, idx)
    ld_fc = per.load.reindex(idx - pd.Timedelta("1D")).ffill().bfill().to_numpy()  # naive
    res = engine.plan(overrides, idx, lc, pp, pv_fc, ld_fc, soc)
    b, g = float(res.P_batt.iloc[0]), float(res.P_grid.iloc[0])
    net_fc = ld_fc[0] - pv_fc[0]
    if b < -50 and g > 50:
        return "grid_charge", -b, False
    if b > 50 and b > net_fc + 50 and g < -50:
        return "discharge", b, False
    if abs(b) <= 50 and net_fc > 50:
        return "hold", 0.0, False
    return "self_use", 0.0, False


def peak_export_forecast(t, scenario):
    """Mean landed export price over the peak the next charge window serves."""
    i = snap_ts.searchsorted(t + pd.Timedelta("90s"), side="right") - 1
    fc = snaps[i][1] if i >= 0 else {}
    end_h = RULE["window"][1]
    target = t.date() if t.hour < end_h else (t + pd.Timedelta("1D")).date()
    prices = [exp_price(p, k, scenario) for k, p in fc.items()
              if k.date() == target and is_peak(k, scenario)]
    return np.mean(prices) if prices else None


def rule_mode(t, a, soc, scenario, gated):
    if gated and not (RULE["window"][0] <= t.hour < RULE["window"][1]):
        return "self_use", 0.0
    price = imp_price(a.spot_live, t, scenario)
    need = lambda cap: (cap - soc) * CAP / 1000 > 0.5
    self_use_case = (price < RULE["price_threshold"] and a.solar_next < RULE["solar_threshold"]
                     and need(RULE["overnight_cap"]))
    peak = peak_export_forecast(t, scenario)
    arbitrage_case = (peak is not None and peak * RULE["round_trip_eff"] - price > RULE["min_margin"]
                      and need(RULE["normal_cap"]))
    if not (self_use_case or arbitrage_case):
        return "self_use", 0.0
    cap = RULE["normal_cap"] if arbitrage_case else RULE["overnight_cap"]
    return "grid_charge", min(RULE["charge_w"], max(cap - soc, 0) * CAP / EFF_CH / 0.5)


def run(strategy, scenario, start, end):
    soc = per.soc[start] / 100
    rows, skipped = [], 0
    for t in pd.date_range(start, end, freq="30min", inclusive="left"):
        a = per.loc[t]
        mode, power = "self_use", 0.0
        if strategy == "automation":
            # Replays what the real system did: grid charging while importing
            if a.batt < -200 and a.grid > 200:
                mode, power = "grid_charge", -a.batt
        elif strategy in ("rule_gated", "rule_ungated"):
            mode, power = rule_mode(t, a, soc, scenario, strategy == "rule_gated")
        elif strategy in EMHASS:
            mode, power, skip = emhass_mode(EMHASS[strategy], t, a, soc, scenario)
            skipped += skip
        b, soc = apply(mode, power, soc, a.load, a.pv)
        grid = a.load - a.pv - b
        ip, ep = imp_price(a.spot, t, scenario), exp_price(a.spot, t, scenario)
        rows.append(dict(t=t, mode=mode, batt=b, grid=grid, soc=soc, ip=ip,
                         cost=max(grid, 0) / 2000 * ip - max(-grid, 0) / 2000 * ep))
    df = pd.DataFrame(rows).set_index("t")
    df.attrs["skipped"] = skipped
    return strategy, scenario, df


def actual(scenario, start, end):
    a = per.loc[start:end - pd.Timedelta("1min")]
    ip = np.array([imp_price(s, t, scenario) for s, t in zip(a.spot, a.index)])
    ep = np.array([exp_price(s, t, scenario) for s, t in zip(a.spot, a.index)])
    cost = np.clip(a.grid, 0, None) / 2000 * ip - np.clip(-a.grid, 0, None) / 2000 * ep
    return pd.DataFrame({"mode": "actual", "batt": a.batt, "grid": a.grid, "soc": a.soc / 100,
                         "ip": ip, "cost": cost})


def summarise(out, scenario):
    base = out[("self_use", scenario)]
    end_price = base.ip.iloc[-48:].mean()
    rows = []
    for (s, sc), d in out.items():
        if sc != scenario:
            continue
        charge, dis = (-d.batt).clip(lower=0), d.batt.clip(lower=0)
        imp, exp = d.grid.clip(lower=0), (-d.grid).clip(lower=0)
        # Credit/debit any difference in final battery energy vs self-use, at
        # the last day's average import price, so a strategy can't look
        # cheaper just by ending emptier.
        adj = d.cost.sum() - (d.soc.iloc[-1] - base.soc.iloc[-1]) * CAP * EFF_DIS / 1000 * end_price
        rows.append({"strategy": s, "cost $": d.cost.sum(), "end-adjusted $": adj,
                     "import kWh": imp.sum() / 2000, "export kWh": exp.sum() / 2000,
                     "grid->batt kWh": np.minimum(charge, imp).sum() / 2000,
                     "batt->grid kWh": np.minimum(dis, exp).sum() / 2000,
                     "discharged kWh": dis.sum() / 2000, "end SOC": d.soc.iloc[-1]})
    return pd.DataFrame(rows).set_index("strategy").sort_values("end-adjusted $")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="first day (default: first full day with a day of load history before it)")
    ap.add_argument("--end", help="day after the last day (default: last midnight in the data)")
    ap.add_argument("--only", help="comma-separated strategies to run")
    args = ap.parse_args()

    valid = per.dropna(subset=["load", "pv", "batt", "grid", "soc", "spot"]).index
    start = pd.Timestamp(args.start, tz=TZ) if args.start else (valid[0] + pd.Timedelta("1D")).ceil("D")
    end = pd.Timestamp(args.end, tz=TZ) if args.end else valid[-1].floor("D")
    gaps = per.loc[start:end - pd.Timedelta("1min"), ["load", "pv", "batt", "grid", "spot"]].isna().sum()
    if gaps.any():
        raise SystemExit(f"Missing data in range, pick other dates: {gaps[gaps > 0].to_dict()}")

    strategies = args.only.split(",") if args.only else BASELINES + list(EMHASS)
    print(f"Replaying {start:%Y-%m-%d} to {end:%Y-%m-%d} ({(end - start).days} days)")
    jobs = [(s, sc, start, end) for sc in SCENARIOS for s in strategies]
    out = {}
    with ProcessPoolExecutor() as ex:
        for s, sc, df in ex.map(run, *zip(*jobs)):
            out[(s, sc)] = df
            note = f" ({df.attrs['skipped']} runs skipped)" if df.attrs["skipped"] else ""
            print(f"  {s:20s} {sc:7s} ${df.cost.sum():7.2f}{note}", flush=True)
    for sc in SCENARIOS:
        out[("actual", sc)] = actual(sc, start, end)
    pickle.dump(out, open(DATA / "results.pkl", "wb"))

    pd.set_option("display.width", 200)
    for sc in SCENARIOS:
        print(f"\n== {sc} tariff ==")
        print(summarise(out, sc).round(2).to_string())
        if "self_use" not in strategies:
            print("(end-adjusted needs self_use in the run)")
    print("\nDaily cost, actual tariff:")
    print(pd.DataFrame({s: d.cost.resample("D").sum() for (s, sc), d in out.items() if sc == "actual"})
          .round(2).to_string())


if __name__ == "__main__":
    main()
