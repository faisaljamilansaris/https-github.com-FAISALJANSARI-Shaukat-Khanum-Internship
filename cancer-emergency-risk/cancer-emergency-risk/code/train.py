"""
Learn and test on one standard table, then save the learned models.
Works the same for every dataset: it uses whichever inputs and outcomes the table has.

Run from the main cancer-risk folder, after the matching prepare file:
    python code/train.py nhamcs
    python code/train.py yale

What it prints, for each outcome (admitted, serious):
  1. AUC (5 test rounds) for: triage level alone, all inputs without triage, all inputs,
     with logistic regression and XGBoost. 0.5 = guessing, 1.0 = perfect.
  2. Which inputs matter most (how much the AUC drops when one input is mixed up).
Saves: models/<dataset>_<outcome>.json, models/<dataset>_info.json,
       results/scores_<dataset>.csv
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from sklearn.model_selection import (StratifiedKFold, StratifiedGroupKFold,
                                     cross_val_score, train_test_split)
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier
from common import CLEAN_DIR, MODEL_DIR, RESULT_DIR, INPUTS, OUTCOMES, ID_COLUMN

name = sys.argv[1] if len(sys.argv) > 1 else "nhamcs"
df = pd.read_csv(f"{CLEAN_DIR}/{name}.csv")

inputs = [c for c in INPUTS if c in df.columns and df[c].notna().any()]
outcomes = [o for o in OUTCOMES if o in df.columns and df[o].nunique() == 2]
X = df[inputs].astype(float)

# keep all visits of one patient on the same side when testing, if we know the patient
if ID_COLUMN in df.columns:
    cv = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    groups = df[ID_COLUMN]
    print("Testing keeps each patient's visits together (patient_id found)")
else:
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    groups = None

depth = 3 if len(df) < 10000 else 4        # smaller trees for small data


def logistic():
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                         LogisticRegression(max_iter=1000, class_weight="balanced"))


def xgboost():
    return XGBClassifier(n_estimators=300, max_depth=depth, learning_rate=0.05,
                         subsample=0.8, eval_metric="logloss")


def title(text):
    print("\n" + "=" * 70 + "\n" + text + "\n" + "=" * 70)


print("Dataset:", name, "| rows:", len(df), "| inputs used:", len(inputs))
print("Inputs:", inputs)

os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(RESULT_DIR, exist_ok=True)
rows = []
info = {"dataset": name, "inputs": inputs, "outcomes": outcomes, "average": {}}

for outcome in outcomes:
    y = df[outcome]
    info["average"][outcome] = float(y.mean())
    title(f"Outcome: {outcome} | with outcome: {int(y.sum())} of {len(y)} ({100 * y.mean():.1f}%)")

    # 1. scores
    sets = {}
    if "triage_level" in inputs:
        sets["Triage level alone"] = ["triage_level"]
        sets["All inputs without triage"] = [c for c in inputs if c != "triage_level"]
    sets["All inputs"] = inputs
    for set_name, cols in sets.items():
        for model_name, model in [("Logistic regression", logistic()), ("XGBoost", xgboost())]:
            scores = cross_val_score(model, X[cols], y, cv=cv, groups=groups, scoring="roc_auc")
            print(f"   {set_name:26s} | {model_name:19s} | inputs: {len(cols):2d}"
                  f" | AUC: {scores.mean():.3f} | spread: {scores.std():.3f}")
            rows.append({"dataset": name, "outcome": outcome, "inputs": set_name,
                         "model": model_name, "n_inputs": len(cols),
                         "auc": round(scores.mean(), 3), "spread": round(scores.std(), 3)})

    # 2. which inputs matter most (XGBoost, hidden 20%)
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, stratify=y, random_state=42)
    m = xgboost().fit(X_tr, y_tr)
    base = roc_auc_score(y_te, m.predict_proba(X_te)[:, 1])
    rng = np.random.default_rng(42)
    drops = {}
    for col in inputs:
        d = []
        for _ in range(5):
            X_mix = X_te.copy()
            X_mix[col] = rng.permutation(X_mix[col].values)
            d.append(base - roc_auc_score(y_te, m.predict_proba(X_mix)[:, 1]))
        drops[col] = np.mean(d)
    print(f"\n   Most important inputs (XGBoost, hidden 20% AUC {base:.3f}):")
    for i, (col, drop) in enumerate(pd.Series(drops).sort_values(ascending=False).items(), 1):
        print(f"   {i:2d}. {col:24s} {drop:6.3f}  {'#' * int(max(drop, 0) * 300)}")

    # 3. final model: learn from ALL rows and save it for predict.py
    final = xgboost().fit(X, y)
    final.save_model(f"{MODEL_DIR}/{name}_{outcome}.json")

with open(f"{MODEL_DIR}/{name}_info.json", "w") as f:
    json.dump(info, f, indent=2)
pd.DataFrame(rows).to_csv(f"{RESULT_DIR}/scores_{name}.csv", index=False)
print(f"\nSaved models in {MODEL_DIR}/ and scores in {RESULT_DIR}/scores_{name}.csv")
