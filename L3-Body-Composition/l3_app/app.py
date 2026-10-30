"""
L3 Body Composition web app (Stage 2 prototype).

Upload a CT (DICOM folder, .zip of a DICOM folder, or .nii/.nii.gz), type height,
and the app runs l3_analysis.py in the background, then builds the colour report.

Run (in Ubuntu/WSL, c2c_env active):
    cd ~/l3_app
    pip install fastapi uvicorn python-multipart      # once
    python app.py
then open http://localhost:8000 in Chrome/Edge on Windows.

Settings (environment variables, all optional):
    L3_SCRIPT   path of l3_analysis.py          (default ~/l3_analysis.py)
    L3_JOBS     where uploads and results go    (default ~/l3_app_jobs)
    L3_PORT     port                            (default 8000)
"""
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

import db
import report

HERE = os.path.dirname(os.path.abspath(__file__))
L3_SCRIPT = os.environ.get("L3_SCRIPT", os.path.expanduser("~/l3_analysis.py"))
JOBS_DIR = os.environ.get("L3_JOBS", os.path.expanduser("~/l3_app_jobs"))
PORT = int(os.environ.get("L3_PORT", "8000"))
report.L3_SCRIPT = L3_SCRIPT
os.makedirs(JOBS_DIR, exist_ok=True)
db.DB_PATH = os.environ.get("L3_DB", os.path.join(JOBS_DIR, "l3_app.db"))
db.init()

# progress steps: (text in l3_analysis.py output that means the step has started, label)
STEPS = [
    ("Found CT series", "Reading the CT"),
    ("Running TotalSegmentator", "Finding L3 and both psoas (TotalSegmentator)"),
    ("Running Comp2Comp", "Drawing muscle and fat (Comp2Comp model)"),
    ("===== L3 RESULTS", "Measuring areas, diameters, indices"),
    ("__REPORT__", "Making the colour report"),
]
DOWNLOADS = {  # name in URL -> file in the output folder
    "report.png": "report.png", "report.pdf": "report.pdf", "results.csv": "results.csv",
    "l3_labels.nii.gz": "l3_labels.nii.gz", "l3_ct.nii.gz": "l3_ct.nii.gz", "log.txt": "log.txt",
}

app = FastAPI(title="L3 Body Composition")
jobs = {}            # id -> job dict (also saved as job.json in the job folder)
work_q = queue.Queue()
lock = threading.Lock()


# ----------------------------------------------------------------------------
# Jobs
# ----------------------------------------------------------------------------
def job_dir(jid):
    return os.path.join(JOBS_DIR, jid)


def save_job(j, to_db=True):
    with open(os.path.join(job_dir(j["id"]), "job.json"), "w") as f:
        json.dump(j, f, indent=1)
    if to_db:
        try:
            db.save_analysis(j, os.path.join(job_dir(j["id"]), "output"))
        except Exception as e:  # the database must never stop an analysis
            print("DB warning:", e)


def load_old_jobs():
    for jid in sorted(os.listdir(JOBS_DIR)):
        p = os.path.join(JOBS_DIR, jid, "job.json")
        if os.path.exists(p):
            try:
                j = json.load(open(p))
                if j["status"] in ("queued", "running"):  # app was stopped mid-run
                    j["status"], j["error"] = "error", "The app was restarted during this analysis. Run it again."
                    save_job(j, to_db=False)
                jobs[jid] = j
            except Exception:
                pass
    try:  # put every old analysis into the database (only adds what is missing)
        n = db.import_app_jobs(JOBS_DIR)
        if n:
            print(f"  Added {n} earlier result(s) to the database")
    except Exception as e:
        print("DB warning:", e)


def set_job(j, **kw):
    with lock:
        j.update(kw)
        # the log tail changes on every output line; only status/step changes go to the database
        save_job(j, to_db=set(kw) != {"log_tail"})


def worker():
    while True:
        jid = work_q.get()
        j = jobs.get(jid)
        if j:
            try:
                run_job(j)
            except Exception as e:
                set_job(j, status="error", error=str(e), finished=time.time())
        work_q.task_done()


