"""Read a CSV or Excel (.xlsx) export and turn it into hourly readings.

* Columns are found by name in Russian or English (lift, time, kWh, trips, door cycles); the user can
  override every choice.
* Readings finer than one hour (for example every 15 minutes) are summed per hour.
* "Cumulative" files (a meter that shows a running total) are converted to differences first.
* The .xlsx reader uses only the standard library, so odd styles or fonts inside the workbook can never
  break the import.
"""
import csv
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from statistics import median

from .i18n import tr

MAX_ROWS = 1_000_000
MAX_SHEET_BYTES = 200 * 1024 * 1024
FIELDS = ("lift_id", "name", "ts", "kwh", "trips", "door_cycles")

# exact (normalised) header names
ALIASES = {
    "lift_id": ["lift_id", "lift", "lift id", "id", "лифт", "номер лифта", "№ лифта", "№", "номер", "устройство", "device", "объект"],
    "name": ["name", "название", "наименование", "имя"],
    "ts": ["ts", "timestamp", "datetime", "date time", "date", "time", "время", "дата", "дата и время", "дата/время", "период"],
    "kwh": ["kwh", "energy", "energy_kwh", "квтч", "квт ч", "электроэнергия", "энергия", "расход", "потребление", "показания"],
    "trips": ["trips", "trip", "rides", "поездки", "поездок", "рейсы", "рейсов", "количество поездок", "число поездок"],
    "door_cycles": ["door_cycles", "door cycles", "doors", "door", "двери", "циклы дверей", "цикл дверей", "открытия дверей"],
}
# fallback: header contains one of these fragments
CONTAINS = {
    "kwh": ["kwh", "квт", "энерги"],
    "trips": ["trip", "поезд", "рейс"],
    "door_cycles": ["door", "двер"],
    "ts": ["time", "date", "врем", "дата"],
    "lift_id": ["lift", "лифт"],
}
DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%Y", "%d.%m.%y %H:%M", "%d/%m/%Y %H:%M:%S",
                "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y.%m.%d %H:%M")


class ImportProblem(Exception):
    """A problem the user can fix; the message is already localised."""


# ---------------------------------------------------------------- reading files
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def read_csv(data: bytes):
    text = _decode(data)
    if "\x00" in text[:4096]:
        raise ValueError("this looks like a binary file, not text")
    sample = text[:4096]
    try:
        delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample else ""
        delim = max(",;\t|", key=first.count)
    return [row for row in csv.reader(io.StringIO(text), delimiter=delim)]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _col_index(ref):
    letters = re.match(r"[A-Za-z]+", ref).group(0).upper()
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data: bytes):
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    shared = []
    if "xl/sharedStrings.xml" in names:
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")):
            shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
    sheets = sorted((n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n)),
                    key=lambda n: int(re.findall(r"\d+", n)[0]))
    best = []
    for name in sheets:
        if z.getinfo(name).file_size > MAX_SHEET_BYTES:
            raise ValueError("the sheet is too large")
        rows = []
        for row in ET.fromstring(z.read(name)).iter():
            if _local(row.tag) != "row":
                continue
            cells = {}
            for c in row:
                if _local(c.tag) != "c":
                    continue
                v = next((x for x in c if _local(x.tag) == "v"), None)
                t = c.get("t")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter() if _local(x.tag) == "t")
                elif v is None or v.text is None:
                    continue
                elif t == "s":
                    val = shared[int(v.text)]
                elif t in ("str", "d"):
                    val = v.text
                elif t == "b":
                    val = bool(int(v.text))
                elif t == "e":
                    continue
                else:
                    try:
                        val = float(v.text)
                    except ValueError:
                        val = v.text
                cells[_col_index(c.get("r", "A1"))] = val
            if cells:
                rows.append([cells.get(i) for i in range(max(cells) + 1)])
            if len(rows) > MAX_ROWS:
                break
        if len(rows) > len(best):
            best = rows
    return best


def read_table(filename: str, data: bytes, lang):
    if not data:
        raise ImportProblem(tr(lang, "imp.empty"))
    name = (filename or "").lower()
    try:
        if name.endswith(".xls"):
            raise ImportProblem(tr(lang, "imp.xls"))
        if name.endswith(".xlsx") or name.endswith(".xlsm") or data[:2] == b"PK":
            rows = read_xlsx(data)
        else:
            rows = read_csv(data)
    except ImportProblem:
        raise
    except Exception as e:
        raise ImportProblem(tr(lang, "imp.bad_file", err=f"{type(e).__name__}: {e}"))
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        raise ImportProblem(tr(lang, "imp.empty"))
    return rows


# ---------------------------------------------------------------- columns
def _norm(h):
    h = re.sub(r"\(.*?\)|\[.*?\]", " ", str(h or "").lower())
    h = h.replace("·", " ").replace("*", " ").replace(".", " ").replace(",", " ")
    return re.sub(r"\s+", " ", h).strip()


def detect_mapping(headers):
    """{field: column index or None}"""
    norm = [_norm(h) for h in headers]
    mapping = {f: None for f in FIELDS}
    taken = set()
    for field in FIELDS:  # exact names first
        for i, h in enumerate(norm):
            if i not in taken and h in ALIASES[field]:
                mapping[field] = i
                taken.add(i)
                break
    for field, frags in CONTAINS.items():  # then fragments
        if mapping[field] is None:
            for i, h in enumerate(norm):
                if i not in taken and any(fr in h for fr in frags):
                    mapping[field] = i
                    taken.add(i)
                    break
    return mapping


