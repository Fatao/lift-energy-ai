import os
import sys
import tempfile

os.environ["LIFT_NO_DOTENV"] = "1"   # never read the real .env (real keys, real ports) during tests
_tmp = tempfile.mkdtemp()
os.environ["LIFT_DB"] = os.path.join(_tmp, "test.db")
for k in ("LLM_PROVIDER", "MQTT_URL", "MODBUS_PORT"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))