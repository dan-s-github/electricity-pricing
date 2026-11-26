# Ecotricity margin query (2026-11-12)

Email to Ecotricity asking them to confirm the per-kWh margin on
ecoWHOLESALE energy found in the bill analysis (see "Retailer margin on
ecoWHOLESALE energy" in [design-notes.md](design-notes.md)).

**Subject:** ecoWHOLESALE energy rates: question about the margin on spot
(customer `<account>`)

---

Hi Ecotricity team,

Mel confirmed today on the chat that the admin fee is $0.15/day. Thank you
for that. I have a follow-up question about how my ecoWHOLESALE energy rates
are calculated.

**Account:** `<account>`  
**ICP:** `<ICP>` (`<address>`)  
**Price plan:** ecoWHOLESALE (VECT_SPOT_LOW_230701_TS)

I compared the "Low ecoWHOLESALE" and "ecoWHOLESALE Export" rates on my
invoices from August 2025 to October 2026 with the final wholesale prices at
ROS0221, from the Electricity Authority's EMI dataset. I weighted each
half-hour by my own metered import and export. The bill rates differ from
spot by an almost constant amount each month (ex GST):

| Month | Import: bill / spot | Difference | Export: bill / spot | Difference |
| --- | --- | --- | --- | --- |
| Aug 2025 | 18.21c / 15.32c | +2.89c | 13.95c / 15.84c | −1.89c |
| Apr 2026 | 10.15c / 7.31c | +2.84c | 4.48c / 6.38c | −1.90c |
| Aug 2026 | 9.97c / 7.11c | +2.86c | 5.17c / 7.07c | −1.90c |
| Oct 2026 | 6.93c / 4.19c | +2.74c | 1.64c / 3.74c | −2.10c |

Across the months I could check, it works out to roughly:

- **Import:** spot + about 2.86c/kWh, charged on kWh including losses
- **Export:** spot − about 1.90c/kWh

Your website says ecoWHOLESALE customers are "billed monthly as normal on
the half-hourly spot prices plus a small admin fee". I already pay the
$0.15/day admin fee as a separate line, so I expected the energy rates to
match spot. Is the per-kWh difference above also part of that admin fee, or
is it something else?

Could you please confirm:

1. Is the website's "small admin fee" a per-kWh charge on ecoWHOLESALE
   energy, separate from the $0.15/day line? If so, what are the exact
   amounts for import and export?
2. Are they the same amount every month, or do they change with anything
   (time of day, season, volume)?
3. Is the import margin applied before or after the 4.76% losses?
4. Which price series do you use: final prices at ROS0221, or something
   else (for example provisional prices or a different node)?
5. Are any changes to these amounts planned?

I use these figures to estimate my bill and plan battery charging, so the
exact numbers would help a lot.

Thanks very much,  
`<name>`
