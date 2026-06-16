from __future__ import annotations

import csv
import datetime as dt
import io
import json
import mimetypes
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "weather.sqlite3"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
APP_SOURCE = "Open-Meteo, Nominatim, OpenStreetMap"
USER_AGENT = "WeatherWiseTechnicalAssessment/1.0 (local interview project)"


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "sun"),
    1: ("Mainly clear", "sun-cloud"),
    2: ("Partly cloudy", "sun-cloud"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "drizzle"),
    53: ("Moderate drizzle", "drizzle"),
    55: ("Dense drizzle", "drizzle"),
    56: ("Light freezing drizzle", "drizzle"),
    57: ("Dense freezing drizzle", "drizzle"),
    61: ("Slight rain", "rain"),
    63: ("Moderate rain", "rain"),
    65: ("Heavy rain", "rain"),
    66: ("Light freezing rain", "rain"),
    67: ("Heavy freezing rain", "rain"),
    71: ("Slight snow", "snow"),
    73: ("Moderate snow", "snow"),
    75: ("Heavy snow", "snow"),
    77: ("Snow grains", "snow"),
    80: ("Slight rain showers", "rain"),
    81: ("Moderate rain showers", "rain"),
    82: ("Violent rain showers", "storm"),
    85: ("Slight snow showers", "snow"),
    86: ("Heavy snow showers", "snow"),
    95: ("Thunderstorm", "storm"),
    96: ("Thunderstorm with slight hail", "storm"),
    99: ("Thunderstorm with heavy hail", "storm"),
}


