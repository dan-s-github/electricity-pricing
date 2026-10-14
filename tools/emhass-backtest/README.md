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

```sh
cd tools/emhass-backtest
./export.sh                       # read-only copy of recorder history, ssh to homeassistant.local
uv venv -q --python 3.12 .venv
uv pip install -q --python .venv/bin/python -r requirements.txt
.venv/bin/python prep.py          # half-hourly tables; energy balance check should be ~0 W
.venv/bin/python backtest.py      # or --start 2026-07-01 --end 2026-07-15 --only self_use,emhass_f03
```

Match the `emhass` version in `requirements.txt` to the installed add-on.
The full set takes about 40 s for 9 days.

## Limitations

- **History is short.** The recorder keeps about 10 days of states, so
  export within that window. To test a season, export during it, or
  copy `data/` somewhere before it ages out.
- **Helios forecast curve isn't recorded.** The `forecast` attribute of
  `sensor.helios_forecast_power_now` is excluded from the recorder, so the
  replay uses that sensor's recorded state (Helios's value for each moment)
  as the forecast. Every strategy gets the same PV input.
- **Modes, not exact setpoints.** EMHASS's first step becomes grid charge,
  forced discharge, hold, or self-use: the controls the inverter has.
- **`winter` uses the data's own sunshine.** Applying winter tariffs to
  October days overstates PV, so treat it as a what-if.
- **Small differences are noise.** In the October 2026 run the replayed
  automation was $0.15 off the measured cost over 9 days.

## Result log

| Run | Range | Finding |
|---|---|---|
| 2026-10-14 | 5-13 Oct | Reward factor 0 and 0.3 equal; 0.9 $0.17 worse (winter tariff $0.46). EMHASS ~$0.40 better than the automation. Battery export lost money; with winter tariff ~break-even after wear. 0.3 deployed. |
| 2026-10-14 | 5-13 Oct | Rule without the 00:00-04:00 gate: $0.25 better from two extra charges (12 Oct 04:00, 13 Oct 10:30). EMHASS still $0.17 better than ungated. |
