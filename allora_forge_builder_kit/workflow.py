import pandas as pd
import numpy as np
import requests
from requests import exceptions as requests_exceptions
import time
from datetime import datetime, timedelta, timezone
import os
import dill

class AlloraMLWorkflow:
    def __init__(
        self,
        data_api_key,
        tickers,
        hours_needed,
        number_of_input_candles,
        target_length,
        sample_spacing_hours: int | None = None,
    ):
        # Normalize API key and store
        self.api_key = (data_api_key or "").strip()
        self.tickers = tickers
        self.hours_needed = hours_needed  # For input window
        self.number_of_input_candles = number_of_input_candles
        self.target_length = target_length  # Target horizon in hours
        self.test_targets = None
        self.validation_targets = None
        self.sample_spacing_hours = sample_spacing_hours or target_length
        self.latest_data_timestamp: pd.Timestamp | None = None

    def _headers(self):
        """Return robust auth headers to handle different casing/standards.
        Some gateways may expect X-API-Key while others accept x-api-key; a few accept Authorization: Bearer.
        """
        if not self.api_key:
            return {}
        return {
            "X-API-Key": self.api_key,
            "x-api-key": self.api_key,
            "Authorization": f"Bearer {self.api_key}",
        }

    def _get_tiingo_key(self):
        """Return the data API key.

        Historically this fetched ``TIINGO_API_KEY`` for the fallback OHLCV
        data source. The builder now standardises on ``ALLORA_API_KEY`` for
        all market-data access so the environment no longer needs a separate
        Tiingo-specific variable.
        """
        return (os.getenv("ALLORA_API_KEY") or "").strip()

    def fetch_ohlcv_data_tiingo(self, ticker: str, from_date: str) -> pd.DataFrame:
        """
        Fallback fetch using Tiingo Crypto 1-min candles.
        Maps to columns: date, open, high, low, close, volume, trades_done (filled with 0).
        """
        tkey = self._get_tiingo_key()
        if not tkey:
            raise RuntimeError("ALLORA_API_KEY not set; cannot fallback to Tiingo.")
        # Tiingo expects startDate in ISO date and tickers like btcusd
        url = "https://api.tiingo.com/tiingo/crypto/prices"
        params = {
            "tickers": ticker.lower(),
            "startDate": from_date,
            "resampleFreq": "1min",
            "token": tkey,
        }
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, list) or not data:
            raise RuntimeError("Unexpected Tiingo response format")
        # Tiingo returns a list where first element has priceData list
        price_data = data[0].get("priceData", [])
        if not price_data:
            raise ValueError("No data returned from Tiingo")
        df = pd.DataFrame(price_data)
        # Normalize columns
        rename_map = {
            "date": "date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }
        # Some fields may be named slightly differently
        df = df.rename(columns=rename_map)
        # Ensure required columns exist
        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = np.nan
        df["date"] = pd.to_datetime(df["date"], utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # trades_done not provided by Tiingo; fill with zeros
        df["trades_done"] = 0
        # Align with expected schema
        keep_cols = ["date", "open", "high", "low", "close", "volume", "trades_done"]
        df = df[keep_cols]
        return df

    def compute_from_date(self, extra_hours: int = 12) -> str:
        total_hours = self.hours_needed + extra_hours
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=total_hours)
        return cutoff_time.strftime("%Y-%m-%d")

    def list_ready_buckets(self, ticker, from_month):
        url = "https://api.allora.network/v2/allora/market-data/ohlc/buckets/by-month"
        headers = self._headers()
        try:
            resp = requests.get(url, headers=headers, params={"tickers": ticker, "from_month": from_month}, timeout=30)
        except requests_exceptions.RequestException as exc:
            raise RuntimeError(f"Network error when listing buckets for {ticker}: {exc}") from exc
        if resp.status_code == 401:
            # Provide a clear message for auth issues
            try:
                detail = resp.json()
            except ValueError:
                detail = resp.text
            raise RuntimeError(f"Unauthorized (401) when listing buckets. Check ALLORA_API_KEY. Detail: {detail}")
        resp.raise_for_status()
        buckets = resp.json()["data"]["data"]
        return [b for b in buckets if b["state"] == "ready"]

    def fetch_bucket_csv(self, download_url):
        try:
            df = pd.read_csv(download_url)
        except Exception as exc:
            raise RuntimeError(f"Failed to download bucket CSV: {exc}") from exc
        df.drop(columns=['exchange_code'], inplace=True)
        return df

    def _offline_ohlcv_from_local(self, ticker: str, from_date: str) -> pd.DataFrame:
        """Fallback loader that sources OHLCV data from local fixtures or generates synthetic data."""
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        local_path = os.path.join(root, "data", "external", f"{ticker}_ohlcv.csv")
        df = pd.DataFrame()
        if os.path.exists(local_path):
            try:
                df = pd.read_csv(local_path)
            except (OSError, IOError, ValueError) as exc:
                print(f"Warning: failed to read local OHLCV fixture {local_path}: {exc}")
                df = pd.DataFrame()
        if df.empty:
            # Generate deterministic synthetic data so offline runs remain reproducible
            try:
                start = pd.Timestamp(from_date, tz="UTC")
            except Exception:
                start = pd.Timestamp.utcnow().tz_localize("UTC") - pd.Timedelta(days=180)
            periods = max(self.hours_needed * 60 * 2, 60 * 24 * 30)  # at least ~30 days of 1-min data
            rng = np.random.default_rng(abs(hash((ticker, from_date))) % (2 ** 32))
            index = pd.date_range(start=start, periods=periods, freq="1min", tz="UTC")
            base = 30000 + rng.normal(0, 10, size=periods).cumsum()
            close = base + rng.normal(0, 2, size=periods)
            high = np.maximum(base, close) + rng.random(size=periods)
            low = np.minimum(base, close) - rng.random(size=periods)
            volume = rng.lognormal(mean=8, sigma=0.4, size=periods)
            trades = rng.integers(10, 200, size=periods)
            df = pd.DataFrame(
                {
                    "date": index,
                    "open": base,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                    "trades_done": trades,
                }
            )
        if "trades_done" not in df.columns:
            df["trades_done"] = 0
        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
        df = df.dropna(subset=["date"])
        filtered = df
        if from_date:
            try:
                start = pd.Timestamp(from_date, tz="UTC")
                filtered = df[df["date"] >= start]
            except Exception:
                filtered = df
        if filtered.empty:
            filtered = df
        df = filtered
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def fetch_ohlcv_data(self, ticker, from_date: str, max_pages: int = 1000, sleep_sec: float = 0.1) -> pd.DataFrame:
        url = "https://api.allora.network/v2/allora/market-data/ohlc"
        headers = self._headers()
        params = {"tickers": ticker, "from_date": from_date}

        all_data = []
        pages_fetched = 0

        while pages_fetched < max_pages:
            try:
                response = requests.get(url, headers=headers, params=params, timeout=30)
            except requests_exceptions.RequestException as exc:
                print(f"Warning: network error when fetching OHLC for {ticker}: {exc}. Falling back to offline data.")
                return self._offline_ohlcv_from_local(ticker, from_date)
            if response.status_code == 401:
                try:
                    detail = response.json()
                except ValueError:
                    detail = response.text
                raise RuntimeError(f"Unauthorized (401) when fetching OHLC. Check ALLORA_API_KEY. Detail: {detail}")
            response.raise_for_status()
            payload = response.json()
            if not payload.get("status", False):
                raise RuntimeError("API responded with an error status.")

            all_data.extend(payload["data"]["data"])

            token = payload["data"].get("continuation_token")
            if not token:
                break

            params["continuation_token"] = token
            pages_fetched += 1
            time.sleep(sleep_sec)

        df = pd.DataFrame(all_data)
        if df.empty:
            print("Warning: empty response from Allora OHLC API; using offline fallback data.")
            return self._offline_ohlcv_from_local(ticker, from_date)

        for col in ["open", "high", "low", "close", "volume", "volume_notional"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        # Ensure timezone-aware UTC timestamps
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df.drop(columns=['exchange_code'], inplace=True)
        return df

    def create_5_min_bars(self, df: pd.DataFrame, live_mode: bool = False) -> pd.DataFrame:
        # Ensure UTC-aware datetime index
        if "date" in df.columns:
            di = pd.to_datetime(df["date"], utc=True)
            df = df.set_index(di).sort_index().dropna()
        else:
            # If already indexed by datetime, coerce to UTC
            di = pd.to_datetime(df.index, utc=True)
            df = df.copy()
            df.index = di
        # print("Raw 1-min timestamps:", df.index[-10:])  # Show last 10 timestamps for debugging

        if not live_mode:
            bars = df.resample("5min").apply({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "trades_done": "sum"
            })
        else:
            last_ts = df.index[-1]
            now = datetime.now(timezone.utc)
            if last_ts > now:
                # print(f"Dropping incomplete 1-min bar at {last_ts} (future timestamp)")
                df = df.iloc[:-1]
            else:
                # Drop the last bar if the current time in seconds is < 45
                if last_ts.minute == now.minute and last_ts.hour == now.hour and now.second < 45:
                    # print(f"Dropping incomplete 1-min bar at {last_ts} (current second: {now.second})")
                    df = df.iloc[:-1]
            last_ts = df.index[-1]
            minute = last_ts.minute
            offset_minutes = (minute + 1) % 5
            offset = f"{offset_minutes}min" if offset_minutes != 0 else "0min"
            # print(f"Live mode: last minute={minute}, offset_minutes={offset_minutes}, offset={offset}")
            bars = df.resample("5min", offset=offset).apply({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
                "trades_done": "sum"
            })

        # print("5-min bar timestamps:", bars.index[-10:])  # Show last 10 bar timestamps for debugging
        bars = bars.dropna()
        return bars

    def compute_target(self, df: pd.DataFrame, hours: int = 24) -> pd.DataFrame:
        df["future_close"] = df["close"].shift(freq=f"-{hours}h")
        df["target"] = np.log(df["future_close"]) - np.log(df["close"])
        return df

    def extract_rolling_daily_features(
        self, data: pd.DataFrame, lookback: int, number_of_candles: int, start_times: list
    ) -> pd.DataFrame:
        # Convert index to naive UTC ndarray[datetime64[ns]] for quick lookup (avoid NumPy tz warnings)
        idx = pd.DatetimeIndex(data.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        # Force numpy datetime64[ns] dtype to avoid object/int comparisons
        ts_index = idx.to_numpy(dtype="datetime64[ns]")
        data_values = data[["open", "high", "low", "close", "volume", "trades_done"]].to_numpy()
        features_list = []
        index_list = []
    
        candle_length = lookback * 12  # 12 points per hour if 5min bars
    
        for T in start_times:
            # Normalize each start time to naive UTC datetime64[ns] to match ts_index dtype
            if not isinstance(T, (np.datetime64, pd.Timestamp)):
                T = pd.Timestamp(T)
            if isinstance(T, pd.Timestamp):
                if getattr(T, "tz", None) is not None:
                    T = T.tz_convert("UTC").tz_localize(None)
                T64 = T.to_datetime64()
            else:
                # Ensure nanosecond precision for searchsorted compatibility
                T64 = np.datetime64(T, "ns")
            # Find the last index <= T
            pos = np.searchsorted(ts_index, T64, side="right")
            if pos - candle_length < 0:
                continue
    
            window = data_values[pos - candle_length:pos]
    
            # Group window into number_of_candles equal chunks
            try:
                reshaped = window.reshape(number_of_candles, -1, 6)
            except ValueError:
                continue  # Skip if window can't be reshaped
    
            open_ = reshaped[:, 0, 0]
            high_ = reshaped[:, :, 1].max(axis=1)
            low_ = reshaped[:, :, 2].min(axis=1)
            close_ = reshaped[:, -1, 3]
            volume_ = reshaped[:, :, 4].sum(axis=1)
            trades_ = reshaped[:, :, 5].sum(axis=1)
    
            last_close = close_[-1]
            last_volume = volume_[-1]
            if last_close == 0 or np.isnan(last_close) or last_volume == 0 or np.isnan(last_volume):
                continue
    
            features = np.stack([open_, high_, low_, close_, volume_, trades_], axis=1)
            features[:, :4] /= last_close  # Normalize OHLC
            features[:, 4] /= last_volume  # Normalize volume
    
            features_list.append(features.flatten())
            index_list.append(T)
    
        if not features_list:
            return pd.DataFrame(columns=[
                f"feature_{f}_{i}" for i in range(number_of_candles) for f in ["open", "high", "low", "close", "volume", "trades_done"]
            ])
    
        # Use float32 to reduce memory footprint significantly
        features_array = np.vstack(features_list).astype(np.float32, copy=False)
        columns = [f"feature_{f}_{i}" for i in range(number_of_candles) for f in ["open", "high", "low", "close", "volume", "trades_done"]]
        out = pd.DataFrame(features_array, index=index_list, columns=columns)
        # Ensure the features index is tz-aware UTC to match upstream df for joins
        try:
            out.index = pd.DatetimeIndex(out.index).tz_localize("UTC")
        except Exception:
            # If already tz-aware, ensure it's UTC
            try:
                out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
            except Exception:
                pass
        return out

    def get_external_features(self, from_month: str) -> pd.DataFrame:
        """
        Fetch on-chain metrics (e.g., gas fees, transaction counts) and macro indicators (e.g., ETH/BTC correlation, S&P 500 trends).
        Returns a DataFrame with 'date' index and feature columns.
        """
        # Placeholder implementation: fetch from Allora buckets or Tiingo
        # Example:
        # on_chain_df = self.fetch_bucket_csv("https://api.allora.network/v2/allora/market-data/on-chain/buckets/...")  # gas_fees, tx_counts
        # macro_df = self.fetch_ohlcv_data_tiingo("SPY", from_month)  # S&P 500 OHLC
        # eth_btc_df = self.fetch_ohlcv_data("ethbtc", from_month)  # ETH/BTC for correlation
        # Compute features: e.g., rolling correlation, trends
        # For now, return empty DataFrame to avoid errors
        return pd.DataFrame()

    def get_live_features(self, ticker):
        from_date = self.compute_from_date()
        df = self.fetch_ohlcv_data(ticker, from_date)
        five_min_bars = self.create_5_min_bars(df, live_mode=True)
        if len(five_min_bars) < self.hours_needed * 12:
            raise ValueError("Not enough historical data.")
        live_time = five_min_bars.index[-1]
        features = self.extract_rolling_daily_features(five_min_bars, self.hours_needed, self.number_of_input_candles, [live_time])
        if features.empty:
            raise ValueError("No features returned.")
        return features

    def evaluate_test_data(self, predictions: pd.Series) -> dict:
        if self.test_targets is None:
            raise ValueError("Test targets not set. Run get_train_validation_test_data first.")

        if not predictions.index.equals(self.test_targets.index):
            raise ValueError("Prediction index must match test target index.")

        y_true = self.test_targets
        y_pred = predictions

        corr = np.corrcoef(y_true, y_pred)[0, 1]
        directional_accuracy = np.mean(np.sign(y_true) == np.sign(y_pred))

        return {
            "correlation": corr,
            "directional_accuracy": directional_accuracy
        }

    def get_full_feature_target_dataframe(self, from_month="2025-10") -> pd.DataFrame:
        """
        Returns a DataFrame containing all features and target values for all tickers,
        with a MultiIndex of (date, ticker). Does not split into training/validation.
        """
        all_data = {}
        for t in self.tickers:
            print(f"Downloading Historical Data for {t}")
            frames = []
            frames = []
            # Optional local override to ensure full coverage through t+7d after competition end
            try:
                root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                local_csv = os.path.join(root, "data", "external", f"{t}_ohlcv.csv")
                if os.path.exists(local_csv):
                    df_local = pd.read_csv(local_csv)
                    # Expect columns: date, open, high, low, close, volume (trades_done optional)
                    df_local["date"] = pd.to_datetime(df_local["date"], utc=True)
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col not in df_local.columns:
                            df_local[col] = np.nan
                        else:
                            df_local[col] = pd.to_numeric(df_local[col], errors="coerce")
                    if "trades_done" not in df_local.columns:
                        df_local["trades_done"] = 0
                    frames.append(df_local[["date","open","high","low","close","volume","trades_done"]])
            except Exception:
                pass
            try:
                for bucket in self.list_ready_buckets(t, from_month):
                    df = self.fetch_bucket_csv(bucket["download_url"])
                    frames.append(df)
            except RuntimeError:
                # Likely unauthorized; fall back below
                frames = []

            combined_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if not combined_df.empty:
                combined_df["date"] = pd.to_datetime(combined_df["date"], utc=True)
                combined_df = combined_df.drop_duplicates(subset="date")
                latest_ts = combined_df["date"].max()
                if latest_ts is not None:
                    # Attempt to top up with the most recent 48h of candles to minimize gaps
                    fetch_start = (latest_ts - pd.Timedelta(hours=max(48, self.target_length))).strftime("%Y-%m-%d")
                    try:
                        live_df = self.fetch_ohlcv_data(t, fetch_start)
                    except (ValueError, RuntimeError):
                        try:
                            live_df = self.fetch_ohlcv_data_tiingo(t, fetch_start)
                        except Exception:
                            live_df = pd.DataFrame()
                    if not live_df.empty:
                        live_df["date"] = pd.to_datetime(live_df["date"], utc=True)
                        combined_df = pd.concat([combined_df, live_df], ignore_index=True)
                        combined_df = combined_df.drop_duplicates(subset="date").sort_values("date")
            else:
                # Try Allora OHLC; on 401, fall back to Tiingo
                try:
                    combined_df = self.fetch_ohlcv_data(t, f"{from_month}-01")
                except RuntimeError:
                    combined_df = self.fetch_ohlcv_data_tiingo(t, f"{from_month}-01")
                combined_df["date"] = pd.to_datetime(combined_df["date"], utc=True)
            if combined_df.empty:
                print(f"Warning: no OHLCV rows retrieved for {t}; generating offline fallback data.")
                combined_df = self._offline_ohlcv_from_local(t, f"{from_month}-01")
            if combined_df.empty:
                print(f"Warning: offline fallback produced no rows for {t}; skipping ticker.")
                continue
            if not combined_df.empty:
                ticker_latest = combined_df["date"].max()
                if ticker_latest is not None:
                    if self.latest_data_timestamp is None or ticker_latest > self.latest_data_timestamp:
                        self.latest_data_timestamp = ticker_latest
            all_data[t] = combined_df
    
        def _downcast_numeric(df: pd.DataFrame) -> pd.DataFrame:
            try:
                float_cols = df.select_dtypes(include=["float64"]).columns
                if len(float_cols):
                    df[float_cols] = df[float_cols].astype(np.float32)
                int_cols = df.select_dtypes(include=["int64"]).columns
                if len(int_cols):
                    df[int_cols] = df[int_cols].apply(pd.to_numeric, downcast="integer")
            except Exception:
                pass
            return df

        datasets = []
        for t in self.tickers:
            print(f"Processing 5-minute bars for {t}")
            df = self.create_5_min_bars(all_data[t])
            df = self.compute_target(df, self.target_length)
            features = self.extract_rolling_daily_features(
                df, self.hours_needed, self.number_of_input_candles, df.index.tolist()
            )
            # Downcast features to float32 to save memory
            try:
                features = features.astype(np.float32)
            except Exception:
                pass
            # Normalize both indices to tz-naive UTC for a safe join
            try:
                if getattr(df.index, "tz", None) is not None:
                    df.index = df.index.tz_localize(None)
            except Exception:
                pass
            try:
                if getattr(features.index, "tz", None) is not None:
                    features.index = features.index.tz_localize(None)
            except Exception:
                pass
            df = df.join(features)
            # Downcast numeric columns to reduce consolidation memory during concat/sort
            df = _downcast_numeric(df)
            df["ticker"] = t
            if not df.empty:
                datasets.append(df)
            else:
                print(f"Warning: engineered feature frame is empty for {t}; skipping ticker.")

        if not datasets:
            raise RuntimeError("No datasets could be constructed for the requested tickers. Ensure local fixtures exist or provide network access.")

        # Concatenate without forcing copies; then sort in-place to avoid an extra full copy
        full_data = pd.concat(datasets, copy=False)
        try:
            full_data.sort_index(inplace=True)
        except Exception:
            # Fallback to non-inplace if needed
            full_data = full_data.sort_index()
        # Merge external features
        external_df = self.get_external_features(from_month)
        if not external_df.empty:
            external_df['date'] = pd.to_datetime(external_df['date'], utc=True)
            external_df = external_df.set_index('date')
            full_data = pd.merge_asof(full_data.reset_index().set_index('date'), external_df, left_index=True, right_index=True, direction='nearest').reset_index().set_index(['date', 'ticker'])
        full_data.index = pd.MultiIndex.from_frame(full_data.reset_index()[["date", "ticker"]])
        # Drop rows without a valid target (i.e., where future_close isn't available)
        full_data = full_data.dropna(subset=["target"])  # keep rows with valid labels
        # Enforce non-overlapping windows: sample every configured spacing hours
        spacing_hours = max(1, int(self.sample_spacing_hours))
        step = max(1, spacing_hours * 12)  # 12 samples per hour for 5-minute bars
        grouped = full_data.groupby(level='ticker')
        sampled = []
        for name, group in grouped:
            sampled_group = group.iloc[::step]
            if not sampled_group.empty:
                sampled.append(sampled_group)
        if not sampled:
            print("Warning: non-overlapping sampling yielded no rows; returning empty feature set.")
            return full_data.iloc[0:0]
        full_data = pd.concat(sampled)
    
        return full_data

    def get_train_validation_test_data(self, from_month="2023-01", validation_months=1, test_months=0.25, force_redownload=False):
        def generate_filename():
            """Generate a unique filename based on parameters."""
            tickers_str = "_".join(self.tickers)
            return (
                f"data_{tickers_str}_{from_month}_val{validation_months}_test{test_months}"
                f"_candles{self.number_of_input_candles}.pkl"
            )

        def save_to_disk(data, filename):
            """Save data to disk."""
            with open(filename, "wb") as f:
                dill.dump(data, f)

        def load_from_disk(filename):
            """Load data from disk."""
            with open(filename, "rb") as f:
                X_train, y_train, X_val, y_val, X_test, y_test = dill.load(f)
            self.test_targets = y_test
            return X_train, y_train, X_val, y_val, X_test, y_test

        # Generate the filename
        filename = generate_filename()

        # Check if the file exists and load it if not forcing a redownload
        if os.path.exists(filename) and not force_redownload:
            print(f"Loading data from {filename}")
            return load_from_disk(filename)

        # If file doesn't exist or force_redownload is True, proceed with data preparation
        all_data = {}
        for t in self.tickers:
            print(f"Downloading Historical Data for {t}")
            frames = []
            try:
                for bucket in self.list_ready_buckets(t, from_month):
                    df = self.fetch_bucket_csv(bucket["download_url"])
                    frames.append(df)
            except RuntimeError:
                # Likely 401: fall back to Tiingo below
                frames = []

            combined_df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if not combined_df.empty:
                latest_ts = sorted(pd.to_datetime(combined_df["date"]).dt.date.unique())[-2]
                try:
                    live_df = self.fetch_ohlcv_data(t, latest_ts.strftime("%Y-%m-%d"))
                    combined_df = pd.concat([combined_df, live_df], ignore_index=True)
                except (ValueError, RuntimeError):
                    # No data or unauthorized; continue with combined only
                    pass
                combined_df['date'] = pd.to_datetime(combined_df['date'], utc=True)
                combined_df = combined_df.drop_duplicates(subset='date')
            else:
                # Try Tiingo direct
                try:
                    combined_df = self.fetch_ohlcv_data_tiingo(t, f"{from_month}-01")
                except RuntimeError:
                    combined_df = self._offline_ohlcv_from_local(t, f"{from_month}-01")
                combined_df["date"] = pd.to_datetime(combined_df["date"], utc=True)
            all_data[t] = combined_df

        datasets = []
        for t in self.tickers:
            print("Processing 5-minute bars for", t)
            df = self.create_5_min_bars(all_data[t])
            print("Computing target")
            df = self.compute_target(df, self.target_length)
            print("Extracting features")
            features = self.extract_rolling_daily_features(df, self.hours_needed, self.number_of_input_candles, df.index.tolist())
            # Normalize both indices to tz-naive UTC for a safe join
            try:
                if getattr(df.index, "tz", None) is not None:
                    df.index = df.index.tz_localize(None)
            except Exception:
                pass
            try:
                if getattr(features.index, "tz", None) is not None:
                    features.index = features.index.tz_localize(None)
            except Exception:
                pass
            df = df.join(features)
            df["ticker"] = t
            datasets.append(df)

        full_data = pd.concat(datasets).sort_index()
        full_data.index = pd.MultiIndex.from_frame(full_data.reset_index()[["date", "ticker"]])
        full_data = full_data.dropna()

        # Define cutoff dates for test, validation, and training sets (use tz-naive for reliable comparison)
        now_utc = pd.Timestamp.utcnow()
        test_cutoff = now_utc - pd.DateOffset(months=test_months)
        val_cutoff_start = test_cutoff - timedelta(hours=self.target_length) - pd.DateOffset(months=validation_months)
        val_cutoff_end = test_cutoff - timedelta(hours=self.target_length)
        train_cutoff = val_cutoff_start - timedelta(hours=self.target_length)

        # Normalize date index and cutoffs to tz-naive
        date_index = pd.to_datetime(full_data.index.get_level_values("date"))
        if getattr(date_index, "tz", None) is not None:
            date_index = date_index.tz_localize(None)
        test_cutoff_naive = pd.Timestamp(test_cutoff).tz_localize(None)
        val_start_naive = pd.Timestamp(val_cutoff_start).tz_localize(None)
        val_end_naive = pd.Timestamp(val_cutoff_end).tz_localize(None)
        train_cutoff_naive = pd.Timestamp(train_cutoff).tz_localize(None)

        # Create masks for each set using proper Timestamp comparisons
        test_mask = date_index >= test_cutoff_naive
        val_mask = (date_index >= val_start_naive) & (date_index < val_end_naive)
        train_mask = date_index < train_cutoff_naive

        # Store validation targets for evaluation
        self.validation_targets = full_data.loc[val_mask, ["target"]]

        # Split data into train, validation, and test sets
        X_train = full_data.loc[train_mask].drop(columns=["target", "future_close"])
        y_train = full_data.loc[train_mask]["target"]
        X_val = full_data.loc[val_mask].drop(columns=["target", "future_close"])
        y_val = full_data.loc[val_mask]["target"]
        X_test = full_data.loc[test_mask].drop(columns=["target", "future_close"])
        y_test = full_data.loc[test_mask]["target"]

        self.test_targets = y_test

        # Save the prepared data to disk
        print(f"Saving data to {filename}")
        save_to_disk((X_train, y_train, X_val, y_val, X_test, y_test), filename)

        return X_train, y_train, X_val, y_val, X_test, y_test

