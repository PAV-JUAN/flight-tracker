import os
from datetime import date, timedelta

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("IGNAV_API_KEY")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_URL = f"postgresql://flights:{os.getenv('DB_PASSWORD')}@{DB_HOST}:5432/flights"

URL = "https://ignav.com/api/fares/cheapest-dates"

# (origin, destination, market) - the market sets the currency
ROUTES = [
    ("YUL", "AMS", "CA"),  # from Montreal, priced in CAD
    ("AMS", "YUL", "NL"),  # from Amsterdam, priced in EUR
]

# Two versions of each scan: direct only, and any number of stops
STOP_FILTERS = {"direct": 0, "any": None}

MONTHS_AHEAD = 11
WINDOW_DAYS = 31  # the API's maximum per request

INSERT_SQL = """
    INSERT INTO fare_calendar (origin, destination, departure_date, stops_filter,
                               price, currency, price_status)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
"""


def date_windows():
    """Split the next 12 months into 31-day chunks, starting tomorrow."""
    start = date.today() + timedelta(days=1)
    for _ in range(MONTHS_AHEAD):
        end = start + timedelta(days=WINDOW_DAYS - 1)
        yield start, end
        start = end + timedelta(days=1)


def scan(origin, destination, market, max_stops, start, end):
    """Ask Ignav for the cheapest one-way price on every day in one window."""
    body = {
        "origin": origin,
        "destination": destination,
        "market": market,
        "departure_date_range": {"start": start.isoformat(), "end": end.isoformat()},
    }
    if max_stops is not None:
        body["max_stops"] = max_stops
    response = requests.post(URL, headers={"X-Api-Key": API_KEY}, json=body, timeout=90)
    response.raise_for_status()
    return response.json().get("dates", [])


def main():
    with psycopg.connect(DB_URL) as conn:
        for origin, destination, market in ROUTES:
            for label, max_stops in STOP_FILTERS.items():
                best = None
                for start, end in date_windows():
                    try:
                        days = scan(origin, destination, market, max_stops, start, end)
                    except requests.RequestException as error:
                        print(f"{origin}->{destination} {label} {start}..{end}: FAILED ({error})")
                        continue  # skip this window, keep going

                    for day in days:
                        price = day.get("price")
                        conn.execute(INSERT_SQL, (
                            origin, destination, day["departure_date"], label,
                            price["amount"] if price else None,
                            price["currency"] if price else None,
                            price.get("status") if price else None,
                        ))
                        if price and (best is None or price["amount"] < best[1]):
                            best = (day["departure_date"], price["amount"], price["currency"])
                    conn.commit()  # save this window to the database

                if best:
                    print(f"{origin}->{destination} {label}: cheapest {best[1]} {best[2]} on {best[0]}")
                else:
                    print(f"{origin}->{destination} {label}: no prices found")


if __name__ == "__main__":
    main()
