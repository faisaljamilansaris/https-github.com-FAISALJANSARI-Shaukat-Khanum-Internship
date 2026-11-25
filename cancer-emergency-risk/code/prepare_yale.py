"""
Prepare the Yale data: keep visits of patients with cancer and save the
standard table data/clean/yale.csv. Outcome: admitted (Yale has no ICU or death).

Data: data/5v_cleandf.RData (slow to open: 5-15 minutes).
If data/yale_cancer.pkl already exists from an earlier run, it is used instead.
Run from the main cancer-risk folder:
    python code/prepare_yale.py
"""

import os
import pandas as pd
from common import CLEAN_DIR, f_to_c

BIG_FILE = "data/5v_cleandf.RData"
SMALL_FILE = "data/yale_cancer.pkl"

CANCER_COLS = ["2ndarymalig", "bladdercncr", "bonectcncr", "brainnscan", "breastcancr",
               "brnchlngca", "cervixcancr", "coloncancer", "esophcancer", "femgenitca",
               "giperitcan", "hdnckcancr", "hodgkinsds", "kidnyrnlca", "leukemias",
               "liveribdca", "malgenitca", "maligneopls", "multmyeloma", "nonhodglym",
               "otprimryca", "otrespirca", "ovarycancer", "pancreascan", "prostatecan",
               "rctmanusca", "skinmelanom", "stomchcancr", "testiscancr", "thyroidcncr",
               "urinyorgca", "uteruscancr"]
BLOOD_CANCER_COLS = ["leukemias", "hodgkinsds", "nonhodglym", "multmyeloma"]

if os.path.exists(SMALL_FILE):
    print("Using", SMALL_FILE)
    df = pd.read_pickle(SMALL_FILE)
else:
    import rdata
    print("Opening", BIG_FILE, "- please wait, this can take 5-15 minutes...")
    result = rdata.read_rda(BIG_FILE)
    big = result[list(result.keys())[0]]
    print("All visits:", len(big))
    df = big[(big[CANCER_COLS].astype(float) > 0).any(axis=1)].copy()
    del big
    df.to_pickle(SMALL_FILE)


def num(col):
    return pd.to_numeric(df[col].astype(str), errors="coerce")


out = pd.DataFrame({
    "age": num("age"),
    "male": (df["gender"].astype(str) == "Male").astype(float),
    "triage_level": num("esi"),
    "pulse": num("triage_vital_hr"),
    "bp_top": num("triage_vital_sbp"),
    "bp_bottom": num("triage_vital_dbp"),
    "breathing": num("triage_vital_rr"),
    "oxygen": num("triage_vital_o2"),
    "temperature_c": f_to_c(num("triage_vital_temp")),
    "on_oxygen": num("triage_vital_o2_device"),
    "blood_cancer": (df[BLOOD_CANCER_COLS].astype(float) > 0).any(axis=1).astype(float),
    "cancer_spread": num("2ndarymalig"),
    "cancer_medicine": num("meds_antineoplastics"),
    "chemo_or_radio_history": num("maintchemr"),
    "white_cells": num("wbc_last"),
    "neutrophil_count": num("anc(absneutrophilcount)_last"),
    "neutrophil_percent": num("neutrophils_last"),
    "hemoglobin": num("hemoglobin_last"),
    "platelets": num("platelets_last"),
    "creatinine": num("creatinine_last"),
    "glucose": num("glucose_last"),
    "admitted": (df["disposition"].astype(str) == "Admit").astype(int),
})

print("Cancer visits:", len(out), "| admitted:", int(out["admitted"].sum()),
      "| blood cancer:", int(out["blood_cancer"].sum()),
      "| on cancer medicines:", int((out["cancer_medicine"] > 0).sum()))

os.makedirs(CLEAN_DIR, exist_ok=True)
out.to_csv(f"{CLEAN_DIR}/yale.csv", index=False)
print("Saved", len(out), "cancer visits in", f"{CLEAN_DIR}/yale.csv")
