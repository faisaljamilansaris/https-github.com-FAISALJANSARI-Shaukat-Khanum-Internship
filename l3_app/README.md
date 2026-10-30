# L3 Body Composition web app

Upload a CT → the app runs `l3_analysis.py` → one colour report image (and PDF) with SMI, PMI, psoas,
SAT, VAT, IMAT, HU and LOW/HIGH/NORMAL flags, plus CSV and masks.

> **No Ubuntu?** Use the Docker version: see `DOCKER_README.md` in the main folder (Windows/Mac: double-click `start.bat`).

## Install (once, in Ubuntu/WSL)

1. Copy this `l3_app` folder to your WSL home, so you have `~/l3_app/app.py`
   (in File Explorer: `\\wsl$\Ubuntu\home\ifra\l3_app`).
2. Open Ubuntu, then:
   ```
   conda activate c2c_env
   pip install fastapi uvicorn python-multipart
   ```
## Run

```
conda activate c2c_env
cd ~/l3_app
python app.py
```
Open **http://localhost:8000** in Chrome or Edge on Windows. Leave the Ubuntu window open while using it.

- Choose the CT's DICOM folder  or a .zip, or a .nii.gz.
- Type height in cm (needed for SMI/PMI/indices). Weight is optional (BMI for the muscle-HU cut-off).
- Sex: leave "From DICOM" or pick M/F (cut-offs depend on sex).
- One scan takes 15–30 min on CPU; you can close the browser and come back.

Results are kept in `~/l3_app_jobs/<id>/output/` (report.png, report.pdf, results.csv, l3_labels.nii.gz, log.txt).

## Settings

- `L3_SCRIPT=/path/to/l3_analysis.py` (default `~/l3_analysis.py`)
- `L3_JOBS=/path/for/jobs` (default `~/l3_app_jobs`)
- `L3_PORT=8000`
- Cut-offs: edit `CUTOFFS` at the top of `report.py`.

Make a report for an existing result folder without the web page:
```
python ~/l3_app/report.py ~/l3_results/PANCREAS_0001 --sex M --weight 70
```

## Files

- `app.py` — web server, upload, job queue, runs l3_analysis.py
- `report.py` — the colour report image/PDF and cut-off flags
- `static/index.html` — the page
- `PROJECT_CONTEXT.md` — everything about the project (attach it in a new Claude chat)

## Database (SQLite)

Every analysis and its results are saved automatically in `~/l3_app_jobs/l3_app.db` (one file, no server needed).

- Tables: `patients`, `analyses` (status, settings, times), `results` (all measurements + LOW/NORMAL/HIGH flags).
  Images, masks and reports stay as files; the database stores where they are.
- In the app: **🗄️ All results** → search, filter (low SMI, low PMI, low psoas density, high VAT…), export to Excel (CSV).
- Analyses done before the database existed are added automatically when the app starts.
- From the command line (in `~/l3_app`):
  ```
  python db.py show                                   # list everything
  python db.py import ~/l3_results/PANCREAS_0001 --sex M   # add a result made with l3_analysis.py directly
  python db.py export ~/all_results.csv               # everything to one CSV
  ```
- To look inside with SQL: `sqlite3 ~/l3_app_jobs/l3_app.db` (install with `sudo apt install sqlite3`), e.g.
  `SELECT patient_key, SMI, SMI_status FROM results JOIN analyses ON analyses.id = results.analysis_id JOIN patients ON patients.id = analyses.patient_ref;`
