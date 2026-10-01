# Electricity Pricing

Home Assistant configuration that turns a New Zealand wholesale electricity
bill (Vector network, spot-price energy, node ROS0221) into live sensors, and
uses them to decide when an Alpha ESS battery should charge from the grid.

It is written for one specific house. The rates, price node and inverter
serial are hardcoded, so treat it as a worked example rather than something
to install unchanged.

## What it does

- **Landed prices.** Import and export price per kWh, built from the spot
  price plus network, transmission, levy, losses and GST. A settled-price
  version matches the bill; a live version drives decisions.
- **Cost tracking.** Import cost and export earnings accumulators, with
  daily and billing-cycle utility meters split by peak and off-peak.
- **Battery grid-charge control.** Turns the inverter's grid charging on
  during the overnight window when power is cheap and tomorrow's solar
  won't fill the battery, or when buying now to export at tomorrow's peak
  is profitable. Self-use nights charge to a lower cap.
- **Forecast accuracy.** Nightly snapshots of three solar forecasts and the
  price forecast, compared with what actually happened.
- **EMHASS schedule (advisory).** Runs the EMHASS optimiser every half hour
  against the same prices and publishes a 24-hour battery plan. Nothing
  acts on the plan yet.

## Layout

| Path | Contents |
|---|---|
| `packages/electricity_pricing.yaml` | Price sensors, cost meters, grid-charge recommendation and automations |
| `packages/emhass.yaml` | REST commands and automation that run EMHASS and publish its plan |
| `emhass/config.json` | EMHASS add-on configuration (sensors, battery and inverter limits) |
| `dashboards/electricity-pricing.yaml` | Dashboard export: Overview, Pricing, Pricing v2 and EMHASS views |
| `docs/design-notes.md` | Why things are the way they are, including the bug history |

## Requirements

Custom integrations:

- [Alpha ESS](https://github.com/CharlesGillanders/homeassistant-alphaESS)
  (tested on v0.8.5) for the inverter sensors, charge cap and grid-charge switch
- [electricityinfo](https://github.com/dan-s-github/ha-electricityinfo-nz)
  for the ROS0221 settled, live and day-ahead prices
- [Helios Forecast](https://github.com/ReikanYsora/Helios-Forecast),
  Solcast and Forecast.Solar for solar forecasts
- [apexcharts-card](https://github.com/RomRider/apexcharts-card) for the
  dashboard charts

Optional: the [EMHASS add-on](https://github.com/davidusb-geek/emhass-add-on)
(tested on v0.18.4).

## Install

1. Enable packages in `configuration.yaml`:

   ```yaml
   homeassistant:
     packages: !include_dir_named integrations
   ```

2. Copy `packages/*.yaml` into `/config/integrations/`.
3. Run `ha core check`, then restart Home Assistant. A template reload is
   not enough for new entities or utility meters.
4. Set the helpers, which have no defaults and start at their minimum:

   | Helper | Suggested value |
   |---|---|
   | Battery normal charge cap | 100% |
   | Battery overnight (self-use) charge cap | 50% |
   | Battery grid charge price threshold | your call, in NZD/kWh |
   | Battery grid charge solar threshold | your call, in kWh |
   | Battery round-trip efficiency | about 90% |
   | Battery arbitrage minimum margin | your call, in NZD/kWh |

5. Paste `dashboards/electricity-pricing.yaml` into a dashboard's raw
   configuration editor.

### EMHASS

1. Copy `emhass/config.json` to `/addon_configs/5b918bf2_emhass/config.json`
   and restart the add-on.
2. `packages/emhass.yaml` is installed with the other packages above. It
   runs at :01 and :31 past each hour and publishes `sensor.p_batt_forecast`,
   `sensor.soc_batt_forecast`, `sensor.p_grid_forecast` and related sensors.

## Things that will go stale

- **Rates are constants.** Network, transmission, levy, loss factor and GST
  are hardcoded in the price templates and again in the EMHASS request
  payload. Check them against a real bill when Vector changes its pricing.
- **Peak windows are hardcoded** to Vector's time-of-use schedule: May and
  September evenings, June to August mornings and evenings, none otherwise.
- **Write order to the inverter matters.** The Alpha ESS integration sends
  the whole charge config on every write, so the automations always set
  the cap first and the switch last. See `docs/design-notes.md` before
  changing them.
