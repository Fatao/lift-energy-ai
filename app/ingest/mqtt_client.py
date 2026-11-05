"""MQTT subscriber.

Topic:   lifts/<lift_id>/telemetry          (configurable, '+' = lift id)
Payload (JSON), either deltas since the previous message:
   {"kwh": 0.12, "trips": 3, "door_cycles": 6, "ts": "2026-10-23T14:05:00"}
or cumulative counters:
   {"kwh_total": 1234.56, "trips_total": 80211, "door_cycles_total": 160500}
Every field is optional (an energy meter may send only kwh, a controller only trips).
"ts" is optional (default: arrival time). "lift_id" in the payload overrides the topic.
"""
import json
from urllib.parse import urlparse

from . import status
from .aggregator import aggregator, parse_ts

SOURCE = "mqtt"


def handle_message(topic, payload):
    """Pure-ish handler (easy to unit-test). Returns 'delta' | 'counters' | 'baseline'."""
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("payload must be a JSON object")
    parts = topic.split("/")
    lift_id = data.get("lift_id") or (parts[1] if len(parts) >= 3 else None)
    ts = parse_ts(data.get("ts"))
    totals = {k: data.get(k) for k in ("kwh_total", "trips_total", "door_cycles_total")}
    deltas = {k: data.get(k) for k in ("kwh", "trips", "door_cycles")}
    if any(v is not None for v in totals.values()):
        stored = aggregator.add_counters(lift_id, ts, totals["kwh_total"], totals["trips_total"],
                                         totals["door_cycles_total"])
        return "counters" if stored else "baseline"
    if any(v is not None for v in deltas.values()):
        aggregator.add_delta(lift_id, ts, float(deltas["kwh"] or 0), int(deltas["trips"] or 0),
                             int(deltas["door_cycles"] or 0))
        return "delta"
    raise ValueError("payload needs at least one of: kwh, trips, door_cycles, kwh_total, trips_total, door_cycles_total")


def start(url, topic, user=None, password=None):
    import paho.mqtt.client as mqtt

    u = urlparse(url)
    host, port = u.hostname, u.port or (8883 if u.scheme == "mqtts" else 1883)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="lift-energy-ai")
    if user:
        client.username_pw_set(user, password)
    if u.scheme == "mqtts":
        client.tls_set()

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code == 0:
            c.subscribe(topic)
            status.update(SOURCE, state="connected", detail=f"{host}:{port} · {topic}")
        else:
            status.update(SOURCE, state="error", detail=f"connect refused: {reason_code}")

    def on_disconnect(c, userdata, flags, reason_code, properties):
        status.update(SOURCE, state="reconnecting", detail=f"{host}:{port}")

    def on_message(c, userdata, msg):
        try:
            handle_message(msg.topic, msg.payload)
            status.message(SOURCE)
        except Exception as e:  # bad payloads must never kill the client thread
            status.error(SOURCE, f"{msg.topic}: {e}")

    client.on_connect, client.on_disconnect, client.on_message = on_connect, on_disconnect, on_message
    status.update(SOURCE, state="connecting", detail=f"{host}:{port}")
    client.connect_async(host, port, keepalive=30)
    client.reconnect_delay_set(1, 30)
    client.loop_start()
    return client