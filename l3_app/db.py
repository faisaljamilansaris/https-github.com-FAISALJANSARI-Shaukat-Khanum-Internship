"""
SQLite database for the L3 app.

One file (default ~/l3_app_jobs/l3_app.db) with three tables:

  patients  - one row per patient (patient ID from DICOM, or the scan name for NIfTI files)
  analyses  - one row per analysis/job: status, settings, timings, where the files are
  results   - one row per finished analysis: every measurement + LOW/NORMAL/HIGH flags

Images, masks and reports stay as files on disk; the database stores where they are.

Command line (run inside ~/l3_app with c2c_env active):
  python db.py show                          # list everything in the database
  python db.py import ~/l3_results/PANCREAS_0001 [--sex M] [--weight 70]
                                             # add a result folder made by l3_analysis.py on the command line
  python db.py export all_results.csv        # all results to one CSV (opens in Excel)
"""
import argparse
import csv
import json
import os
import sqlite3
import threading
import time

DB_PATH = os.environ.get("L3_DB", os.path.join(os.environ.get("L3_JOBS", os.path.expanduser("~/l3_app_jobs")), "l3_app.db"))
_lock = threading.Lock()

# result columns copied from results.csv (same names as l3_analysis.py)
RESULT_COLS = [
    "study_date", "series_uid", "contrast_agent", "slice_thickness_mm", "pixel_spacing_mm",
    "L3_slice_index", "L3_slice_range", "height_m", "height_source",
    "SMA_cm2", "SMI", "muscle_HU_mean", "muscle_HU_sd",
    "psoas_R_area_cm2", "psoas_L_area_cm2", "psoas_total_area_cm2",
    "psoas_R_A_mm", "psoas_R_B_mm", "psoas_L_C_mm", "psoas_L_D_mm",
    "PMI_diam", "PMI_area", "psoas_R_HU_mean", "psoas_R_HU_sd", "psoas_L_HU_mean", "psoas_L_HU_sd",
    "low_psoas_density", "psoas_HU_cutoff",
    "SAT_cm2", "SATI", "VAT_cm2", "VATI", "IMAT_cm2", "models", "masks",
]
TEXT_COLS = {"study_date", "series_uid", "contrast_agent", "pixel_spacing_mm", "L3_slice_range",
             "height_source", "models", "masks"}
