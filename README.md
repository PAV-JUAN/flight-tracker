# Flight Tracker

A self-hosted flight price tracker running on my home Ubuntu server.

Every Wednesday it scans one-way fares between Montreal (YUL) and Amsterdam (AMS)
in both directions for the next 11 months, separating direct flights from options
with layovers. Prices are stored in PostgreSQL and visualized in Grafana.

## Stack

- **Python**: collects fares from the Ignav flight price API
- **PostgreSQL**: stores the price history
- **Grafana**: dashboard with a price chart, cheapest months and cheapest days
- **Docker Compose**: runs everything
- **cron**: schedules the weekly scan

## Files

- `scanner.py`: weekly one-way scan (cheapest price per day, direct vs any stops)
- `collector.py`: detailed round-trip check for specific dates
- `schema.sql`: database tables
- `grafana/provisioning/`: Grafana data source configuration

## Setup

1. Copy `.env.example` to `.env` and fill in your own values
2. `docker compose up -d` to start the database and Grafana
3. `docker compose run --rm tracker` to run a scan

Work in progress.
