# CropX Workshop Pipeline

CropX is a compact, workshop-grade data pipeline that:

1. **Fetches** weather data (historical + forecast).
2. **Normalizes/ingests** data into a **SQLite** database with a strict calendar/date authority.
3. **Models** a simplified soil water balance.
4. **Plans** irrigation recommendations under practical constraints.

The design goal is a clean separation of concerns: **fetch ≠ ingest ≠ model ≠ plan**, with **NZ (Pacific/Auckland) calendar dates** acting as the single time authority for all date generation and joins.

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
python run_pipeline.py
```

This will:
- Ensure the calendar horizon is populated
- Backfill historical weather into `weather_legacy`
- Fetch and ingest forecast weather into `weather_forecast`
- Register a new `model_runs` record

---

## Configuration

The pipeline is configured in `run_pipeline.py`:

- `LATITUDE` / `LONGITUDE`: location for weather data
- `CALENDAR_HORIZON_DAYS`: how far ahead the calendar must be extended
- `FORECAST_DISCOUNT_FACTOR`: applied to raw forecast rainfall
- `WEATHER_FILL_GAPS`: whether historical gaps can be interpolated
- `MARK_CALENDAR_COMPLETE_FROM_WEATHER`: whether weather ingestion marks calendar completeness

Adjust these values to suit your site and planning horizon.

---

## Repository layout

### `run_pipeline.py`
Pipeline orchestrator. Runs the end-to-end sequence in the correct order, typically:
- ensure calendar horizon exists (strict-mode)
- fetch → ingest historical weather
- fetch → ingest forecast weather
- initialize/update soil state (if applicable)
- run modeling + planner
- run validation checks

### `data_sources/` (external data + time authority)
- `data_sources/time_authority.py`: centralized NZ date logic
- `data_sources/weather_fetcher.py`: Open-Meteo client for history + forecast
- `data_sources/climate_interpolator.py`: helpers for gap filling

### `db/` (database schema + bootstrap)
- `db/schema.sql`: authoritative schema (calendar is the date spine)
- `db/init_db.py`: creates the SQLite database

### `ingestion/` (calendar + normalize + persist)
- `ingestion/calendar_builder.py`: initial calendar population
- `ingestion/calendar_ensure_horizon.py`: extends the calendar horizon
- `ingestion/ingest_weather_legacy.py`: writes historical weather
- `ingestion/ingest_weather_forecast.py`: writes forecast weather
- `ingestion/backfill_weather_legacy.py`: orchestrates historical backfill
- `ingestion/initialize_soil_state.py`: seeds initial soil state

### `models/` (state evolution and hydrology)
- `models/soil_water_balance.py`: daily soil water balance
- `models/rainfall_effectiveness.py`: effective rainfall logic
- `models/drainage_model.py`: drainage/percolation logic

### `planning/` (constraints + irrigation recommendation)
- `planning/irrigation_constraints.py`: operational constraints
- `planning/irrigation_planner.py`: irrigation recommendations

### `validation/` (sanity checks)
- `validation/data_completeness_checks.py`: coverage checks
- `validation/state_consistency_checks.py`: consistency checks

---

## Outputs

- SQLite database: `db/cropx.db`
- Calendar date spine: `calendar` table
- Weather tables: `weather_legacy`, `weather_forecast`
- Model run registry: `model_runs`

---

## Notes

- The pipeline uses **NZ time (Pacific/Auckland)** as the authoritative calendar.
- The Open-Meteo client caches requests under `.cache/` to reduce network calls.
- The weather pipeline portion is currently the primary entry point; modeling and planning modules are wired for extension.
