"""
Download the model weights into the Docker image (runs once, during `docker compose build`).

  - TotalSegmentator v2 weights (tasks 291-295 + 298, ~1.5 GB, from GitHub)  -> $TOTALSEG_HOME_DIR
  - Comp2Comp muscle/fat model Task927_FatMuscle (from Hugging Face)           -> $L3_MODEL

So the finished image works offline, and nothing is downloaded while a scan is running.
"""
import json
import os
import shutil
import sys
import urllib.request
import zipfile

TS_HOME = os.environ["TOTALSEG_HOME_DIR"]
L3_MODEL = os.environ["L3_MODEL"]
HF = "https://huggingface.co/stanfordmimi/multilevel_muscle_adipose_tissue/resolve/main/"


def fetch(url, dest):
    print("  downloading", url, flush=True)
    tmp = dest + ".part"
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 20)
    os.replace(tmp, dest)


def totalsegmentator():
    os.makedirs(TS_HOME, exist_ok=True)
    # no usage statistics sent from a medical app; no first-run message
    with open(os.path.join(TS_HOME, "config.json"), "w") as f:
        json.dump({"totalseg_id": "totalseg_l3docker", "send_usage_stats": False,
                   "prediction_counter": 0, "statistics_disclaimer_shown": True}, f, indent=4)
    from totalsegmentatorv2.config import setup_nnunet
    setup_nnunet()
    from totalsegmentatorv2.libs import download_pretrained_weights
    # 291-295 = the 5 parts of the "total" model (L3 is in 292, iliopsoas in 293; TS loads all 5),
    # 298 = 6 mm body model that TotalSegmentator uses first to crop when roi_subset is given
    for tid in (291, 292, 293, 294, 295, 298):
        print(f"TotalSegmentator weights, task {tid}", flush=True)
        download_pretrained_weights(tid)


def comp2comp_muscle_fat():
    os.makedirs(L3_MODEL, exist_ok=True)
    if not os.path.exists(os.path.join(L3_MODEL, "all", "model_final_checkpoint.model")):
        z = os.path.join(L3_MODEL, "all.zip")
        fetch(HF + "all.zip", z)
        with zipfile.ZipFile(z) as zf:
            zf.extractall(L3_MODEL)
        os.remove(z)
    if not os.path.exists(os.path.join(L3_MODEL, "plans.pkl")):
        fetch(HF + "plans.pkl", os.path.join(L3_MODEL, "plans.pkl"))
    for need in ("plans.pkl", "all/model_final_checkpoint.model", "all/model_final_checkpoint.model.pkl"):
        if not os.path.exists(os.path.join(L3_MODEL, need)):
            sys.exit(f"ERROR: muscle/fat model incomplete, missing {need}")
    print("Comp2Comp muscle/fat model ready:", L3_MODEL)


if __name__ == "__main__":
    what = sys.argv[1:] or ["all"]
    if "all" in what or "totalseg" in what:
        totalsegmentator()
    if "all" in what or "musclefat" in what:
        comp2comp_muscle_fat()
