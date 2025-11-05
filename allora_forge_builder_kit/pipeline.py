from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
import yaml

from .alpha_features import build_alpha_features
from .environment import load_environment, require_api_key
from .logging_utils import get_stage_logger, initialise_logging
from .schedule import CompetitionSchedule, WindowSet
from .submission import SubmissionConfig, SubmissionResult, submit_prediction
from .submission_log import ensure_submission_log_schema
from .workflow import AlloraMLWorkflow


@dataclass
class TrainingResult:
    prediction_time: datetime
    prediction_value: float
    windows: WindowSet
    metrics: Dict[str, float]
    artifact_path: Path


@dataclass
class PipelineConfig:
    root: Path
    topic_id: int
    ticker: str
    target_hours: int
    history_buffer_hours: int
    schedule: CompetitionSchedule
    artifact_path: Path
    metrics_path: Path
    model_path: Path
    submission_log: Path
    submission_timeout: int
    submission_retries: int

    @classmethod
    def from_file(cls, root: Path) -> "PipelineConfig":
        cfg_path = root / "config" / "pipeline.yaml"
        if not cfg_path.exists():
            raise FileNotFoundError(f"Missing configuration file: {cfg_path}")
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}

        data_cfg = data.get("data", {})
        schedule_cfg = data.get("schedule", {})
        submission_cfg = data.get("submission", {})

        schedule = CompetitionSchedule.from_dict(schedule_cfg)
        artifact_rel = submission_cfg.get("artifact_path", "data/artifacts/predictions.json")
        metrics_rel = submission_cfg.get("metrics_path", "data/artifacts/metrics.json")
        model_rel = submission_cfg.get("model_path", "data/artifacts/model.joblib")
        log_rel = submission_cfg.get("log_path", "submission_log.csv")

        return cls(
            root=root,
            topic_id=int(submission_cfg.get("topic_id", 67)),
            ticker=str(data_cfg.get("ticker", "btcusd")),
            target_hours=int(data_cfg.get("target_hours", 168)),
            history_buffer_hours=int(data_cfg.get("history_buffer_hours", 24)),
            schedule=schedule,
            artifact_path=(root / artifact_rel).resolve(),
            metrics_path=(root / metrics_rel).resolve(),
            model_path=(root / model_rel).resolve(),
            submission_log=(root / log_rel).resolve(),
            submission_timeout=int(submission_cfg.get("timeout_seconds", 120)),
            submission_retries=int(submission_cfg.get("retries", 2)),
        )


