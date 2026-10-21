"""
Flight prices web app: backend.

A small read-only API over the fare_calendar table filled by scanner.py.
It connects with the web_reader database user, which can only SELECT.

Endpoints
  GET /api/meta                                   routes, currencies, scan dates
  GET /api/calendar?route=YUL-AMS&stops=direct    latest price for every upcoming day
  GET /api/cheapest?route=YUL-AMS&stops=any       cheapest upcoming prices, equal prices grouped
  GET /api/history?route=YUL-AMS&stops=any&date=2026-12-10
                                                  how one day's price moved, scan after scan
  GET /api/rates                                  today's EUR/CAD exchange rate, for converting prices
  GET /health                                     is the app up and can it reach the database
"""

import json
import os
import threading
import time
import urllib.request
from datetime import date

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from psycopg.rows import dict_row

DB = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "flights"),
    "user": os.getenv("DB_USER", "web_reader"),
    "password": os.getenv("DB_PASSWORD", ""),
    "connect_timeout": 5,
}

# Only these values are ever accepted from visitors. Anything else is rejected
# before it gets near the database.
ROUTES = {"YUL-AMS": ("YUL", "AMS"), "AMS-YUL": ("AMS", "YUL")}
STOPS = {"direct", "any"}
CITY = {"YUL": "Montreal", "AMS": "Amsterdam"}

STATIC = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="Flight prices", docs_url=None, redoc_url=None, openapi_url=None)


def query(sql, params=()):
    """Run one read-only query and return the rows as dictionaries."""
    try:
        with psycopg.connect(**DB, row_factory=dict_row) as conn:
            conn.read_only = True  # extra safety on top of the read-only user
            return conn.execute(sql, params).fetchall()
    except psycopg.OperationalError:
        raise HTTPException(503, "Database unavailable")


def pick(route, stops):
    if route not in ROUTES:
        raise HTTPException(400, f"route must be one of: {', '.join(ROUTES)}")
    if stops not in STOPS:
        raise HTTPException(400, "stops must be 'direct' or 'any'")
    return (*ROUTES[route], stops)


# The newest scan for one route + stop type. A scan takes a few minutes, so it
# is identified by its date, not its exact time.
LATEST_SCAN = """
    SELECT max(checked_at::date) FROM fare_calendar
    WHERE origin = %(o)s AND destination = %(d)s AND stops_filter = %(s)s
"""

# Latest price for each upcoming day. If a scan was run twice the same day,
# keep the most recent row for each departure date.
CALENDAR_SQL = f"""
    SELECT DISTINCT ON (departure_date)
           departure_date, price, currency
    FROM fare_calendar
    WHERE origin = %(o)s AND destination = %(d)s AND stops_filter = %(s)s
      AND checked_at::date = ({LATEST_SCAN})
      AND departure_date >= current_date
    ORDER BY departure_date, checked_at DESC
"""


@app.get("/api/meta")
def meta():
    rows = query("""
        SELECT origin, destination, stops_filter,
               max(checked_at::date)            AS last_scan,
               count(DISTINCT checked_at::date) AS scans,
               max(currency)                    AS currency
        FROM fare_calendar
        GROUP BY 1, 2, 3
    """)
    routes = {}
    for r in rows:
        key = f"{r['origin']}-{r['destination']}"
        if key not in ROUTES:
            continue
        info = routes.setdefault(key, {
            "route": key,
            "from": {"code": r["origin"], "city": CITY.get(r["origin"], r["origin"])},
            "to": {"code": r["destination"], "city": CITY.get(r["destination"], r["destination"])},
            "currency": r["currency"],
            "stops": {},
        })
        info["currency"] = info["currency"] or r["currency"]
        info["stops"][r["stops_filter"]] = {"last_scan": r["last_scan"], "scans": r["scans"]}
    order = list(ROUTES)
    return {"routes": sorted(routes.values(), key=lambda x: order.index(x["route"]))}


