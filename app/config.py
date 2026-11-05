"""Configuration from environment variables (see README). Nothing secret is hard-coded."""
import json
import os


def _load_dotenv(path=None):
    """Tiny .env reader (no extra dependency). Real environment variables win over the file."""
    if path is None and os.environ.get("LIFT_NO_DOTENV"):
        return  # tests set this so a real .env (with real keys) is never used by the test run
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            if v[:1] not in ("'", '"') and " #" in v:
                v = v.split(" #", 1)[0].strip()  # inline comment: KEY=value   # note
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            os.environ.setdefault(k.strip(), v)


_load_dotenv()


def env(key, default=None):
    v = os.environ.get(key)
    return v if v not in (None, "") else default


# --- MQTT ---------------------------------------------------------------
MQTT_URL = env("MQTT_URL")                       # mqtt://host:1883  or  mqtts://host:8883
MQTT_TOPIC = env("MQTT_TOPIC", "lifts/+/telemetry")
MQTT_USER = env("MQTT_USER")
MQTT_PASSWORD = env("MQTT_PASSWORD")

# --- Modbus RTU over RS-485 ---------------------------------------------
MODBUS_PORT = env("MODBUS_PORT")                 # COM3 | /dev/ttyUSB0 | socket://192.168.1.50:4001
MODBUS_BAUD = int(env("MODBUS_BAUD", "9600"))
MODBUS_PARITY = env("MODBUS_PARITY", "N")        # N | E | O
MODBUS_STOPBITS = int(env("MODBUS_STOPBITS", "1"))
MODBUS_UNITS = env("MODBUS_UNITS", "L1=1")       # "L1=1,L2=2" lift_id=slave address
MODBUS_POLL_SECONDS = float(env("MODBUS_POLL_SECONDS", "10"))
MODBUS_WORD_ORDER = env("MODBUS_WORD_ORDER", "big")  # order of 16-bit words in 32-bit values

# Register map. Real devices differ: find yours with tools/modbus_probe.py, then put it in
# regmap.json and set MODBUS_REGMAP=regmap.json. Every field is optional.
#   function : 3 = holding registers, 4 = input registers (energy meters often use 4)
#   type     : uint16 | int16 | uint32 | int32 | float32
#   scale    : multiplier applied to the raw number (0.01 means the device counts in 1/100 kWh)
DEFAULT_REGMAP = {
    "function": 3,
    "start": 0,
    "count": 6,
    "fields": {
        "kwh":   {"offset": 0, "type": "uint32", "scale": 0.01},   # total energy, 0.01 kWh units
        "trips": {"offset": 2, "type": "uint32", "scale": 1},      # total trips
        "doors": {"offset": 4, "type": "uint32", "scale": 1},      # total door cycles
    },
}


def modbus_regmap():
    raw = env("MODBUS_REGMAP")
    if not raw:
        return DEFAULT_REGMAP
    if os.path.isfile(raw):
        with open(raw, encoding="utf-8") as f:
            return json.load(f)
    return json.loads(raw)


def modbus_units():
    out = {}
    for part in MODBUS_UNITS.split(","):
        if "=" in part:
            lid, unit = part.split("=", 1)
            out[lid.strip()] = int(unit)
    return out


# --- misc -----------------------------------------------------------------
LIVE_MODE = bool(MQTT_URL or MODBUS_PORT)                      # live source -> no demo data