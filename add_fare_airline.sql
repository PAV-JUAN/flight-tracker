-- New table: the airline behind the cheapest day of each weekly scan
CREATE TABLE IF NOT EXISTS fare_airline (
    id             SERIAL PRIMARY KEY,
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    origin         TEXT NOT NULL,
    destination    TEXT NOT NULL,
    departure_date DATE NOT NULL,
    stops_filter   TEXT NOT NULL,
    calendar_price NUMERIC(10,2),
    price          NUMERIC(10,2) NOT NULL,
    currency       TEXT NOT NULL,
    carrier        TEXT,
    carrier_codes  TEXT,
    mixed_carriers BOOLEAN,
    ignav_id       TEXT
);

-- Let the Fare Watch web app read it (read-only)
GRANT SELECT ON fare_airline TO web_reader;
