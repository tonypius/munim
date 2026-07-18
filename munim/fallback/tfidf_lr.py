"""Stage 5: fallback classifier for the long tail.

Character n-gram TF-IDF + logistic regression:
  - ~2MB model, retrains in seconds on a laptop (which is what makes
    the weekly retraining loop actually feasible)
  - char n-grams are robust to the truncation/spacing noise of bank strings
  - probability output feeds threshold calibration (Loop 3)

Trained on: community dictionary patterns + the user's own confirmed labels.
Predictions are ALWAYS provisional — they display, but never enter memory
until the user confirms.

Optional dependency: pip install munim[ml]. Without it, unknowns simply
go to the review queue unlabeled — the system still works.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    import joblib
    SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover
    SKLEARN_AVAILABLE = False

MIN_TRAINING_SAMPLES = 20
MIN_CLASSES = 3


class TfidfClassifier:
    def __init__(self, model_path: Optional[Path] = None):
        self.model_path = model_path
        self.pipeline = None
        if model_path and model_path.exists() and SKLEARN_AVAILABLE:
            self.pipeline = joblib.load(model_path)

    def train(self, samples: list[tuple[str, str]]) -> bool:
        """samples: (merchant_string, category). Returns True if trained."""
        if not SKLEARN_AVAILABLE or len(samples) < MIN_TRAINING_SAMPLES:
            return False
        texts, labels = zip(*samples)
        if len(set(labels)) < MIN_CLASSES:
            return False
        self.pipeline = Pipeline([
            ("tfidf", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4),
                                      lowercase=True, min_df=1)),
            ("clf", LogisticRegression(max_iter=1000, C=5.0)),
        ])
        self.pipeline.fit(list(texts), list(labels))
        if self.model_path:
            joblib.dump(self.pipeline, self.model_path)
        return True

    def predict(self, merchant: str) -> Optional[tuple[str, float]]:
        if self.pipeline is None or not merchant:
            return None
        proba = self.pipeline.predict_proba([merchant])[0]
        idx = proba.argmax()
        return self.pipeline.classes_[idx], float(proba[idx])
