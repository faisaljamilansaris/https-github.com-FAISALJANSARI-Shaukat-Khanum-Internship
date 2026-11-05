import os
import sqlite3
from contextlib import closing

DB_PATH = os.environ.get("DASH_DB", "/data/dashboard.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")


def connect():
    """Open the database and make sure the tables from schema.sql exist."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        con.executescript(f.read())
    return con


def load_saved():
    """{container_name: [ {id, container, url, kind}, ... ]}"""
    with closing(connect()) as con:
        out = {}
        for r in con.execute("SELECT id, container, url, kind FROM saved_urls ORDER BY id"):
            out.setdefault(r["container"], []).append(dict(r))
        return out


def list_all():
    with closing(connect()) as con:
        return [dict(r) for r in con.execute(
            "SELECT id, container, url, kind FROM saved_urls ORDER BY container, id")]


def sync_auto_saves(pending):
    """pending = {container_name: [url, ...]} for running containers.
    Each container is auto-saved only the first time it is seen."""
    with closing(connect()) as con:
        for name, urls in pending.items():
            seen = con.execute(
                "SELECT 1 FROM seen_containers WHERE container = ?", (name,)).fetchone()
            if seen:
                continue
            for url in urls:
                con.execute(
                    "INSERT OR IGNORE INTO saved_urls (container, url, kind) VALUES (?, ?, 'http')",
                    (name, url))
            con.execute("INSERT OR IGNORE INTO seen_containers (container) VALUES (?)", (name,))
        con.commit()


def set_url(container, url, kind):
    """Replace all saved URLs for a container with one URL. url=None clears them."""
    with closing(connect()) as con:
        con.execute("DELETE FROM saved_urls WHERE container = ?", (container,))
        if url is not None:
            con.execute(
                "INSERT INTO saved_urls (container, url, kind) VALUES (?, ?, ?)",
                (container, url, kind))
        con.execute("INSERT OR IGNORE INTO seen_containers (container) VALUES (?)", (container,))
        con.commit()