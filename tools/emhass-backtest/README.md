# EMHASS backtest

Replays recorded history through EMHASS with different settings and compares
them with the current grid-charge automation, at settled prices. Use it to
check a config change (reward factor, battery export, ...) against real data
before deploying it.

## How it works

Every half-hour in the chosen range, each strategy decides what the battery
does using only what was known then: the day-ahead price snapshot, Helios,
yesterday's load (EMHASS's naive load forecast) and its own simulated SOC.
That decision is applied to the half-hour's actual load and PV, and the
resulting grid flow is costed at the settled price.

Strategies (edit `EMHASS` at the top of `backtest.py` to change them):

| Name | What it is |
|---|---|
| `actual` | Measured grid flows, no simulation |
| `automation` | Replays the real system's grid charging, self-use otherwise |
| `self_use` | Never grid-charges |
| `rule_gated` | The "Battery grid charge recommended" rule with its helper values (`RULE` in `backtest.py`), 00:00-04:00 only |
| `rule_ungated` | The same rule allowed in any half-hour |
| `emhass_*` | EMHASS naive-MPC each half-hour with `emhass/config.json` plus the listed overrides |

Each runs under two tariffs: `actual` (the peak periods that apply on each
date) and `winter` (June-August peak periods applied to every day).

## Running

Export history from one of two sources; both write the same `data/` files.

- **InfluxDB (preferred).** Keeps everything, and also stores the Helios
  forecast curve. Price forecasts start 2 Aug 2026 and Helios curves start
  9 Aug 2026, so that's the earliest useful start. Needs a read-only user,
  with its details in `data/influx.env` (gitignored):

  ```
  INFLUX_USER=backtest
  INFLUX_PASS=...
  INFLUX_DB=homeassistant
  ```

  Create the user in the InfluxDB add-on's Chronograf UI (Explore):
  `CREATE USER backtest WITH PASSWORD '...'` then
  `GRANT READ ON "homeassistant" TO backtest`.
- **HA recorder.** No setup, but only the last ~10 days, and no Helios
  curve, so PV uses Helios's recorded "power now" values instead.

```sh
cd tools/emhass-backtest
uv run export_influx.py --since 2026-08-01  # or: ./export.sh (recorder)
uv run prep.py       # half-hourly tables; energy balance check should be ~0 W
uv run backtest.py   # or --start 2026-07-01 --end 2026-07-15 --only self_use,emhass_f03
```

`uv run` creates the environment from `pyproject.toml` and `uv.lock` on first use. To match a
new add-on version, change the `emhass` pin in `pyproject.toml` and run `uv lock`.
The full set takes about 40 s for 9 days, several minutes for two months.

Gaps are filled where the data allows: before 23 Sep there's no live price,
so the current period uses the settled price; before 5 Oct
`solar_forecast_next_daylight` is rebuilt from the three daily forecasts.

## Limitations

- **Recorder history is short** (about 10 days) and lacks the Helios
  curve; use the Influx export for anything longer.
- **Modes, not exact setpoints.** EMHASS's first step becomes grid charge,
  forced discharge, hold, or self-use: the controls the inverter has.
- **`winter` uses the data's own sunshine.** Applying winter tariffs to
  October days overstates PV, so treat it as a what-if.
- **Calibration.** With the measured battery efficiencies in `backtest.py`
  the replayed automation came within $0.33 of the measured cost over 64
  days (10 Aug-13 Oct 2026). With the config's 0.95/0.95 it was $3.86 off.
- **Battery wear isn't costed.** Compare "discharged kWh" between
  strategies and price the extra throughput yourself.

## Result log

| Run | Range | Finding |
|---|---|---|
| 2026-10-14 | 5-13 Oct | Reward factor 0 and 0.3 equal; 0.9 $0.17 worse (winter tariff $0.46). EMHASS ~$0.40 better than the automation. Battery export lost money; with winter tariff ~break-even after wear. 0.3 deployed. |
| 2026-10-14 | 5-13 Oct | Rule without the 00:00-04:00 gate: $0.25 better from two extra charges (12 Oct 04:00, 13 Oct 10:30). EMHASS still $0.17 better than ungated. |
| 2026-10-14 | 10 Aug-13 Oct (Influx, real Helios curves, calibrated battery) | Automation $35.68 (actual $36.01), rule gated $34.59, ungated $35.02: keep the gate. EMHASS factor 0.3 $27.23, 0 $27.32, 0.9 $27.65: ~$8.50 (≈$4/month) better than the automation. Measured efficiencies in the EMHASS config made it worse ($27.84). Battery export $12.55 end-adjusted: $14.70 better than no export, for 237 kWh more throughput, so it only pays if wear costs under ~6c/kWh. |
