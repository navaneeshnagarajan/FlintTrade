"""RL agent trainer for trading environments.

Adapts patterns from FinRL's DRLAgent and train.py. Provides a unified
interface for training RL agents on historical market data using
stable-baselines3 (optional dependency).

All stable-baselines3 imports are lazy — this module can be imported
and the trainer instantiated without RL libraries installed. Only
train/predict/save/load require the actual libraries.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

try:
    from .rl_environment import TradingEnvironment
except ImportError:
    from flinttrade_backtest.rl_environment import TradingEnvironment

logger = logging.getLogger("flinttrade.backtest.rl_trainer")


# ---------------------------------------------------------------------------
# Supported algorithms (matches FinRL's MODELS dict)
# ---------------------------------------------------------------------------


class RLAlgorithm(StrEnum):
    """Supported RL algorithms (from stable-baselines3)."""

    PPO = "PPO"
    A2C = "A2C"
    DDPG = "DDPG"
    SAC = "SAC"
    TD3 = "TD3"


# Default hyperparameters per algorithm (from FinRL's config.py)
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "PPO": {
        "n_steps": 2048,
        "ent_coef": 0.01,
        "learning_rate": 0.00025,
        "batch_size": 64,
    },
    "A2C": {
        "n_steps": 5,
        "ent_coef": 0.01,
        "learning_rate": 0.0007,
    },
    "DDPG": {
        "batch_size": 128,
        "buffer_size": 50_000,
        "learning_rate": 0.001,
    },
    "SAC": {
        "batch_size": 64,
        "buffer_size": 100_000,
        "learning_rate": 0.0001,
        "learning_starts": 100,
    },
    "TD3": {
        "batch_size": 100,
        "buffer_size": 1_000_000,
        "learning_rate": 0.001,
    },
}


# ---------------------------------------------------------------------------
# Training result
# ---------------------------------------------------------------------------


@dataclass
class TrainingResult:
    """Result of an RL training run."""

    algorithm: str = ""
    total_timesteps: int = 0
    training_time_seconds: float = 0.0
    final_reward: float = 0.0
    episode_rewards: list[float] = field(default_factory=list)
    model_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Training job status (for async API)
# ---------------------------------------------------------------------------


@dataclass
class TrainingJob:
    """Tracks an RL training job's progress."""

    job_id: str = ""
    status: str = "pending"  # pending, running, completed, failed
    progress_pct: float = 0.0
    algorithm: str = ""
    total_timesteps: int = 0
    elapsed_seconds: float = 0.0
    result: TrainingResult | None = None
    error: str = ""


