"""
train_fraud_model.py  (Phase 5, Step 5.2)
------------------------------------------------------------------
Unsupervised anomaly detection on transaction features, native to Snowflake.

Pipeline:
  1. Pull HARMONIZED.USER_SPEND_FEATURES via Snowpark (compute stays in SF).
  2. Impute cold-start NULLs (a user's first txns have no rolling window).
  3. Train an Isolation Forest -- UNSUPERVISED, no labels.
  4. Evaluate against the eval-only ground truth (is_synthetic_anomaly) to
     prove the model works: precision / recall / F1 / confusion matrix.
  5. Log params + metrics + score plot to Snowflake Experiment Tracking.
  6. Register the model in the Snowflake Model Registry (governed artifact).

The label is used ONLY to evaluate -- never as a training feature.
"""

import sys
import time

# Windows consoles default to cp1252, which can't encode the emoji the
# experiment-tracking SDK prints. Force UTF-8 so those prints don't crash.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import matplotlib
matplotlib.use("Agg")  # headless: save plots to file, no display
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)

from snowflake.ml.experiment import ExperimentTracking
from snowflake.ml.registry import Registry

from snowpark_session import create_session

# V2: USER-RELATIVE features only. Fraud is relative to each user's norm,
# not an absolute dollar amount -- absolute AMOUNT made V1 flag big spenders.
FEATURES = ["AMOUNT_ZSCORE", "AMOUNT_TO_AVG_RATIO"]
MODEL_NAME = "FRAUD_ISOLATION_FOREST"
MODEL_VERSION = "V2"
EXPERIMENT_NAME = "FRAUD_ANOMALY_DETECTION"
PLOT_PATH = "anomaly_score_distribution.png"
CONTAMINATION = 0.015     # realistic fraud domain prior (~1.5%)
N_ESTIMATORS = 300
RANDOM_STATE = 42

session = create_session()

# ------------------------------------------------------------------
# 1. Pull features via Snowpark (pushdown; data movement is minimal).
# ------------------------------------------------------------------
print("Loading features from FRAUD_DB.HARMONIZED.USER_SPEND_FEATURES ...")
sdf = session.table("FRAUD_DB.HARMONIZED.USER_SPEND_FEATURES")
df = sdf.select(
    "TXN_ID", "USER_ID", "AMOUNT", "ROLLING_AVG_AMOUNT", "ROLLING_STD_AMOUNT",
    "AMOUNT_ZSCORE", "IS_SYNTHETIC_ANOMALY",
).to_pandas()
print(f"  loaded {len(df)} rows")

# ------------------------------------------------------------------
# 2. Cold-start imputation. A user's first transactions have no prior
#    window, so rolling stats / z-score are NULL. Impute conservatively:
#    - rolling_avg NULL -> the txn's own amount (assume it's its own normal)
#    - rolling_std NULL -> 0
#    - zscore NULL      -> 0 (no deviation info)
#    The raw AMOUNT feature still carries the signal, so the model can
#    still flag a huge first-transaction -- something the univariate
#    z-score rule COULD NOT (it was NULL for that row).
# ------------------------------------------------------------------
df["ROLLING_AVG_AMOUNT"] = df["ROLLING_AVG_AMOUNT"].fillna(df["AMOUNT"])
df["ROLLING_STD_AMOUNT"] = df["ROLLING_STD_AMOUNT"].fillna(0.0)
df["AMOUNT_ZSCORE"] = df["AMOUNT_ZSCORE"].fillna(0.0)

# V2 engineered feature: how many times the user's rolling average is this
# transaction? Ratio ~1 = normal; >>1 = spending far above personal norm.
# Cold-start rows (rolling_avg imputed to amount) get ratio = 1 (looks normal).
df["AMOUNT_TO_AVG_RATIO"] = df["AMOUNT"] / df["ROLLING_AVG_AMOUNT"].replace(0, np.nan)
df["AMOUNT_TO_AVG_RATIO"] = df["AMOUNT_TO_AVG_RATIO"].fillna(1.0)

X = df[FEATURES]
y_true = df["IS_SYNTHETIC_ANOMALY"].astype(int)  # eval ONLY

# ------------------------------------------------------------------
# 3. Train the Isolation Forest (unsupervised).
# ------------------------------------------------------------------
print("Training Isolation Forest (unsupervised) ...")
model = IsolationForest(
    n_estimators=N_ESTIMATORS,
    contamination=CONTAMINATION,
    random_state=RANDOM_STATE,
)
model.fit(X)

