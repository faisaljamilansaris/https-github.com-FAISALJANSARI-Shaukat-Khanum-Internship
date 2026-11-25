# Cancer Emergency Risk Project

A tool that estimates the risk for a **cancer patient who comes to the emergency department**,
using only what is known when the patient arrives: age, sex, vital signs, the nurse's triage
level and, where available, cancer details and blood tests.

For each patient it gives:

- a **risk number** (0 to 100%) for two outcomes: **admitted** to hospital, and **serious**
  (went to ICU or died),
- **HIGH** or **LOW**, compared with a cut-off line,
- the **top 3 reasons** for the risk (for example: low blood pressure, fast pulse),
- how many of the **50 most similar past patients** had that outcome.

Hospital data is not available yet, so the tool was built and tested on two public US
datasets (NHAMCS and Yale). **It is a research prototype, not ready for use on patients.**
The doctor always makes the decision.

---

## 1. How it works, in two stages

1. **Learning (`train.py`, once):** the model studies past patients whose outcome is known
   (who was admitted, who went to ICU or died) and learns which arrival details go with
   which outcome. It is tested on patients it did not learn from, then saved.
2. **Using (`predict.py`, for every new patient):** the saved model reads a new patient's
   arrival details and gives the risk, HIGH/LOW, reasons and similar patients. No learning
   happens here, so it is instant.

```
NHAMCS files → prepare_nhamcs.py ┐
                                  ├→ standard table → train.py → saved model → predict.py → risk
Yale file    → prepare_yale.py   ┘
                 (all files read their settings from common.py)
```

Each dataset names things differently (NHAMCS says `PULSE`, Yale says `triage_vital_hr`).
The **prepare** files translate every dataset into one **standard table** with the same
column names (`pulse`, `oxygen`, `triage_level`, …). Because of this, `train.py` and
`predict.py` are written once and work for every dataset, including hospital data later.

---

## 2. Folder layout

```
cancer-risk/
  README.md
  requirements.txt              Python packages needed
  code/
    common.py                   shared settings: list of inputs, outcomes, folder names
    prepare_nhamcs.py           NHAMCS → data/clean/nhamcs.csv
    prepare_yale.py             Yale   → data/clean/yale.csv
    train.py                    learn + test on a standard table, save the model
    predict.py                  risk for new patients with a saved model
  data/
    new_patients_example.csv    3 made-up new patients, to try predict.py
    (raw data files go here; data/clean/ is made by the prepare files)
  models/                       saved models (made by train.py)
  results/                      scores and predictions (made by train.py and predict.py)
```

| File | What it does | When it runs |
|---|---|---|
| `common.py` | Holds the settings every other file uses. Never run on its own. | Read by the others |
| `prepare_nhamcs.py` | Opens the 3 NHAMCS years, counts patients and outcomes, keeps cancer patients, cleans special codes, saves the standard table | Once |
| `prepare_yale.py` | Opens the Yale file, keeps visits of patients with cancer, saves the standard table | Once (first time is slow) |
| `train.py` | Tests the models 5 times, compares with the triage level alone, ranks the inputs, saves the final model | Once per dataset |
| `predict.py` | Gives risk, HIGH/LOW, reasons and similar patients for a file of new patients | Every time there are new patients |

---

## 3. Data

The data files are not included (they are large). Download them and put them in `data/`.

| Dataset | What it is | Download | Put in `data/` as |
|---|---|---|---|
| **NHAMCS 2012–2014** | US national survey of emergency department visits (CDC) | `ed2012-stata.zip`, `ed2013-stata.zip`, `ed2014-stata.zip` from https://ftp.cdc.gov/pub/health_statistics/nchs/dataset_documentation/NHAMCS/stata/ (unzip them) | `ed2012-stata.dta`, `ed2013-stata.dta`, `ed2014-stata.dta` |
| **Yale** | Emergency visits from one US hospital system, with past history, medicines and blood tests | https://zenodo.org/records/1308993 (inside the zip: `Results/5v_cleandf.RData`) | `5v_cleandf.RData` |

NHAMCS column meanings are in its codebook: https://www.nber.org/nhamcs/docs/doc14_ed.pdf

---

## 4. Setup

Python 3.12 was used. In a terminal, inside the main `cancer-risk` folder:

```
pip install -r requirements.txt
```

This installs `pandas`, `numpy`, `scikit-learn`, `xgboost` and `rdata`.

---

## 5. How to run

Open a terminal **in the main `cancer-risk` folder** (the one that contains `code` and
`data`) and run:

**NHAMCS**

```
python code/prepare_nhamcs.py
python code/train.py nhamcs
python code/predict.py nhamcs data/new_patients_example.csv
```

**Yale** (the first `prepare_yale.py` run opens a large file and takes 5–15 minutes; after
that it uses a saved small copy, `data/yale_cancer.pkl`)

```
python code/prepare_yale.py
python code/train.py yale
python code/predict.py yale data/new_patients_example.csv
```

`train.py` takes about a minute on NHAMCS and a few minutes on Yale. `predict.py` is instant.

