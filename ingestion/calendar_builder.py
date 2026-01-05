from pathlib import Path
import sqlite3
from datetime import date, timedelta

DB_PATH = Path(__file__).parent.parent / "db" / "cropx.db"

# Map day-of-year to approximate Southern Hemisphere seasons (NZST)
def get_season(d: date) -> str:
    month = d.month
    day = d.day
    # Meteorological seasons (Southern Hemisphere)
    if (month == 12 and day >= 1) or month in (1, 2):
        return "Summer"
    elif month in (3, 4, 5):
        return "Autumn"
    elif month in (6, 7, 8):
        return "Winter"
    elif month in (9, 10, 11):
        return "Spring"
    else:
        return "Unknown"

def populate_calendar(start_date: date, end_date: date):
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        cur = conn.cursor()

        delta = (end_date - start_date).days + 1
        calendar_data = []
        for i in range(delta):
            d = start_date + timedelta(days=i)
            day_of_year = d.timetuple().tm_yday
            season = get_season(d)
            is_complete = True  # initially mark all days complete
            calendar_data.append((d.isoformat(), day_of_year, season, is_complete))

        cur.executemany(
            "INSERT OR IGNORE INTO calendar (date, day_of_year, season, is_complete) VALUES (?, ?, ?, ?);",
            calendar_data
        )
        conn.commit()
        print(f"Inserted {len(calendar_data)} days into calendar ({start_date} → {end_date})")

    finally:
        conn.close()


if __name__ == "__main__":
    # Example: populate 2025 full year
    populate_calendar(date(2025, 1, 1), date(2025, 12, 31))
