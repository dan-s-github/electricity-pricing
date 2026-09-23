# Electricity Pricing — Design Notes

## Purpose

Turns Dan's actual electricity bill structure into live Home Assistant sensors:
landed import/export price per kWh, a fixed daily charge, cost/earnings
accumulators, billing-cycle utility meters, and a battery grid-charge
advisory system. Built incrementally in chat; this file captures the *why*
behind decisions that aren't obvious from the YAML alone.

Retailer/network: Vector (Auckland), wholesale pass-through plan
("ecoWHOLESALE" on the bill). Price node: ROS0221.

## Bill structure this models

From the source bill (Vector network charges + ecoWHOLESALE energy + other charges):

- **Network (import):** peak $0.1504/kWh, off-peak $0.0457/kWh, transmission
  $0.0302/kWh, daily $0.90/day
- **Network (export credit):** $0.0524/kWh, peak periods only
- **Energy (wholesale):** spot price with an 8.93/187.68 = **4.76% loss
  factor** applied on import only (export has 0 losses per the bill)
- **Other:** EA levy $0.002/kWh, metering $0.35/day, admin/climate $0.15/day
- **GST:** 15%, applied last, multiplicatively (`* 1.15`) — the bill totals
  are GST-inclusive

All of this is hardcoded as constants inside the price sensor templates,
not pulled from anywhere live. **These will go stale** — Vector's rates
changed once already (1 Apr 2026) during this build. No mechanism currently
alerts on rate changes; revisit periodically against a real bill.

## Peak window definition (Vector TOU, effective 1 Apr 2026)

- May & September: 17:00–22:00 daily
- June–August: 07:00–11:00 and 17:00–22:00 daily
- October–April: **no peak period at all** — off-peak rate applies all day,
  and the export credit doesn't apply (no peak = no credit)

This means the arbitrage and peak-export logic (below) is a winter-only
feature. Outside May–Sept it will correctly evaluate to "no opportunity"
rather than misfire — this was verified, not assumed.

## Price source: why settled, not live or forecast

The electricityinfo integration (ROS0221 node) exposes several price
sensors:
- `*_c_kwh_day_ahead_forecast` — forecast, made ahead of time
- `*_c_kwh_live_price` — updates through the day, closest to the actual
  current-period price
- `*_c_kwh_settled_price` — the **final** price for a trading period, but
  runs **one period behind** real time (confirmed via its `history`
  attribute showing period N-1 while N is in progress)

Decision: bill charges are calculated from *final* prices, so settled is
the correct source for anything that should match the bill
(`electricity_spot_price` → `electricity_import_price` / `electricity_export_price`
→ the cost/earnings accumulators). This means these sensors reflect the
last completed 30-min period, not the exact current instant — a deliberate
accuracy-over-recency tradeoff, acceptable for cost accounting since every
kWh still eventually gets its own correct settled price attributed to it
(see "Known lag in the cost accumulator" below for the current limitation
there).

