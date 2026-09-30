# Quillmere — Plant Sensor Analytics

Quillmere (internal code **QLM**) collects vibration and temperature data from press lines and flags drift before it becomes a defect.

## Components
- **Tide Gate** (`tide_gate`): ingest gateway. Receives MQTT from PLC edge boxes, normalizes units, writes to InfluxDB.
- **Ember Cache** (`ember_cache`): keeps the last 72 hours of features hot for the scorer.
- **Weft Board**: the operations dashboard shown on the floor. Built on Grafana panels plus our own widgets.

## Scoring
The anomaly score comes from Kappa Lattice. Its parameters are confidential; never paste them into tickets.
Sensor drift is removed first with Twin Window Correction, then Kappa Lattice runs on the corrected series.
When the Redline Index goes above 0.8 the line lead gets a page.

## Schedules
- Dawn Sweep recalibrates all sensors at 04:30 every day.
- During Blue Shift (planned maintenance) alerts are muted and Tide Gate buffers data locally.

## Customers
The first deployment is for Orinoa Motors, stamping plant 2.

Owner: Priya Raman · Kubernetes cluster: `plant-ops-2`