def run_job(j):
    out = os.path.join(job_dir(j["id"]), "output")
    os.makedirs(out, exist_ok=True)
    cmd = [sys.executable, "-u", L3_SCRIPT, "-i", j["input_path"], "-o", out]
    if j.get("height_m"):
        cmd += ["--height", str(j["height_m"])]
    set_job(j, status="running", started=time.time(), step=0)
    log_path = os.path.join(out, "log.txt")
    with open(log_path, "w") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                             env={**os.environ, "PYTHONUNBUFFERED": "1"})
        tail = []
        for line in p.stdout:
            log.write(line); log.flush()
            line = line.rstrip()
            if line:
                tail = (tail + [line[-300:]])[-12:]
            for i, (marker, _) in enumerate(STEPS):
                if marker in line and i > j.get("step", 0):
                    j["step"] = i
            set_job(j, log_tail=tail)
        rc = p.wait()
    if rc != 0 or not os.path.exists(os.path.join(out, "results.csv")):
        err = next((l for l in reversed(tail) if "ERROR" in l or "Error" in l), tail[-1] if tail else "unknown error")
        set_job(j, status="error", error=err, finished=time.time())
        return
    set_job(j, step=len(STEPS) - 1)
    _, _, rows = report.make_report(out, j.get("sex") or None, j.get("weight_kg"))
    import pandas as pd
    res = pd.read_csv(os.path.join(out, "results.csv")).iloc[0].to_dict()
    res = {k: (None if isinstance(v, float) and v != v else v) for k, v in res.items()}
    try:
        ev = json.load(open(os.path.join(out, "evaluation.json")))
    except Exception:
        ev = {}
    set_job(j, status="done", finished=time.time(), step=len(STEPS), rows=rows, results=res,
            patient_id=str(res.get("patient_id") or j.get("patient_id") or ""))
    try:
        db.save_results(j["id"], res, rows, ev.get("sex") or j.get("sex"), ev.get("bmi"))
    except Exception as e:
        print("DB warning (results not stored):", e)


# ----------------------------------------------------------------------------
# Upload handling
# ----------------------------------------------------------------------------
def safe_rel(name):
    """Keep the folder structure of an uploaded folder, but never allow '..' or absolute paths."""
    parts = [p for p in re.split(r"[\\/]+", name or "") if p not in ("", ".", "..")]
    return os.path.join(*parts) if parts else "file"


def extract_zip(zpath, dest):
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            if m.is_dir():
                continue
            target = os.path.join(dest, safe_rel(m.filename))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)


# ----------------------------------------------------------------------------
# API
# ----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    with open(os.path.join(HERE, "static", "index.html"), encoding="utf-8") as f:
        return f.read()


MIN_SLICES = 20  # fewer DICOM files than this cannot be a CT volume that covers L3
NII_EXT = (".nii", ".nii.gz")
NOT_DICOM_EXT = NII_EXT + (".zip", ".json", ".txt", ".csv", ".xml", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".py")
MASK_DIRS = {"segmentations", "segmentation", "labels", "label", "masks", "mask", "labelstr", "labelsts", "seg"}
MASK_WORDS = re.compile(r"(seg|label|mask)", re.I)


def is_ct_nifti(path, root):
    """NIfTI that looks like a CT, not a segmentation mask (e.g. TotalSegmentator dataset segmentations/)."""
    rel = os.path.relpath(path, root)
    folders = [p.lower() for p in rel.split(os.sep)[:-1]]
    if any(f in MASK_DIRS for f in folders):
        return False
    return not MASK_WORDS.search(os.path.basename(path))


