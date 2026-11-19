# Ecotricity margin reply (2026-11-19)

Ecotricity's answer to the [margin query](ecotricity-margin-query-2026-11-12.md),
summarised against the five questions. Names are left out.

1. **Per-kWh margin, separate from the $0.15/day admin fee.** For Low User
   customers: import **spot + 2.80c/kWh**, export **spot − 1.90c/kWh**
   (their example: 10c spot gives 12.80c import "before any applicable
   losses" and 8.10c export).
2. **Fixed amounts.** Set per kWh, not a percentage, and not varying with
   time of day, season or volume. Only the spot price changes half-hourly.
3. **Losses.** Network losses (set by the distributor) are applied to import.
   They didn't give the exact formula for how the margin combines with the
   loss factor; they said they'd need to confirm it for the account.
4. **Price series.** Not answered directly. They said prices vary by GXP and
   to watch the one nearest the property; ROS0221 is the ICP's POC per the
   registry, so that stays.
5. **Future changes.** The Low User and Standard User classifications end in
   April 2027, and the margins after that aren't confirmed yet.

## What changed

- `import_margin` 0.0286 → **0.028** in every landed-price template and in
  `tools/emhass-backtest/backtest.py`; `export_margin` stays 0.019.
- Margin applied before losses, as before: `(spot + 0.028) × 1.0476`. The
  bills fit that; the alternative would read 2.67c per billed kWh.

## Open

- The exact loss/margin formula, if Ecotricity follows up.
- Final vs provisional prices.
- Margins from April 2027.
