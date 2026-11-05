# Lift Energy AI — prototype (team №48)

AI system for monitoring and optimising lift energy use. Stage 1 is **read-only**: no interference with the equipment.

```
RS-485 / Modbus RTU ─┐
MQTT ────────────────┼─► hourly aggregator ─► SQLite ─► analytics + scikit-learn ─► FastAPI ─► React + TypeScript
Excel / CSV import ──┘                                         └─► LLM layer (Gemini / GigaChat / Ollama / OpenAI-compatible)
```

## Run (Windows, Git Bash)

```bash
cd lift-energy
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload      # open http://127.0.0.1:8000
```

`frontend/dist` is the ready build, so Node.js is **not** needed to run. To change the UI (Node 18+):

```bash
cd frontend && npm install && npm run build   # or: npm run dev  -> http://localhost:5173
```

Tests: `pip install -r requirements-dev.txt && python -m pytest tests`.

## Settings (.env)

Copy `.env.example` to `.env` and edit. **Secrets live only in `.env`** (it is in `.gitignore`). Never paste keys into chat or screenshots.
After editing `.env`, restart the server, open *Data & sources* and press **Test connection**.

### Gemini (Google AI Studio key)
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-2.5-flash
```
### GigaChat
```
LLM_PROVIDER=gigachat
GIGACHAT_AUTH_KEY=base64(ClientID:ClientSecret)
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_CA_BUNDLE=C:\certs\russian_trusted_root_ca.pem     # or GIGACHAT_VERIFY_SSL=false for a quick test
```
The LLM only explains facts the system already computed. Every number in its answer is checked against those facts; otherwise a template text is shown.

## Excel / CSV import

*Data & sources → Import.* Russian and English headers are recognised (Лифт, Дата и время, Электроэнергия, Поездки…). You can fix the column mapping, import a running meter total (“cumulative”), and 15-minute data is summed per hour. A bad file gives a readable message, never a server error.

## RS-485 (Modbus RTU)

1. Stop the app (a COM port can be opened by one program only).
2. Find the slave addresses: `python tools/modbus_probe.py --port COM3 --scan 1-32`
3. Dump registers: `python tools/modbus_probe.py --port COM3 --unit 1 --fn 4 --start 0 --count 40`
   Find a value you can see on the device display (e.g. total kWh) in the table: note address, column (type + word order), and the multiplier.
4. Copy `regmap.example.json` to `regmap.json` and fill it in (`function` 3 or 4; types `uint16 int16 uint32 int32 float32`; `scale`).
5. `.env`: `MODBUS_PORT=COM3`, `MODBUS_UNITS=L1=1,L2=2`, `MODBUS_REGMAP=regmap.json`, `MODBUS_WORD_ORDER=big|little`.

Without hardware: `python tools/modbus_slave_sim.py --port 5020`, then `MODBUS_PORT=socket://127.0.0.1:5020`.

## MQTT

Topic `lifts/<lift_id>/telemetry`, JSON with any of: `kwh`, `trips`, `door_cycles` (increments) or `kwh_total`, `trips_total`, `door_cycles_total` (counters). Energy and trips may come from different sources; they are summed per lift-hour.
Local test: `python tools/mqtt_broker_dev.py` and `python tools/mqtt_publisher_sim.py`.

## Verified vs not

Verified by tests: Modbus frames/CRC/types over a real TCP socket, MQTT through a real broker, importer (xlsx, csv, cumulative, garbage), Gemini/GigaChat/Ollama/OpenAI request shapes against fake servers, number guard, secret scrubbing, UI in a browser.
**Not verified (needs you):** real RS-485 hardware and the real Arpicon register map; a live call to real Gemini/GigaChat with your key; LLM behaviour on real data.
# Lift Energy AI — prototype (team №48)

AI system for monitoring and optimising lift energy use. Stage 1 is **read-only**: no interference with the equipment.

```
RS-485 / Modbus RTU ─┐
MQTT ────────────────┼─► hourly aggregator ─► SQLite ─► analytics + scikit-learn ─► FastAPI ─► React + TypeScript
Excel / CSV import ──┘                                         └─► LLM layer (Gemini / GigaChat / Ollama / OpenAI-compatible)
```

## Run (Windows, Git Bash)

```bash
cd lift-energy
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload      # open http://127.0.0.1:8000
```

