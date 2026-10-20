import os
import requests
from dotenv import load_dotenv

# Load the API key from the .env file
load_dotenv()
API_KEY = os.getenv("IGNAV_API_KEY")

URL = "https://ignav.com/api/fares/round-trip"

# What we're searching for
search = {
    "origin": "AMS",
    "destination": "YUL",
    "departure_date": "2026-12-23",
    "return_date": "2027-01-04",
    "market": "NL",  # Netherlands market, so prices should come back in euros
}

# Send the request to Ignav
response = requests.post(
    URL,
    headers={"X-Api-Key": API_KEY},
    json=search,
    timeout=60,
)
response.raise_for_status()  # Stop with a clear error if something went wrong
data = response.json()

itineraries = data.get("itineraries", [])
print(f"Found {len(itineraries)} options (checked at {data.get('observed_at')})\n")

# Sort from cheapest to most expensive
itineraries.sort(key=lambda it: it["price"]["amount"])

# Show the 5 cheapest
for it in itineraries[:5]:
    price = it["price"]
    out = it["outbound"]
    back = it.get("inbound", {})
    out_stops = len(out["segments"]) - 1
    back_stops = len(back.get("segments", [])) - 1
    print(
        f"{price['amount']} {price['currency']} | {out.get('carrier')} | "
        f"out: {out_stops} stop(s), {out.get('duration_minutes', 0) // 60}h | "
        f"back: {back_stops} stop(s), {back.get('duration_minutes', 0) // 60}h"
    )
