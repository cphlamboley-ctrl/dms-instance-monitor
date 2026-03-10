# DMS Instance Monitor

A web dashboard to track and manage the availability of DMS (sportdata.org) instances in real time.

## Features

- **29 instance buttons** (ports 9091–9119) with live status indicators
- **3 statuses**: 🟢 Available · 🔴 In Use · ⚫ In Maintenance
- **Assignment panel**: assign an instance to a user with From/To dates and notes
- **Auto-expiry**: instances revert to Available automatically when the end date is passed
- **Auto-refresh** every 30 seconds
- **Responsive** dark glassmorphism UI

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 · FastAPI · SQLite |
| Frontend | HTML · Vanilla CSS · Vanilla JS |
| Server | Uvicorn |

## Project Structure

```
DMS_INSTANCES/
├── backend/
│   ├── main.py          # FastAPI app + API endpoints
│   ├── database.py      # SQLite init & connection
│   ├── models.py        # Pydantic models
│   └── requirements.txt
└── frontend/
    ├── index.html       # Main dashboard
    ├── style.css        # Dark glassmorphism theme
    └── app.js           # Frontend logic
```

## Getting Started

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Start the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8099 --reload
```

### 3. Open the app

Navigate to [http://localhost:8099](http://localhost:8099)

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/instances` | List all 29 instances |
| `GET` | `/api/instances/{id}` | Get one instance |
| `PUT` | `/api/instances/{id}` | Update assignment |
| `POST` | `/api/instances/{id}/free` | Mark as Available |
| `POST` | `/api/instances/{id}/maintenance` | Mark as In Maintenance |

## License

Internal use — sportdata.org