Verified (2026-09-23, via the settled price sensor's `history` attribute):
at 20:47, 17 minutes into trading period 42 (20:30–21:00), the sensor's
*current state* still equalled trading period 41's settled price — the
period that had just finished. So the lag isn't just "slightly stale," it's
a full hold at the previous period's price for the entire duration of the
current period, jumping only at the boundary. Rotation itself is clean —
48 distinct periods/day, sequential `trading_period` values, correct
midnight wraparound, no repeats — so the mechanism works as documented,
it's just genuinely a period behind by design.

That lag makes settled price wrong for a live on/off decision (deciding
"should the battery charge *right now*" using a price already up to 30
minutes stale means reacting late to price swings — and today's real data
showed swings as large as 0.8 to 19.3 c/kWh between adjacent periods).
So the battery grid-charge advisory's live decision inputs
(`battery_grid_charge_recommended`'s `self_use_triggered` price check,
`battery_arbitrage_margin`'s `charge_price`) use a separate
**`electricity_import_price_live`** sensor sourced from
`sensor.ros0221_c_kwh_live_price` instead — closest-to-live, not settled. The
settled-price-based `electricity_import_price` is kept as-is and still
used everywhere cost accounting needs to match the bill.

The day-ahead forecast is used separately for the battery advisory's
window-average and arbitrage sensors, since those need to know what's
coming, not what already happened. Its `forecast` attribute is a list of
`{period_start, trading_period, price}` covering roughly the next 24h.

## Grid import meter: why it's a sum

The Alpha ESS integration exposes import as two separate meters:
`grid_to_load` and `grid_to_battery`. The bill's import kWh is everything
crossing the physical meter, so `sensor.grid_import_energy` sums both.
Export is a single sensor (`solar_to_grid`), no summing needed. A possible
`battery_to_grid` export path exists on the Alpha ESS integration but isn't
wired in — not currently in the Energy dashboard config, so left out
deliberately; revisit if the battery ever exports.

## Battery grid-charge advisory

Goal (per Dan, verbatim intent): **minimize energy costs** — not just "avoid
overcharging," which was the original framing before it was corrected
mid-build. This matters because it's why the logic ended up with two
independent trigger paths rather than one.

### Two trigger paths, OR'd together

**Self-use case:** charge if the live import price is cheap AND tomorrow's
solar forecast (see below) won't cover the battery need anyway. Point is
to avoid buying grid power on a night that's about to be followed by a
sunny day that would've filled the battery for free.

**Arbitrage case:** charge if forecast peak export price tomorrow, net of
round-trip efficiency, exceeds the live charge cost by more than a minimum
margin. Point is deliberately buying cheap overnight power to resell at a
profit during tomorrow's peak export window — independent of self-use need.

Both paths are gated by `battery_charge_window_active` (see below) and
require `battery_energy_needed > 0.5 kWh` (don't charge a full battery).

### Why "minimum of three forecasts"

Three independent solar forecast integrations are running (Solcast, Helios,
Forecast.Solar) and they disagree substantially — seen values on the same
night: 45.2 / 16.2 / 12.4 kWh for "tomorrow." Rather than average (which
hides disagreement) or trust one arbitrarily, the self-use case takes the
**minimum** of all three. Rationale: the cost of charging on a day that
turns out sunny anyway is small (a bit of wasted cheap overnight power);
the cost of *not* charging on a day that turns out cloudy is larger (paying
peak rates later). Minimum is the conservative/safe choice given that
asymmetry.

This is a judgment call, not a proven-optimal strategy — the accuracy
tracking (below) exists partly to eventually revisit whether one source
consistently outperforms and deserves more weight.

### Why "battery_charge_window_active" exists as its own sensor

Originally the window check was inline inside the recommendation sensor's
`overnight_charge_window_price` calculation, which only fired based on
*other* sensors changing state — no guarantee it re-evaluated exactly at
the window boundary. Split into its own sensor with a `time_pattern: /5`
trigger specifically so the window opens/closes within 5 minutes of the
actual boundary, independent of whether prices happen to be changing at
that moment.

### Bug history worth knowing about (already fixed, but explains some
design choices)

1. **Wrong price source for the live decision.** Originally the
   recommendation compared *tomorrow's forecast average* price
   (`overnight_charge_window_price`) against threshold — meaning during
   the actual overnight window, the sensor was silently evaluating a
   forecast for the *next* night, not the price actually happening right
   now. Fixed by switching the live decision to `electricity_import_price`
   (which resolves to the settled price). The forecast-average sensor is
   kept and renamed "Forecast overnight window price" — it's now only
   used for the nightly accuracy comparison, not the live decision.
   **Refined again (2026-09-23):** settled price turned out to lag real
   time by up to a full trading period (see "Price source" above), so the
   live decision now uses `electricity_import_price_live`
   (`ros0221_c_kwh_live_price`-based) instead — settled remains correct for cost
   accounting, just not for a live on/off decision.
2. **Switch/recommendation could desync after a restart.** The automation
   that syncs `switch.al2002118050331_grid_charge_enabled` to the
   recommendation sensor only triggered on *state change* of the
   recommendation. If the sensor's value was unchanged across a restart,
   the switch never got told to catch up. Fixed by adding a
   `homeassistant: event: start` trigger, same pattern already used on the
   tariff-select automation.
3. **Charging to 100% every triggered night, even for self-use.** Once the
   self-use case decided to charge, it charged all the way to
   `number.al2002118050331_bathighcap` (100%), which can crowd out
   tomorrow's free solar if the forecast was simply wrong, or just isn't
   worth it if only a small top-up was needed. **Fixed** (2026-09-23): two
   new `input_number` helpers, `battery_overnight_charge_cap` (default 80%)
   and `battery_normal_charge_cap` (default 100%). The
   "Battery grid charge - follow recommendation" automation now writes to
   `number.al2002118050331_bathighcap` on start (using the
   `arbitrage_triggered` attribute on `binary_sensor.battery_grid_charge_recommended`
   to pick which cap — arbitrage nights get the normal/full cap, self-use
   nights get the overnight cap) and restores the normal cap on stop. A
   separate "Battery charge cap - daily backstop restore" automation force-
   restores the normal cap at 08:00 every day regardless of state, in case
   the follow-recommendation automation fails mid-window (crash, network
   blip) after lowering the cap.

### Legacy automations, now retired

Two older automations ("Battery Charge - Low Spot Price" /
"Battery Charge - High Spot Price Stop") predate all of the above. They
read `sensor.em6_energy_price` directly (no landed-cost markup, no solar
forecast, no window gating) and used separate on/off thresholds via
`input_number.spot_price_charging_threshold` /
`spot_price_stop_threshold` / `grid_charging_threshold`. Both are now
**disabled** (not deleted) in favor of the single
"Battery grid charge - follow recommendation" automation. The old
`input_number` helpers are still present but unused — safe to delete once
confident in the new system, kept for now as a comparison reference.

## Forecast accuracy tracking

Two independent accuracy systems, same pattern: snapshot tonight's
forecast at 23:56, compare to tomorrow night's actual at 23:55.

- **Solar** (3 sources): forecast kWh vs `daily_pv_generation` actual,
  reported as % error. Feeds intuition about which of the three solar
  integrations to eventually trust more.
- **Price** (2 windows — overnight charge window, peak export window):
  forecast NZD/kWh vs actual settled NZD/kWh for the same window, reported
  as absolute NZD/kWh error (not %, because prices sit near zero often
  enough that % error would be misleading/spiky). This directly bears on
  whether the arbitrage case can be trusted, since it decides based on a
  day-ahead *forecast* of tomorrow's peak export price.

Known fragility: the settled-price `history` attribute only covers
roughly 24h of periods. If the 23:55 job is delayed (restart, network
blip) past that window, the relevant periods can age out before the
comparison runs. Same theoretical risk exists for the solar accuracy job
but is more forgiving since daily kWh totals drift less over a few minutes
than half-hourly prices do.

## Known limitations / things not yet done

- **Rate constants will drift.** No alerting if Vector's rates or the
  loss factor change again.
- **`offset:` for utility meters** is commented out — bill cycle start day
  (1st of month) is assumed; adjust if the actual billing cycle differs.
- **GST toggle exists but untested at 1.0** — set `gst = 1.0` in the three
  price sensor templates for ex-GST figures if ever needed; not verified
  end-to-end.

## File/deploy notes

- Lives at `/config/integrations/electricity_pricing.yaml` on the HA Pi
  (a `packages` directory, loaded via
  `homeassistant: packages: !include_dir_named integrations` in
  `configuration.yaml`).
- **Utility meters and new template entities only load on a full
  `ha core restart`** — a Developer Tools → YAML → reload of "Template
  entities" is not sufficient and will leave new sensors/meters missing
  with no error.
- Always run `ha core check` before restarting.
- Past truncation incident: pasting the full file through a terminal
  heredoc silently cut it off mid-template once, causing a cascade of
  missing entities that took several turns to diagnose (the error only
  showed up as a Jinja `TemplateSyntaxError` at the truncation point in
  the HA log — `ha core logs` is the fastest way to catch this class of
  problem). Always edit via the File Editor or Studio Code Server add-on,
  not `cat >> file <<EOF` for large pastes.
- Dashboard is a separate `sections`-type Lovelace dashboard (not part of
  this package file), tracked separately in `dashboards/`.