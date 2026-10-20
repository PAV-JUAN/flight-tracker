import os
from itertools import product

import psycopg
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("IGNAV_API_KEY")
DB_URL = f"postgresql://flights:{os.getenv('DB_PASSWORD')}@localhost:5432/flights"

URL = "https://ignav.com/api/fares/round-trip"

# What to track: every combination of these dates gets checked
ORIGIN = "AMS"
DESTINATION = "YUL"
DEPARTURE_DATES = ["2026-12-21", "2026-12-22", "2026-12-23"]
RETURN_DATES = ["2027-01-02", "2027-01-03", "2027-01-04"]
MARKET = "NL"

INSERT_SQL = """
    INSERT INTO prices (origin, destination, departure_date, return_date,
                        price, currency, carrier, out_stops, back_stops,
                        out_minutes, back_minutes, ignav_id)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def search(departure, return_date):
    """Ask Ignav for all options on one date combination."""
    response = requests.post(
        URL,
        headers={"X-Api-Key": API_KEY},
        json={
            "origin": ORIGIN,
            "destination": DESTINATION,
            "departure_date": departure,
            "return_date": return_date,
            "market": MARKET,
        },
        timeout=60,
    )
    response.raise_for_status()
    return response.json().get("itineraries", [])


def main():
    with psycopg.connect(DB_URL) as conn:
        for departure, return_date in product(DEPARTURE_DATES, RETURN_DATES):
            try:
                itineraries = search(departure, return_date)
            except requests.RequestException as error:
                print(f"{departure} -> {return_date}: FAILED ({error})")
                continue  # skip this one, keep going with the others

            for it in itineraries:
                out = it["outbound"]
                back = it.get("inbound", {})
                conn.execute(INSERT_SQL, (
                    ORIGIN, DESTINATION, departure, return_date,
                    it["price"]["amount"], it["price"]["currency"],
                    out.get("carrier"),
                    len(out["segments"]) - 1,
                    len(back.get("segments", [])) - 1,
                    out.get("duration_minutes"),
                    back.get("duration_minutes"),
                    it.get("ignav_id"),
                ))
            conn.commit()  # save this batch to the database

            if itineraries:
                cheapest = min(i["price"]["amount"] for i in itineraries)
                currency = itineraries[0]["price"]["currency"]
                print(f"{departure} -> {return_date}: {len(itineraries)} options saved, "
                      f"cheapest {cheapest} {currency}")
            else:
                print(f"{departure} -> {return_date}: no results")


if __name__ == "__main__":
    main()
