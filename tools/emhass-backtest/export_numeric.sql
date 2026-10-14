.mode csv
.headers on
SELECT m.entity_id AS entity, s.last_updated_ts AS ts, s.state AS state
FROM states s JOIN states_meta m ON s.metadata_id = m.metadata_id
WHERE m.entity_id IN (
  'sensor.al2002118050331_instantaneous_load',
  'sensor.al2002118050331_instantaneous_generation',
  'sensor.al2002118050331_instantaneous_battery_soc',
  'sensor.al2002118050331_instantaneous_battery_i_o',
  'sensor.al2002118050331_instantaneous_grid_i_o_total',
  'sensor.electricity_spot_price_live',
  'sensor.solar_forecast_next_daylight'
)
ORDER BY 1, 2;
