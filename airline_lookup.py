"""Find out which airline sells the cheapest fare from the latest weekly scan.

The cheapest-dates search (scanner.py) gives a price per day but no airline.
For each route and stop filter, this script takes the cheapest day from the
latest scan, runs ONE one-way search for that day, and saves the airline.
That is 4 extra Ignav requests per week (2 routes x 2 stop filters).
"""

import os

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["IGNAV_API_KEY"]
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PASSWORD = os.environ["DB_PASSWORD"]
DB_URL = f"postgresql://flights:{DB_PASSWORD}@{DB_HOST}:5432/flights"

ONE_WAY_URL = "https://ignav.com/api/fares/one-way"

# Same routes and markets as scanner.py
ROUTES = [
    ("YUL", "AMS", "CA"),  # priced in CAD
    ("AMS", "YUL", "NL"),  # priced in EUR
]

# Same stop filters as scanner.py: label -> max_stops (None = any number)
STOP_FILTERS = {"direct": 0, "any": None}


def cheapest_day(cur, origin, destination, stops_filter):
    """Return (departure_date, price) of the cheapest day in the latest scan."""
    cur.execute(
        """
        SELECT departure_date, price
        FROM fare_calendar
        WHERE origin = %s
          AND destination = %s
          AND stops_filter = %s
          AND price IS NOT NULL
          AND departure_date >= current_date
          AND checked_at::date = (SELECT max(checked_at)::date FROM fare_calendar)
        ORDER BY price, departure_date
        LIMIT 1
        """,
        (origin, destination, stops_filter),
    )
    return cur.fetchone()


def search_one_way(origin, destination, day, market, max_stops):
    """Ask Ignav for the itineraries on one exact date."""
    body = {
        "origin": origin,
        "destination": destination,
        "departure_date": day.isoformat(),
        "market": market,
    }
    if max_stops is not None:
        body["max_stops"] = max_stops

    response = requests.post(
        ONE_WAY_URL,
        json=body,
        headers={"X-Api-Key": API_KEY},
        timeout=90,
    )
    response.raise_for_status()
    return response.json().get("itineraries", [])


def airline_info(itinerary):
    """Pull the airline name and codes out of one itinerary."""
    outbound = itinerary.get("outbound", {})
    segments = outbound.get("segments", [])

    # 2-letter codes of each flight in the trip, without repeats, in order
    codes = []
    for seg in segments:
        code = seg.get("marketing_carrier_code")
        if code and code not in codes:
            codes.append(code)

    # Ignav's display name for the leg; it can be missing, so fall back
    # to the operating airline names of the flights
    name = outbound.get("carrier")
    if not name:
        names = []
        for seg in segments:
            op = seg.get("operating_carrier_name")
            if op and op not in names:
                names.append(op)
        name = " + ".join(names) or None

    return name, ",".join(codes) or None


def main():
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for origin, destination, market in ROUTES:
                for stops_filter, max_stops in STOP_FILTERS.items():
                    label = f"{origin}->{destination} ({stops_filter})"

                    row = cheapest_day(cur, origin, destination, stops_filter)
                    if row is None:
                        print(f"{label}: no priced day in the latest scan")
                        continue
                    day, calendar_price = row

                    try:
                        itineraries = search_one_way(
                            origin, destination, day, market, max_stops
                        )
                    except requests.RequestException as err:
                        print(f"{label}: one-way search failed for {day}: {err}")
                        continue

                    priced = [i for i in itineraries if i.get("price")]
                    if not priced:
                        print(f"{label}: no itineraries for {day}")
                        continue

                    cheapest = min(priced, key=lambda i: i["price"]["amount"])
                    name, codes = airline_info(cheapest)

                    cur.execute(
                        """
                        INSERT INTO fare_airline
                            (origin, destination, departure_date, stops_filter,
                             calendar_price, price, currency, carrier,
                             carrier_codes, mixed_carriers, ignav_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            origin,
                            destination,
                            day,
                            stops_filter,
                            calendar_price,
                            cheapest["price"]["amount"],
                            cheapest["price"]["currency"],
                            name,
                            codes,
                            cheapest.get("has_mixed_carriers"),
                            cheapest.get("ignav_id"),
                        ),
                    )
                    conn.commit()
                    print(
                        f"{label}: {day} {cheapest['price']['amount']} "
                        f"{cheapest['price']['currency']} on {name or 'unknown airline'}"
                    )


if __name__ == "__main__":
    main()
