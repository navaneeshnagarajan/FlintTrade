"""ML-based stock recommendation engine.

Adapts openadvisor CatBoost patterns. Combines fundamental features (PE, PB,
ROE), technical features (trend, momentum), and sentiment scores to rank stocks
and generate portfolio suggestions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("flinttrade.ai.advisor")


@dataclass
class StockFeatures:
    """Feature vector for a single stock."""

    symbol: str
    exchange: str = "NSE"
    # Fundamental
    pe_ratio: float = 0.0
    pb_ratio: float = 0.0
    roe: float = 0.0
    debt_to_equity: float = 0.0
    dividend_yield: float = 0.0
    market_cap: float = 0.0  # in crores
    # Technical
    rsi_14: float = 50.0
    macd_signal: float = 0.0  # MACD histogram value
    price_vs_200dma: float = 0.0  # % above/below 200-day MA
    price_vs_50dma: float = 0.0
    volatility_30d: float = 0.0
    # Momentum
    return_1m: float = 0.0
    return_3m: float = 0.0
    return_6m: float = 0.0
    return_1y: float = 0.0
    # Sentiment
    sentiment_score: float = 0.0  # -1 to +1 from SentimentAnalyzer


@dataclass
class StockRanking:
    """A ranked stock recommendation."""

    symbol: str
    exchange: str = "NSE"
    score: float = 0.0  # 0 to 1, higher = stronger recommendation
    rank: int = 0
    action: str = "HOLD"  # "BUY", "SELL", "HOLD"
    allocation_pct: float = 0.0  # Suggested portfolio weight
    reasoning: str = ""


@dataclass
class PortfolioSuggestion:
    """Complete portfolio suggestion with top picks."""

    rankings: list[StockRanking] = field(default_factory=list)
    total_stocks: int = 0
    rebalance_needed: bool = False
    model_accuracy: float = 0.0

    @property
    def buy_picks(self) -> list[StockRanking]:
        return [r for r in self.rankings if r.action == "BUY"]

    @property
    def sell_picks(self) -> list[StockRanking]:
        return [r for r in self.rankings if r.action == "SELL"]


@dataclass
class RebalanceAlert:
    """Alert when portfolio drifts from target allocation."""

    symbol: str
    current_pct: float
    target_pct: float
    drift_pct: float
    action: str  # "INCREASE", "DECREASE", "EXIT"


def features_to_array(stock: StockFeatures) -> list[float]:
    """Convert StockFeatures to a flat array for ML input."""
    return [
        stock.pe_ratio,
        stock.pb_ratio,
        stock.roe,
        stock.debt_to_equity,
        stock.dividend_yield,
        stock.market_cap,
        stock.rsi_14,
        stock.macd_signal,
        stock.price_vs_200dma,
        stock.price_vs_50dma,
        stock.volatility_30d,
        stock.return_1m,
        stock.return_3m,
        stock.return_6m,
        stock.return_1y,
        stock.sentiment_score,
    ]


FEATURE_NAMES = [
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity", "dividend_yield",
    "market_cap", "rsi_14", "macd_signal", "price_vs_200dma", "price_vs_50dma",
    "volatility_30d", "return_1m", "return_3m", "return_6m", "return_1y",
    "sentiment_score",
]


class StockAdvisor:
    """CatBoost-based stock ranking and portfolio advisor.

    Usage::

        advisor = StockAdvisor()
        advisor.train(historical_features, labels)

        stocks = [StockFeatures(symbol="RELIANCE", pe_ratio=25, ...), ...]
        suggestion = advisor.rank(stocks, top_n=10)
        for pick in suggestion.buy_picks:
            print(f"{pick.symbol}: score={pick.score:.2f}, alloc={pick.allocation_pct:.1f}%")

        advisor.save("models/advisor.joblib")
    """

    def __init__(self) -> None:
        self._model = None
        self._is_trained = False
        self._accuracy: float = 0.0

    @property
    def is_trained(self) -> bool:
        return self._is_trained

    def train(
        self,
        features_list: list[StockFeatures],
        labels: list[int],
        test_ratio: float = 0.2,
        **catboost_params: Any,
    ) -> dict[str, float]:
        """Train a CatBoost ranking model.

        Labels: 2=BUY (outperform), 1=HOLD (neutral), 0=SELL (underperform).
        Returns dict with train_accuracy and test_accuracy.
        """
        try:
            from catboost import CatBoostClassifier
        except ImportError:
            raise ImportError("catboost required — pip install catboost")

        X = [features_to_array(f) for f in features_list]
        y = labels

        split = int(len(X) * (1 - test_ratio))
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]

        params = {
            "iterations": 500,
            "learning_rate": 0.05,
            "depth": 6,
            "loss_function": "MultiClass",
            "verbose": False,
            **catboost_params,
        }

        self._model = CatBoostClassifier(**params)
        self._model.fit(X_train, y_train, eval_set=(X_test, y_test) if X_test else None)

        train_acc = sum(
            1 for a, b in zip(self._model.predict(X_train).flatten(), y_train) if int(a) == b
        ) / len(y_train) if y_train else 0

        test_acc = sum(
            1 for a, b in zip(self._model.predict(X_test).flatten(), y_test) if int(a) == b
        ) / len(y_test) if y_test else 0

        self._is_trained = True
        self._accuracy = test_acc
        logger.info("Advisor model trained: train_acc=%.2f, test_acc=%.2f", train_acc, test_acc)
        return {"train_accuracy": train_acc, "test_accuracy": test_acc}

    def rank(
        self,
        stocks: list[StockFeatures],
        top_n: int = 10,
    ) -> PortfolioSuggestion:
        """Rank stocks and generate portfolio suggestions."""
        if not stocks:
            return PortfolioSuggestion()

        rankings: list[StockRanking] = []

        if self._model and self._is_trained:
            X = [features_to_array(s) for s in stocks]
            probas = self._model.predict_proba(X)

            for i, stock in enumerate(stocks):
                # Probability of class 2 (BUY) is the score
                buy_prob = float(probas[i][2]) if len(probas[i]) > 2 else 0.0
                sell_prob = float(probas[i][0]) if len(probas[i]) > 0 else 0.0

                if buy_prob > 0.5:
                    action = "BUY"
                    score = buy_prob
                elif sell_prob > 0.5:
                    action = "SELL"
                    score = 1.0 - sell_prob
                else:
                    action = "HOLD"
                    score = 0.5

                rankings.append(StockRanking(
                    symbol=stock.symbol,
                    exchange=stock.exchange,
                    score=score,
                    action=action,
                ))
        else:
            # Fallback: simple score from available features
            rankings = self._simple_rank(stocks)

        # Sort by score descending
        rankings.sort(key=lambda r: r.score, reverse=True)
        for i, r in enumerate(rankings):
            r.rank = i + 1

        # Top N buy picks get allocation
        top = [r for r in rankings if r.action == "BUY"][:top_n]
        if top:
            total_score = sum(r.score for r in top)
            for r in top:
                r.allocation_pct = (r.score / total_score * 100) if total_score > 0 else 100 / len(top)

        return PortfolioSuggestion(
            rankings=rankings[:top_n * 2],
            total_stocks=len(stocks),
            model_accuracy=self._accuracy,
        )

    @staticmethod
    def _simple_rank(stocks: list[StockFeatures]) -> list[StockRanking]:
        """Simple heuristic ranking when model is not trained."""
        rankings: list[StockRanking] = []
        for s in stocks:
            # Composite score from momentum + value + sentiment
            momentum = (s.return_1m + s.return_3m * 0.5 + s.return_6m * 0.3) / 100
            value = 0.0
            if s.pe_ratio > 0:
                value = max(0, 1 - s.pe_ratio / 50)  # Lower PE = higher value
            if s.roe > 0:
                value += min(0.3, s.roe / 100)

            score = max(0, min(1, 0.5 + momentum + value * 0.3 + s.sentiment_score * 0.2))

            action = "HOLD"
            if score > 0.65:
                action = "BUY"
            elif score < 0.35:
                action = "SELL"

            rankings.append(StockRanking(
                symbol=s.symbol,
                exchange=s.exchange,
                score=score,
                action=action,
            ))
        return rankings

    def check_rebalance(
        self,
        current_holdings: dict[str, float],
        target_allocations: dict[str, float],
        threshold_pct: float = 5.0,
    ) -> list[RebalanceAlert]:
        """Check if portfolio needs rebalancing.

        current_holdings: {"RELIANCE": 15.0, "TCS": 12.0, ...} — current % allocation
        target_allocations: {"RELIANCE": 10.0, "TCS": 10.0, ...} — target %
        threshold_pct: minimum drift % to trigger alert
        """
        alerts: list[RebalanceAlert] = []
        all_symbols = set(current_holdings.keys()) | set(target_allocations.keys())

        for sym in all_symbols:
            current = current_holdings.get(sym, 0.0)
            target = target_allocations.get(sym, 0.0)
            drift = current - target

            if abs(drift) >= threshold_pct:
                if target == 0 and current > 0:
                    action = "EXIT"
                elif drift > 0:
                    action = "DECREASE"
                else:
                    action = "INCREASE"

                alerts.append(RebalanceAlert(
                    symbol=sym,
                    current_pct=current,
                    target_pct=target,
                    drift_pct=drift,
                    action=action,
                ))

        return sorted(alerts, key=lambda a: abs(a.drift_pct), reverse=True)

    def save(self, path: str) -> None:
        """Save trained model to disk."""
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self._model,
            "is_trained": self._is_trained,
            "accuracy": self._accuracy,
        }, path)
        logger.info("Advisor model saved to %s", path)

    def load(self, path: str) -> None:
        """Load trained model from disk."""
        try:
            import joblib
        except ImportError:
            raise ImportError("joblib required — pip install joblib")
        data = joblib.load(path)
        self._model = data["model"]
        self._is_trained = data["is_trained"]
        self._accuracy = data["accuracy"]
        logger.info("Advisor model loaded from %s (accuracy=%.2f)", path, self._accuracy)