def describe_weather(code: Any) -> dict[str, Any]:
    try:
        numeric_code = int(code)
    except (TypeError, ValueError):
        numeric_code = -1
    label, icon = WEATHER_CODES.get(numeric_code, ("Weather data unavailable", "cloud"))
    return {"code": numeric_code, "label": label, "icon": icon}


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                location_query TEXT NOT NULL,
                resolved_name TEXT NOT NULL,
                country TEXT,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                unit_system TEXT NOT NULL,
                notes TEXT,
                current_json TEXT NOT NULL,
                forecast_json TEXT NOT NULL,
                range_json TEXT NOT NULL,
                air_quality_json TEXT NOT NULL,
                map_json TEXT NOT NULL,
                source TEXT NOT NULL
            )
            """
        )


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def today() -> dt.date:
    return dt.date.today()


def parse_iso_date(value: Any, field_name: str) -> dt.date:
    if not isinstance(value, str) or not value.strip():
        raise AppError(400, "invalid_date", f"{field_name} is required.")
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise AppError(400, "invalid_date", f"{field_name} must use YYYY-MM-DD format.") from exc


def validate_date_range(start_value: Any, end_value: Any) -> tuple[dt.date, dt.date]:
    start = parse_iso_date(start_value, "Start date")
    end = parse_iso_date(end_value, "End date")
    if start > end:
        raise AppError(400, "invalid_date_range", "Start date must be before or equal to end date.")
    if (end - start).days > 15:
        raise AppError(400, "invalid_date_range", "Date ranges can include up to 16 days.")
    if start < dt.date(1940, 1, 1):
        raise AppError(400, "invalid_date_range", "Start date must be on or after 1940-01-01.")
    if end > today() + dt.timedelta(days=16):
        raise AppError(400, "invalid_date_range", "End date must be within the next 16 days.")
    return start, end


def normalize_unit_system(value: Any) -> str:
    unit_system = str(value or "imperial").lower().strip()
    if unit_system not in {"imperial", "metric"}:
        raise AppError(400, "invalid_units", "Unit system must be imperial or metric.")
    return unit_system


def unit_params(unit_system: str) -> dict[str, str]:
    if unit_system == "imperial":
        return {
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
        }
    return {
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
    }


COORDINATE_PATTERN = re.compile(
    r"^\s*(?P<lat>[+-]?\d+(?:\.\d+)?)\s*,\s*(?P<lon>[+-]?\d+(?:\.\d+)?)\s*$"
)


def parse_coordinate_query(value: str) -> tuple[float, float] | None:
    match = COORDINATE_PATTERN.match(value)
    if not match:
        return None
    return float(match.group("lat")), float(match.group("lon"))


def validate_coordinates(latitude: Any, longitude: Any) -> tuple[float, float]:
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError) as exc:
        raise AppError(400, "invalid_coordinates", "Latitude and longitude must be numbers.") from exc
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise AppError(400, "invalid_coordinates", "Latitude or longitude is outside the valid range.")
    return lat, lon


def fetch_json(url: str, timeout: int = 15) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return json.loads(response.read().decode(charset))
    except HTTPError as exc:
        raise AppError(exc.code, "upstream_error", "A weather or location service returned an error.") from exc
    except URLError as exc:
        raise AppError(502, "network_error", "Could not reach the external weather services.") from exc
    except TimeoutError as exc:
        raise AppError(504, "timeout", "The external weather service timed out.") from exc
    except json.JSONDecodeError as exc:
        raise AppError(502, "bad_upstream_response", "The external service sent an unreadable response.") from exc


def compact_place_name(result: dict[str, Any]) -> str:
    address = result.get("address") or {}
    parts = [
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or result.get("name"),
        address.get("state"),
        address.get("country"),
    ]
    compact = ", ".join(str(part) for part in parts if part)
    return compact or result.get("display_name") or "Selected coordinates"


def build_map_urls(latitude: float, longitude: float) -> dict[str, str]:
    lat_pad = 0.045
    lon_pad = 0.07
    bbox = f"{longitude - lon_pad:.6f},{latitude - lat_pad:.6f},{longitude + lon_pad:.6f},{latitude + lat_pad:.6f}"
    params = urlencode({"bbox": bbox, "layer": "mapnik", "marker": f"{latitude:.6f},{longitude:.6f}"})
    return {
        "embedUrl": f"https://www.openstreetmap.org/export/embed.html?{params}",
        "externalUrl": f"https://www.openstreetmap.org/?mlat={latitude:.6f}&mlon={longitude:.6f}#map=12/{latitude:.6f}/{longitude:.6f}",
    }


def reverse_geocode(latitude: float, longitude: float) -> dict[str, Any]:
    params = urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.6f}",
            "lon": f"{longitude:.6f}",
            "addressdetails": 1,
        }
    )
    try:
        result = fetch_json(f"https://nominatim.openstreetmap.org/reverse?{params}")
    except AppError:
        return {
            "query": f"{latitude:.6f},{longitude:.6f}",
            "resolvedName": f"{latitude:.4f}, {longitude:.4f}",
            "country": None,
            "latitude": latitude,
            "longitude": longitude,
        }
    address = result.get("address") or {}
    return {
        "query": f"{latitude:.6f},{longitude:.6f}",
        "resolvedName": compact_place_name(result),
        "country": address.get("country"),
        "latitude": latitude,
        "longitude": longitude,
    }


def geocode_location(location: Any, latitude: Any = None, longitude: Any = None) -> dict[str, Any]:
    if latitude is not None and longitude is not None:
        lat, lon = validate_coordinates(latitude, longitude)
        return reverse_geocode(lat, lon)

    location_text = str(location or "").strip()
    if not location_text:
        raise AppError(400, "missing_location", "Location is required.")

    coordinates = parse_coordinate_query(location_text)
    if coordinates:
        lat, lon = validate_coordinates(*coordinates)
        resolved = reverse_geocode(lat, lon)
        resolved["query"] = location_text
        return resolved

    params = urlencode(
        {
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
            "q": location_text,
        }
    )
    results = fetch_json(f"https://nominatim.openstreetmap.org/search?{params}")
    if not isinstance(results, list) or not results:
        raise AppError(
            404,
            "location_not_found",
            "I could not find that location. Try a city, ZIP code, landmark, or coordinates.",
        )

    result = results[0]
    lat, lon = validate_coordinates(result.get("lat"), result.get("lon"))
    address = result.get("address") or {}
    return {
        "query": location_text,
        "resolvedName": compact_place_name(result),
        "country": address.get("country"),
        "latitude": lat,
        "longitude": lon,
    }


def open_meteo_url(path: str, params: dict[str, Any]) -> str:
    filtered = {key: value for key, value in params.items() if value is not None}
    return f"https://api.open-meteo.com/{path}?{urlencode(filtered)}"


def open_meteo_archive_url(params: dict[str, Any]) -> str:
    filtered = {key: value for key, value in params.items() if value is not None}
    return f"https://archive-api.open-meteo.com/v1/archive?{urlencode(filtered)}"


def air_quality_url(params: dict[str, Any]) -> str:
    filtered = {key: value for key, value in params.items() if value is not None}
    return f"https://air-quality-api.open-meteo.com/v1/air-quality?{urlencode(filtered)}"


def list_value(values: dict[str, Any], key: str, index: int) -> Any:
    sequence = values.get(key) or []
    if index >= len(sequence):
        return None
    return sequence[index]


def normalize_daily(data: dict[str, Any], units: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    daily = data.get("daily") or {}
    times = daily.get("time") or []
    normalized = []
    for index, day in enumerate(times):
        weather = describe_weather(list_value(daily, "weather_code", index))
        normalized.append(
            {
                "date": day,
                "condition": weather["label"],
                "icon": weather["icon"],
                "weatherCode": weather["code"],
                "temperatureMax": list_value(daily, "temperature_2m_max", index),
                "temperatureMin": list_value(daily, "temperature_2m_min", index),
                "precipitation": list_value(daily, "precipitation_sum", index),
                "precipitationProbability": list_value(daily, "precipitation_probability_max", index),
                "windSpeedMax": list_value(daily, "wind_speed_10m_max", index),
                "uvIndexMax": list_value(daily, "uv_index_max", index),
                "sunrise": list_value(daily, "sunrise", index),
                "sunset": list_value(daily, "sunset", index),
                "units": {
                    "temperature": (units or {}).get("temperature_2m_max"),
                    "precipitation": (units or {}).get("precipitation_sum"),
                    "windSpeed": (units or {}).get("wind_speed_10m_max"),
                },
            }
        )
    return normalized


def fetch_current_and_forecast(latitude: float, longitude: float, unit_system: str) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": ",".join(
            [
                "temperature_2m",
                "relative_humidity_2m",
                "apparent_temperature",
                "is_day",
                "precipitation",
                "weather_code",
                "cloud_cover",
                "pressure_msl",
                "wind_speed_10m",
                "wind_direction_10m",
            ]
        ),
        "daily": ",".join(
            [
                "weather_code",
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "uv_index_max",
                "sunrise",
                "sunset",
            ]
        ),
        "forecast_days": 5,
        "timezone": "auto",
        **unit_params(unit_system),
    }
    data = fetch_json(open_meteo_url("v1/forecast", params))
    current = data.get("current") or {}
    current_units = data.get("current_units") or {}
    weather = describe_weather(current.get("weather_code"))
    return {
        "current": {
            "time": current.get("time"),
            "temperature": current.get("temperature_2m"),
            "apparentTemperature": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "cloudCover": current.get("cloud_cover"),
            "pressure": current.get("pressure_msl"),
            "windSpeed": current.get("wind_speed_10m"),
            "windDirection": current.get("wind_direction_10m"),
            "isDay": current.get("is_day"),
            "condition": weather["label"],
            "icon": weather["icon"],
            "weatherCode": weather["code"],
            "units": {
                "temperature": current_units.get("temperature_2m"),
                "apparentTemperature": current_units.get("apparent_temperature"),
                "humidity": current_units.get("relative_humidity_2m"),
                "precipitation": current_units.get("precipitation"),
                "pressure": current_units.get("pressure_msl"),
                "windSpeed": current_units.get("wind_speed_10m"),
            },
        },
        "forecast": normalize_daily(data, data.get("daily_units") or {}),
    }


def fetch_daily_range(latitude: float, longitude: float, start: dt.date, end: dt.date, unit_system: str) -> list[dict[str, Any]]:
    daily_variables = ",".join(
        [
            "weather_code",
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "wind_speed_10m_max",
        ]
    )
    segments: list[dict[str, Any]] = []
    current_day = today()

    if start < current_day:
        archive_end = min(end, current_day - dt.timedelta(days=1))
        if start <= archive_end:
            archive_params = {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": start.isoformat(),
                "end_date": archive_end.isoformat(),
                "daily": daily_variables,
                "timezone": "auto",
                **unit_params(unit_system),
            }
            archive_data = fetch_json(open_meteo_archive_url(archive_params))
            segments.extend(normalize_daily(archive_data, archive_data.get("daily_units") or {}))

    if end >= current_day:
        forecast_start = max(start, current_day)
        forecast_params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": forecast_start.isoformat(),
            "end_date": end.isoformat(),
            "daily": daily_variables,
            "timezone": "auto",
            **unit_params(unit_system),
        }
        forecast_data = fetch_json(open_meteo_url("v1/forecast", forecast_params))
        segments.extend(normalize_daily(forecast_data, forecast_data.get("daily_units") or {}))

    return sorted(segments, key=lambda day: day["date"])


def fetch_air_quality(latitude: float, longitude: float) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "us_aqi,pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone",
        "timezone": "auto",
    }
    try:
        data = fetch_json(air_quality_url(params))
    except AppError:
        return {"available": False}
    current = data.get("current") or {}
    units = data.get("current_units") or {}
    return {
        "available": bool(current),
        "time": current.get("time"),
        "usAqi": current.get("us_aqi"),
        "pm10": current.get("pm10"),
        "pm25": current.get("pm2_5"),
        "carbonMonoxide": current.get("carbon_monoxide"),
        "nitrogenDioxide": current.get("nitrogen_dioxide"),
        "ozone": current.get("ozone"),
        "units": {
            "pm10": units.get("pm10"),
            "pm25": units.get("pm2_5"),
            "carbonMonoxide": units.get("carbon_monoxide"),
            "nitrogenDioxide": units.get("nitrogen_dioxide"),
            "ozone": units.get("ozone"),
        },
    }


def weather_package(payload: dict[str, Any], existing: sqlite3.Row | None = None) -> dict[str, Any]:
    default_start = today()
    default_end = default_start + dt.timedelta(days=4)
    start_value = payload.get("startDate") or payload.get("start_date") or (existing["start_date"] if existing else default_start.isoformat())
    end_value = payload.get("endDate") or payload.get("end_date") or (existing["end_date"] if existing else default_end.isoformat())
    start, end = validate_date_range(start_value, end_value)
    unit_system = normalize_unit_system(payload.get("unitSystem") or payload.get("unit_system") or (existing["unit_system"] if existing else "imperial"))

    location = payload.get("location")
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if location is None and latitude is None and existing is not None:
        location = existing["location_query"]
    geo = geocode_location(location, latitude, longitude)

    weather = fetch_current_and_forecast(geo["latitude"], geo["longitude"], unit_system)
    range_daily = fetch_daily_range(geo["latitude"], geo["longitude"], start, end, unit_system)
    air_quality = fetch_air_quality(geo["latitude"], geo["longitude"])
    return {
        "geo": geo,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "unitSystem": unit_system,
        "current": weather["current"],
        "forecast": weather["forecast"],
        "rangeDaily": range_daily,
        "airQuality": air_quality,
        "map": build_map_urls(geo["latitude"], geo["longitude"]),
        "notes": str(payload.get("notes") if payload.get("notes") is not None else (existing["notes"] if existing else "")).strip(),
    }


def create_record(payload: dict[str, Any]) -> dict[str, Any]:
    package = weather_package(payload)
    timestamp = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    geo = package["geo"]
    with db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO weather_requests (
                created_at, updated_at, location_query, resolved_name, country,
                latitude, longitude, start_date, end_date, unit_system, notes,
                current_json, forecast_json, range_json, air_quality_json, map_json, source
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                timestamp,
                geo["query"],
                geo["resolvedName"],
                geo.get("country"),
                geo["latitude"],
                geo["longitude"],
                package["startDate"],
                package["endDate"],
                package["unitSystem"],
                package["notes"],
                json.dumps(package["current"]),
                json.dumps(package["forecast"]),
                json.dumps(package["rangeDaily"]),
                json.dumps(package["airQuality"]),
                json.dumps(package["map"]),
                APP_SOURCE,
            ),
        )
        record_id = cursor.lastrowid
    return get_record(record_id)


def row_to_record(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "locationQuery": row["location_query"],
        "resolvedName": row["resolved_name"],
        "country": row["country"],
        "coordinates": {"latitude": row["latitude"], "longitude": row["longitude"]},
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "unitSystem": row["unit_system"],
        "notes": row["notes"] or "",
        "current": json.loads(row["current_json"]),
        "forecast": json.loads(row["forecast_json"]),
        "rangeDaily": json.loads(row["range_json"]),
        "airQuality": json.loads(row["air_quality_json"]),
        "map": json.loads(row["map_json"]),
        "source": row["source"],
    }


def get_record(record_id: int) -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM weather_requests WHERE id = ?", (record_id,)).fetchone()
    if not row:
        raise AppError(404, "record_not_found", "Weather record was not found.")
    return row_to_record(row)


def list_records() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute("SELECT * FROM weather_requests ORDER BY created_at DESC, id DESC").fetchall()
    return [row_to_record(row) for row in rows]


def update_record(record_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    with db() as conn:
        existing = conn.execute("SELECT * FROM weather_requests WHERE id = ?", (record_id,)).fetchone()
    if not existing:
        raise AppError(404, "record_not_found", "Weather record was not found.")

    package = weather_package(payload, existing)
    timestamp = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat()
    geo = package["geo"]
    with db() as conn:
        conn.execute(
            """
            UPDATE weather_requests
            SET updated_at = ?, location_query = ?, resolved_name = ?, country = ?,
                latitude = ?, longitude = ?, start_date = ?, end_date = ?,
                unit_system = ?, notes = ?, current_json = ?, forecast_json = ?,
                range_json = ?, air_quality_json = ?, map_json = ?, source = ?
            WHERE id = ?
            """,
            (
                timestamp,
                geo["query"],
                geo["resolvedName"],
                geo.get("country"),
                geo["latitude"],
                geo["longitude"],
                package["startDate"],
                package["endDate"],
                package["unitSystem"],
                package["notes"],
                json.dumps(package["current"]),
                json.dumps(package["forecast"]),
                json.dumps(package["rangeDaily"]),
                json.dumps(package["airQuality"]),
                json.dumps(package["map"]),
                APP_SOURCE,
                record_id,
            ),
        )
    return get_record(record_id)


def delete_record(record_id: int) -> dict[str, Any]:
    with db() as conn:
        cursor = conn.execute("DELETE FROM weather_requests WHERE id = ?", (record_id,))
    if cursor.rowcount == 0:
        raise AppError(404, "record_not_found", "Weather record was not found.")
    return {"deleted": True, "id": record_id}


def export_rows() -> list[dict[str, Any]]:
    rows = []
    for record in list_records():
        current = record["current"]
        air = record["airQuality"]
        rows.append(
            {
                "id": record["id"],
                "created_at": record["createdAt"],
                "location_query": record["locationQuery"],
                "resolved_name": record["resolvedName"],
                "latitude": record["coordinates"]["latitude"],
                "longitude": record["coordinates"]["longitude"],
                "start_date": record["startDate"],
                "end_date": record["endDate"],
                "unit_system": record["unitSystem"],
                "current_temperature": current.get("temperature"),
                "current_condition": current.get("condition"),
                "humidity": current.get("humidity"),
                "wind_speed": current.get("windSpeed"),
                "us_aqi": air.get("usAqi") if air.get("available") else None,
                "notes": record["notes"],
                "source": record["source"],
            }
        )
    return rows


def export_payload(fmt: str) -> tuple[bytes, str, str]:
    rows = export_rows()
    timestamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d-%H%M%S")
    if fmt == "json":
        return (
            json.dumps({"exportedAt": timestamp, "records": list_records()}, indent=2).encode("utf-8"),
            "application/json",
            f"weather-export-{timestamp}.json",
        )
    if fmt == "csv":
        buffer = io.StringIO()
        fieldnames = list(rows[0].keys()) if rows else [
            "id",
            "created_at",
            "location_query",
            "resolved_name",
            "latitude",
            "longitude",
            "start_date",
            "end_date",
            "unit_system",
            "current_temperature",
            "current_condition",
            "humidity",
            "wind_speed",
            "us_aqi",
            "notes",
            "source",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        return buffer.getvalue().encode("utf-8"), "text/csv; charset=utf-8", f"weather-export-{timestamp}.csv"
    if fmt == "markdown":
        headers = ["id", "resolved_name", "date_range", "current_temperature", "condition", "us_aqi", "notes"]
        lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
        for row in rows:
            values = [
                row["id"],
                row["resolved_name"],
                f"{row['start_date']} to {row['end_date']}",
                row["current_temperature"],
                row["current_condition"],
                row["us_aqi"] or "",
                str(row["notes"]).replace("|", "/"),
            ]
            lines.append("| " + " | ".join(str(value) for value in values) + " |")
        return "\n".join(lines).encode("utf-8"), "text/markdown; charset=utf-8", f"weather-export-{timestamp}.md"
    raise AppError(400, "invalid_export_format", "Export format must be json, csv, or markdown.")


class WeatherHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def send_body(self, status: int, body: bytes, content_type: str, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store" if content_type.startswith("application/json") else "public, max-age=60")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, Any] | list[Any]) -> None:
        self.send_body(status, json.dumps(payload).encode("utf-8"), "application/json; charset=utf-8")

    def send_error_payload(self, error: AppError) -> None:
        self.send_json(error.status, {"error": {"code": error.code, "message": error.message}})

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1_000_000:
            raise AppError(413, "payload_too_large", "Request body is too large.")
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise AppError(400, "invalid_json", "Request body must be valid JSON.") from exc

    def route_id(self, path: str) -> int | None:
        match = re.fullmatch(r"/api/requests/(\d+)", path)
        return int(match.group(1)) if match else None

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/health":
                self.send_json(200, {"ok": True, "database": str(DB_PATH.name), "source": APP_SOURCE})
                return
            if parsed.path == "/api/requests":
                self.send_json(200, {"records": list_records()})
                return
            record_id = self.route_id(parsed.path)
            if record_id is not None:
                self.send_json(200, {"record": get_record(record_id)})
                return
            if parsed.path == "/api/export":
                fmt = (parse_qs(parsed.query).get("format") or ["json"])[0].lower()
                body, content_type, filename = export_payload(fmt)
                self.send_body(
                    200,
                    body,
                    content_type,
                    {"Content-Disposition": f'attachment; filename="{filename}"'},
                )
                return
            self.serve_static(parsed.path)
        except AppError as error:
            self.send_error_payload(error)
        except Exception as exc:
            print(f"Unhandled error: {exc}")
            self.send_error_payload(AppError(500, "internal_error", "Something went wrong on the server."))

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            if parsed.path != "/api/requests":
                raise AppError(404, "not_found", "Route was not found.")
            self.send_json(201, {"record": create_record(self.read_json_body())})
        except AppError as error:
            self.send_error_payload(error)
        except Exception as exc:
            print(f"Unhandled error: {exc}")
            self.send_error_payload(AppError(500, "internal_error", "Something went wrong on the server."))

    def do_PUT(self) -> None:
        try:
            record_id = self.route_id(urlparse(self.path).path)
            if record_id is None:
                raise AppError(404, "not_found", "Route was not found.")
            self.send_json(200, {"record": update_record(record_id, self.read_json_body())})
        except AppError as error:
            self.send_error_payload(error)
        except Exception as exc:
            print(f"Unhandled error: {exc}")
            self.send_error_payload(AppError(500, "internal_error", "Something went wrong on the server."))

    def do_DELETE(self) -> None:
        try:
            record_id = self.route_id(urlparse(self.path).path)
            if record_id is None:
                raise AppError(404, "not_found", "Route was not found.")
            self.send_json(200, delete_record(record_id))
        except AppError as error:
            self.send_error_payload(error)
        except Exception as exc:
            print(f"Unhandled error: {exc}")
            self.send_error_payload(AppError(500, "internal_error", "Something went wrong on the server."))

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"/", ""} else path.lstrip("/")
        target = (PUBLIC_DIR / relative).resolve()
        public_root = PUBLIC_DIR.resolve()
        if not target.is_file() or not target.is_relative_to(public_root):
            raise AppError(404, "not_found", "File was not found.")
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_body(200, target.read_bytes(), content_type)


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), WeatherHandler)
    print(f"WeatherWise running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
