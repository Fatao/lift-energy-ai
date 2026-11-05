"""Demo data generator (SYNTHETIC - not real measurements).

Four lifts in two entrances. Each has a deliberately different "story" so that
the analytics have something real to find:
  L1  healthy reference lift
  L2  higher energy per trip (e.g. worn guides / door friction)
  L3  high standby load (lighting + ventilation + displays always on)
  L4  healthy, but two night-time fault events (drive/door stuck, energy spike)
"""
import math
import random
from datetime import datetime, timedelta

from . import db

# average trips per hour on a weekday, hour 0..23
WEEKDAY = [0.3, 0.2, 0.1, 0.1, 0.2, 0.8, 3, 9, 12, 6, 4, 4, 5, 5, 4, 4, 5, 9, 12, 9, 6, 4, 2, 1]
WEEKEND = [0.4, 0.3, 0.1, 0.1, 0.1, 0.3, 1, 2, 4, 6, 7, 7, 7, 6, 6, 6, 6, 6, 6, 5, 4, 3, 2, 1]

LIFTS = [
    # id, name, standby kW, kWh per trip, traffic multiplier
    ("L1", "Подъезд 1 · Лифт 1", 0.18, 0.085, 1.00),
    ("L2", "Подъезд 1 · Лифт 2", 0.19, 0.108, 0.95),
    ("L3", "Подъезд 2 · Лифт 1", 0.34, 0.086, 1.05),
    ("L4", "Подъезд 2 · Лифт 2", 0.18, 0.084, 0.90),
]


def _poisson(rng, mu):
    if mu <= 0:
        return 0
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def generate(days=35, seed=48, end=None):
    rng = random.Random(seed)
    end = end or datetime.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=days) + timedelta(hours=1)
    # fault events on L4: (day offset from start, start hour, length h, extra kW)
    faults = {"L4": [(days - 20, 2, 4, 0.9), (days - 6, 1, 3, 1.2)]}
    rows = []
    for lift_id, name, standby, per_trip, mult in LIFTS:
        db.upsert_lift(lift_id, name)
        t = start
        while t <= end:
            prof = WEEKEND if t.weekday() >= 5 else WEEKDAY
            trips = _poisson(rng, prof[t.hour] * mult)
            kwh = standby * (1 + rng.gauss(0, 0.04)) + per_trip * trips * (1 + rng.gauss(0, 0.05))
            for d_off, h0, ln, extra in faults.get(lift_id, []):
                day0 = (start + timedelta(days=d_off)).date()
                if t.date() == day0 and h0 <= t.hour < h0 + ln:
                    kwh += extra * (1 + rng.gauss(0, 0.05))
            doors = trips * 2 + (1 if trips and rng.random() < 0.15 else 0)
            rows.append((lift_id, t.strftime("%Y-%m-%dT%H:00:00"), round(max(kwh, 0.01), 4), trips, doors))
            t += timedelta(hours=1)
    db.insert_readings(rows)
    return len(rows)


def reset_demo():
    db.clear()
    return generate()