def find_scans(root):
    """Split an upload into scans. Returns list of dict(kind, paths, name, n_files).
    - every CT NIfTI file = one scan
    - DICOM folders are grouped by study (StudyInstanceUID); non-CT series (PET, SEG...) are skipped.
      l3_analysis.py then picks the largest CT series inside each study."""
    scans, dicom_dirs = [], {}
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            if f.lower().endswith(NII_EXT):
                if is_ct_nifti(p, root):
                    base = f[:-7] if f.lower().endswith(".nii.gz") else f[:-4]
                    parent = os.path.basename(r) if r != root else ""
                    name = parent if base.lower() in ("ct", "image", "img", "volume") and parent else base
                    scans.append(dict(kind="NIfTI", paths=[p], name=name, n_files=1))
            elif not f.lower().endswith(NOT_DICOM_EXT):
                dicom_dirs.setdefault(r, []).append(p)

    studies = {}
    try:
        import pydicom
    except ImportError:
        pydicom = None
    for d, files in sorted(dicom_dirs.items()):
        key, name, modality = d, os.path.basename(d), ""
        if pydicom is not None:
            ds = None
            for p in files[:5]:  # first readable DICOM file in this folder
                try:
                    ds = pydicom.dcmread(p, stop_before_pixels=True, force=True)
                    if getattr(ds, "SOPClassUID", None) or getattr(ds, "Modality", None):
                        break
                    ds = None
                except Exception:
                    ds = None
            if ds is None:
                continue  # not DICOM
            modality = str(getattr(ds, "Modality", "") or "")
            key = str(getattr(ds, "StudyInstanceUID", "") or getattr(ds, "PatientID", "") or d)
            name = str(getattr(ds, "PatientID", "") or name)
        if modality and modality != "CT":
            continue  # PET, SEG, RTSTRUCT, SR ...
        s = studies.setdefault(key, dict(kind="DICOM", paths=[], name=name, n_files=0))
        s["paths"].append(d)
        s["n_files"] += len(files)
    scans += list(studies.values())
    return scans


def new_job_id():
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


@app.post("/api/jobs")
async def create_job(request: Request):
    # default upload limit is 1000 files, which a single thin-slice CT can exceed -> raise it
    try:
        form = await request.form(max_files=1_000_000, max_fields=1000)
    except TypeError:  # very old starlette
        form = await request.form()
    files = [f for f in form.getlist("files") if hasattr(f, "filename")]
    label = str(form.get("label") or "").strip()
    sex = report.norm_sex(form.get("sex") or "")

    def fnum(k):
        try:
            v = float(form.get(k) or 0)
            return v if v > 0 else None
        except ValueError:
            raise HTTPException(400, f"{k} is not a number")
    height_cm, weight_kg = fnum("height_cm"), fnum("weight_kg")
    if not files:
        raise HTTPException(400, "No files uploaded")

    h = None
    if height_cm:
        h = height_cm / 100 if height_cm > 3 else height_cm  # accept cm or m
        if not 0.5 < h < 2.5:
            raise HTTPException(400, f"Height {height_cm} looks wrong; enter it in cm, e.g. 170")

    # 1. save the whole upload in a staging folder
    stage = os.path.join(JOBS_DIR, "_upload_" + uuid.uuid4().hex[:8])
    os.makedirs(stage)
    try:
        for uf in files:
            target = os.path.join(stage, safe_rel(uf.filename))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                shutil.copyfileobj(uf.file, f)
        await form.close()
        for r, _, fs in list(os.walk(stage)):
            for f in fs:
                if f.lower().endswith(".zip"):
                    z = os.path.join(r, f)
                    extract_zip(z, os.path.join(r, f[:-4]))
                    os.remove(z)

        # 2. split into scans, one job each
        scans = find_scans(stage)
        if not scans:
            raise HTTPException(400, "No CT found in the upload. Upload a DICOM folder, a .zip of one, "
                                     "or a CT .nii/.nii.gz file (mask files are ignored).")
        few = [s for s in scans if s["kind"] == "DICOM" and s["n_files"] < MIN_SLICES]
        if few:
            s = few[0]
            raise HTTPException(400, f"Only {s['n_files']} DICOM file(s) for {s['name']}. A CT series has many slices "
                                     f"(one file per slice). Use 'Choose folder' and select the whole series folder, "
                                     f"not single files.")
        created = []
        for i, s in enumerate(scans):
            jid = new_job_id()
            inp = os.path.join(job_dir(jid), "input")
            os.makedirs(inp)
            if s["kind"] == "NIfTI":
                src = s["paths"][0]
                input_path = os.path.join(inp, os.path.basename(src))
                shutil.move(src, input_path)
            else:
                for k, d in enumerate(s["paths"]):
                    shutil.move(d, os.path.join(inp, f"{k:03d}_{os.path.basename(d) or 'dicom'}"))
                input_path = inp
            if len(scans) > 1:
                jl = f"{label} · {s['name']}" if label else s["name"]
            else:
                jl = label
            j = dict(id=jid, label=jl, status="queued", created=time.time() + i * 1e-3, files=s["n_files"],
                     input_path=input_path, input_kind=s["kind"], height_m=h, weight_kg=weight_kg,
                     sex=sex, step=-1, log_tail=[], batch_size=len(scans), name=s["name"])
            jobs[jid] = j
            save_job(j)
            work_q.put(jid)
            created.append(j)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    out = public(created[0])
    out["jobs"] = [public(j) for j in created]
    return out


