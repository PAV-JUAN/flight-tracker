CREATE TABLE prices (
    id             SERIAL PRIMARY KEY,
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    origin         TEXT NOT NULL,
    destination    TEXT NOT NULL,
    departure_date DATE NOT NULL,
    return_date    DATE NOT NULL,
    price          NUMERIC(10,2) NOT NULL,
    currency       TEXT NOT NULL,
    carrier        TEXT,
    out_stops      INT,
    back_stops     INT,
    out_minutes    INT,
    back_minutes   INT,
    ignav_id       TEXT
);

CREATE TABLE fare_calendar (
    id             SERIAL PRIMARY KEY,
    checked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    origin         TEXT NOT NULL,
    destination    TEXT NOT NULL,
    departure_date DATE NOT NULL,
    stops_filter   TEXT NOT NULL,
    price          NUMERIC(10,2),
    currency       TEXT,
    price_status   TEXT
);