# predict: -1 = anomaly, 1 = normal  ->  1 = anomaly, 0 = normal
y_pred = (model.predict(X) == -1).astype(int)
# anomaly score: higher = more anomalous
anomaly_score = -model.score_samples(X)

# ------------------------------------------------------------------
# 4. Evaluate against ground truth (label used ONLY here).
# ------------------------------------------------------------------
precision = precision_score(y_true, y_pred, zero_division=0)
recall = recall_score(y_true, y_pred, zero_division=0)
f1 = f1_score(y_true, y_pred, zero_division=0)
cm = confusion_matrix(y_true, y_pred)
tn, fp, fn, tp = cm.ravel()

print("\n===== EVALUATION (unsupervised model vs. ground truth) =====")
print(f"  Precision : {precision:.3f}")
print(f"  Recall    : {recall:.3f}")
print(f"  F1        : {f1:.3f}")
print(f"  Confusion matrix: TP={tp} FP={fp} FN={fn} TN={tn}")
print(f"  Flagged {y_pred.sum()} of {len(df)} transactions as anomalous")

# ------------------------------------------------------------------
# 5. Score-distribution plot (saved to file on CLI).
# ------------------------------------------------------------------
plt.figure(figsize=(9, 5))
normal_scores = anomaly_score[y_true == 0]
fraud_scores = anomaly_score[y_true == 1]
plt.hist(normal_scores, bins=40, alpha=0.7, label="Normal (ground truth)")
plt.hist(fraud_scores, bins=40, alpha=0.9, label="Fraud (ground truth)")
plt.xlabel("Isolation Forest anomaly score (higher = more anomalous)")
plt.ylabel("Transaction count")
plt.title("Anomaly Score Distribution: Normal vs. Injected Fraud")
plt.legend()
plt.tight_layout()
plt.savefig(PLOT_PATH, dpi=120)
print(f"\nSaved score plot to {PLOT_PATH}")

# ------------------------------------------------------------------
# 6a. Experiment Tracking: log params, metrics, and the plot artifact.
# ------------------------------------------------------------------
print("\nLogging to Snowflake Experiment Tracking ...")
exp = ExperimentTracking(session=session, database_name="FRAUD_DB", schema_name="ANALYTICS")
exp.set_experiment(EXPERIMENT_NAME)

run_name = "iforest_" + time.strftime("%Y%m%d_%H%M%S")
with exp.start_run(run_name):
    exp.log_params({
        "algorithm": "IsolationForest",
        "n_estimators": N_ESTIMATORS,
        "contamination": CONTAMINATION,
        "random_state": RANDOM_STATE,
        "features": ",".join(FEATURES),
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
    })
    exp.log_metrics({
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "flagged_count": int(y_pred.sum()),
    })
    exp.log_artifact(PLOT_PATH, artifact_path="plots")
print(f"  logged experiment run: {run_name}")

# ------------------------------------------------------------------
# 6b. Model Registry: register the governed, versioned artifact.
#     Explainability disabled (SHAP is unreliable for IsolationForest;
#     our z-score already provides interpretable severity).
# ------------------------------------------------------------------
print("\nRegistering model in the Snowflake Model Registry ...")
reg = Registry(session=session, database_name="FRAUD_DB", schema_name="ANALYTICS")
sample_input = X.head(5)

version_name = MODEL_VERSION
def _log(v):
    return reg.log_model(
        model,
        model_name=MODEL_NAME,
        version_name=v,
        sample_input_data=sample_input,
        conda_dependencies=["scikit-learn"],
        target_platforms=["WAREHOUSE"],
        options={"enable_explainability": False},
        comment="Unsupervised Isolation Forest v2 (user-relative features) for fraud detection",
    )

try:
    mv = _log(version_name)
except Exception as e:
    if "already exists" in str(e).lower():
        version_name = "V_" + time.strftime("%Y%m%d_%H%M%S")
        print(f"  V1 exists; using version {version_name}")
        mv = _log(version_name)
    else:
        raise

print(f"\nModel registered: {mv.model_name} version {version_name}")
print("Available functions:", [f["name"] for f in mv.show_functions()])

session.close()
print("\nDONE.")
