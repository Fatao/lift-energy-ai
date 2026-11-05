"""Find out what a real RS-485 device exposes, so you can write its register map.

Stop the Lift Energy app first: only one program can open a COM port at a time.

Read 20 registers starting at address 0 from device (slave) 1, holding registers:
    python tools/modbus_probe.py --port COM3 --unit 1 --start 0 --count 20

Energy meters often keep their data in INPUT registers (function 4):
    python tools/modbus_probe.py --port COM3 --unit 1 --fn 4 --start 0 --count 40

Find which slave addresses answer on the bus (1..32):
    python tools/modbus_probe.py --port COM3 --scan 1-32

Without hardware, against the simulator:
    python tools/modbus_slave_sim.py --port 5020
    python tools/modbus_probe.py --port socket://127.0.0.1:5020 --unit 1 --start 0 --count 6

How to read the table: take a value you can check against the device display (for example the
total energy in kWh), find it in one of the columns, and note the address, the column (type and
word order) and what you must multiply by (scale). That is one field of regmap.json.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from app.ingest.modbus_rtu import ModbusClient, ModbusError  # noqa: E402


def f32(hi, lo):
    try:
        v = struct.unpack(">f", struct.pack(">HH", hi, lo))[0]
    except struct.error:
        return "-"
    if v != v or abs(v) in (float("inf"),) or (v != 0 and not 1e-6 < abs(v) < 1e9):
        return "-"
    return f"{v:.4g}"


def show(regs, start):
    print(f"{'address':>8} {'uint16':>7} {'int16':>7} {'hex':>6} | {'uint32 big':>12} {'uint32 little':>14} {'float32 big':>12} {'float32 little':>15}")
    for i, r in enumerate(regs):
        s16 = r - 65536 if r >= 32768 else r
        if i + 1 < len(regs):
            n = regs[i + 1]
            u_big, u_lit = (r << 16) | n, (n << 16) | r
            fb, fl = f32(r, n), f32(n, r)
        else:
            u_big = u_lit = fb = fl = "-"
        print(f"{start + i:>8} {r:>7} {s16:>7} {r:>#06x} | {u_big!s:>12} {u_lit!s:>14} {fb:>12} {fl:>15}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", required=True, help="COM3, /dev/ttyUSB0 or socket://host:port")
    ap.add_argument("--baud", type=int, default=9600)
    ap.add_argument("--parity", default="N", choices=["N", "E", "O"])
    ap.add_argument("--stopbits", type=int, default=1, choices=[1, 2])
    ap.add_argument("--unit", type=int, default=1, help="slave address")
    ap.add_argument("--fn", type=int, default=3, choices=[3, 4], help="3 = holding, 4 = input registers")
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--scan", help="range of slave addresses to try, for example 1-32")
    a = ap.parse_args()

    if a.scan:
        lo, hi = (int(x) for x in a.scan.split("-"))
        client = ModbusClient(a.port, a.baud, a.parity, a.stopbits, timeout=0.3)
        found = []
        for unit in range(lo, hi + 1):
            try:
                client.read_registers(unit, a.start, 1, a.fn)
                found.append(unit)
                print(f"unit {unit}: answers")
            except ModbusError as e:
                if "exception" in str(e):  # it answered, just refused this address: the device exists
                    found.append(unit)
                    print(f"unit {unit}: answers ({e})")
        print("devices found:", found or "none (check wiring A/B, baud rate, parity)")
        return

    client = ModbusClient(a.port, a.baud, a.parity, a.stopbits, timeout=1.0)
    try:
        regs = client.read_registers(a.unit, a.start, a.count, a.fn)
    except ModbusError as e:
        sys.exit(f"Read failed: {e}\nTry --fn 4, another --unit, or check baud rate and parity.")
    show(regs, a.start)


if __name__ == "__main__":
    main()