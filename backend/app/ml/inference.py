"""Model inference loader.

Loads the ACTIVE model from the model_versions table + its .joblib artifact.
Cache is per-process; the app loads the model on startup and re-uses it.
"""

from __future__ import annotations

import threading
from pathlib import Path

import joblib
import numpy as np
from app.db.session import SessionLocal
from app.ml.features import FEATURE_COLUMNS, TransactionFeatures, features_to_vector
from app.models.model_version import ModelVersion
from sklearn.pipeline import Pipeline
from sqlalchemy import select


class ModelNotLoadedError(RuntimeError):
    pass


class InferenceService:
    def __init__(self) -> None:
        self._pipeline: Pipeline | None = None
        self._version: str | None = None
        self._schema_version: str | None = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load the active model from DB + disk. Raises if none configured."""
        with self._lock:
            db = SessionLocal()
            try:
                active = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
            finally:
                db.close()

            if active is None:
                raise ModelNotLoadedError(
                    "No active model in model_versions. Run: " "python -m app.ml.train_bootstrap"
                )

            path = Path(active.artifact_path)
            if not path.exists():
                raise ModelNotLoadedError(f"Artifact missing at {path}")

            self._pipeline = joblib.load(path)
            self._version = active.version
            self._schema_version = active.feature_schema_version

            if self._schema_version != _current_schema_version():
                raise ModelNotLoadedError(
                    f"Schema mismatch: model expects {self._schema_version}, "
                    f"code is {_current_schema_version()}. Retrain."
                )

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    @property
    def version(self) -> str:
        if self._version is None:
            raise ModelNotLoadedError("Model not loaded")
        return self._version

    @property
    def schema_version(self) -> str:
        if self._schema_version is None:
            raise ModelNotLoadedError("Model not loaded")
        return self._schema_version

    def predict_proba(self, features: TransactionFeatures) -> float:
        """Return fraud probability in [0, 1]."""
        if self._pipeline is None:
            raise ModelNotLoadedError("Model not loaded")
        vec = np.array([features_to_vector(features)], dtype=np.float64)
        proba = self._pipeline.predict_proba(vec)[0, 1]
        return float(max(0.0, min(1.0, proba)))


def _current_schema_version() -> str:
    from app.ml.features import FEATURE_SCHEMA_VERSION

    return FEATURE_SCHEMA_VERSION


# Module-level singleton
inference = InferenceService()

__all__ = ["inference", "InferenceService", "ModelNotLoadedError", "FEATURE_COLUMNS"]
