"""
Shared settings used by all the other files. Normally nothing here needs changing.

Every dataset is turned into ONE standard table with these column names.
train.py uses every input column that is present and not empty, so a dataset
can have more or fewer inputs (later datasets may have more).
"""

import os

# Always work from the main cancer-risk folder (the one above "code"), wherever a
# file is started from, e.g. the Run button in VS Code. Then "data/..." is always found.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)

CLEAN_DIR = "data/clean"      # standard tables are saved here
MODEL_DIR = "models"          # learned models are saved here
RESULT_DIR = "results"        # scores and predictions are saved here

# The inputs a nurse and doctor check when a cancer patient comes to emergency.
# train.py uses every one that the data has, and skips the rest. Inputs marked
# "later" are not in NHAMCS or Yale; they are used automatically when hospital
# data has them. Yes/no inputs are 1 = yes, 0 = no.
INPUTS = [
    # ---- 1. at triage (nurse, first minutes)
    "age",                      # years
    "male",                     # 1 = male, 0 = female
    "triage_level",             # nurse's triage level, 1 (most urgent) to 5
    "pulse",                    # beats per minute
    "bp_top",                   # systolic blood pressure, mmHg
    "bp_bottom",                # diastolic blood pressure, mmHg
    "breathing",                # breaths per minute
    "oxygen",                   # oxygen saturation, %
    "temperature_c",            # degrees C
    "on_oxygen",                # on extra oxygen at arrival
    "pain",                     # pain score 0 to 10
    "confused",                 # later: confused, drowsy or not fully alert
    "complaint_fever",          # later: came with fever
    "complaint_breathless",     # later: came with breathlessness
    "complaint_bleeding",       # later: came with bleeding

    # ---- 2. questions and records (doctor, first contact)
    "blood_cancer",             # leukaemia, lymphoma or myeloma (0 = solid cancer)
    "cancer_spread",            # cancer has spread to other organs
    "cancer_medicine",          # currently on cancer medicine
    "chemo_or_radio_history",   # has had chemotherapy or radiotherapy
    "days_since_chemo",         # later: days since the last chemotherapy
    "on_steroids",              # later: taking steroids
    "on_immunotherapy",         # later: on immunotherapy
    "ecog",                     # later: general condition 0 (normal) to 4 (in bed all day)
    "disease_count",            # number of other long-term diseases

    # ---- 3. first blood tests
    "white_cells",              # x10^9/L
    "neutrophil_count",         # x10^9/L; below 0.5 with fever is an emergency
    "neutrophil_percent",       # %
    "hemoglobin",               # g/dL
    "platelets",                # x10^9/L
    "creatinine",               # mg/dL (kidney)
    "glucose",                  # mg/dL
    "calcium",                  # later: mg/dL (high calcium is a cancer emergency)
    "lactate",                  # later: mmol/L (severe infection)
]

# outcomes (1 = happened, 0 = did not)
OUTCOMES = ["admitted", "serious"]     # serious = went to ICU or died

ID_COLUMN = "patient_id"               # optional; keeps all visits of one patient together when testing


def f_to_c(temp_f):
    return (temp_f - 32) * 5 / 9