# In-memory job registry (for the Flask endpoint)
_jobs: dict[str, TrainingJob] = {}


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class RLTrainer:
    """Train RL agents on historical market data.

    Wraps stable-baselines3 algorithms with a clean interface.
    The trainer is usable without SB3 installed — only train/predict
    methods require it.

    Usage::

        env = TradingEnvironment(df, features=['returns', 'rsi_14'])
        trainer = RLTrainer(env, algorithm='PPO')
        result = trainer.train(total_timesteps=100_000)
        action = trainer.predict(observation)
        trainer.save('models/ppo_nifty')
    """

    def __init__(
        self,
        env: TradingEnvironment,
        algorithm: str = "PPO",
        model_kwargs: dict[str, Any] | None = None,
        policy: str = "MlpPolicy",
        seed: int | None = None,
        verbose: int = 0,
    ) -> None:
        """Initialise the trainer.

        Args:
            env: TradingEnvironment instance.
            algorithm: one of PPO, A2C, DDPG, SAC, TD3.
            model_kwargs: override default hyperparameters.
            policy: SB3 policy class name.
            seed: random seed for reproducibility.
            verbose: SB3 verbosity level.
        """
        self._env = env
        self._algorithm = RLAlgorithm(algorithm.upper())
        self._policy = policy
        self._seed = seed
        self._verbose = verbose

        # Merge defaults with overrides
        self._model_kwargs = dict(DEFAULT_PARAMS.get(self._algorithm.value, {}))
        if model_kwargs:
            self._model_kwargs.update(model_kwargs)

        self._model: Any = None
        self._is_trained = False

    @property
    def algorithm(self) -> str:
        """The algorithm name."""
        return self._algorithm.value

    @property
    def is_trained(self) -> bool:
        """Whether the model has been trained."""
        return self._is_trained

    # ------------------------------------------------------------------
    # Core methods
    # ------------------------------------------------------------------

    def train(
        self,
        total_timesteps: int = 100_000,
        progress_callback: Any | None = None,
    ) -> TrainingResult:
        """Train the RL agent.

        Args:
            total_timesteps: number of environment steps to train for.
            progress_callback: optional callable(timestep, total) for progress.

        Returns:
            TrainingResult with training metrics.

        Raises:
            ImportError if stable-baselines3 is not installed.
        """
        sb3_models = self._import_sb3()

        # Build model
        model_class = sb3_models[self._algorithm.value]
        kwargs = {k: v for k, v in self._model_kwargs.items() if k != "action_noise"}

        # Handle action noise for off-policy algorithms
        if "action_noise" in self._model_kwargs and self._algorithm.value in ("DDPG", "TD3", "SAC"):
            try:
                from stable_baselines3.common.noise import NormalActionNoise
                n_actions = self._env.action_space.shape[-1]
                kwargs["action_noise"] = NormalActionNoise(
                    mean=np.zeros(n_actions),
                    sigma=0.1 * np.ones(n_actions),
                )
            except ImportError:
                pass

        self._model = model_class(
            policy=self._policy,
            env=self._env,
            verbose=self._verbose,
            seed=self._seed,
            **kwargs,
        )

        start = time.time()
        logger.info(
            "Training %s for %d timesteps...", self._algorithm.value, total_timesteps,
        )

        self._model.learn(total_timesteps=total_timesteps)
        elapsed = time.time() - start
        self._is_trained = True

        logger.info("Training complete in %.1fs", elapsed)

        result = TrainingResult(
            algorithm=self._algorithm.value,
            total_timesteps=total_timesteps,
            training_time_seconds=elapsed,
            metadata={
                "policy": self._policy,
                "model_kwargs": {k: str(v) for k, v in self._model_kwargs.items()},
            },
        )

        return result

    def predict(
        self,
        observation: np.ndarray,
        deterministic: bool = True,
    ) -> np.ndarray:
        """Get action from trained agent.

        Args:
            observation: observation vector from the environment.
            deterministic: if True, use deterministic policy.

        Returns:
            Action array.

        Raises:
            RuntimeError if model has not been trained or loaded.
        """
        if self._model is None:
            raise RuntimeError(
                "No model available. Call train() or load() first."
            )

        action, _states = self._model.predict(observation, deterministic=deterministic)
        return np.asarray(action)

    def evaluate(
        self,
        env: TradingEnvironment | None = None,
        n_episodes: int = 1,
        deterministic: bool = True,
    ) -> dict[str, Any]:
        """Evaluate the trained agent on an environment.

        Args:
            env: environment to evaluate on (defaults to training env).
            n_episodes: number of episodes to run.
            deterministic: use deterministic policy.

        Returns:
            Dict with evaluation metrics.
        """
        if self._model is None:
            raise RuntimeError("No model available. Call train() or load() first.")

        eval_env = env or self._env
        episode_returns: list[float] = []
        episode_lengths: list[int] = []

        for _ in range(n_episodes):
            obs, info = eval_env.reset()
            total_reward = 0.0
            steps = 0
            done = False

            while not done:
                action = self.predict(obs, deterministic=deterministic)
                obs, reward, terminated, truncated, info = eval_env.step(action)
                total_reward += reward
                steps += 1
                done = terminated or truncated

            episode_returns.append(info.get("total_return", total_reward))
            episode_lengths.append(steps)

        return {
            "mean_return": float(np.mean(episode_returns)),
            "std_return": float(np.std(episode_returns)),
            "mean_length": float(np.mean(episode_lengths)),
            "n_episodes": n_episodes,
            "episode_returns": episode_returns,
        }

    def save(self, path: str) -> None:
        """Save trained model to disk.

        Args:
            path: file path (without extension — SB3 adds .zip).

        Raises:
            RuntimeError if model has not been trained.
        """
        if self._model is None:
            raise RuntimeError("No model to save. Call train() first.")

        # Ensure parent directory exists
        parent = Path(path).parent
        parent.mkdir(parents=True, exist_ok=True)

        self._model.save(path)
        logger.info("Model saved to %s", path)

        # Save metadata alongside
        meta_path = f"{path}_meta.json"
        meta = {
            "algorithm": self._algorithm.value,
            "policy": self._policy,
            "model_kwargs": {k: str(v) for k, v in self._model_kwargs.items()},
            "obs_dim": self._env.obs_dim,
            "stock_dim": self._env.stock_dim,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    def load(self, path: str) -> None:
        """Load a trained model from disk.

        Args:
            path: file path (without extension).

        Raises:
            ImportError if stable-baselines3 is not installed.
        """
        sb3_models = self._import_sb3()
        model_class = sb3_models[self._algorithm.value]

        self._model = model_class.load(path, env=self._env)
        self._is_trained = True
        logger.info("Model loaded from %s", path)

    # ------------------------------------------------------------------
    # SB3 import helper
    # ------------------------------------------------------------------

    @staticmethod
    def _import_sb3() -> dict[str, Any]:
        """Lazily import stable-baselines3 models.

        Returns:
            Dict mapping algorithm name to SB3 class.

        Raises:
            ImportError with installation instructions.
        """
        try:
            from stable_baselines3 import A2C, DDPG, PPO, SAC, TD3
            return {
                "PPO": PPO,
                "A2C": A2C,
                "DDPG": DDPG,
                "SAC": SAC,
                "TD3": TD3,
            }
        except ImportError as exc:
            raise ImportError(
                "stable-baselines3 is required for RL training. "
                "Install with: pip install 'stable-baselines3[extra]'"
            ) from exc


# ---------------------------------------------------------------------------
# Flask endpoint helpers
# ---------------------------------------------------------------------------


def register_rl_endpoints(app: Any) -> None:
    """Register RL training/prediction Flask endpoints.

    Endpoints:
        POST /api/v1/backtest/rl/train — start RL training job
        GET  /api/v1/backtest/rl/status/<job_id> — training progress
        POST /api/v1/backtest/rl/predict — get action from trained model

    Args:
        app: Flask application instance.
    """
    try:
        from flask import Flask, jsonify, request  # noqa: F401
    except ImportError:
        logger.warning("Flask not available — RL endpoints not registered")
        return

    @app.route("/api/v1/backtest/rl/train", methods=["POST"])
    def rl_train() -> Any:
        """Start an RL training job.

        Request body (JSON):
            algorithm: str (PPO, A2C, DDPG, SAC, TD3)
            total_timesteps: int
            initial_capital: float
            features: list[str]
            reward_type: str
            model_kwargs: dict (optional)

        Returns:
            JSON with job_id and status.
        """
        data = request.get_json(silent=True) or {}
        job_id = f"rl_{int(time.time() * 1000)}"

        job = TrainingJob(
            job_id=job_id,
            status="pending",
            algorithm=data.get("algorithm", "PPO"),
            total_timesteps=data.get("total_timesteps", 100_000),
        )
        _jobs[job_id] = job

        # In a production setup this would be dispatched to a background
        # worker (Celery, threading, etc.). For now, return immediately
        # with the job_id — the caller polls /status/<job_id>.
        job.status = "pending"

        return jsonify({
            "job_id": job_id,
            "status": job.status,
            "algorithm": job.algorithm,
            "total_timesteps": job.total_timesteps,
        }), 202

    @app.route("/api/v1/backtest/rl/status/<job_id>", methods=["GET"])
    def rl_status(job_id: str) -> Any:
        """Get training job status.

        Returns:
            JSON with job status, progress, and result (if completed).
        """
        job = _jobs.get(job_id)
        if job is None:
            return jsonify({"error": f"Job {job_id} not found"}), 404

        response: dict[str, Any] = {
            "job_id": job.job_id,
            "status": job.status,
            "progress_pct": job.progress_pct,
            "algorithm": job.algorithm,
            "elapsed_seconds": job.elapsed_seconds,
        }

        if job.result is not None:
            response["result"] = {
                "training_time_seconds": job.result.training_time_seconds,
                "total_timesteps": job.result.total_timesteps,
                "model_path": job.result.model_path,
            }

        if job.error:
            response["error"] = job.error

        return jsonify(response), 200

    @app.route("/api/v1/backtest/rl/predict", methods=["POST"])
    def rl_predict() -> Any:
        """Get action from a trained model.

        Request body (JSON):
            model_path: str — path to saved model
            algorithm: str
            observation: list[float]
            deterministic: bool (default True)

        Returns:
            JSON with action array.
        """
        data = request.get_json(silent=True) or {}

        model_path = data.get("model_path", "")
        algorithm = data.get("algorithm", "PPO")
        observation = data.get("observation", [])
        deterministic = data.get("deterministic", True)

        if not model_path or not observation:
            return jsonify({
                "error": "model_path and observation are required",
            }), 400

        try:
            sb3_models = RLTrainer._import_sb3()
            model_class = sb3_models[algorithm.upper()]
            model = model_class.load(model_path)

            obs = np.array(observation, dtype=np.float32)
            action, _states = model.predict(obs, deterministic=deterministic)

            return jsonify({
                "action": action.tolist() if hasattr(action, "tolist") else list(action),
                "algorithm": algorithm,
            }), 200
        except ImportError:
            return jsonify({"error": "Internal server error"}), 500
        except Exception:
            return jsonify({"error": "Internal server error"}), 500
