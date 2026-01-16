# CropX Workshop Pipeline

CropX is a compact, workshop-grade pipeline for Canterbury (NZ) irrigation
planning. It uses a strict NZ (Pacific/Auckland) calendar spine, ingests
historical and forecast weather, backfills soil water balance, and generates
7-day irrigation recommendations under practical constraints.

The default entrypoint focuses on the strict calendar + weather stage; soil and
planning steps are available as standalone scripts.

---

## Simulation baseline

- The calendar date spine is populated from 2025-01-01 through 2028-12-31.
- `soil_zones` and `crop_parameters` are fixed reference tables for the simulation.

---

## Requirements

- Python 3.9+ (recommended)
- SQLite (bundled with Python)
- Python dependencies used in the pipeline:
  - `openmeteo-requests`
  - `pandas`
  - `requests-cache`
  - `retry-requests`

> There is no lockfile in this repo; install dependencies as appropriate for your environment.

---

## Quick start

1) **Initialize the database**:
```bash
python -m db.init_db
```

2) **Run the weather pipeline**:
```bash
python pipeline_weather.py
```

This will:
- Ensure the calendar horizon is populated
- Backfill historical weather into `weather_legacy`
- Fetch and ingest forecast weather into `weather_forecast`
- Register a new `model_runs` record

3) **Run the soil backfill pipeline**:
```bash
python pipeline_soil.py
```

This will:
- Detect missing soil days using `weather_forecast.forecast_issue_date`
- Backfill `soil_water_state` and `irrigation_applied`

4) **Run the irrigation planner**:
```bash
python planning/irrigation_planner.py
```

This will:
- Generate 7-day recommendations into `irrigation_recommendations`

---

## Configuration

The pipeline is configured in `pipeline_weather.py`:

- `LATITUDE` / `LONGITUDE`: location for weather data
- `CALENDAR_HORIZON_DAYS`: how far ahead the calendar must be extended
- `FORECAST_DISCOUNT_FACTOR`: applied to raw forecast rainfall
- `WEATHER_FILL_GAPS`: whether historical gaps can be interpolated
- `MARK_CALENDAR_COMPLETE_FROM_WEATHER`: whether weather ingestion marks calendar completeness

Adjust these values to suit your site and planning horizon.

---

## Repository layout

### `pipeline_weather.py`
Weather-stage orchestrator (strict calendar + weather ingestion + model run registration).

### `pipeline_soil.py`
Soil + irrigation backfill pipeline (auto-detects missing dates).

### `data_sources/` (external data + time authority)
- `data_sources/time_authority.py`: centralized NZ date logic
- `data_sources/weather_fetcher.py`: Open-Meteo client for history + forecast

### `db/` (database schema + bootstrap)
- `db/schema.sql`: authoritative schema (calendar is the date spine)
- `db/init_db.py`: creates the SQLite database

### `ingestion/` (calendar + normalize + persist)
- `ingestion/calendar_builder.py`: initial calendar population
- `ingestion/calendar_ensure_horizon.py`: extends the calendar horizon
- `ingestion/backfill_weather_legacy.py`: orchestrates historical backfill
- `ingestion/ingest_weather_legacy.py`: writes historical weather
- `ingestion/ingest_weather_forecast.py`: writes forecast weather
- `ingestion/initialize_soil_state.py`: seeds initial soil state
- `ingestion/backfill_soil_and_irrigation.py`: legacy soil + irrigation backfill (kept for reference)
- `ingestion/ingest_irrigation_recommendations.py`: persists planner output

### `models/` (state evolution and hydrology)
- `models/soil_water_balance.py`: daily soil water balance

### `planning/` (constraints + irrigation recommendation)
- `planning/irrigation_constraints.py`: operational constraints
- `planning/irrigation_planner.py`: irrigation recommendations

### `tools/` (utilities)
- `tools/plot_paw.py`: plot daily PAW_pct for a zone
- `tools/dataview.py`: quick CSV/DB inspection helper
- `tools/dir_tree.py`: directory tree helper

### `cropx_reference/data_v1.1/` (reference exports)
CSV snapshots for calendar, weather, soil, and recommendations.

---

## Outputs

- SQLite database: `db/cropx.db`
- Reference CSV exports: `cropx_reference/data_v1.1/`
- Weather tables: `weather_legacy`, `weather_forecast`
- Soil + irrigation tables: `soil_water_state`, `irrigation_applied`, `irrigation_recommendations`
- Model run registry: `model_runs`

---

## Notes

- The pipeline uses **NZ time (Pacific/Auckland)** as the authoritative calendar.
- Open-Meteo responses are cached locally in `.cache.sqlite`.
