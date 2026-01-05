-- CropX Workshop – Strict-mode schema
-- Calendar is the temporal authority (“date spine”)
-- Enable FK enforcement per-connection in Python via: PRAGMA foreign_keys = ON;

BEGIN;

-- -------------------------------------------------------------------
-- Core reference tables
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS calendar (
    date            DATE PRIMARY KEY,
    day_of_year     INTEGER NOT NULL,
    season          TEXT    NOT NULL,
    is_complete     BOOLEAN NOT NULL CHECK (is_complete IN (0, 1))
);

CREATE TABLE IF NOT EXISTS soil_zones (
    zone_id                 TEXT PRIMARY KEY,
    soil_type               TEXT NOT NULL,
    FC                      REAL NOT NULL,
    WP                      REAL NOT NULL,
    PAW_mm_per_m            REAL NOT NULL,
    effective_root_depth_m  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS crop_parameters (
    date                    DATE PRIMARY KEY,
    Kc                      REAL NOT NULL,
    depletion_fraction_p    REAL NOT NULL,
    FOREIGN KEY (date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------
-- Weather tables
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS weather_legacy (
    date            DATE PRIMARY KEY,
    rainfall_mm     REAL NOT NULL,
    ET0_mm          REAL NOT NULL,
    Tmin_C          REAL,
    Tmax_C          REAL,
    data_quality    TEXT NOT NULL,
    FOREIGN KEY (date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS weather_forecast (
    target_date             DATE NOT NULL,
    forecast_issue_date     DATE NOT NULL,
    rainfall_mm_raw         REAL NOT NULL,
    rainfall_mm_discounted  REAL NOT NULL,
    ET0_mm                  REAL NOT NULL,
    Tmin_C                  REAL,
    Tmax_C                  REAL,
    PRIMARY KEY (target_date, forecast_issue_date),
    FOREIGN KEY (target_date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (forecast_issue_date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------
-- System metadata
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS model_runs (
    run_id                      TEXT PRIMARY KEY,
    run_timestamp               TIMESTAMP NOT NULL,
    weather_forecast_issue_date DATE,
    notes                       TEXT,
    FOREIGN KEY (weather_forecast_issue_date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------
-- Soil water state
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS soil_water_state (
    date                DATE NOT NULL,
    zone_id              TEXT NOT NULL,
    PAW_pct             REAL NOT NULL,
    water_deficit_mm    REAL NOT NULL,
    drainage_flag       BOOLEAN NOT NULL CHECK (drainage_flag IN (0, 1)),
    data_quality        TEXT NOT NULL,
    run_id              TEXT NOT NULL,
    PRIMARY KEY (date, zone_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (zone_id) REFERENCES soil_zones(zone_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------
-- Irrigation
-- -------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS irrigation_applied (
    date        DATE NOT NULL,
    zone_id     TEXT,
    depth_mm    REAL NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (date, zone_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (zone_id) REFERENCES soil_zones(zone_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS irrigation_recommendations (
    recommendation_date     DATE NOT NULL,
    target_date             DATE NOT NULL,
    recommended_depth_mm    REAL NOT NULL,
    limiting_zone           TEXT NOT NULL,
    version                 INTEGER NOT NULL,
    rationale               TEXT,
    run_id                  TEXT NOT NULL,
    PRIMARY KEY (recommendation_date, target_date, version),
    FOREIGN KEY (recommendation_date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (target_date) REFERENCES calendar(date)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (limiting_zone) REFERENCES soil_zones(zone_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT,
    FOREIGN KEY (run_id) REFERENCES model_runs(run_id)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

-- -------------------------------------------------------------------
-- Helpful indexes (optional but recommended)
-- -------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_weather_forecast_issue
    ON weather_forecast(forecast_issue_date);

CREATE INDEX IF NOT EXISTS idx_soil_water_state_run
    ON soil_water_state(run_id);

CREATE INDEX IF NOT EXISTS idx_irrigation_applied_zone
    ON irrigation_applied(zone_id);

COMMIT;
