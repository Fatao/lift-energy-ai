"""Fake RS-485 Modbus RTU slaves (one TCP port, several unit addresses) for testing without hardware.

    python tools/modbus_slave_sim.py --port 5020 --speed 120

Then run the app with   MODBUS_PORT=socket://127.0.0.1:5020  MODBUS_UNITS="L1=1,L2=2,L3=3,L4=4"
--speed N: simulated time runs N times faster than wall clock, so counters visibly move.
Counter layout = DEFAULT_REGMAP in app/config.py (uint32 big-endian words).
"""
import argparse
import math
import os
import random
import socketserver
import struct
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.ingest.modbus_rtu import build_read_request, crc16, with_crc  # noqa: E402
from app.simulator import LIFTS, WEEKDAY  # noqa: E402


def _poisson(rng, mu):
    limit, k, p = math.exp(-mu), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


class World:
    """Cumulative counters per unit, advanced by a background thread."""

    def __init__(self, speed):
        self.speed = speed
        self.rng = random.Random(1)
        self.lock = threading.Lock()
        # unit -> [kwh_total, trips_total, doors_total, standby_kw, kwh_per_trip, mult]
        self.units = {i + 1: [1000.0 * (i + 1), 50000 + 1000 * i, 100000 + 2000 * i, sb, pt, m]
                      for i, (_, _, sb, pt, m) in enumerate(LIFTS)}
        self.sim_hour = time.localtime().tm_hour

    def tick(self, dt):
        sim_dt_h = dt * self.speed / 3600.0
        with self.lock:
            for c in self.units.values():
                trips = _poisson(self.rng, WEEKDAY[int(self.sim_hour) % 24] * c[5] * sim_dt_h)
                c[1] += trips
                c[2] += trips * 2
                c[0] += c[3] * sim_dt_h + c[4] * trips
            self.sim_hour = (self.sim_hour + sim_dt_h) % 24

    def registers(self, unit, start, count):
        with self.lock:
            c = self.units[unit]
            words = []
            for v in (int(c[0] * 100), int(c[1]), int(c[2])):
                words += [(v >> 16) & 0xFFFF, v & 0xFFFF]
        return words[start:start + count]


def make_handler(world):
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            sock = self.request
            while True:
                req = b""
                while len(req) < 8:
                    chunk = sock.recv(8 - len(req))
                    if not chunk:
                        return
                    req += chunk
                if struct.unpack("<H", req[-2:])[0] != crc16(req[:-2]):
                    continue  # bad CRC -> silence, like a real slave
                unit, func, start, count = struct.unpack(">BBHH", req[:6])
                if unit not in world.units:
                    continue  # not on this bus -> no answer
                if func != 0x03:
                    sock.sendall(with_crc(struct.pack(">BBB", unit, func | 0x80, 1)))
                    continue
                regs = world.registers(unit, start, count)
                if len(regs) != count:
                    sock.sendall(with_crc(struct.pack(">BBB", unit, func | 0x80, 2)))
                    continue
                sock.sendall(with_crc(struct.pack(">BBB", unit, 3, count * 2) + struct.pack(f">{count}H", *regs)))

    return Handler


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5020)
    ap.add_argument("--speed", type=float, default=120.0)
    a = ap.parse_args()
    w = World(a.speed)

    def loop():
        while True:
            time.sleep(1)
            w.tick(1.0)

    threading.Thread(target=loop, daemon=True).start()
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("127.0.0.1", a.port), make_handler(w)) as srv:
        print(f"Modbus RTU simulator on socket://127.0.0.1:{a.port}, units 1..{len(w.units)}, speed x{a.speed}")
        srv.serve_forever()
