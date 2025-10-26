from typing import Optional, Dict, List

import numpy as np
import pandas as pd


def _safe_ewm(series: pd.Series, span: int) -> pd.Series:
    try:
        return series.ewm(span=span, adjust=False, min_periods=span).mean()
    except (ValueError, AttributeError, TypeError):
        return pd.Series(index=series.index, dtype=float)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)
    roll_up = up.ewm(com=period - 1, adjust=False, min_periods=period).mean()
    roll_down = down.ewm(com=period - 1, adjust=False, min_periods=period).mean()
    roll_down = roll_down.where(roll_down != 0.0, np.nan)
    rs = roll_up / roll_down
    out = 100.0 - (100.0 / (1.0 + rs))
    out = pd.Series(out, index=close.index)
    out = out.bfill()
    out = pd.Series(np.where(pd.isna(out), 50.0, out), index=out.index)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = _safe_ewm(close, fast)
    ema_slow = _safe_ewm(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _safe_ewm(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "macd_signal": signal_line,
        "macd_hist": hist,
    })


def bollinger_bands(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    ma = close.rolling(window=window, min_periods=window).mean()
    sd = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = ma + n_std * sd
    lower = ma - n_std * sd
    width = (upper - lower) / ma.where(ma != 0.0, np.nan)
    return pd.DataFrame({
        "bb_ma": ma,
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_width": width,
    })


def rolling_stats(series: pd.Series, windows: List[int]) -> pd.DataFrame:
    cols: Dict[str, pd.Series] = {}
    for w in windows:
        r = series.rolling(window=w, min_periods=max(2, w // 4))
        cols[f"roll_mean_{w}"] = r.mean()
        cols[f"roll_std_{w}"] = r.std(ddof=0)
        # Protect against scipy dependency for skew/kurt: use pandas
        try:
            cols[f"roll_skew_{w}"] = r.skew()
            cols[f"roll_kurt_{w}"] = r.kurt()
        except (ValueError, TypeError):
            cols[f"roll_skew_{w}"] = pd.Series(index=series.index, dtype=float)
            cols[f"roll_kurt_{w}"] = pd.Series(index=series.index, dtype=float)
    return pd.DataFrame(cols)


def realized_vol(logret: pd.Series, window: int = 24) -> pd.Series:
    return (logret.rolling(window=window, min_periods=max(2, window // 4)).std(ddof=0) * np.sqrt(24.0)).rename(f"rv_{window}")


def lagged(series: pd.Series, lags: List[int]) -> pd.DataFrame:
    return pd.concat({f"lag_{l}": series.shift(l) for l in lags}, axis=1)


def rolling_corr(a: pd.Series, b: pd.Series, window: int = 24) -> pd.Series:
    return a.rolling(window, min_periods=max(2, window // 4)).corr(b).rename(f"corr_{window}")


def build_alpha_features(
    close: pd.Series,
    freq: str = "h",
    extra: Optional[Dict[str, pd.Series]] = None,
) -> pd.DataFrame:
    """
    Build a rich set of alpha features on hourly close series.
    - Momentum: RSI, MACD, Bollinger
    - Returns & lags: log-return, lagged returns
    - Volatility: realized vol, rolling stats of returns
    - Cross asset: optional rolling correlations from `extra` (e.g., ETH log-returns)
    """
    # Helper: normalize any Series index to a tz-naive DatetimeIndex and collapse duplicates by last
    def _to_datetime_series(series: pd.Series) -> pd.Series:
        idx = series.index
        # DatetimeIndex path
        if isinstance(idx, pd.DatetimeIndex):
            new_idx = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
            s2 = pd.Series(series.to_numpy(), index=new_idx, name=series.name)
            s2 = s2[~s2.index.duplicated(keep="last")].sort_index()
            return s2
        # MultiIndex path: use 'date' level if present, else try first level that converts
        if isinstance(idx, pd.MultiIndex):
            names = list(idx.names or [])
            lvl = "date" if "date" in names else 0
            try:
                lv = idx.get_level_values(lvl)
            except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                try:
                    lv = idx.get_level_values(0)
                except (KeyError, IndexError, ValueError, AttributeError, TypeError):
                    return pd.Series(dtype=float)
            di = pd.to_datetime(lv, errors="coerce")
            if getattr(di, "tz", None) is not None:
                di = di.tz_localize(None)
            mask = pd.notna(di)
            mask_arr = np.asarray(mask)
            vals = series.to_numpy()
            s2 = pd.Series(vals[mask_arr], index=pd.DatetimeIndex(di[mask]), name=series.name)
            s2 = s2[~s2.index.duplicated(keep="last")].sort_index()
            return s2
        # Generic Index -> try coercion
        try:
            di2 = pd.to_datetime(idx, errors="coerce")
            if getattr(di2, "tz", None) is not None:
                di2 = di2.tz_localize(None)
            s2 = pd.Series(series.to_numpy(), index=di2, name=series.name)
            s2 = s2[~pd.isna(s2.index)]
            s2 = s2[~s2.index.duplicated(keep="last")].sort_index()
            return s2
        except (ValueError, TypeError, AttributeError):
            return pd.Series(dtype=float)

    # Ensure hourly frequency without future leakage
    s0 = _to_datetime_series(close)
    if s0.empty:
        return pd.DataFrame()
    s = s0.resample(freq).last().dropna()
    s = s[~s.index.duplicated(keep="last")]
    logret = pd.Series(np.log(s / s.shift(1)), index=s.index)

    # Core indicators
    rsi14 = rsi(s, period=14)
    macd_df = macd(s)
    bb_df = bollinger_bands(s)
    lag_df = lagged(logret, lags=[1, 2, 3, 6, 12, 24])
    rv24 = realized_vol(logret, window=24)
    rv168 = realized_vol(logret, window=168)
    rst = rolling_stats(logret, windows=[6, 12, 24, 72, 168])

    feats = pd.concat([
        logret.rename("logret_1h"),
        rsi14.rename("rsi14"),
        macd_df,
        bb_df,
        lag_df,
        rv24,
        rv168,
        rst,
    ], axis=1)

    # Cross-asset correlations
    if extra:
        for name, series in extra.items():
            s_extra0 = _to_datetime_series(series)
            if s_extra0.empty:
                continue
            series_h = s_extra0.resample(freq).last().dropna()
            series_ret = pd.Series(np.log(series_h / series_h.shift(1)), index=series_h.index)
            feats[f"{name}_corr24"] = rolling_corr(logret, series_ret, window=24)
            feats[f"{name}_corr168"] = rolling_corr(logret, series_ret, window=168)

    # Basic cleaning on numeric columns
    num_cols = feats.select_dtypes(include=[np.number]).columns
    if len(num_cols) > 0:
        arr = feats.loc[:, num_cols].to_numpy(dtype=float, copy=True)
        arr[~np.isfinite(arr)] = np.nan
        feats.loc[:, num_cols] = arr
        feats.loc[:, num_cols] = feats.loc[:, num_cols].ffill(limit=3)
    return feats


def merge_external_features(base_index: pd.DatetimeIndex, external_frames: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Merge pre-loaded external features (e.g., macro/on-chain) aligned to hourly base index.
    Each external df should have a DatetimeIndex and numeric columns.
    """
    aligned: List[pd.DataFrame] = []
    for key, df in external_frames.items():
        if not isinstance(df.index, pd.DatetimeIndex):
            continue
        idx = df.index.tz_localize(None) if getattr(df.index, "tz", None) is not None else df.index
        df = df.copy()
        df.index = idx
        df2 = df.resample("h").last().sort_index()
        df2.columns = [f"ext_{key}_{c}" for c in df2.columns]
        aligned.append(df2)
    if not aligned:
        return pd.DataFrame(index=base_index)
    out = pd.concat(aligned, axis=1)
    return out.reindex(base_index)
