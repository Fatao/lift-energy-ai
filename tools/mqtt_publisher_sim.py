"""Publishes fake lift telemetry to an MQTT broker.

    python tools/mqtt_publisher_sim.py --url mqtt://localhost:1883 --interval 5 --mode deltas
Topic: lifts/<id>/telemetry. --mode counters sends cumulative totals instead of deltas.
"""
import argparse
import json
import math
import os
import random
import sys
import time
from urllib.parse import urlparse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.simulator import LIFTS, WEEKDAY  # noqa: E402


def poisson(rng, mu):
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="mqtt://localhost:1883")
    ap.add_argument("--interval", type=float, default=5.0, help="seconds between messages")
    ap.add_argument("--speed", type=float, default=60.0, help="simulated time speed-up")
    ap.add_argument("--mode", choices=["deltas", "counters"], default="deltas")
    ap.add_argument("--count", type=int, default=0, help="stop after N rounds (0 = forever)")
    a = ap.parse_args()
    import paho.mqtt.client as mqtt

    u = urlparse(a.url)
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lift-sim")
    cli.connect(u.hostname, u.port or 1883)
    cli.loop_start()
    rng = random.Random(7)
    totals = {lid: [5000.0, 100000, 200000] for lid, *_ in LIFTS}
    n = 0
    while a.count == 0 or n < a.count:
        hours = a.interval * a.speed / 3600
        hour = time.localtime().tm_hour
        for lid, _, standby, per_trip, mult in LIFTS:
            trips = poisson(rng, WEEKDAY[hour] * mult * hours)
            kwh = round(standby * hours + per_trip * trips, 4)
            if a.mode == "deltas":
                payload = {"kwh": kwh, "trips": trips, "door_cycles": trips * 2}
            else:
                t = totals[lid]
                t[0] += kwh; t[1] += trips; t[2] += trips * 2
                payload = {"kwh_total": round(t[0], 3), "trips_total": t[1], "door_cycles_total": t[2]}
            cli.publish(f"lifts/{lid}/telemetry", json.dumps(payload))
        n += 1
        print(f"round {n} published ({a.mode})")
        time.sleep(a.interval)
    cli.loop_stop()
    cli.disconnect()
