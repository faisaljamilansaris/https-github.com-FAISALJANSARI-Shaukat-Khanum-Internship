"""
Give the risk for new patients, using a saved model. No training happens here.

Run from the main cancer-risk folder:
    python code/predict.py <model> <patients file>
Examples:
    python code/predict.py nhamcs data/new_patients_example.csv

The patients file uses the standard column names (see code/common.py). Empty cells are allowed: the model works with
what is known. Temperature in C (a column named temperature_f is converted).

For each patient and outcome it prints: the risk (%), HIGH or LOW, the main
reasons, and what happened to the most similar past patients.
Results are also saved in results/predictions_<model>.csv
"""

import sys
import os
import json
import pandas as pd
import xgboost as xgb
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.neighbors import NearestNeighbors
from common import CLEAN_DIR, MODEL_DIR, RESULT_DIR, f_to_c

# EXAMPLE lines only (%): at or above the line = HIGH. A doctor must set the real lines.
LINE = {"admitted": 50, "serious": 10}
K = 50     # how many similar past patients to look at

name = sys.argv[1] if len(sys.argv) > 1 else "nhamcs"
patients_file = sys.argv[2] if len(sys.argv) > 2 else "data/new_patients_example.csv"

with open(f"{MODEL_DIR}/{name}_info.json") as f:
    info = json.load(f)
inputs, outcomes = info["inputs"], info["outcomes"]

# new patients
new = pd.read_csv(patients_file)
if "temperature_c" not in new.columns and "temperature_f" in new.columns:
    new["temperature_c"] = f_to_c(new["temperature_f"])
X_new = new.reindex(columns=inputs).apply(pd.to_numeric, errors="coerce")
labels = new["patient"] if "patient" in new.columns else pd.Series(
    [f"Patient {i + 1}" for i in range(len(new))])

# similar past patients, from the table the model learned from
past = pd.read_csv(f"{CLEAN_DIR}/{name}.csv")
prepare = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
finder = NearestNeighbors(n_neighbors=min(K, len(past))).fit(prepare.fit_transform(past[inputs]))
_, similar_rows = finder.kneighbors(prepare.transform(X_new))

results = pd.DataFrame({"patient": labels})
for outcome in outcomes:
    model = xgb.XGBClassifier()
    model.load_model(f"{MODEL_DIR}/{name}_{outcome}.json")
    results[f"{outcome}_risk_%"] = (100 * model.predict_proba(X_new)[:, 1]).round(1)
    results[f"{outcome}_label"] = ["HIGH" if r >= LINE.get(outcome, 50) else "LOW"
                                   for r in results[f"{outcome}_risk_%"]]
    contrib = model.get_booster().predict(xgb.DMatrix(X_new), pred_contribs=True)[:, :-1]
    reasons = []
    for i in range(len(new)):
        c = pd.Series(contrib[i], index=inputs).sort_values(ascending=False)
        up = [f"{col}={'empty' if pd.isna(X_new.iloc[i][col]) else round(X_new.iloc[i][col], 1)}"
              for col in c.index[:3] if c[col] > 0]
        reasons.append(", ".join(up) if up else "-")
    results[f"{outcome}_reasons"] = reasons
    results[f"{outcome}_similar"] = [int(past.iloc[r][outcome].sum()) for r in similar_rows]

print(f"Model: {name} | similar patients looked at: {min(K, len(past))}")
print("Lines used (examples only):", {o: LINE.get(o, 50) for o in outcomes})
for i, row in results.iterrows():
    known = int(X_new.iloc[i].notna().sum())
    print(f"\n{row['patient']}  (known inputs: {known} of {len(inputs)})")
    for o in outcomes:
        print(f"   {o:9s} risk: {row[f'{o}_risk_%']:5.1f}%  -> {row[f'{o}_label']:4s}"
              f" (average: {100 * info['average'][o]:.1f}%)")
        print(f"             main reasons up: {row[f'{o}_reasons']}")
        print(f"             similar past patients: {row[f'{o}_similar']} of {min(K, len(past))} had it")

os.makedirs(RESULT_DIR, exist_ok=True)
results.to_csv(f"{RESULT_DIR}/predictions_{name}.csv", index=False)
print(f"\nSaved in {RESULT_DIR}/predictions_{name}.csv")
