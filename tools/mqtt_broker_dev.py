"""Tiny local MQTT broker for development (so you do not have to install Mosquitto on Windows).

    python tools/mqtt_broker_dev.py --port 1883
Anonymous, plain TCP, 127.0.0.1 only. For production use a real broker (Mosquitto, EMQX) with auth + TLS.
"""
import argparse
import asyncio
import logging

from amqtt.broker import Broker


async def main(port):
    cfg = {
        "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
        "sys_interval": 0,
        "auth": {"allow-anonymous": True, "plugins": ["auth_anonymous"]},
        "topic-check": {"enabled": False},
    }
    broker = Broker(cfg)
    await broker.start()
    print(f"MQTT dev broker on mqtt://127.0.0.1:{port}  (Ctrl+C to stop)")
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=1883)
    asyncio.run(main(ap.parse_args().port))
