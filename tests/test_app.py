import datetime as dt
import unittest
from unittest.mock import patch

from app import AppError, build_map_urls, describe_weather, parse_coordinate_query, validate_date_range


class WeatherWiseValidationTests(unittest.TestCase):
    def test_parse_coordinate_query_accepts_lat_lon(self):
        self.assertEqual(parse_coordinate_query("29.7604, -95.3698"), (29.7604, -95.3698))

    def test_parse_coordinate_query_rejects_plain_location(self):
        self.assertIsNone(parse_coordinate_query("Houston, TX"))

    @patch("app.today")
    def test_validate_date_range_allows_sixteen_days(self, fake_today):
        fake_today.return_value = dt.date(2026, 6, 16)
        start, end = validate_date_range("2026-06-16", "2026-07-01")
        self.assertEqual(start, dt.date(2026, 6, 16))
        self.assertEqual(end, dt.date(2026, 7, 1))

    @patch("app.today")
    def test_validate_date_range_rejects_too_long(self, fake_today):
        fake_today.return_value = dt.date(2026, 6, 16)
        with self.assertRaises(AppError):
            validate_date_range("2026-06-16", "2026-07-02")

    def test_describe_weather_maps_known_code(self):
        self.assertEqual(describe_weather(95)["label"], "Thunderstorm")

    def test_build_map_urls_returns_embed_and_external_urls(self):
        urls = build_map_urls(29.7604, -95.3698)
        self.assertIn("openstreetmap.org", urls["embedUrl"])
        self.assertIn("mlat=29.760400", urls["externalUrl"])


if __name__ == "__main__":
    unittest.main()
