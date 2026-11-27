"""Render a GitHub contribution calendar as an isometric SVG."""
import argparse
from calendar import month_abbr
import json
import math
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.etree.ElementTree import Element, SubElement, tostring

QUERY = """
query CommitCity($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""
# Background, text, empty tile, roof, and two visible wall colors.
THEMES = {
    "midnight": ("#0b1220", "#e2e8f0", "#202f46", "#5eead4", "#168c87", "#10585f"),
    "daylight": ("#f4f8fc", "#172b46", "#dbe6f1", "#3794fc", "#2464bb", "#194d92"),
    "sunset": ("#211327", "#ffe8dc", "#432640", "#ffae83", "#bd5476", "#853e67"),
}
TILE = 0.82
GROUND_ANGLE = math.radians(23)


@dataclass(frozen=True)
class Day:
    date: date
    count: int


def fetch(login, token):
    request = Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "CommitCity"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise ValueError(f"GitHub returned HTTP {exc.code}. Check token access and rate limits.") from None
    except (URLError, TimeoutError):
        raise ValueError("Could not reach GitHub GraphQL.") from None


def parse_calendar(payload):
    if isinstance(payload, dict) and payload.get("errors"):
        raise ValueError("GitHub GraphQL rejected the query. Check the login and token access.")
    try:
        user = payload["data"]["user"]
        if user is None:
            raise ValueError("GitHub user was not found.")
        weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
        days = []
        for week in weeks:
            for entry in week["contributionDays"]:
                count = entry["contributionCount"]
                if type(count) is not int or count < 0:
                    raise ValueError("Contribution counts must be nonnegative integers.")
                days.append(Day(date.fromisoformat(entry["date"]), count))
    except (KeyError, TypeError):
        raise ValueError("Expected a GitHub GraphQL contribution calendar.") from None
    if not days or len({day.date for day in days}) != len(days):
        raise ValueError("The calendar must contain unique contribution dates.")
    return sorted(days, key=lambda day: day.date)


def project(x, y, height=0):
    return ((x - y) * 12, (x + y) * 12 * math.tan(GROUND_ANGLE) - height)


def faces(x, y, height):
    footprint = [(x, y), (x + TILE, y), (x + TILE, y + TILE), (x, y + TILE)]
    base = [project(*corner) for corner in footprint]
    roof = [project(*corner, height) for corner in footprint]
    if height == 0:
        return [roof]
    return [[base[1], base[2], roof[2], roof[1]],
            [base[2], base[3], roof[3], roof[2]], roof]


def render(days, theme="midnight"):
    background, ink, empty, roof, right, left = THEMES[theme]
    earliest = min(day.date for day in days)
    sunday = earliest - timedelta(days=(earliest.weekday() + 1) % 7)
    positions = [(day, *divmod((day.date - sunday).days, 7)) for day in days]
    positions.sort(key=lambda item: (item[1] + item[2], item[1]))
    peak = max(day.count for day in days)
    buildings = []
    for day, x, y in positions:
        height = 5 + 85 * math.log1p(day.count) / math.log1p(peak) if day.count else 0
        buildings.append((day, faces(x, y, height)))

    week_end = max(x for _, x, _ in positions) + 1.35
    weekday_end = 7.35
    corner = project(week_end, weekday_end)
    points = [point for _, building in buildings for face in building for point in face]
    points.extend([project(0, weekday_end), project(week_end, 0), corner])
    min_x, max_x = min(x for x, _ in points), max(x for x, _ in points)
    min_y, max_y = min(y for _, y in points), max(y for _, y in points)
    width = max(420, math.ceil(max_x - min_x + 88))
    height = math.ceil(max_y - min_y + 104)
    svg = Element("svg", xmlns="http://www.w3.org/2000/svg",
                  viewBox=f"0 0 {width} {height}", width=str(width), height=str(height),
                  role="img", attrib={"aria-labelledby": "title description"})
    SubElement(svg, "title", id="title").text = "CommitCity contribution skyline"
    total = sum(day.count for day in days)
    latest = max(day.date for day in days)
    caption = f"{earliest:%b %Y} – {latest:%b %Y}  ·  {total:,} contributions"
    SubElement(svg, "desc", id="description").text = (
        f"{caption}. Each tile is a day. Taller buildings represent more contributions."
    )
    SubElement(svg, "rect", width=str(width), height=str(height), rx="18", fill=background)
    header = SubElement(svg, "g", fill=ink, attrib={"font-family": "system-ui, sans-serif"})
    SubElement(header, "text", x="24", y="31",
               attrib={"font-size": "22", "font-weight": "700"}).text = "CommitCity"
    SubElement(header, "text", x="24", y="52",
               attrib={"font-size": "12"}).text = caption
    offset_x = (width - (max_x - min_x)) / 2 - min_x
    city = SubElement(svg, "g", transform=f"translate({offset_x:.2f} {70 - min_y:.2f})")
    for day, building in buildings:
        tile = SubElement(city, "g")
        SubElement(tile, "title").text = f"{day.date} · {day.count} contributions"
        colors = (right, left, roof) if day.count else (empty,)
        for face, color in zip(building, colors):
            points_attr = " ".join(f"{x:.2f},{y:.2f}" for x, y in face)
            SubElement(tile, "polygon", points=points_attr, fill=color)
    labels = SubElement(svg, "g", fill=ink, transform=city.get("transform"), attrib={
        "font-family": "system-ui, sans-serif", "font-size": "11",
        "text-anchor": "middle", "dominant-baseline": "central",
    })
    months = {}
    for day, week, _ in sorted(positions, key=lambda item: item[0].date):
        months.setdefault((day.date.year, day.date.month), week)
    month_starts = list(months.items())
    # A partial first month can share its first column with the next month.
    if len(month_starts) > 1 and month_starts[1][1] - month_starts[0][1] < 3:
        month_starts.pop(0)
    angle = math.degrees(GROUND_ANGLE)
    for (_, month), week in month_starts:
        x, y = project(week + TILE / 2, weekday_end)
        SubElement(labels, "text", transform=(
            f"translate({x:.2f} {y + 12:.2f}) rotate({angle:.2f})"
        )).text = month_abbr[month]
    for weekday, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        x, y = project(week_end, weekday + TILE / 2)
        SubElement(labels, "text", transform=(
            f"translate({x + 12:.2f} {y + 8:.2f}) rotate({-angle:.2f})"
        )).text = label
    return tostring(svg, encoding="unicode") + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--fixture", type=Path, help="Read a saved GraphQL response")
    source.add_argument("--user", help="Fetch the calendar for this GitHub login")
    parser.add_argument("--theme", choices=THEMES, default="midnight")
    parser.add_argument("--output", type=Path, default=Path("assets/commitcity.svg"))
    args = parser.parse_args(argv)
    try:
        if args.fixture:
            payload = json.loads(args.fixture.read_text(encoding="utf-8"))
        else:
            token = os.environ.get("GITHUB_TOKEN")
            if not token:
                parser.error("Set GITHUB_TOKEN to fetch live GitHub data.")
            payload = fetch(args.user, token)
        svg = render(parse_calendar(payload), args.theme)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(svg, encoding="utf-8")
    except (ValueError, OSError) as exc:
        parser.exit(1, f"commitcity: {exc}\n")


if __name__ == "__main__":
    main()