class Pipeline:
    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        self.root = config.root
        self.train_logger = get_stage_logger("train")

    @classmethod
    def from_repo_root(cls, root: Optional[Path] = None) -> "Pipeline":
        repo_root = root or Path(__file__).resolve().parent.parent
        load_environment(repo_root)
        initialise_logging(repo_root)
        cfg = PipelineConfig.from_file(repo_root)
        ensure_submission_log_schema(str(cfg.submission_log))
        return cls(cfg)

    def run_training(self, when: Optional[datetime] = None) -> TrainingResult:
        windows = self.config.schedule.windows(when)
        self.train_logger.info("Training for inference window ending %s", windows.inference_time)

        series = self._load_hourly_series(windows)
        features = build_alpha_features(series["close"])  # type: ignore[arg-type]
        features = features.fillna(method="ffill").dropna()
        features = self._deduplicate_features(features)

        # Add simple volume feature for additional signal
        if "volume" in series:
            volume_hourly = series["volume"].resample("1h").sum().reindex(features.index).fillna(0.0)
            features["volume_log"] = np.log1p(volume_hourly)

        target = np.log(series["close"].shift(-self.config.target_hours) / series["close"])
        frame = features.join(target.rename("target"), how="left")
        cutoff = windows.inference_time.astimezone(timezone.utc).replace(tzinfo=None)
        features = features.loc[features.index <= cutoff]
        frame = frame.loc[frame.index <= cutoff]
        if features.empty:
            raise RuntimeError("No feature rows available prior to inference time.")

        train_df = self._slice(frame, windows.train_start, windows.train_end)
        val_df = self._slice(frame, windows.validation_start, windows.validation_end)
        test_df = self._slice(frame, windows.test_start, windows.test_end)

        self.train_logger.info(
            "Samples - train: %s validation: %s test: %s",
            len(train_df),
            len(val_df),
            len(test_df),
        )

        if train_df.empty:
            raise RuntimeError("Training window produced no samples. Check data availability.")

        model = GradientBoostingRegressor(random_state=42)
        model.fit(train_df.drop(columns=["target"]).values, train_df["target"].values)

        metrics = self._evaluate(model, train_df, val_df, test_df)

        inference_row, inference_time = self._select_inference_row(features, windows.inference_time)
        prediction_value = float(model.predict(inference_row.values.reshape(1, -1))[0])

        self._write_artifacts(prediction_value, inference_time, windows, metrics, model)

        return TrainingResult(
            prediction_time=inference_time,
            prediction_value=prediction_value,
            windows=windows,
            metrics=metrics,
            artifact_path=self.config.artifact_path,
        )

    def run_submission(self, artifact_path: Optional[Path] = None, topic_id: Optional[int] = None, timeout: Optional[int] = None, retries: Optional[int] = None) -> SubmissionResult:
        path = Path(artifact_path or self.config.artifact_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        value = float(data["value"])
        topic = int(topic_id or data.get("topic_id", self.config.topic_id))
        api_key = require_api_key()

        cfg = SubmissionConfig(
            topic_id=topic,
            timeout_seconds=int(timeout or self.config.submission_timeout),
            retries=int(retries or self.config.submission_retries),
            log_path=self.config.submission_log,
            repo_root=self.root,
            api_key=api_key,
        )
        return asyncio.run(submit_prediction(value, cfg))

    def train_and_submit(self, when: Optional[datetime] = None) -> SubmissionResult:
        self.run_training(when)
        return self.run_submission(self.config.artifact_path, self.config.topic_id)

    def _load_hourly_series(self, windows: WindowSet) -> pd.DataFrame:
        api_key = require_api_key()
        hours_needed = int((windows.inference_time - windows.train_start).total_seconds() // 3600) + self.config.target_hours + self.config.history_buffer_hours
        workflow = AlloraMLWorkflow(
            data_api_key=api_key,
            tickers=[self.config.ticker],
            hours_needed=hours_needed,
            number_of_input_candles=12,
            target_length=self.config.target_hours,
        )

        start_date = (windows.train_start - timedelta(hours=self.config.history_buffer_hours)).date().isoformat()
        raw = workflow.fetch_ohlcv_data(self.config.ticker, start_date)
        bars = workflow.create_5_min_bars(raw, live_mode=False)

        hourly = bars.resample("1h").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        idx = pd.DatetimeIndex(hourly.index)
        if getattr(idx, "tz", None) is not None:
            hourly.index = idx.tz_convert("UTC").tz_localize(None)
        else:
            hourly.index = idx
        if hourly.empty:
            raise RuntimeError("No hourly data returned from market data service.")
        return hourly

    def _slice(self, frame: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
        start_naive = start.astimezone(timezone.utc).replace(tzinfo=None)
        end_naive = end.astimezone(timezone.utc).replace(tzinfo=None)
        sliced = frame.loc[(frame.index >= start_naive) & (frame.index < end_naive)]
        return sliced.dropna(subset=["target"])

    def _select_inference_row(self, features: pd.DataFrame, inference_time: datetime) -> tuple[pd.Series, datetime]:
        idx = features.index
        if isinstance(idx, pd.DatetimeIndex):
            idx = idx.tz_localize(None) if idx.tz is not None else idx
        target_time = inference_time.replace(tzinfo=None)
        if target_time in idx:
            row = features.loc[target_time]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            return row, target_time
        eligible = features.loc[idx <= target_time]
        if eligible.empty:
            raise ValueError("No features available before inference time")
        row = eligible.iloc[-1]
        actual_time = eligible.index[-1]
        return row, pd.Timestamp(actual_time).to_pydatetime() if isinstance(actual_time, pd.Timestamp) else actual_time

    def _evaluate(self, model: GradientBoostingRegressor, train_df: pd.DataFrame, val_df: pd.DataFrame, test_df: pd.DataFrame) -> Dict[str, float]:
        metrics: Dict[str, float] = {}
        for label, df in (("train", train_df), ("validation", val_df), ("test", test_df)):
            if df.empty:
                continue
            preds = model.predict(df.drop(columns=["target"]).values)
            y_true = df["target"].values
            mse = mean_squared_error(y_true, preds)
            mae = mean_absolute_error(y_true, preds)
            metrics[f"{label}_mae"] = float(mae)
            metrics[f"{label}_mse"] = float(mse)
            metrics[f"{label}_log10_loss"] = float(np.log10(mse)) if mse > 0 else float("-inf")
        return metrics

    def _write_artifacts(self, prediction_value: float, inference_time: datetime, windows: WindowSet, metrics: Dict[str, float], model: GradientBoostingRegressor) -> None:
        artifact_dir = self.config.artifact_path.parent
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metrics_dir = self.config.metrics_path.parent
        metrics_dir.mkdir(parents=True, exist_ok=True)
        self.config.model_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "topic_id": self.config.topic_id,
            "value": prediction_value,
            "prediction_time_utc": inference_time.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z"),
            "windows": windows.as_dict(),
        }
        self.config.artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.train_logger.info("Wrote prediction artifact to %s", self.config.artifact_path)

        metrics_payload = {k: float(v) for k, v in metrics.items()}
        self.config.metrics_path.write_text(json.dumps(metrics_payload, indent=2), encoding="utf-8")
        self.train_logger.info("Wrote metrics artifact to %s", self.config.metrics_path)

        joblib.dump(model, self.config.model_path)
        self.train_logger.info("Persisted model to %s", self.config.model_path)


    def _deduplicate_features(self, features: pd.DataFrame) -> pd.DataFrame:
        """Drop duplicate feature columns (by name or identical values) and log counts."""
        if features.empty:
            return features

        initial_count = features.shape[1]

        # Drop duplicate column names, keeping the last occurrence to mirror pandas join semantics
        if features.columns.duplicated().any():
            dup_names = features.columns[features.columns.duplicated()].unique().tolist()
            before = features.shape[1]
            features = features.loc[:, ~features.columns.duplicated(keep="last")]
            removed = before - features.shape[1]
            self.train_logger.warning(
                "Duplicate feature names detected; removed %d columns (names: %s)",
                removed,
                dup_names,
            )

        # Drop columns that are perfectly correlated due to identical values
        if not features.empty:
            before_redundant = features.shape[1]
            transposed = features.T.drop_duplicates(keep="last")
            features = transposed.T
            redundant_removed = before_redundant - features.shape[1]
            if redundant_removed > 0:
                self.train_logger.warning(
                    "Redundant feature vectors detected; removed %d columns due to identical values.",
                    redundant_removed,
                )

        if features.columns.duplicated().any():
            dup = features.columns[features.columns.duplicated()].unique().tolist()
            raise RuntimeError(f"Feature engineering produced duplicate columns after deduplication: {dup}")

        removed_total = initial_count - features.shape[1]
        self.train_logger.info(
            "Feature dimensionality after deduplication: %d columns (removed %d)",
            features.shape[1],
            removed_total,
        )
        return features


    
