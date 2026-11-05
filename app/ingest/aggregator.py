"""Turns raw samples into hourly readings.

Two kinds of input:
  deltas   - energy / trips / door cycles that happened since the previous message
  counters - cumulative totals (typical for Modbus meters). We keep the previous value
             per lift AND per field and store the difference; the first sample of a field
             only sets the baseline, a counter that goes backwards (reset / rollover) is
             skipped, not stored.

Every field is optional. Energy can come from one source (a meter on Modbus) and trips from
another (the controller over MQTT): rows of the same lift and hour are added together.
"""
import threading
from datetime import datetime

from .. import config, db

FMT = "%Y-%m-%dT%H:00:00"


class Aggregator:
    def __init__(self):
        self._prev = {}
        self._lock = threading.Lock()

    def add_delta(self, lift_id, ts, kwh=0.0, trips=0, doors=0):
        if not lift_id:
            raise ValueError("empty lift_id")
        if kwh < 0 or trips < 0 or doors < 0:
            raise ValueError("negative delta")
        limit = float(config.env("MAX_KWH_PER_SAMPLE", "50"))
        if kwh > limit:
            raise ValueError(f"kwh delta {kwh} above sanity limit {limit}")
        db.add_to_hour(lift_id, ts.strftime(FMT), float(kwh), int(trips), int(doors))

    def add_counters(self, lift_id, ts, kwh=None, trips=None, doors=None):
        """Returns True if a delta was stored, False if it only set a baseline / was skipped."""
        deltas = {}
        with self._lock:
            for name, value in (("kwh", kwh), ("trips", trips), ("doors", doors)):
                if value is None:
                    continue
                prev = self._prev.get((lift_id, name))
                self._prev[(lift_id, name)] = float(value)
                if prev is None:
                    continue
                d = float(value) - prev
                if d >= 0:  # a negative step is a counter reset: skip it
                    deltas[name] = d
        if not deltas:
            return False
        self.add_delta(lift_id, ts, deltas.get("kwh", 0.0), deltas.get("trips", 0), deltas.get("doors", 0))
        return True


aggregator = Aggregator()


def parse_ts(value):
    if value in (None, ""):
        return datetime.now()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None)