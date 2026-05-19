"""LightGBM-based ML trading advisor for FlintTrade.

Provides feature engineering, model training, prediction, and persistence for
a BUY / SELL / HOLD classifier trained on OHLCV data.

Classes:
    MLAdvisorConfig  — Pydantic config model.
    FeatureEngineer  — Builds RSI, MACD, Bollinger Band, and volume-ratio features.
    MLAdvisor        — Trains, loads, and runs the LightGBM classifier.

Signal enum:
    Signal.BUY  = 0
    Signal.HOLD = 1
    Signal.SELL = 2

Absorbed from: openadvisor/training_predictions.py (CatBoost → LightGBM per project stack).

Design decisions:
- LightGBM (not CatBoost / sklearn): project stack choice in packages/ai/CLAUDE.md.
- Classifier (BUY/SELL/HOLD), not regressor: actionable discrete signals.
- Label generation: forward-looking n-bar return thresholds (configurable).
- Feature engineering is pure NumPy / pandas — no TA-Lib dependency here
  (the indicators package handles TA-Lib; this module is self-contained).
- Model saved/loaded as pickle (not .cbm) for portability.
- LightGBM is imported lazily so the module loads without it installed.

Usage::

    import pandas as pd
    from packages.ai.src.ml_advisor import MLAdvisor, MLAdvisorConfig

    df = pd.read_csv("NIFTY_1D.csv")   # columns: open, high, low, close, volume
    advisor = MLAdvisor(MLAdvisorConfig(lookback=100, forward_bars=5))
    advisor.train(df)
    prediction = advisor.predict(df)
    print(prediction.signal, prediction.confidence, prediction.feature_importance)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field


def _const_time_eq(a: str, b: str) -> bool:
    """Constant-time equality for hex digest strings (no timing side-channel)."""
    return hmac.compare_digest(a, b)


logger = logging.getLogger("flinttrade.ai.ml_advisor")

# ---------------------------------------------------------------------------
# Enums / constants
# ---------------------------------------------------------------------------

_SIGNAL_NAMES = {0: "BUY", 1: "HOLD", 2: "SELL"}
_FEATURE_COLUMNS = [
    "rsi",
    "macd",
    "macd_signal",
    "macd_hist",
    "bb_position",
    "volume_ratio_5",
    "volume_ratio_20",
    "returns_1",
    "returns_5",
    "hl_range",
    "body_pct",
]


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


class MLAdvisorConfig(BaseModel):
    """Configuration for MLAdvisor.

    Attributes:
        lookback:           Minimum rows of history required before training.
        forward_bars:       Number of bars ahead to compute forward return.
        buy_threshold:      Forward return > buy_threshold → BUY label.
        sell_threshold:     Forward return < sell_threshold → SELL label.
        test_size:          Fraction of data held out for evaluation.
        n_estimators:       LightGBM trees.
        learning_rate:      LightGBM learning rate.
        max_depth:          Maximum tree depth.
        num_leaves:         LightGBM num_leaves.
        random_state:       Reproducibility seed.
        model_path:         Path to save / load the trained model pickle.
    """

    lookback: int = Field(default=100, ge=10)
    forward_bars: int = Field(default=5, ge=1)
    buy_threshold: float = Field(default=0.005, gt=0.0)
    sell_threshold: float = Field(default=-0.005, lt=0.0)
    test_size: float = Field(default=0.2, gt=0.0, lt=1.0)
    n_estimators: int = Field(default=300, ge=1)
    learning_rate: float = Field(default=0.05, gt=0.0)
    max_depth: int = Field(default=6, ge=1)
    num_leaves: int = Field(default=31, ge=2)
    random_state: int = 42
    model_path: str = ""


# ---------------------------------------------------------------------------
# Prediction result
# ---------------------------------------------------------------------------


@dataclass
class Prediction:
    """Output from MLAdvisor.predict().

    Attributes:
        signal:            ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
        signal_code:       Integer code: 0=BUY, 1=HOLD, 2=SELL.
        confidence:        Probability of the predicted class (0–1).
        probabilities:     Full class probability vector [BUY, HOLD, SELL].
        feature_importance: Dict mapping feature name to its importance score.
        error:             Non-empty if prediction failed.
    """

    signal: str = "HOLD"
    signal_code: int = 1
    confidence: float = 0.0
    probabilities: list[float] = field(default_factory=lambda: [0.0, 1.0, 0.0])
    feature_importance: dict[str, float] = field(default_factory=dict)
    error: str = ""

    @property
    def success(self) -> bool:
        return not self.error


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------


class FeatureEngineer:
    """Compute technical-indicator features from OHLCV data.

    All features are computed from OHLCV columns:
    ``open``, ``high``, ``low``, ``close``, ``volume``.

    Returns the input DataFrame with extra feature columns appended in-place
    (on a copy — original is not mutated).

    Features:
        rsi            — 14-period RSI.
        macd           — MACD line (12/26 EMA diff).
        macd_signal    — 9-period EMA of MACD.
        macd_hist      — MACD histogram.
        bb_position    — Bollinger Band position (0=lower, 1=upper, 0.5=mid).
        volume_ratio_5 — Volume / 5-bar rolling average.
        volume_ratio_20— Volume / 20-bar rolling average.
        returns_1      — 1-bar log return.
        returns_5      — 5-bar log return.
        hl_range       — (high-low) / close.
        body_pct       — |close-open| / (high-low), 0 if doji.
    """

    def build_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all features on a copy of the DataFrame.

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, volume.

        Returns:
            New DataFrame with original columns plus all feature columns.

        Raises:
            ValueError: If required OHLCV columns are missing.
        """
        required = {"open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Missing required columns: {missing}")

        out = df.copy()
        close = out["close"]
        high = out["high"]
        low = out["low"]
        volume = out["volume"]

        out["rsi"] = self._rsi(close)
        macd, signal, hist = self._macd(close)
        out["macd"] = macd
        out["macd_signal"] = signal
        out["macd_hist"] = hist
        out["bb_position"] = self._bollinger_position(close)
        out["volume_ratio_5"] = volume / volume.rolling(5).mean().replace(0, np.nan)
        out["volume_ratio_20"] = volume / volume.rolling(20).mean().replace(0, np.nan)
        out["returns_1"] = np.log(close / close.shift(1))
        out["returns_5"] = np.log(close / close.shift(5))
        out["hl_range"] = (high - low) / close
        out["body_pct"] = (out["close"] - out["open"]).abs() / (high - low).replace(0, np.nan)

        return out

    # ------------------------------------------------------------------
    # Internal — pure NumPy / pandas, no TA-Lib
    # ------------------------------------------------------------------

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
        avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        return 100.0 - (100.0 / (1.0 + rs))

    @staticmethod
    def _macd(
        close: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        macd_signal = macd.ewm(span=signal, adjust=False).mean()
        macd_hist = macd - macd_signal
        return macd, macd_signal, macd_hist

    @staticmethod
    def _bollinger_position(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.Series:
        """Return 0-to-1 position within the Bollinger Band.

        0 = at lower band, 1 = at upper band, 0.5 = at midline.
        """
        mid = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        band_width = upper - lower
        return ((close - lower) / band_width.replace(0, np.nan)).clip(0.0, 1.0)


# ---------------------------------------------------------------------------
# MLAdvisor
# ---------------------------------------------------------------------------


class MLAdvisor:
    """LightGBM BUY/SELL/HOLD classifier trained on OHLCV data.

    Workflow::

        advisor = MLAdvisor(config)
        metrics = advisor.train(df)       # fit and evaluate
        advisor.save()                    # persist to config.model_path
        advisor.load()                    # load from config.model_path
        prediction = advisor.predict(df)  # latest-bar prediction

    The advisor is stateless between calls except for the trained model.
    """

    def __init__(
        self,
        config: MLAdvisorConfig | None = None,
        feature_engineer: FeatureEngineer | None = None,
    ) -> None:
        self.config = config or MLAdvisorConfig()
        self._fe = feature_engineer or FeatureEngineer()
        self._model: Any = None
        self._feature_names: list[str] = list(_FEATURE_COLUMNS)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, df: pd.DataFrame) -> dict[str, float]:
        """Train the LightGBM classifier on OHLCV data.

        Labels are generated from forward log-returns:
        - forward_return > buy_threshold  → 0 (BUY)
        - forward_return < sell_threshold → 2 (SELL)
        - otherwise                       → 1 (HOLD)

        Args:
            df: OHLCV DataFrame (at least ``config.lookback`` rows).

        Returns:
            Dict of evaluation metrics: ``accuracy``, ``train_samples``, ``test_samples``.

        Raises:
            ImportError: If lightgbm is not installed.
            ValueError: If df has fewer rows than ``config.lookback``.
        """
        try:
            import lightgbm as lgb  # type: ignore[import]
        except ImportError:
            raise ImportError("lightgbm required — pip install lightgbm")

        if len(df) < self.config.lookback:
            raise ValueError(
                f"DataFrame has {len(df)} rows; need at least {self.config.lookback}."
            )

        featured = self._fe.build_features(df)
        featured = self._add_labels(featured)
        featured = featured.dropna(subset=self._feature_names + ["label"])

        X = featured[self._feature_names].values
        y = featured["label"].values.astype(int)

        split = int(len(X) * (1 - self.config.test_size))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        self._model = lgb.LGBMClassifier(
            n_estimators=self.config.n_estimators,
            learning_rate=self.config.learning_rate,
            max_depth=self.config.max_depth,
            num_leaves=self.config.num_leaves,
            random_state=self.config.random_state,
            verbose=-1,
        )
        self._model.fit(X_train, y_train)

        accuracy = float(np.mean(self._model.predict(X_test) == y_test))
        logger.info(
            "[MLAdvisor] Trained — train=%d test=%d accuracy=%.3f",
            len(X_train),
            len(X_test),
            accuracy,
        )
        return {
            "accuracy": accuracy,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
        }

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------

    def predict(self, df: pd.DataFrame) -> Prediction:
        """Predict the signal for the latest bar in df.

        Args:
            df: OHLCV DataFrame.  The last row is used for prediction.

        Returns:
            Prediction with signal, confidence, and feature importance.
        """
        if self._model is None:
            return Prediction(error="Model not trained. Call train() or load() first.")

        try:
            featured = self._fe.build_features(df)
            last_row = featured[self._feature_names].iloc[[-1]]

            if last_row.isnull().any(axis=None):
                return Prediction(error="Insufficient data — NaN features in last row.")

            probas = self._model.predict_proba(last_row.values)[0]
            signal_code = int(np.argmax(probas))
            confidence = float(probas[signal_code])
            importance = self._feature_importance()

            return Prediction(
                signal=_SIGNAL_NAMES[signal_code],
                signal_code=signal_code,
                confidence=confidence,
                probabilities=probas.tolist(),
                feature_importance=importance,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("[MLAdvisor] Prediction failed: %s", exc)
            return Prediction(error=str(exc))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _checksum_path(model_path: Path) -> Path:
        """Return the sidecar path for the model's SHA-256 checksum."""
        return model_path.with_suffix(model_path.suffix + ".sha256")

    @staticmethod
    def _compute_sha256(path: Path) -> str:
        """Stream-read ``path`` and return its hex SHA-256 digest."""
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def save(self, path: str | Path | None = None) -> Path:
        """Serialise the trained model to a pickle file with a SHA-256 sidecar.

        The sidecar file (``<model>.pkl.sha256``) is written alongside the
        model so that :meth:`load` can verify the model bytes have not been
        tampered with before unpickling. See :meth:`load` for the threat
        model.

        Args:
            path: Override save path.  Falls back to ``config.model_path``,
                  then ``~/.flinttrade/models/ml_advisor.pkl``.

        Returns:
            Resolved save path.

        Raises:
            RuntimeError: If no model has been trained.
        """
        if self._model is None:
            raise RuntimeError("No trained model to save.")

        target = Path(path or self.config.model_path or self._default_model_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            pickle.dump({"model": self._model, "feature_names": self._feature_names}, f)
        digest = self._compute_sha256(target)
        self._checksum_path(target).write_text(digest, encoding="ascii")
        logger.info("[MLAdvisor] Model saved to %s (sha256=%s)", target, digest[:12])
        return target

    def load(self, path: str | Path | None = None) -> None:
        """Load a previously saved model, verifying its SHA-256 checksum first.

        Security model: pickle deserialisation is arbitrary-code-execution by
        design. The 2026-05-19 multi-agent audit (CRITICAL-3) flagged this
        path as RCE-exploitable if an attacker can drop a malicious
        ``ml_advisor.pkl`` (e.g. via a different vulnerability, shared
        workspace, backup restore, or a "pre-trained model" download).

        We mitigate by writing a SHA-256 sidecar in :meth:`save` and
        verifying it here before unpickling. An attacker who can write the
        model file would also need to write the matching sidecar; an
        attacker who can do both has full FS write access already and is
        beyond this layer's scope.

        For development workflows where the sidecar is missing (legacy
        models, hand-built test fixtures), set
        ``FLINTTRADE_ML_ADVISOR_TRUST_UNVERIFIED=1`` to load anyway. The
        load logs a loud warning when that flag is honoured.

        Args:
            path: Override load path.  Falls back to ``config.model_path``,
                  then ``~/.flinttrade/models/ml_advisor.pkl``.

        Raises:
            FileNotFoundError: If the model file does not exist.
            RuntimeError: If the checksum sidecar is missing or does not
                match the model bytes (unless trust override is set).
        """
        target = Path(path or self.config.model_path or self._default_model_path())
        if not target.exists():
            raise FileNotFoundError(f"Model file not found: {target}")

        checksum_file = self._checksum_path(target)
        actual = self._compute_sha256(target)

        if checksum_file.exists():
            expected = checksum_file.read_text(encoding="ascii").strip()
            if not _const_time_eq(expected, actual):
                raise RuntimeError(
                    f"Refusing to load {target.name}: SHA-256 checksum mismatch "
                    f"(expected {expected[:12]}…, got {actual[:12]}…). Either "
                    "regenerate the model with MLAdvisor.save() or delete the "
                    "sidecar to force a fresh integrity record."
                )
        else:
            trust = os.environ.get(
                "FLINTTRADE_ML_ADVISOR_TRUST_UNVERIFIED", ""
            ).strip().lower() in ("1", "true", "yes")
            if not trust:
                raise RuntimeError(
                    f"Refusing to load {target.name}: no SHA-256 sidecar found "
                    f"at {checksum_file.name}. Pickle deserialisation is RCE — "
                    "loading unverified model files is disabled. Either save "
                    "the model via MLAdvisor.save() (which writes the sidecar) "
                    "or set FLINTTRADE_ML_ADVISOR_TRUST_UNVERIFIED=1 to override."
                )
            logger.warning(
                "[MLAdvisor] Loading %s WITHOUT sha256 verification because "
                "FLINTTRADE_ML_ADVISOR_TRUST_UNVERIFIED is set. Do not use in "
                "production.", target,
            )

        with open(target, "rb") as f:
            payload = pickle.load(f)  # noqa: S301
        self._model = payload["model"]
        self._feature_names = payload.get("feature_names", list(_FEATURE_COLUMNS))
        logger.info(
            "[MLAdvisor] Model loaded from %s (sha256=%s)", target, actual[:12]
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _add_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute forward return and assign BUY/HOLD/SELL labels."""
        forward_return = df["close"].shift(-self.config.forward_bars) / df["close"] - 1
        labels = pd.Series(1, index=df.index, name="label")  # default HOLD
        labels[forward_return > self.config.buy_threshold] = 0   # BUY
        labels[forward_return < self.config.sell_threshold] = 2  # SELL
        df = df.copy()
        df["label"] = labels
        return df

    def _feature_importance(self) -> dict[str, float]:
        if self._model is None:
            return {}
        try:
            importances = self._model.feature_importances_.tolist()
            return dict(zip(self._feature_names, importances))
        except AttributeError:
            return {}

    @staticmethod
    def _default_model_path() -> Path:
        import os
        import platform

        system = platform.system()
        if system == "Darwin":
            base = Path.home() / "Library" / "Application Support" / "flinttrade"
        elif system == "Windows":
            appdata = os.environ.get("APPDATA")
            base = Path(appdata) / "flinttrade" if appdata else Path.home() / "AppData" / "Roaming" / "flinttrade"
        else:
            base = Path.home() / ".flinttrade"
        return base / "models" / "ml_advisor.pkl"
