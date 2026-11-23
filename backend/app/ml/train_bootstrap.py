"""Bootstrap ML training.

Generates synthetic transactions that mimic fraud patterns, trains a
LogisticRegression + StandardScaler pipeline, saves the artifact and registers
it in model_versions. This is a placeholder for real UCI credit-card training,
but the pipeline shape (sklearn Pipeline + joblib) matches what Phase 4 will
produce, so swapping the dataset later is a one-function change.

Run:
    docker compose exec backend python -m app.ml.train_bootstrap
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
from app.db.session import SessionLocal
from app.ml.features import FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION
from app.models.model_version import ModelVersion
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

MODEL_DIR = Path("/app/models")
MODEL_VERSION = "fraud-model-bootstrap-1.0"
DATASET_NAME = "synthetic-v1"


def _synth_row(rng: random.Random) -> tuple[list[float], int]:
    """Generate one synthetic transaction feature vector + label.

    Fraud is rare (~5%) and correlates with high amount, unusual hours,
    foreign currency, and atypical transaction types.
    """
    is_fraud = 1 if rng.random() < 0.05 else 0

    if is_fraud:
        amount = rng.uniform(800, 15000)
        hour = rng.choice([0, 1, 2, 3, 4, 23])
        dow = rng.randint(0, 6)
        currency_risk = rng.choice([0.15, 0.2])
        type_encoded = rng.choice([1, 3, 4])
    else:
        amount = rng.gauss(150, 120)
        amount = max(5.0, amount)
        hour = rng.randint(8, 21)
        dow = rng.randint(0, 6)
        currency_risk = 0.1
        type_encoded = rng.choice([0, 1, 2])

    is_weekend = 1 if dow >= 5 else 0
    is_night = 1 if (hour < 6 or hour >= 22) else 0
    amount_log = math.log1p(max(amount, 0.0))

    vec = [amount, hour, dow, is_weekend, is_night, amount_log, currency_risk, type_encoded]
    return vec, is_fraud


def generate_dataset(n: int = 20000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = random.Random(seed)
    X = np.zeros((n, len(FEATURE_COLUMNS)), dtype=np.float64)
    y = np.zeros(n, dtype=np.int32)
    for i in range(n):
        vec, label = _synth_row(rng)
        X[i] = vec
        y[i] = label
    return X, y


def _sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def train() -> dict:
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    X, y = generate_dataset()
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=42,
                ),
            ),
        ]
    )
    pipeline.fit(X_train, y_train)

    y_pred = pipeline.predict(X_test)
    y_proba = pipeline.predict_proba(X_test)[:, 1]

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "average_precision": float(average_precision_score(y_test, y_proba)),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
        "n_train": int(len(y_train)),
        "n_test": int(len(y_test)),
        "fraud_rate_train": float(y_train.mean()),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }

    artifact_path = MODEL_DIR / f"{MODEL_VERSION}.joblib"
    joblib.dump(pipeline, artifact_path)
    checksum = _sha256_of(artifact_path)

    metadata = {
        "model_version": MODEL_VERSION,
        "dataset": DATASET_NAME,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_columns": list(FEATURE_COLUMNS),
        "metrics": metrics,
        "trained_at": datetime.now(UTC).isoformat(),
        "checksum": checksum,
    }
    (MODEL_DIR / f"{MODEL_VERSION}.metadata.json").write_text(json.dumps(metadata, indent=2))

    db = SessionLocal()
    try:
        existing = db.query(ModelVersion).filter(ModelVersion.version == MODEL_VERSION).first()
        if existing:
            existing.artifact_path = str(artifact_path)
            existing.checksum = checksum
            existing.metrics_json = metrics
            existing.trained_at = datetime.now(UTC)
            existing.is_active = True
            # deactivate others
            db.query(ModelVersion).filter(ModelVersion.id != existing.id).update(
                {ModelVersion.is_active: False}
            )
        else:
            db.query(ModelVersion).update({ModelVersion.is_active: False})
            db.add(
                ModelVersion(
                    version=MODEL_VERSION,
                    artifact_path=str(artifact_path),
                    checksum=checksum,
                    dataset_name=DATASET_NAME,
                    feature_schema_version=FEATURE_SCHEMA_VERSION,
                    metrics_json=metrics,
                    notes="Bootstrap synthetic model — replaced by UCI credit-card model in Phase 4",
                    trained_at=datetime.now(UTC),
                    is_active=True,
                )
            )
        db.commit()
    finally:
        db.close()

    return metadata


def main() -> None:
    meta = train()
    print("=" * 60)
    print("Model trained and registered")
    print("=" * 60)
    print(f"  version:   {meta['model_version']}")
    print(f"  dataset:   {meta['dataset']}")
    print(f"  checksum:  {meta['checksum'][:16]}...")
    print(f"  artifact:  /app/models/{meta['model_version']}.joblib")
    print()
    print("Metrics:")
    for k, v in meta["metrics"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
