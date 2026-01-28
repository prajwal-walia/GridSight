# GridSight 🏎️
**Professional F1 Telemetry Dashboard** — Real-time pit wall experience
for F1 fans and sim racers.

## Features
- 🗺️ Live Track Map — All 22 drivers with real-time positions
- 📊 Telemetry Charts — Speed, Throttle, Brake, Gear per driver  
- 🏁 Leaderboard — Gaps, tyre compounds, pit prediction, sector times
- 🌦️ Weather HUD — Air/track temp, humidity, wind
- 🚦 Race Control — Flag overlays, safety car banners, notifications
- 🎮 F1 25 UDP Bridge — Live sim telemetry from EA F1 25
- 📱 Mobile Layout — Full 4-tab responsive UI
- 🖼️ Picture-in-Picture — Detached floating window
- 📅 2022–2026 Seasons — Ground Effect and Active Aero eras
- ⏺️ Session Recording — Record and replay F1 25 sim sessions

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.10, FastAPI, WebSockets |
| F1 Data | FastF1 3.8.x |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, Recharts |
| Sim Data | EA F1 25 UDP (port 20777) |

## Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## F1 25 Integration
1. Start GridSight backend
2. In F1 25: Settings → Telemetry → UDP On → IP: [your PC's IP] → Port: 20777
3. Click "START SIM SESSION" on the opening screen

## Precompute Sessions (optional but recommended)
```bash
cd backend
python utils/precompute.py --year 2025
python utils/precompute.py --session 2026 3 R
```

## Credits
- FastF1 by theOehrly
- Inspired by F1ReplayTiming (MIT)
- F1 25 UDP parsing inspired by Fredrik2002/f1-25-telemetry-application

## Disclaimer
GridSight is unofficial and not associated with Formula 1, FIA, or EA Sports.

## License
MIT
