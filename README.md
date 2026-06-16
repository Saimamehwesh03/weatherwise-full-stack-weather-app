# WeatherWise - Full Stack Weather Assessment

Assessment completed: **Full Stack**, covering Tech Assessment #1 and Tech Assessment #2.

Built by **Saima Mehwesh Syeda** for the AI Engineer Intern technical assessment.

## What It Does

- Accepts a city, town, ZIP/postal code, landmark, address, or GPS coordinates.
- Uses browser geolocation for current-location weather.
- Shows current weather, humidity, wind, precipitation, pressure, AQI, UV, a 5-day forecast, and a requested date range.
- Validates date ranges, coordinates, unit selection, and location lookup results.
- Saves every request to SQLite.
- Supports full CRUD for saved weather records.
- Exports saved records as JSON, CSV, or Markdown.
- Includes map context for the resolved location.
- Displays PM Accelerator information in the application.

## API Integrations

- **Nominatim / OpenStreetMap**: geocoding, reverse geocoding, and map context.
- **Open-Meteo Forecast API**: current weather, 5-day forecast, and date-range forecast/archive data.
- **Open-Meteo Air Quality API**: AQI and pollutant details.

No API keys are required.

## Tech Stack

- Frontend: HTML, CSS, and browser JavaScript.
- Backend: Python standard-library HTTP server.
- Database: SQLite.
- Testing: Python `unittest`.

The frontend is not built with a Python or Java framework. It is a web-first JavaScript interface served by the backend.

## Run Locally

```bash
python3 app.py
```

Open:

```text
http://127.0.0.1:8000
```

The database is created automatically at:

```text
data/weather.sqlite3
```

## Run Tests

```bash
python3 -m unittest discover -s tests
```

## REST Endpoints

```text
GET    /api/health
GET    /api/requests
GET    /api/requests/{id}
POST   /api/requests
PUT    /api/requests/{id}
DELETE /api/requests/{id}
GET    /api/export?format=json
GET    /api/export?format=csv
GET    /api/export?format=markdown
```

Example create payload:

```json
{
  "location": "New York, NY",
  "startDate": "2026-06-16",
  "endDate": "2026-06-20",
  "unitSystem": "imperial",
  "notes": "Interview demo"
}
```

## Demo Video Outline

1. Start the app and open the local URL.
2. Search for a city or landmark and save the request.
3. Show current weather, 5-day forecast, date-range table, AQI, and map.
4. Use current location.
5. Edit a saved record, then delete one.
6. Export JSON, CSV, or Markdown.
7. Briefly show `app.py`, `public/app.js`, and the SQLite/CRUD endpoints.

## PM Accelerator Note

Product Manager Accelerator supports aspiring and current product managers with product management training, career coaching, resume support, and AI product education.