`frontend/dist` is the ready build, so Node.js is **not** needed to run. To change the UI (Node 18+):

```bash
cd frontend && npm install && npm run build   # or: npm run dev  -> http://localhost:5173
```

Tests: `pip install -r requirements-dev.txt && python -m pytest tests`.

## Settings (.env)

Copy `.env.example` to `.env` and edit. **Secrets live only in `.env`** (it is in `.gitignore`). Never paste keys into chat or screenshots.
After editing `.env`, restart the server, open *Data & sources* and press **Test connection**.

### Gemini (Google AI Studio key)
```
LLM_PROVIDER=gemini
GEMINI_API_KEY=your-key
GEMINI_MODEL=gemini-3.8-flash
```
### GigaChat
```
LLM_PROVIDER=gigachat
GIGACHAT_AUTH_KEY=base64(ClientID:ClientSecret)
GIGACHAT_SCOPE=GIGACHAT_API_PERS
GIGACHAT_CA_BUNDLE=C:\certs\russian_trusted_root_ca.pem     # or GIGACHAT_VERIFY_SSL=false for a quick test
```
The LLM only explains facts the system already computed. Every number in its answer is checked against those facts; otherwise a template text is shown.

## Login
Off by default. Set `APP_PASSWORD` (and optionally `APP_USER`, default `admin`) in `.env` and restart: the API and `/docs` then require a login, and the page shows a sign-in form. The session is a signed HttpOnly cookie valid for 7 days; 5 wrong attempts from one address lock it out for 5 minutes. Changing the password signs everybody out. Use HTTPS when the app is on the internet (the cookie is marked `Secure` automatically behind an HTTPS proxy).

## Docker (server or Raspberry Pi)
```bash
cp .env.example .env        # fill in APP_PASSWORD, API keys, MQTT_URL ...
docker compose up -d --build
# open http://localhost:8000  (database is kept in the "lift-data" volume)
```
Update after a code change: `docker compose up -d --build`. Logs: `docker compose logs -f`.
RS-485 needs a Linux host: add the adapter under `devices:` in `docker-compose.yml` and set `MODBUS_PORT=/dev/ttyUSB0`. Docker Desktop on Windows cannot pass a COM port into a container; use an RS-485-to-Ethernet gateway (`MODBUS_PORT=socket://IP:PORT`) or run the app without Docker.

## Excel / CSV import

*Data & sources → Import.* Russian and English headers are recognised (Лифт, Дата и время, Электроэнергия, Поездки…). You can fix the column mapping, import a running meter total (“cumulative”), and 15-minute data is summed per hour. A bad file gives a readable message, never a server error.

## RS-485 (Modbus RTU)

1. Stop the app (a COM port can be opened by one program only).
2. Find the slave addresses: `python tools/modbus_probe.py --port COM3 --scan 1-32`
3. Dump registers: `python tools/modbus_probe.py --port COM3 --unit 1 --fn 4 --start 0 --count 40`
   Find a value you can see on the device display (e.g. total kWh) in the table: note address, column (type + word order), and the multiplier.
4. Copy `regmap.example.json` to `regmap.json` and fill it in (`function` 3 or 4; types `uint16 int16 uint32 int32 float32`; `scale`).
5. `.env`: `MODBUS_PORT=COM3`, `MODBUS_UNITS=L1=1,L2=2`, `MODBUS_REGMAP=regmap.json`, `MODBUS_WORD_ORDER=big|little`.

Without hardware: `python tools/modbus_slave_sim.py --port 5020`, then `MODBUS_PORT=socket://127.0.0.1:5020`.

## MQTT

Topic `lifts/<lift_id>/telemetry`, JSON with any of: `kwh`, `trips`, `door_cycles` (increments) or `kwh_total`, `trips_total`, `door_cycles_total` (counters). Energy and trips may come from different sources; they are summed per lift-hour.
Local test: `python tools/mqtt_broker_dev.py` and `python tools/mqtt_publisher_sim.py`.

## Verified vs not

Verified by tests: Modbus frames/CRC/types over a real TCP socket, MQTT through a real broker, importer (xlsx, csv, cumulative, garbage), Gemini/GigaChat/Ollama/OpenAI request shapes against fake servers, number guard, secret scrubbing, UI in a browser.
**Not verified (needs you):** real RS-485 hardware and the real Arpicon register map; a live call to real Gemini/GigaChat with your key; LLM behaviour on real data.