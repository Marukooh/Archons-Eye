# Archon's Eye

> *"The strong prey upon the weak. We simply make it efficient."*

**Archon's Eye** is a real-time piracy scouting tool for **Elite Dangerous**. It listens to the [EDDN](https://eddn.edcd.io/) live data feed and scores star systems based on mining activity, high-value commodity traffic, faction states, and security level — so you always know where the richest, most vulnerable targets are.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![PySide6](https://img.shields.io/badge/UI-PySide6-green)
![License](https://img.shields.io/badge/license-MIT-crimson)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

---

## Features

- **Live EDDN feed** — receives commodity and journal events from the community network in real time via ZeroMQ
- **System scoring** — combines hotspot ring presence, high-value commodities (Void Opals, LTDs, Painite…), faction states, and security level into a single opportunity score
- **Miner & trader detection** — tracks active CMDRs uploading FSD jumps to estimate traffic density
- **EDSM enrichment** — asynchronously fetches system metadata (population, allegiance, economy) for new systems
- **SQLite cache** — persists all system data locally so scores survive restarts
- **Elite-themed HUD** — animated glitch title, pulsing HUD bars, phosphor-green terminal aesthetic

---

## Requirements

- Windows 10 / 11
- Python 3.12+ (only needed if running from source)
- An internet connection (for EDDN and EDSM)
- Elite Dangerous is **not required** to be running — the tool reads the community data feed, not your local game

---

## Installation

### Option A — Pre-built exe (recommended)

1. Download `archons_eye.exe` from the [Releases](https://github.com/Marukooh/Archons-Eye/releases) page
2. Place it anywhere you like
3. Run it — no installer needed

Data and logs are stored in `%APPDATA%\ArchonsEye\`, not next to the exe.

### Option B — Run from source

```bash
git clone https://github.com/Marukooh/Archons-Eye.git
cd "Archon's Eye"
pip install -e .
python -m archons_eye.main
```

Or with a virtual environment:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m archons_eye.main
```

---

## Usage

1. **Launch** the app. It immediately connects to the EDDN relay and starts receiving live data.
2. **Click Start** in the sidebar to begin scoring. The table will populate as systems are reported.
3. **Filter** results using the sidebar controls:
   - Toggle **Miners** / **Traders** to focus on the traffic type you want to intercept
   - Adjust **Min score** to hide low-opportunity systems
   - Set the **security** filter to narrow down by system security level
4. **Table columns**:
   | Column | Description |
   |--------|-------------|
   | System | Star system name |
   | Score | Composite piracy opportunity score (higher = better) |
   | Security | System security level |
   | Distance | Distance from your current position (requires journal) |
   | Mining | Active hotspot rings and minerals being mined |
   | Trading | High-value commodities recently reported at market |
5. **Click a row** to copy the system name to clipboard for quick galaxy map navigation.

### Score breakdown

| Factor | Points |
|--------|--------|
| Hotspot ring (per ring) | varies by mineral |
| High-value commodity at market | varies by commodity |
| Anarchy security | +25 |
| Low security | +15 |
| Active faction state (War, Civil War…) | bonus |
| Recent CMDR activity | bonus |

Systems older than 60 minutes are automatically removed.

---

## Configuration

Edit `archons_eye/config.py` to change defaults:

```python
alert_score_threshold   = 60     # minimum score to highlight a system
max_system_age_minutes  = 60     # how long before a system is pruned
cmdr_window_minutes     = 10     # window for counting active CMDRs
target_miner            = True   # score mining traffic
target_trader           = True   # score trading traffic
```

---

## Data & Privacy

- **No account required.** Archon's Eye only reads from the public EDDN feed.
- **No data is sent.** The app is purely a consumer; it never uploads anything.
- **Local storage**: `%APPDATA%\ArchonsEye\archons_eye.db` (cache) and `archons_eye_debug.log` (logs, max 10 MB × 4 backups).

---

## Building the exe

Requires [PyInstaller](https://pyinstaller.org):

```bash
pip install pyinstaller
build.bat
```

The output exe is placed in `dist\archons_eye\`.

---

## License

[MIT](LICENSE) — © 2026 Marukooh

*Archon's Eye is a fan-made tool and is not affiliated with Frontier Developments or Elite Dangerous.*
