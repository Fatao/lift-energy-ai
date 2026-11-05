"""Minimal Modbus RTU master over RS-485.

Reads holding registers (function 0x03) or input registers (function 0x04).
Works with a real serial port (COM3, /dev/ttyUSB0 - USB-RS485 adapter) and with
serial-over-TCP gateways via pyserial URLs (socket://host:port) - the same RTU frames.
No hardware: run tools/modbus_slave_sim.py and use MODBUS_PORT=socket://127.0.0.1:5020.
To discover the register map of a real device use tools/modbus_probe.py.
"""
import math
import struct
import threading
from datetime import datetime

from . import status
from .aggregator import aggregator

SOURCE = "modbus"

# type -> (number of 16-bit registers, struct format of the assembled big-endian bytes)
TYPES = {
    "uint16": (1, ">H"),
    "int16": (1, ">h"),
    "uint32": (2, ">I"),
    "int32": (2, ">i"),
    "float32": (2, ">f"),
}


class ModbusError(Exception):
    pass


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    return frame + struct.pack("<H", crc16(frame))


def build_read_request(unit: int, start: int, count: int, function: int = 3) -> bytes:
    return with_crc(struct.pack(">BBHH", unit, function, start, count))


def check_crc(frame: bytes):
    if len(frame) < 4 or struct.unpack("<H", frame[-2:])[0] != crc16(frame[:-2]):
        raise ModbusError("CRC mismatch")


def parse_read_response(unit: int, frame: bytes, count: int, function: int = 3):
    check_crc(frame)
    if frame[0] != unit:
        raise ModbusError(f"unexpected unit {frame[0]}")
    if frame[1] & 0x80:
        raise ModbusError(f"modbus exception code {frame[2]}")
    if frame[1] != function or frame[2] != count * 2 or len(frame) != 5 + count * 2:
        raise ModbusError("malformed response")
    return list(struct.unpack(f">{count}H", frame[3:3 + count * 2]))


def field_type(field):
    t = field.get("type")
    if t is None:  # older maps used {"words": 1 | 2}
        t = "uint32" if field.get("words", 1) == 2 else "uint16"
    if t not in TYPES:
        raise ModbusError(f"unknown register type '{t}' (use one of {', '.join(TYPES)})")
    return t


def decode_field(regs, field, word_order="big"):
    """Decode one value from a block of registers. word_order only matters for 32-bit types:
    'big' = high word first (AB CD), 'little' = low word first (CD AB)."""
    words, fmt = TYPES[field_type(field)]
    chunk = list(regs[field["offset"]: field["offset"] + words])
    if len(chunk) != words:
        raise ModbusError("the register map points outside the block that was read (check start/count/offset)")
    if word_order == "little":
        chunk.reverse()
    value = struct.unpack(fmt, b"".join(struct.pack(">H", w) for w in chunk))[0]
    if isinstance(value, float) and not math.isfinite(value):
        raise ModbusError("device returned an invalid floating point number")
    return value * field.get("scale", 1)


class ModbusClient:
    def __init__(self, url, baud=9600, parity="N", stopbits=1, timeout=1.0):
        import serial

        self.ser = serial.serial_for_url(
            url, baudrate=baud, parity=parity, stopbits=stopbits, timeout=timeout
        )

    def close(self):
        self.ser.close()

    def read_registers(self, unit, start, count, function=3):
        if not 1 <= count <= 125:
            raise ModbusError("count must be between 1 and 125")
        self.ser.reset_input_buffer()
        self.ser.write(build_read_request(unit, start, count, function))
        head = self.ser.read(3)
        if len(head) < 3:
            raise ModbusError("timeout (no answer from slave)")
        rest = 2 if head[1] & 0x80 else head[2] + 2
        tail = self.ser.read(rest)
        if len(tail) < rest:
            raise ModbusError("timeout (truncated frame)")
        return parse_read_response(unit, head + tail, count, function)

    def read_holding(self, unit, start, count):  # kept for older callers
        return self.read_registers(unit, start, count, 3)


def poll_once(client, units, regmap, word_order="big"):
    """Read every unit once. Returns {lift_id: error or None}."""
    results = {}
    for lift_id, unit in units.items():
        try:
            regs = client.read_registers(unit, regmap["start"], regmap["count"], regmap.get("function", 3))
            f = regmap["fields"]
            vals = {name: decode_field(regs, f[name], word_order) for name in ("kwh", "trips", "doors") if name in f}
            if not vals:
                raise ModbusError("the register map defines no fields (need kwh, trips or doors)")
            aggregator.add_counters(lift_id, datetime.now(), vals.get("kwh"), vals.get("trips"), vals.get("doors"))
            status.message(SOURCE)
            results[lift_id] = None
        except ModbusError as e:
            status.error(SOURCE, f"{lift_id} (unit {unit}): {e}")
            results[lift_id] = str(e)
    return results


def start(url, units, regmap, baud, parity, stopbits, interval, word_order="big"):
    stop = threading.Event()

    def run():
        client = None
        while not stop.is_set():
            try:
                if client is None:
                    client = ModbusClient(url, baud, parity, stopbits)
                    status.update(SOURCE, state="connected", detail=f"{url} · {baud} baud · units {units}")
                poll_once(client, units, regmap, word_order)
            except Exception as e:  # port missing / connection lost -> retry
                status.update(SOURCE, state="error", detail=f"{url}")
                status.error(SOURCE, e)
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass
                client = None
            stop.wait(interval)

    status.update(SOURCE, state="connecting", detail=url)
    t = threading.Thread(target=run, name="modbus-poller", daemon=True)
    t.start()
    return stop