# flags taken from the report table (report.evaluate): column -> row name starts with
FLAG_COLS = {
    "SMI_status": "SMI",
    "PMI_area_status": "PMI (area)",
    "muscle_HU_status": "Muscle density",
    "psoas_L_HU_status": "Left psoas density",
    "VAT_status": "VAT",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS patients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_key TEXT UNIQUE NOT NULL,     -- DICOM PatientID, or scan name for NIfTI
    patient_id  TEXT,                     -- DICOM PatientID ('' for NIfTI)
    sex         TEXT,
    age         TEXT,
    created_at  TEXT,
    updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
    id          TEXT PRIMARY KEY,         -- job id, e.g. 20261029-111224-ab12cd
    patient_ref INTEGER REFERENCES patients(id),
    label       TEXT,
    name        TEXT,
    status      TEXT,                     -- queued / running / done / error
    error       TEXT,
    input_kind  TEXT,                     -- DICOM / NIfTI / CLI
    n_files     INTEGER,
    height_m    REAL,                     -- as typed by the user (NULL = from DICOM)
    weight_kg   REAL,
    sex         TEXT,                     -- as chosen by the user ('' = from DICOM)
    created_at  TEXT,
    started_at  TEXT,
    finished_at TEXT,
    output_dir  TEXT
);
CREATE TABLE IF NOT EXISTS results (
    analysis_id TEXT PRIMARY KEY REFERENCES analyses(id) ON DELETE CASCADE,
    sex TEXT, age TEXT, bmi REAL,
    {cols},
    {flags},
    saved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_analyses_patient ON analyses(patient_ref);
""".format(
    cols=",\n    ".join(f"{c} {'TEXT' if c in TEXT_COLS else 'REAL'}" for c in RESULT_COLS),
    flags=",\n    ".join(f"{c} TEXT" for c in FLAG_COLS),
)


def ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init():
    with _lock, connect() as c:
        c.execute("PRAGMA journal_mode = WAL")
        c.executescript(SCHEMA)


def _clean(v):
    """pandas NaN / numpy types -> plain Python, '' -> None."""
    if v is None:
        return None
    try:
        import numpy as np
        if isinstance(v, np.generic):
            v = v.item()
    except ImportError:
        pass
    if isinstance(v, float) and v != v:
        return None
    if isinstance(v, str) and v.strip() in ("", "nan", "NaN"):
        return None
    return v


def _patient(c, key, patient_id="", sex=None, age=None):
    key = (key or "unknown").strip()
    now = ts(time.time())
    row = c.execute("SELECT id FROM patients WHERE patient_key = ?", (key,)).fetchone()
    if row:
        c.execute("UPDATE patients SET sex = COALESCE(?, sex), age = COALESCE(?, age), updated_at = ? WHERE id = ?",
                  (_clean(sex), _clean(age), now, row["id"]))
        return row["id"]
    cur = c.execute("INSERT INTO patients (patient_key, patient_id, sex, age, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)", (key, patient_id or "", _clean(sex), _clean(age), now, now))
    return cur.lastrowid


def save_analysis(j, output_dir=None):
    """Insert or update one analysis row from the app's job dict."""
    key = j.get("patient_id") or j.get("name") or j.get("label") or j["id"]
    with _lock, connect() as c:
        pref = _patient(c, key, j.get("patient_id") or "", j.get("sex") or None)
        c.execute("""
            INSERT INTO analyses (id, patient_ref, label, name, status, error, input_kind, n_files, height_m,
                                  weight_kg, sex, created_at, started_at, finished_at, output_dir)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET patient_ref=excluded.patient_ref, label=excluded.label,
                status=excluded.status, error=excluded.error, started_at=excluded.started_at,
                finished_at=excluded.finished_at, output_dir=COALESCE(excluded.output_dir, output_dir)
        """, (j["id"], pref, j.get("label"), j.get("name"), j.get("status"), j.get("error"), j.get("input_kind"),
              j.get("files"), j.get("height_m"), j.get("weight_kg"), j.get("sex"), ts(j.get("created")),
              ts(j.get("started")), ts(j.get("finished")), output_dir))


def save_results(analysis_id, res, rows=None, sex=None, bmi=None):
    """Store one results.csv row (+ flags from the report table) for an analysis."""
    rows = rows or []
    flags = {}
    for col, prefix in FLAG_COLS.items():
        r = next((r for r in rows if r.get("name", "").startswith(prefix)), None)
        flags[col] = (r or {}).get("status") or None
    vals = {c: _clean(res.get(c)) for c in RESULT_COLS}
    if isinstance(vals.get("low_psoas_density"), str):
        vals["low_psoas_density"] = {"true": 1, "false": 0}.get(vals["low_psoas_density"].lower())
    cols = ["analysis_id", "sex", "age", "bmi"] + RESULT_COLS + list(FLAG_COLS) + ["saved_at"]
    data = [analysis_id, _clean(sex or res.get("sex")), _clean(res.get("age")), _clean(bmi)] + \
           [vals[c] for c in RESULT_COLS] + [flags[c] for c in FLAG_COLS] + [ts(time.time())]
    with _lock, connect() as c:
        c.execute(f"INSERT OR REPLACE INTO results ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", data)
        # keep the patient's sex/age up to date from the DICOM header
        c.execute("""UPDATE patients SET sex = COALESCE(?, sex), age = COALESCE(?, age)
                     WHERE id = (SELECT patient_ref FROM analyses WHERE id = ?)""",
                  (_clean(sex or res.get("sex")), _clean(res.get("age")), analysis_id))


def delete_analysis(analysis_id):
    with _lock, connect() as c:
        c.execute("DELETE FROM results WHERE analysis_id = ?", (analysis_id,))
        c.execute("DELETE FROM analyses WHERE id = ?", (analysis_id,))
        c.execute("DELETE FROM patients WHERE id NOT IN (SELECT patient_ref FROM analyses WHERE patient_ref IS NOT NULL)")


def has_results(analysis_id):
    with connect() as c:
        return c.execute("SELECT 1 FROM results WHERE analysis_id = ?", (analysis_id,)).fetchone() is not None


SEARCH_SQL = """
SELECT a.id, a.label, a.name, a.status, a.input_kind, a.created_at, a.finished_at,
       p.patient_key, p.patient_id, COALESCE(r.sex, p.sex) AS sex, COALESCE(r.age, p.age) AS age, r.bmi,
       {cols}
FROM analyses a
LEFT JOIN patients p ON p.id = a.patient_ref
LEFT JOIN results r ON r.analysis_id = a.id
""".format(cols=", ".join(f"r.{c}" for c in RESULT_COLS + list(FLAG_COLS)))


def search(q="", sex="", flag="", status="done", limit=1000):
    """Results joined with analysis + patient. flag = e.g. 'SMI_status=LOW' or 'any_low'."""
    where, args = [], []
    if status:
        where.append("a.status = ?"); args.append(status)
    if q:
        where.append("(p.patient_key LIKE ? OR a.label LIKE ? OR a.id LIKE ?)"); args += [f"%{q}%"] * 3
    if sex:
        where.append("COALESCE(r.sex, p.sex) = ?"); args.append(sex)
    if flag == "any_low":
        where.append("(" + " OR ".join(f"r.{c} IN ('LOW','HIGH')" for c in FLAG_COLS) + ")")
    elif flag and "=" in flag:
        col, val = flag.split("=", 1)
        if col in FLAG_COLS:
            where.append(f"r.{col} = ?"); args.append(val)
    sql = SEARCH_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY a.created_at DESC LIMIT ?"
    with connect() as c:
        return [dict(row) for row in c.execute(sql, args + [limit])]


def counts():
    with connect() as c:
        return dict(
            patients=c.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
            analyses=c.execute("SELECT COUNT(*) FROM analyses").fetchone()[0],
            results=c.execute("SELECT COUNT(*) FROM results").fetchone()[0],
        )


EXPORT_COLS = ["id", "patient_key", "label", "sex", "age", "created_at"] + ["bmi"] + RESULT_COLS + list(FLAG_COLS)


def export_csv(path_or_file, **filters):
    rows = search(**filters, limit=1_000_000)
    own = isinstance(path_or_file, str)
    f = open(path_or_file, "w", newline="", encoding="utf-8") if own else path_or_file
    try:
        w = csv.writer(f)
        w.writerow(EXPORT_COLS)
        for r in rows:
            w.writerow(["" if r.get(c) is None else r.get(c) for c in EXPORT_COLS])
    finally:
        if own:
            f.close()
    return len(rows)


# ----------------------------------------------------------------------------
# Importing results that already exist on disk
# ----------------------------------------------------------------------------
def import_folder(out_dir, sex=None, weight_kg=None, name=None):
    """Add a folder made by l3_analysis.py (results.csv) to the database as a finished analysis."""
    import pandas as pd
    out_dir = os.path.abspath(os.path.expanduser(out_dir))
    res = pd.read_csv(os.path.join(out_dir, "results.csv")).iloc[0].to_dict()
    ev_path = os.path.join(out_dir, "evaluation.json")
    rows, bmi = [], None
    if os.path.exists(ev_path):
        ev = json.load(open(ev_path))
        rows, bmi, sex = ev.get("rows", []), ev.get("bmi"), sex or ev.get("sex")
    else:
        try:
            import report
            s = report.norm_sex(sex) or report.norm_sex(res.get("sex"))
            h = report.num(res.get("height_m"))
            bmi = (float(weight_kg) / h ** 2) if (weight_kg and h) else None
            rows = report.evaluate(res, s, bmi)
            sex = s
        except Exception as e:
            print("  (flags not computed:", e, ")")
    pid = str(_clean(res.get("patient_id")) or "")
    jid = "cli-" + os.path.basename(out_dir.rstrip("/"))
    mtime = os.path.getmtime(os.path.join(out_dir, "results.csv"))
    j = dict(id=jid, label=name or os.path.basename(out_dir), name=name or os.path.basename(out_dir),
             patient_id=pid, status="done", input_kind="CLI", files=None, height_m=_clean(res.get("height_m")),
             weight_kg=weight_kg, sex=sex or "", created=mtime, started=mtime, finished=mtime)
    save_analysis(j, out_dir)
    save_results(jid, res, rows, sex, bmi)
    return jid


def import_app_jobs(jobs_dir):
    """Add all app jobs (job.json folders) that are not in the database yet. Returns number added."""
    n = 0
    for jid in sorted(os.listdir(jobs_dir)):
        p = os.path.join(jobs_dir, jid, "job.json")
        if not os.path.exists(p):
            continue
        try:
            j = json.load(open(p))
        except Exception:
            continue
        if j.get("results") and not j.get("patient_id"):
            j["patient_id"] = str(j["results"].get("patient_id") or "")
        save_analysis(j, os.path.join(jobs_dir, jid, "output"))
        if j.get("status") == "done" and j.get("results") and not has_results(jid):
            ev_path = os.path.join(jobs_dir, jid, "output", "evaluation.json")
            ev = json.load(open(ev_path)) if os.path.exists(ev_path) else {}
            save_results(jid, j["results"], j.get("rows") or ev.get("rows"), ev.get("sex") or j.get("sex"), ev.get("bmi"))
            n += 1
    return n


# ----------------------------------------------------------------------------
# Command line
# ----------------------------------------------------------------------------
def _show():
    rows = search(status="", limit=500)
    print(f"Database: {DB_PATH}\n{counts()}\n")
    print(f"{'patient':<18} {'status':<7} {'sex':<4} {'SMI':>6} {'flag':<7} {'PMI(a)':>7} {'flag':<7} "
          f"{'L psoas HU':>10} {'VAT':>7}  id")
    for r in rows:
        f = lambda k, d=1: "" if r.get(k) is None else f"{r[k]:.{d}f}"
        print(f"{(r.get('patient_key') or '')[:18]:<18} {r['status'] or '':<7} {r.get('sex') or '':<4} "
              f"{f('SMI'):>6} {r.get('SMI_status') or '':<7} {f('PMI_area', 2):>7} {r.get('PMI_area_status') or '':<7} "
              f"{f('psoas_L_HU_mean'):>10} {f('VAT_cm2'):>7}  {r['id']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="L3 app database")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="list analyses and results")
    pi = sub.add_parser("import", help="add a result folder made by l3_analysis.py")
    pi.add_argument("folders", nargs="+")
    pi.add_argument("--sex", default=None)
    pi.add_argument("--weight", type=float, default=None)
    pe = sub.add_parser("export", help="write all results to a CSV file")
    pe.add_argument("csv")
    a = ap.parse_args()
    init()
    if a.cmd == "show":
        _show()
    elif a.cmd == "import":
        for fo in a.folders:
            print("imported", fo, "->", import_folder(fo, a.sex, a.weight))
    elif a.cmd == "export":
        print(f"{export_csv(a.csv)} rows written to {a.csv}")