def public(j):
    d = {k: v for k, v in j.items() if k not in ("input_path",)}
    d["steps"] = [s[1] for s in STEPS]
    d["queue_position"] = None
    if j["status"] == "queued":
        waiting = sorted((x for x in jobs.values() if x["status"] == "queued"), key=lambda x: x["created"])
        d["queue_position"] = [x["id"] for x in waiting].index(j["id"]) + 1
    d["now"] = time.time()
    return d


@app.get("/api/jobs")
def list_jobs():
    return [{k: j.get(k) for k in ("id", "label", "name", "status", "created", "patient_id", "height_m", "sex")}
            for j in sorted(jobs.values(), key=lambda x: x["created"], reverse=True)]


# ---------- database: all stored results ----------
@app.get("/api/db/results")
def db_results(q: str = "", sex: str = "", flag: str = ""):
    return {"counts": db.counts(), "db_path": db.DB_PATH,
            "rows": db.search(q=q.strip(), sex=report.norm_sex(sex), flag=flag)}


@app.get("/api/db/export.csv")
def db_export(q: str = "", sex: str = "", flag: str = ""):
    import io
    from fastapi.responses import Response
    buf = io.StringIO()
    db.export_csv(buf, q=q.strip(), sex=report.norm_sex(sex), flag=flag)
    name = time.strftime("l3_all_results_%Y%m%d.csv")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/jobs/{jid}")
def get_job(jid: str):
    if jid not in jobs:
        raise HTTPException(404, "No such analysis")
    return public(jobs[jid])


@app.get("/api/jobs/{jid}/file/{name}")
def get_file(jid: str, name: str, download: int = 0):
    if jid not in jobs or name not in DOWNLOADS:
        raise HTTPException(404)
    p = os.path.join(job_dir(jid), "output", DOWNLOADS[name])
    if not os.path.exists(p):
        raise HTTPException(404, "File not made yet")
    pid = re.sub(r"[^A-Za-z0-9_.-]", "_", jobs[jid].get("patient_id") or jid)
    return FileResponse(p, filename=f"{pid}_{name}" if download else None)


@app.delete("/api/jobs/{jid}")
def delete_job(jid: str):
    j = jobs.get(jid)
    if not j:
        raise HTTPException(404)
    if j["status"] == "running":
        raise HTTPException(409, "Cannot delete while it is running")
    j["status"] = "deleted"
    jobs.pop(jid, None)
    shutil.rmtree(job_dir(jid), ignore_errors=True)
    try:
        db.delete_analysis(jid)
    except Exception as e:
        print("DB warning:", e)
    return {"ok": True}


if __name__ == "__main__":
    if not os.path.exists(L3_SCRIPT):
        print(f"WARNING: {L3_SCRIPT} not found. Set L3_SCRIPT=/path/to/l3_analysis.py")
    load_old_jobs()
    threading.Thread(target=worker, daemon=True).start()  # one analysis at a time (CPU)
    print(f"  Database: {db.DB_PATH}  {db.counts()}")
    print(f"\n  L3 app running:  open http://localhost:{PORT}  in your browser\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