**Run button in VS Code:** it works for every file, but it cannot add words after the file
name, so `train.py` and `predict.py` then use NHAMCS and the example patients file. For Yale,
type the command.

---

## 6. Checking a new patient

`predict.py` reads new patients from a CSV file. Each row is one patient; empty cells mean
"not known" and are allowed.

1. Open `data/new_patients_example.csv` in Excel.
2. Add a row, for example:

| patient | age | male | triage_level | pulse | bp_top | bp_bottom | breathing | oxygen | temperature_c | pain | disease_count |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Patient 4 | 55 | 0 | 3 | 104 | 98 | 62 | 22 | 93 | 38.4 | 5 | 1 |

3. Save as CSV (choose "Keep current format"), **close Excel**, and run
   `python code/predict.py nhamcs data/new_patients_example.csv`.

| Column | Meaning |
|---|---|
| `male` | 1 = male, 0 = female |
| `triage_level` | 1 (most urgent) to 5 (least urgent) |
| `pulse`, `breathing` | per minute |
| `bp_top`, `bp_bottom` | blood pressure, e.g. 98 and 62 for 98/62 mmHg |
| `oxygen` | oxygen saturation, % |
| `temperature_c` | °C |
| `pain` | 0 to 10 |
| `disease_count` | number of other long-term diseases |

For the Yale model, extra columns can be added: `on_oxygen`, `blood_cancer`,
`cancer_spread`, `cancer_medicine`, `chemo_or_radio_history` (1/0), and blood tests
`white_cells`, `neutrophil_count`, `neutrophil_percent`, `hemoglobin`, `platelets`,
`creatinine`, `glucose`.

**Reading the output**

```
Patient 1 (looks sick)  (known inputs: 11 of 11)
   admitted  risk:  75.5%  -> HIGH (average: 29.5%)
             main reasons up: temperature_c=38.8, triage_level=2.0, pulse=118.0
             similar past patients: 32 of 50 had it
   serious   risk:  28.6%  -> HIGH (average: 4.8%)
             main reasons up: triage_level=2.0, bp_top=92.0, pulse=118.0
             similar past patients: 3 of 50 had it
```

- **risk:** the model's estimate. 28.6% means about 29 in 100 patients like this went to
  ICU or died.
- **HIGH/LOW:** compared with the line in `predict.py` (`LINE`): 50% for admitted, 10% for
  serious. **These lines are examples only; a doctor must choose the real ones.**
- **average:** the risk of an average past cancer patient, for comparison.
- **main reasons up:** the 3 details that raised the risk the most.
- **similar past patients:** of the 50 most similar past patients, how many had the outcome.

Results are also saved in `results/predictions_<dataset>.csv`.

---

## 7. Inputs

`code/common.py` lists the 33 inputs the system can use: what a nurse and doctor check when a
cancer patient comes to emergency. `train.py` uses every input the data has and skips the
rest, so inputs marked "later" are used automatically when hospital data has them.

| Stage | Used now | Written for later (hospital data) |
|---|---|---|
| **1. Triage (nurse)** | age, sex, triage level, pulse, blood pressure (top and bottom), breathing rate, oxygen, temperature; pain (NHAMCS); on extra oxygen (Yale) | confused or drowsy; came with fever, breathlessness or bleeding |
| **2. Questions and records (doctor)** | number of long-term diseases (NHAMCS); blood cancer, cancer has spread, on cancer medicine, chemo or radiotherapy history (Yale) | days since last chemotherapy, steroids, immunotherapy, ECOG (general condition) |
| **3. First blood tests** | white cells, neutrophil count and %, haemoglobin, platelets, creatinine, glucose (Yale) | calcium, lactate |

NHAMCS uses 11 of these inputs and Yale uses 21. To add an input later, add its name to
`INPUTS` in `code/common.py`.

---

## 8. Methods

**Outcomes**

- **Admitted:** admitted to hospital from the emergency department.
- **Serious:** went to ICU or died (NHAMCS columns `ADMIT = 1`, `DIEDED = 1` or `HDSTAT = 2`).
  Yale records only admission, so it has no "serious" outcome.

**Who counts as a cancer patient**

- NHAMCS: `CANCER = 1`.
- Yale: any of 32 past-history cancer columns is yes (listed in `prepare_yale.py`).

**Models**

| Model | Idea | Role |
|---|---|---|
| Logistic regression | Gives each input a weight and adds them up | Simple baseline, standard in medical research |
| XGBoost | 300 small decision trees, each correcting the last; handles missing values | Main model; the one that is saved and used by `predict.py` |
| Similar patients (k-nearest neighbours) | Finds the 50 past patients most like the new one | Shown next to the risk in `predict.py` |

**Testing**

- **5-fold cross-validation:** patients are split into 5 parts; each round the model learns
  from 4 parts and is tested on the hidden one. The split keeps a fair share of each outcome
  in every part, and is the same on every run (`random_state = 42`). If the data has a
  `patient_id` column, all visits of one patient stay in the same part.
