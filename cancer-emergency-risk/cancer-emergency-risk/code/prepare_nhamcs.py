"""
Prepare NHAMCS 2012-2014: count the data, keep cancer patients, and save
the standard table data/clean/nhamcs.csv.

Data: data/ed2012-stata.dta, data/ed2013-stata.dta, data/ed2014-stata.dta
Run from the main cancer-risk folder:
    python code/prepare_nhamcs.py
"""

import os
import numpy as np
import pandas as pd
from common import CLEAN_DIR, f_to_c

FILES = {2012: "data/ed2012-stata.dta",
         2013: "data/ed2013-stata.dta",
         2014: "data/ed2014-stata.dta"}
NEED = ["AGE", "SEX", "TEMPF", "PULSE", "RESPR", "BPSYS", "BPDIAS", "POPCT",
        "PAINSCALE", "IMMEDR", "TOTCHRON", "CANCER", "ADMITHOS", "ADMIT", "DIEDED", "HDSTAT"]

frames = []
for year, f in FILES.items():
    d = pd.read_stata(f, convert_categoricals=False)
    d.columns = d.columns.str.upper()
    d = d[NEED].copy()
    d["YEAR"] = year
    frames.append(d)
v = pd.concat(frames, ignore_index=True)

admitted = (v["ADMITHOS"] == 1).astype(int)
icu = (v["ADMIT"] == 1).astype(int)                                  # critical care unit
died = ((v["DIEDED"] == 1) | (v["HDSTAT"] == 2)).astype(int)         # died in ED or in hospital
serious = ((icu == 1) | (died == 1)).astype(int)

print("Cancer patients and outcomes per year")
for year in list(FILES) + ["Total"]:
    rows = v["YEAR"] == year if year != "Total" else v["YEAR"] > 0
    c = rows & (v["CANCER"] == 1)
    print(f"   {year} | all visits: {int(rows.sum())} | cancer: {int(c.sum())}"
          f" | admitted: {int(admitted[c].sum())} | ICU: {int(icu[c].sum())}"
          f" | died: {int(died[c].sum())} | serious: {int(serious[c].sum())}")

# keep cancer patients and clean the special codes
c = v["CANCER"] == 1
raw = v[c].astype(float).mask(v[c].astype(float) < 0)      # negative codes mean "not recorded"
raw.loc[raw["PULSE"] == 998, "PULSE"] = np.nan
raw.loc[raw["BPDIAS"] == 998, "BPDIAS"] = np.nan
raw.loc[raw["IMMEDR"].isin([0, 7]), "IMMEDR"] = np.nan     # 0 = no triage, 7 = ED does not triage

out = pd.DataFrame({
    "age": raw["AGE"],
    "male": (raw["SEX"] == 2).astype(float),
    "triage_level": raw["IMMEDR"],
    "pulse": raw["PULSE"],
    "bp_top": raw["BPSYS"],
    "bp_bottom": raw["BPDIAS"],
    "breathing": raw["RESPR"],
    "oxygen": raw["POPCT"],
    "temperature_c": f_to_c(raw["TEMPF"] / 10),             # stored in tenths of a degree F
    "pain": raw["PAINSCALE"],
    "disease_count": raw["TOTCHRON"],
    "admitted": admitted[c].values,
    "serious": serious[c].values,
})

os.makedirs(CLEAN_DIR, exist_ok=True)
out.to_csv(f"{CLEAN_DIR}/nhamcs.csv", index=False)
print("\nSaved", len(out), "cancer patients in", f"{CLEAN_DIR}/nhamcs.csv")
