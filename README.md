# Flight Tracker

I fly Montreal ↔ Amsterdam a lot, in both directions, and I'm planning to move there for a year. Fares on this route jump around a lot, so I wanted to actually know when the cheap days are instead of guessing. Now my home server checks every Wednesday and keeps the history.

**Live:** [flights.ricamivida.com](https://flights.ricamivida.com)

It started as a Python script saving prices to PostgreSQL, with a Grafana dashboard only I could see. Then I wanted to share it with friends, and Grafana isn't really something you send to people, so I built Fare Watch: a small website just for this.

[![Fare Watch on desktop](docs/fare-watch.png)](docs/fare-watch.png)

## What Fare Watch shows

- A boarding-pass style header to switch direction (YUL → AMS or AMS → YUL) and pick direct flights only or any number of stops
- The cheapest days from the latest scan, with days at the same price grouped together
- An 11-month calendar colored from cheap to expensive, so the cheap stretches jump out
- The price history of any day you click, one point per weekly scan
- Everything in one currency, CAD by default, or EUR if you switch (more on that below)
- Your choices stay in the URL (for example `#AMS-YUL/direct/EUR`), so you can send someone a link to exactly what you're looking at
- It works on phones, which is where I check it most

[![Fare Watch on a phone](docs/fare-watch-phone.png)](docs/fare-watch-phone.png)

## How it works

Every Wednesday, cron runs `scanner.py`. It asks the Ignav flight price API for the cheapest one-way fare on every day of the next 11 months, in both directions, once for direct flights and once for flights with stops. The results go into PostgreSQL.

Fare Watch is a small FastAPI app that reads from that database, plus one HTML page with plain JavaScript (no framework, charts drawn as SVG). Caddy sits in front of it and handles HTTPS. Grafana reads the same database for my private charts.

```
cron (Wednesdays) → scanner.py → Ignav API
                        ↓
                    PostgreSQL → Grafana (private)
                        ↓
              Fare Watch API (read-only)
                        ↓
 internet → router → Caddy (HTTPS) → Fare Watch page
```

Built with Python, PostgreSQL, FastAPI, HTML/CSS/JavaScript, Grafana, Docker Compose, Caddy and cron.

## Problems I had to solve

**Two currencies.** Fares from Amsterdam are sold in euros and fares from Montreal in Canadian dollars, so comparing the two directions side by side didn't mean much. Fare Watch converts everything to the currency you pick using the daily European Central Bank rate (through the Frankfurter API) and keeps the original price visible next to it. The rate is fetched at most every 6 hours and sanity-checked. If the rate service is down, it keeps the last good value, and if there's no rate at all, it falls back to the airline's own currency with a note.

**The API costs money.** Every search on Ignav is a paid request, so visitors never trigger one. The site only shows what the weekly scan already stored, no matter how many people use it.

**It didn't load from my own house.** The site worked from my phone on data but not on my Wi-Fi, because my router can't loop traffic back to its own public IP. Pi-hole now answers the domain with the server's local address for devices at home.

## Keeping it safe

This is the first thing I've put on the public internet that I wrote myself, so I tried to make sure a mistake in my code couldn't do much damage.

The website connects to the database with its own `web_reader` user, which can only `SELECT` from two tables, and every query also runs inside a read-only transaction. Even if there's a bug, it can't change or delete prices.

Routes and stop types from the URL are checked against a fixed list before any query runs, and all queries use parameters instead of building SQL strings.

The web app runs as a non-root user in a read-only container.

## Files

- `scanner.py`: the weekly one-way scan (cheapest price per day, direct vs. any stops)
- `collector.py`: a more detailed round-trip check for specific dates
- `schema.sql`: database tables
- `web/app.py`: the Fare Watch API
- `web/static/index.html`: the Fare Watch page
- `grafana/provisioning/`: Grafana's database connection

## API

| Endpoint | Returns |
|---|---|
| `GET /api/meta` | routes, currencies, last scan date, number of scans |
| `GET /api/calendar?route=YUL-AMS&stops=any` | latest price for every upcoming day |
| `GET /api/cheapest?route=AMS-YUL&stops=direct&limit=6` | cheapest prices, equal prices grouped |
| `GET /api/history?route=YUL-AMS&stops=any&date=2026-12-10` | one day's price, scan after scan |
| `GET /api/rates` | today's EUR/CAD rate |
| `GET /health` | app and database status |

## Running it yourself

1. Copy `.env.example` to `.env` and fill in your own values.
2. Start the database and Grafana:
   ```bash
   docker compose up -d db grafana
   ```
3. Create the read-only user for the website:
   ```bash
   docker exec -i flight-db psql -U flights -d flights -v pw="$(grep '^WEB_DB_PASSWORD=' .env | cut -d= -f2)" <<'SQL'
   CREATE ROLE web_reader LOGIN PASSWORD :'pw';
   GRANT CONNECT ON DATABASE flights TO web_reader;
   GRANT USAGE ON SCHEMA public TO web_reader;
   GRANT SELECT ON fare_calendar, prices TO web_reader;
   SQL
   ```
4. Start Fare Watch (on port 8097):
   ```bash
   docker compose up -d --build web
   ```
5. Run a scan:
   ```bash
   docker compose run --rm tracker
   ```

## What's next

- Show which airline has each price, and where the stops are for flights with layovers
- Alerts when a price drops