- **AUC:** take one patient who had the outcome and one who did not; how often does the model
  give the higher risk to the right one? 0.5 = guessing, 1.0 = perfect. We use AUC instead of
  accuracy because serious outcomes are rare (about 5%): a model that says "LOW" for everyone
  would be 95% accurate and still miss every serious patient.
- **Spread:** how much the AUC changed between the 5 rounds. Small = steady result.
- **Comparison with triage:** each outcome is also predicted from the triage level alone,
  because a new tool must do better than what the emergency already uses.
- **Input importance:** each input is mixed up in turn on a hidden 20% of patients; the bigger
  the drop in AUC, the more the model relies on it.

---

## 9. Results

### NHAMCS 2012–2014

| | 2012 | 2013 | 2014 | Total |
|---|---|---|---|---|
| All visits | 29,453 | 24,777 | 23,844 | 78,074 |
| Cancer patients | 915 | 766 | 783 | **2,464** |
| Admitted | 283 | 212 | 232 | 727 (29.5%) |
| ICU | 37 | 19 | 37 | 93 |
| Died | 18 | 11 | 15 | 44 |
| Serious (ICU or died) | 46 | 30 | 43 | **119 (4.8%)** |

AUC (spread), 5-fold cross-validation, 11 inputs:

| Inputs | Admitted: logistic | Admitted: XGBoost | Serious: logistic | Serious: XGBoost |
|---|---|---|---|---|
| Triage level alone | 0.593 (0.019) | 0.605 (0.018) | 0.675 (0.057) | 0.700 (0.053) |
| All inputs except triage | 0.689 (0.027) | 0.671 (0.030) | 0.726 (0.063) | 0.752 (0.039) |
| **All 11 inputs** | **0.706** (0.026) | 0.690 (0.032) | 0.776 (0.057) | **0.789** (0.054) |

- The model beats the triage level alone for both outcomes.
- Serious outcomes are predicted better than admission (about 0.78 against 0.71).
- With only 119 serious patients, the serious results vary more (spread about 0.05).
- Triage level was missing for 657 of the 2,464 patients.
- An earlier test of the similar-patients model alone gave 0.691 (admitted) and 0.728 (serious).
- Adding COPD, heart failure and reason for visit did not change the scores.

Most important inputs (XGBoost):

| Admitted | Serious |
|---|---|
| triage level, age, blood pressure (bottom number), then number of long-term diseases, pulse, temperature, breathing | **blood pressure (top number)**, breathing rate, number of long-term diseases, age |

Low blood pressure and fast breathing being the strongest signs of ICU or death agrees with
medical knowledge (signs of shock and severe infection).

### Yale (outcome: admitted)

60,751 cancer visits out of 560,486; 32,258 admitted (53%). 6,374 blood cancer and 54,377
solid cancer visits; 2,416 on cancer medicines.

| Inputs | Logistic regression | XGBoost |
|---|---|---|
| Triage level alone (1 input) | 0.729 (0.003) | 0.730 (0.003) |
| All inputs except triage (20) | 0.708 (0.004) | 0.745 (0.004) |
| Basic: age, sex, 6 vital signs, triage (9) | 0.777 | 0.788 |
| **Basic + cancer inputs (21)** | 0.794 (0.004) | **0.809** (0.003) |

- Cancer details and blood tests raised the AUC from 0.788 to 0.809.
- With 60,751 visits, the results are very steady (spread about 0.003).
- The model relies heavily on the triage level: without it, the AUC falls to 0.745.
- Most important inputs: triage level, age, cancer medicine, pulse. The blood tests look small
  one by one because they overlap, but together they add the gain above.
- Yale has no pain score; a count of past diseases did not help.

### Example predictions (NHAMCS model, made-up patients)

| Patient | Admitted | Serious | 50 similar past patients |
|---|---|---|---|
| 1: looks sick (68, BP 92/58, pulse 118, oxygen 91%, 38.8 °C, triage 2) | 75.5% HIGH | 28.6% HIGH | 32 admitted, 3 serious |
| 2: looks stable (45, normal vital signs, triage 4) | 2.7% LOW | 0.3% LOW | 2 admitted, 0 serious |
| 3: little information (72, only pulse and BP known) | 58.3% HIGH | 8.6% LOW | 17 admitted, 2 serious |

For patients with many empty values, the risk is less reliable.

---

## 10. Using hospital data later

The code is ready for it:

1. Export past emergency visits of cancer patients as one CSV, one row per visit, using the
   standard column names from `code/common.py` where possible, plus a `patient_id` and the
   outcomes `admitted`, `icu`, `died` (1/0).
2. Write one small `prepare_hospital.py` that renames the hospital's columns to the standard
   names (like the other two prepare files) and saves `data/clean/hospital.csv`.
3. Run `python code/train.py hospital`, then `python code/predict.py hospital <new patients file>`.

Nothing else changes: inputs such as days since chemotherapy, ECOG, calcium and lactate are
already in the list and are used automatically when the data has them.
