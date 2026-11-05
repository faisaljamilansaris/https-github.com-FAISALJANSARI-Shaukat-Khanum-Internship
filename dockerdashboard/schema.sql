CREATE TABLE IF NOT EXISTS saved_urls (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    container TEXT NOT NULL,
    url       TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'http',   -- 'http' or 'tcp'
    UNIQUE (container, url)
);

CREATE TABLE IF NOT EXISTS seen_containers (
    container TEXT PRIMARY KEY
);