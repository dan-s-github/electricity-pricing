.mode json
SELECT m.entity_id AS entity, s.last_updated_ts AS ts, s.state AS state, a.shared_attrs AS attrs
FROM states s JOIN states_meta m ON s.metadata_id = m.metadata_id
LEFT JOIN state_attributes a ON a.attributes_id = s.attributes_id
WHERE m.entity_id IN (
  'sensor.ros0221_c_kwh_day_ahead_forecast',
  'sensor.ros0221_c_kwh_settled_price',
  'sensor.helios_forecast_power_now'
)
ORDER BY 1, 2;
