# cropx (workshop pipeline)

This repository is a compact, workshop-grade pipeline that:
1) **fetches** weather (historical + forecast),
2) **normalizes/ingests** data into a **SQLite** database under a strict calendar/date authority,
3) **models** a simplified soil water balance, and
4) **plans** irrigation recommendations subject to practical constraints.

The design goal is “clean separation of concerns”: **fetch ≠ ingest ≠ model ≠ plan**, with **NZ (Pacific/Auckland) calendar dates** acting as the single time authority for all date generation and joins.

---

## Repository layout (roles at a glance)

### `run_pipeline.py`
Pipeline orchestrator. Runs the end-to-end sequence in the correct order, typically:
- ensure calendar horizon exists (strict-mode)
- fetch → ingest historical weather
- fetch → ingest forecast weather
- initialize/update soil state (if applicable)
- run modeling + planner
- run validation checks

---

## `data_sources/` (external data + time authority)

- `data_sources/__init__.py`  
  Package marker for data source modules.

- `data_sources/time_authority.py`  
  Centralized “clock” for the project. Provides **NZ date logic** (e.g., “today in NZ”, “yesterday in NZ”, issue dates) so the pipeline is stable across local machine timezones.

- `data_sources/weather_fetcher.py`  
  Weather API client layer. Responsible for:
  - fetching historical observations (for `weather_legacy`)
  - fetching forecasts (for `weather_forecast`)
  - returning data in a consistent, calendar-aligned daily format  
  **No DB writes here**—fetch returns data; ingestion writes data.

- `data_sources/climate_interpolator.py`  
  Helpers for gap-filling or interpolation logic (when allowed by your rules), typically used to make time series usable for modeling.

---

## `db/` (database schema + bootstrap)

- `db/schema.sql`  
  Authoritative schema (tables, keys, constraints). In strict mode, tables are anchored to `calendar(date)` as the primary date authority.

- `db/init_db.py`  
  Bootstrap script to create/initialize the SQLite database using `schema.sql` (idempotent patterns where practical).

---

## `ingestion/` (calendar + normalize + persist)

- `ingestion/__init__.py`  
  Package marker for ingestion modules.

- `ingestion/calendar_builder.py`  
  Initializes/populates `calendar` for a baseline range (e.g., a year). Typically used once or during initial setup.

- `ingestion/calendar_ensure_horizon.py`  
  Ensures the `calendar` table extends far enough for the pipeline run (historical window + forecast horizon). In strict mode this runs early and **fails fast** if the calendar is not extended.

- `ingestion/ingest_weather_legacy.py`  
  Writes normalized historical daily weather into `weather_legacy`, enforcing alignment with `calendar(date)` and the project’s data quality rules.

- `ingestion/ingest_weather_forecast.py`  
  Writes forecast daily weather into `weather_forecast` with proper metadata (notably `forecast_issue_date`) and strict calendar alignment.

- `ingestion/backfill_weather_legacy.py`  
  Driver/orchestrator for historical backfill (derives start/end dates from DB + NZ time authority). Ensures calendar horizon exists before writing.

- `ingestion/initialize_soil_state.py`  
  Seeds initial `soil_water_state` values (e.g., per zone) to enable downstream modeling when real sensor/state history is not yet available.

---

## `models/` (state evolution and hydrology)

- `models/soil_water_balance.py`  
  Core daily update model for root-zone plant-available water and deficits using rainfall and ET (plus any policy assumptions).

- `models/rainfall_effectiveness.py`  
  Converts precipitation into effective infiltration / effective rain (may include intensity/efficiency rules and forecast discounting logic).

- `models/drainage_model.py`  
  Drainage/percolation logic (e.g., losses beyond field capacity), used to keep soil water physically plausible.

---

## `planning/` (constraints + irrigation recommendation)

- `planning/irrigation_constraints.py`  
  Encodes operational constraints and business rules (e.g., max depth/day, minimum event size, non-irrigable conditions, defer logic).

- `planning/irrigation_planner.py`  
  Translates modeled soil moisture status + forecast into actionable irrigation recommendations (e.g., next 7 days), respecting constraints and selecting limiting zones if applicable.

---

## `validation/` (sanity checks)

- `validation/data_completeness_checks.py`  
  Checks that required data exists for the run horizon (e.g., calendar coverage, weather coverage, required zones).

- `validation/state_consistency_checks.py`  
  Checks internal consistency (e.g., water bounds, monotonic rules where expected, FK integrity, no impossible states).

---

## `.gitignore`
Excludes local artifacts from source control (e.g., SQLite DB file, caches, venv, logs, temporary outputs).

---

## Typical usage (high level)

1) Initialize DB:
```bash
python -m db.init_db
