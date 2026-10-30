# L3 Body Composition

CT scan → finds the L3 vertebra → segments left/right psoas, skeletal muscle, SAT, VAT and IMAT on the
mid-L3 slice → SMI, PMI, areas, HU and LOW/NORMAL/HIGH flags → colour report (PNG/PDF), CSV and masks.

Runs in Docker on Windows, Mac or Linux. **Research use only** — baseline pre-trained models, not clinically validated.

## Run

Requires Docker Desktop and ~8 GB RAM for Docker.

**Option A — build from this repository** (needs internet, ~4 GB download, 10–30 min the first time):

```
docker compose up -d --build
```

**Option B — ready-made image** (`l3app_image.tar`, shared separately, no internet needed):

```
docker load -i l3app_image.tar
docker compose up -d
```

Then open **http://localhost:8000**. Stop with `docker compose down`.

One scan takes 15–30 min on CPU. Results are saved in `l3_data/` (created on first start, not in git).

## Pipeline

| Step | Tool |
|---|---|
| L3 vertebra + left/right iliopsoas | TotalSegmentator v2 (3D nnU-Net) |
| Muscle, SAT, VAT, IMAT | Comp2Comp `Task927_FatMuscle` (2D nnU-Net v1) |
| Measurements, indices, flags | `l3_analysis.py` |
| Report, web app, database | `l3_app/` (FastAPI, SQLite) |

- SMA = muscle ∪ left psoas ∪ right psoas, HU −29…150. Fat HU −190…−30.
- SMI = SMA / height². PMI (area) = (R + L psoas area) / height². PMI (diam) = (A·B + C·D) / height².
- Low psoas density: left psoas mean HU ≤ 26.85.
- Cut-offs: `CUTOFFS` in `l3_app/report.py`. See `L3 Body Composition Guide` for what each value means.

## Repository

```
Dockerfile               image build (Python 3.10, PyTorch 2.5.1 CPU, models downloaded at build time)
docker/                  requirements.txt, download_models.py
docker-compose.yml       port 8000, l3_data volume, shm 4 GB
l3_analysis.py           the pipeline (also usable on its own, see below)
l3_app/                  web app: app.py, report.py, db.py, static/index.html
```

Pipeline without the web app:

```
docker compose exec l3app python /app/l3_analysis.py -i /data/in/PATIENT -o /data/out/PATIENT --height 1.70
```

## Notes

- PyTorch is pinned to 2.5.1: torch ≥ 2.6 cannot load the nnU-Net checkpoints.
- `l3_data/` holds patient scans and results — never commit it (it is in `.gitignore`).
- CPU only: ~15–30 min per scan.