# ---------------------------------------------------------------- values
def to_datetime(v):
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "").replace(" ", "T")).replace(tzinfo=None)
        except ValueError:
            pass
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        if 20000 < v < 80000:  # Excel serial day number
            # Excel stores 08:00 as 46296.33333333333..., so convert to whole seconds first;
            # otherwise 07:59:59.999999 would be floored into the previous hour
            return datetime(1899, 12, 30) + timedelta(seconds=round(float(v) * 86400))
        if 1e9 < v < 1e11:     # unix seconds
            return datetime.fromtimestamp(v)
        if 1e11 <= v < 1e14:   # unix milliseconds
            return datetime.fromtimestamp(v / 1000)
    return None


def to_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "").replace(" ", "")
    if not s:
        return None
    s = re.sub(r"[^\d,.\-+eE]", "", s)
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _lift_key(v):
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v).strip() if v is not None else ""


# ---------------------------------------------------------------- main
def process(filename, data, lang="en", mapping=None, lift_id=None, cumulative=False):
    """Parse and convert. Nothing is written to the database here.

    Returns (summary, readings, names, fields) where readings are tuples
    (lift_id, 'YYYY-MM-DDTHH:00:00', kwh, trips, door_cycles) and fields tells which of
    kwh / trips / door_cycles the file really contained."""
    rows = read_table(filename, data, lang)
    headers = ["" if h is None else str(h) for h in rows[0]]
    body = rows[1:]
    auto = detect_mapping(headers)
    m = dict(auto)
    for k, v in (mapping or {}).items():
        if k in m:
            m[k] = int(v) if v not in (None, "", -1) else None

    summary = {
        "headers": headers,
        "mapping": m,
        "auto_mapping": auto,
        "sample": [["" if c is None else str(c) for c in r] for r in body[:5]],
        "rows_total": len(body),
        "warnings": [],
    }
    if m["ts"] is None:
        raise_with(summary, tr(lang, "imp.no_ts"))
    value_cols = [f for f in ("kwh", "trips", "door_cycles") if m[f] is not None]
    if not value_cols:
        raise_with(summary, tr(lang, "imp.no_value"))
    if m["lift_id"] is None and m["name"] is None and not lift_id:
        raise_with(summary, tr(lang, "imp.no_lift"))

    def cell(r, f):
        i = m[f]
        return r[i] if i is not None and i < len(r) else None

    skipped, examples = {}, {}

    def skip(reason, n):
        skipped[reason] = skipped.get(reason, 0) + 1
        examples.setdefault(reason, [])
        if len(examples[reason]) < 5:
            examples[reason].append(n + 2)  # +2: header row and 1-based numbering

    raw, names = {}, {}
    for n, r in enumerate(body):
        if n >= MAX_ROWS:
            break
        ts = to_datetime(cell(r, "ts"))
        if ts is None:
            skip("bad_time", n)
            continue
        lid = _lift_key(cell(r, "lift_id")) or _lift_key(cell(r, "name")) or (lift_id or "").strip()
        if not lid:
            skip("no_lift", n)
            continue
        vals = {}
        bad = False
        for f in value_cols:
            raw_v = cell(r, f)
            x = to_number(raw_v)
            if x is None and raw_v not in (None, ""):
                bad = True
            vals[f] = x
        if bad or all(x is None for x in vals.values()):
            skip("bad_number", n)
            continue
        if not cumulative and any(x is not None and x < 0 for x in vals.values()):
            skip("negative", n)
            continue
        raw.setdefault(lid, []).append((ts, vals))
        nm = _lift_key(cell(r, "name"))
        names[lid] = nm or names.get(lid) or lid

    steps = []
    hourly = {}
    for lid, items in raw.items():
        items.sort(key=lambda x: x[0])
        gaps = [(b[0] - a[0]).total_seconds() / 60 for a, b in zip(items, items[1:]) if b[0] != a[0]]
        if gaps:
            steps.append(median(gaps))
        prev = {}
        for ts, vals in items:
            out = {}
            for f, x in vals.items():
                if x is None:
                    continue
                if cumulative:
                    p = prev.get(f)
                    prev[f] = x
                    if p is None or x < p:  # first row = baseline, a drop = counter reset
                        continue
                    x = x - p
                out[f] = x
            if not out:
                continue
            key = (lid, ts.replace(minute=0, second=0, microsecond=0))
            acc = hourly.setdefault(key, {})
            for f, x in out.items():
                acc[f] = acc.get(f, 0.0) + x

    if not hourly:
        raise_with(summary, tr(lang, "imp.no_rows"))
    if cumulative:
        summary["warnings"].append(tr(lang, "imp.cumulative_first"))
    if steps and median(steps) > 90:
        summary["warnings"].append(tr(lang, "imp.not_hourly", m=int(median(steps))))

    readings = []
    for (lid, hour), acc in sorted(hourly.items()):
        readings.append((lid, hour.strftime("%Y-%m-%dT%H:00:00"), round(acc.get("kwh", 0.0), 4),
                         int(round(acc.get("trips", 0))), int(round(acc.get("door_cycles", 0)))))
    summary.update(
        rows_used=sum(len(v) for v in raw.values()),
        skipped=skipped,
        skipped_rows=examples,
        lifts=sorted(raw),
        hours=len(readings),
        first=readings[0][1],
        last=max(r[1] for r in readings),
        fields=value_cols,
        cumulative=cumulative,
    )
    return summary, readings, names, set(value_cols)


def raise_with(summary, message):
    e = ImportProblem(message)
    e.summary = summary
    raise e