@app.get("/api/calendar")
def calendar(route: str = Query(...), stops: str = Query("any")):
    o, d, s = pick(route, stops)
    rows = query(CALENDAR_SQL, {"o": o, "d": d, "s": s})
    priced = [r["price"] for r in rows if r["price"] is not None]
    return {
        "route": route,
        "stops": stops,
        "currency": next((r["currency"] for r in rows if r["currency"]), None),
        "min": min(priced) if priced else None,
        "max": max(priced) if priced else None,
        "days": [
            {"date": r["departure_date"], "price": float(r["price"]) if r["price"] is not None else None}
            for r in rows
        ],
    }


@app.get("/api/cheapest")
def cheapest(route: str = Query(...), stops: str = Query("any"),
             limit: int = Query(5, ge=1, le=20)):
    o, d, s = pick(route, stops)
    rows = query(f"""
        WITH latest AS ({CALENDAR_SQL})
        SELECT price, max(currency) AS currency,
               array_agg(departure_date ORDER BY departure_date) AS dates
        FROM latest
        WHERE price IS NOT NULL
        GROUP BY price
        ORDER BY price
        LIMIT %(limit)s
    """, {"o": o, "d": d, "s": s, "limit": limit})
    return {
        "route": route,
        "stops": stops,
        "prices": [
            {"price": float(r["price"]), "currency": r["currency"], "dates": r["dates"]}
            for r in rows
        ],
    }


@app.get("/api/history")
def history(route: str = Query(...), stops: str = Query("any"), date_: date = Query(..., alias="date")):
    o, d, s = pick(route, stops)
    rows = query("""
        SELECT DISTINCT ON (checked_at::date)
               checked_at::date AS scan_date, price, currency
        FROM fare_calendar
        WHERE origin = %(o)s AND destination = %(d)s AND stops_filter = %(s)s
          AND departure_date = %(day)s
        ORDER BY checked_at::date, checked_at DESC
    """, {"o": o, "d": d, "s": s, "day": date_})
    return {
        "route": route,
        "stops": stops,
        "date": date_,
        "points": [
            {"scan_date": r["scan_date"], "price": float(r["price"]) if r["price"] is not None else None,
             "currency": r["currency"]}
            for r in rows
        ],
    }


# Exchange rates from Frankfurter (European Central Bank data, free, no key).
# Fetched at most every 6 hours and kept in memory; if the service is down, the
# last good rate keeps being used.
RATES_URL = "https://api.frankfurter.dev/v1/latest?base=EUR&symbols=CAD"
RATES_TTL = 6 * 3600
_rates = {"data": None, "fetched": 0.0}
_rates_lock = threading.Lock()


def fetch_rates():
    req = urllib.request.Request(RATES_URL, headers={"User-Agent": "fare-watch"})
    with urllib.request.urlopen(req, timeout=6) as r:
        body = json.load(r)
    cad = float(body["rates"]["CAD"])
    if not 0.5 < cad < 5:  # sanity check: never trust a crazy number
        raise ValueError(f"unexpected EUR/CAD rate {cad}")
    return {"base": "EUR", "date": body.get("date"), "rates": {"EUR": 1.0, "CAD": cad}}


@app.get("/api/rates")
def rates():
    with _rates_lock:
        if _rates["data"] is None or time.time() - _rates["fetched"] > RATES_TTL:
            try:
                _rates["data"] = fetch_rates()
                _rates["fetched"] = time.time()
            except Exception:
                if _rates["data"] is None:
                    raise HTTPException(503, "Exchange rate unavailable")
                _rates["fetched"] = time.time() - RATES_TTL + 600  # retry in 10 minutes
        return _rates["data"]


@app.get("/health")
def health():
    query("SELECT 1")
    return {"status": "ok"}


# The page itself (built in the next step). Served only if it exists.
if os.path.isdir(STATIC):
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(STATIC, "index.html"))
