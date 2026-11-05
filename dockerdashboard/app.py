import asyncio
import os
import re
import time

import docker
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db

HOST = os.environ.get("DASH_HOST", "localhost")
PORT = int(os.environ.get("DASH_PORT", "9000"))
PING_TIMEOUT = float(os.environ.get("DASH_PING_TIMEOUT", "3"))
SELF_NAME = os.environ.get("DASH_SELF_NAME", "dockerdash")
DOCKER_HOST_NAME = os.environ.get("DASH_DOCKER_HOST", "host.docker.internal")
IN_DOCKER = os.path.exists("/.dockerenv")

BLOCKED_ON_SELF = {"stop", "restart", "pause", "remove"}
ACTIONS = {"start", "stop", "restart", "pause", "unpause", "remove"}

app = FastAPI(title="Docker Dashboard")
client = docker.from_env()


# ---------- helpers ----------

def normalize(raw):
    """Return (kind, target). Empty input -> (None, None)."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    if raw.lower().startswith("tcp:"):
        hp = raw[4:].strip().strip("/")
        if ":" not in hp or not hp.rsplit(":", 1)[1].isdigit():
            raise HTTPException(400, "TCP target must look like tcp:host:port")
        return "tcp", hp
    if not re.match(r"^https?://", raw, re.I):
        raw = "http://" + raw
    return "http", raw


def published_ports(c):
    """[(host_port, container_port), ...]"""
    out = []
    ports = c.attrs.get("NetworkSettings", {}).get("Ports") or {}
    for cport, binds in ports.items():
        if not binds:
            continue
        for b in binds:
            hp = b.get("HostPort")
            if hp and (hp, cport.split("/")[0]) not in out:
                out.append((hp, cport.split("/")[0]))
    return out


def fix_url(url):
    """Inside Docker, 'localhost' means the dashboard itself; use the host instead."""
    if IN_DOCKER:
        for h in ("localhost", "127.0.0.1"):
            url = url.replace(f"//{h}:", f"//{DOCKER_HOST_NAME}:")
    return url


def fix_hostport(hp):
    if IN_DOCKER:
        for h in ("localhost", "127.0.0.1"):
            if hp.startswith(h + ":"):
                return DOCKER_HOST_NAME + hp[len(h):]
    return hp


def describe(c, saved_list):
    """Build one table row. c must already be reloaded."""
    state = c.attrs.get("State", {}) or {}
    running = c.status == "running"
    ports = published_ports(c)
    published_links = [f"http://{HOST}:{hp}" for hp, _ in ports]
    saved_urls = [s["url"] for s in saved_list]

    row = {
        "id": c.short_id,
        "name": c.name,
        "image": c.image.tags[0] if c.image.tags else c.image.short_id,
        "status": c.status,
        "health": (state.get("Health") or {}).get("Status", ""),
        "started": (state.get("StartedAt", "") or "")[:19].replace("T", " ") if running else "",
        "ports": [f"{hp}->{cp}" for hp, cp in ports],
        "links": [u for u in saved_urls if u.startswith("http")]
                 + [l for l in published_links if l not in saved_urls],
        "saved": saved_list,
        "protected": c.name == SELF_NAME,
        "ping": None,
        "_ping": None,
    }

    if running:
        if saved_list:
            row["_ping"] = (saved_list[0]["kind"], saved_list[0]["url"])
        elif ports:
            row["_ping"] = ("http", f"http://localhost:{ports[0][0]}")
    return row


async def ping_http(url):
    t0 = time.perf_counter()
    ms = lambda: int((time.perf_counter() - t0) * 1000)
    try:
        async with httpx.AsyncClient(timeout=PING_TIMEOUT, follow_redirects=True) as s:
            r = await s.get(url)
        return {"ok": r.status_code < 500, "code": r.status_code, "ms": ms()}
    except Exception as e:
        return {"ok": False, "code": None, "ms": ms(), "error": type(e).__name__}


async def ping_tcp(hostport):
    t0 = time.perf_counter()
    ms = lambda: int((time.perf_counter() - t0) * 1000)
    host, port = hostport.rsplit(":", 1)
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, int(port)), PING_TIMEOUT)
        writer.close()
        return {"ok": True, "code": None, "ms": ms()}
    except Exception as e:
        return {"ok": False, "code": None, "ms": ms(), "error": type(e).__name__}


def _load_rows():
    containers = client.containers.list(all=True)

    # Work out which running containers need auto-saving (their published ports)
    pending = {}
    for c in containers:
        c.reload()
        if c.status == "running" and c.name != SELF_NAME:
            pending[c.name] = [f"http://localhost:{hp}" for hp, _ in published_ports(c)]
    db.sync_auto_saves(pending)

    saved = db.load_saved()
    return [describe(c, saved.get(c.name, [])) for c in containers]


# ---------- API ----------

@app.get("/api/containers")
async def list_containers(do_ping: bool = True):
    rows = await asyncio.to_thread(_load_rows)

    async def run(row):
        t = row.get("_ping")
        if not do_ping or not t:
            row["ping"] = None
            return
        kind, target = t
        if kind == "tcp":
            row["ping"] = await ping_tcp(fix_hostport(target))
        else:
            row["ping"] = await ping_http(fix_url(target))

    await asyncio.gather(*(run(r) for r in rows))
    for r in rows:
        r.pop("_ping", None)

    rows.sort(key=lambda r: (r["status"] != "running", r["name"]))
    running = sum(1 for r in rows if r["status"] == "running")
    return {"total": len(rows), "running": running,
            "stopped": len(rows) - running, "containers": rows}


@app.post("/api/containers/{cid}/{action}")
def container_action(cid: str, action: str):
    if action not in ACTIONS:
        raise HTTPException(400, f"unknown action {action}")
    try:
        c = client.containers.get(cid)
    except docker.errors.NotFound:
        raise HTTPException(404, "no such container")
    if c.name == SELF_NAME and action in BLOCKED_ON_SELF:
        raise HTTPException(403, "the dashboard can't stop, restart, pause or remove itself")
    try:
        if action == "remove":
            c.remove(force=True)
        else:
            getattr(c, action)(**({"timeout": 15} if action in ("stop", "restart") else {}))
    except docker.errors.APIError as e:
        raise HTTPException(500, str(e.explanation or e))
    return {"ok": True, "id": cid, "action": action}


@app.get("/api/containers/{cid}/logs")
def container_logs(cid: str, tail: int = 100):
    try:
        c = client.containers.get(cid)
    except docker.errors.NotFound:
        raise HTTPException(404, "no such container")
    return {"logs": c.logs(tail=tail).decode("utf-8", "replace")}


class UrlIn(BaseModel):
    container: str
    url: str  # "http://...", "localhost:8080", or "tcp:host:port". Empty clears saved URLs.


@app.get("/api/urls")
def list_urls():
    return {"urls": db.list_all()}


@app.post("/api/urls")
def save_url(body: UrlIn):
    kind, target = normalize(body.url)
    db.set_url(body.container, target, kind)
    return {"ok": True, "container": body.container, "url": target, "kind": kind}


@app.delete("/api/urls/{name}")
def delete_url(name: str):
    db.set_url(name, None, None)
    return {"ok": True}


@app.get("/api/info")
def info():
    v = client.version()
    return {"docker_version": v.get("Version"), "api_version": v.get("ApiVersion"), "host": HOST}


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    print(f"\n  Docker Dashboard:  open http://localhost:{PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")