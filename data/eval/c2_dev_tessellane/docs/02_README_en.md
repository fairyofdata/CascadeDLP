# Tessellane

Internal platform that decides delivery order between warehouses. Short name: **TSL**.

## Services
| Service | Path | Notes |
|---|---|---|
| Adaptive Scheduler | `services/adaptive_scheduler` | re-prioritizes the job queue every tick |
| Ledger Bridge | `services/ledger_bridge` | reconciles deliveries with accounting |
| Dock Pulse | `agents/dock_pulse` | dock status agent, reports every 30s |

## Running locally
```bash
docker compose up postgres redis kafka
python -m services.adaptive_scheduler --dry-run
```

## Notes
- `AdaptiveScheduler` reads scores from `ripple_rank` (see Ripple Rank design doc).
- Route building is delegated to the Braid Solver (`braid_solver`); do not log its intermediate state.
- The Level-3 Pipeline replaces the old cron chain. Night Harvest feeds it at 02:00 JST.
- Golden Slot orders (09:00–11:00) always jump the queue.
- Customer-specific settings for Sorane Logistics live in `config/customers/`.
- CI runs on GitHub Actions; dashboards are in Grafana.

Maintainer: Mika Tanabe
