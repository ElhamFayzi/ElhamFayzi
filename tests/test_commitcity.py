import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

from commitcity import Day, THEMES, faces, main, parse_calendar, project, render

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic.json"
NS = {"svg": "http://www.w3.org/2000/svg"}


class CommitCityTests(unittest.TestCase):
    def test_fixture_cli_and_theme(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "city.svg"
            main(["--fixture", str(FIXTURE), "--theme", "sunset", "--output", str(output)])
            svg = ElementTree.parse(output)
            self.assertEqual(svg.find("svg:rect", NS).get("fill"), THEMES["sunset"][0])
            self.assertEqual(len(svg.findall("./svg:g/svg:g", NS)), 365)
            expected = render(parse_calendar(json.loads(FIXTURE.read_text())), "sunset")
            self.assertEqual(output.read_text(), expected)

    def test_projection_and_faces(self):
        self.assertLess(project(0, 1)[0], 0)
        self.assertGreater(project(1, 0)[0], 0)
        self.assertEqual(project(2, 3)[1] - project(2, 3, 10)[1], 10)
        self.assertEqual(len(faces(0, 0, 1)), 3)
        self.assertEqual(len(faces(0, 0, 0)), 1)

    def test_depth_order_with_partial_weeks_and_missing_days(self):
        days = [Day(date(2025, 1, 1), 4), Day(date(2025, 1, 5), 0)]
        svg = ElementTree.fromstring(render(days))
        tiles = svg.findall("./svg:g/svg:g/svg:title", NS)
        self.assertEqual([tile.text[:10] for tile in tiles], ["2025-01-05", "2025-01-01"])

    def test_all_zero_calendar(self):
        svg = ElementTree.fromstring(render([Day(date(2025, 1, 1), 0)]))
        self.assertEqual(len(svg.findall(".//svg:polygon", NS)), 1)

    def test_invalid_payloads(self):
        for payload in ({}, {"errors": [{"message": "Forbidden"}]}, {"data": {"user": None}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                parse_calendar(payload)
