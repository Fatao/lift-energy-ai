"""scikit-learn models, always compared against simple rules (see forecast backtest).

Anomalies : IsolationForest learns what a normal (energy, trips, hour, weekend) combination
            looks like for ONE lift. A flagged hour is kept only if it is also clearly ABOVE
            what its trips explain - so "unusually low" or noise hours never alarm.
Forecast  : HuberRegressor (robust to outlier days) on weekday + trend, back-tested on the
            most recent days against two baselines: weekday median and "same day last week".
            The model with the lowest error is the one used (honest model selection).
"""
import math
from datetime import datetime, timedelta
from statistics import median

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import HuberRegressor

from . import analytics
from .i18n import tr

MIN_HOURS = 96


def _features(rows):
    X = []
    for r in rows:
        h = int(r["ts"][11:13])
        wd = datetime.strptime(r["ts"][:10], "%Y-%m-%d").weekday()
        X.append([r["kwh"], r["trips"], math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24),
                  1.0 if wd >= 5 else 0.0])
    return np.array(X)


def flag_anomalies(rows_all, rows_window, contamination=0.05, min_excess=0.3):
    """Returns [(row, residual, expected)] or None when there is not enough history."""
    fit = analytics._fit(rows_all)
    if fit is None or len(rows_all) < MIN_HOURS or not rows_window:
        return None
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=0)
    model.fit(_features(rows_all))
    pred = model.predict(_features(rows_window))
    a, b, _ = fit
    out = []
    for r, p in zip(rows_window, pred):
        expected = a + b * r["trips"]
        res = r["kwh"] - expected
        if p == -1 and res > min_excess:
            out.append((r, res, expected))
    return out


# ---------------------------------------------------------------- forecast
def _design(dates, origin):
    X = np.zeros((len(dates), 8))
    for i, d in enumerate(dates):
        X[i, d.weekday()] = 1.0
        X[i, 7] = (d - origin).days / 30.0
    return X


def _predict_huber(train, day):
    dates = [d for d, _ in train]
    y = np.array([v for _, v in train])
    m = HuberRegressor(alpha=1e-3, max_iter=2000).fit(_design(dates, dates[0]), y)
    return float(m.predict(_design([day], dates[0]))[0])


def _predict_weekday_median(train, day):
    same = [v for d, v in train[-28:] if d.weekday() == day.weekday()]
    return median(same) if len(same) >= 2 else median(v for _, v in train[-28:])


def _predict_naive7(train, day):
    lookup = dict(train)
    return lookup.get(day - timedelta(days=7), _predict_weekday_median(train, day))


MODELS = {
    "huber": _predict_huber,
    "weekday_median": _predict_weekday_median,
    "naive7": _predict_naive7,
}


def forecast(lift_id, horizon=7, lang="ru"):
    d = analytics.daily(lift_id, 60)
    full = [(datetime.strptime(k, "%Y-%m-%d"), v["kwh"]) for k, v in sorted(d.items()) if v["n"] >= 22]
    if len(full) < 21:
        return None
    n_test = min(10, len(full) - 14)
    errors = {k: [] for k in MODELS}
    for i in range(len(full) - n_test, len(full)):
        train, (day, actual) = full[:i], full[i]
        for k, fn in MODELS.items():
            errors[k].append(abs(fn(train, day) - actual))
    mae = {k: float(np.mean(v)) for k, v in errors.items()}
    best = min(mae, key=mae.get)
    # 80% interval from the back-tested absolute errors of the chosen model
    band = float(np.quantile(errors[best], 0.8))
    last_day = full[-1][0]
    fn = MODELS[best]
    fc = []
    for i in range(1, horizon + 1):
        day = last_day + timedelta(days=i)
        v = max(fn(full, day), 0.0)
        fc.append({"date": day.strftime("%Y-%m-%d"), "kwh": round(v, 2),
                   "low": round(max(v - band, 0), 2), "high": round(v + band, 2)})
    hist = full[-28:]
    last7 = sum(v for _, v in full[-7:])
    nxt7 = sum(f["kwh"] for f in fc)
    return {
        "lift_id": lift_id,
        "history": [{"date": d.strftime("%Y-%m-%d"), "kwh": round(v, 2)} for d, v in hist],
        "forecast": fc,
        "trend_factor": round(nxt7 / last7, 3) if last7 else 1.0,
        "band_sd": round(band, 2),
        "last7_actual": round(last7, 1),
        "next7_forecast": round(nxt7, 1),
        "model": best,
        "model_name": tr(lang, "model." + best),
        "backtest": {
            "days": n_test,
            "mae_kwh": {k: round(v, 3) for k, v in mae.items()},
            "names": {k: tr(lang, "model." + k) for k in MODELS},
        },
        "method": tr(lang, "fc.method.ml", n=n_test, model=tr(lang, "model." + best)),
    }