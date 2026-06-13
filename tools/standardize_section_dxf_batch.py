#!/usr/bin/env python3
"""Batch standardize section DXF files without third-party dependencies.

The source files for this task contain LINE entities only.  The script keeps the
parser intentionally small but strict: it scans the ENTITIES section, extracts
LINE geometry, aligns each section-cut file to its matching visible-line file,
cleans the merged geometry, adds lightweight editable construction geometry, and
writes a new ASCII DXF plus a PNG preview and Markdown reports.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from collections.abc import Iterable
from math import atan2, floor, hypot, pi
from pathlib import Path
import re
import struct
import sys
import zlib


ROOT = Path.cwd()
OUT_DIR = ROOT / "out"
REQUIRED_LAYERS = [
    "A-CUT-SECTION",
    "A-VISIBLE-PROJECTION",
    "A-STRUCTURE-FIX",
    "A-HATCH-MATERIAL",
    "A-CENTER-HIDDEN",
    "A-ANNO-NOTE",
]

VISIBLE_KEYWORDS = ("看线", "visible", "projection", "projected", "viewline", "view-line")

LAYER_STYLE = {
    "A-CUT-SECTION": {"color": 7, "ltype": "CONTINUOUS", "weight": 70},
    "A-VISIBLE-PROJECTION": {"color": 8, "ltype": "CONTINUOUS", "weight": 13},
    "A-STRUCTURE-FIX": {"color": 1, "ltype": "CONTINUOUS", "weight": 25},
    "A-HATCH-MATERIAL": {"color": 3, "ltype": "CONTINUOUS", "weight": 9},
    "A-CENTER-HIDDEN": {"color": 5, "ltype": "CENTER", "weight": 9},
    "A-ANNO-NOTE": {"color": 6, "ltype": "CONTINUOUS", "weight": 13},
}


@dataclass
class LineEntity:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str
    source: str = ""
    ltype: str | None = None

    @property
    def length(self) -> float:
        return hypot(self.x2 - self.x1, self.y2 - self.y1)

    @property
    def midpoint(self) -> tuple[float, float]:
        return ((self.x1 + self.x2) / 2.0, (self.y1 + self.y2) / 2.0)

    def shifted(self, dx: float, dy: float, layer: str | None = None) -> "LineEntity":
        return LineEntity(
            self.x1 + dx,
            self.y1 + dy,
            self.x2 + dx,
            self.y2 + dy,
            layer or self.layer,
            self.source,
            self.ltype,
        )


@dataclass
class TextEntity:
    x: float
    y: float
    text: str
    height: float
    layer: str = "A-ANNO-NOTE"


@dataclass
class CleanStats:
    source_total: int = 0
    zero_length: int = 0
    short_lines: int = 0
    isolated_fragments: int = 0
    duplicates: int = 0
    removed_total: int = 0


@dataclass
class GroupResult:
    group: str
    cut_file: Path
    visible_file: Path
    source_cut_count: int
    source_visible_count: int
    cut_bbox_before: tuple[float, float, float, float]
    visible_bbox: tuple[float, float, float, float]
    dx: float
    dy: float
    offset_detected: bool
    align_score: float
    clean_stats: CleanStats
    layer_counts: dict[str, int]
    zero_layer_entities: int
    dxf_path: Path
    png_path: Path
    report_path: Path
    warnings: list[str] = field(default_factory=list)


def dxf_pairs(path: Path):
    lines = path.read_text(errors="ignore").splitlines()
    for i in range(0, len(lines) - 1, 2):
        yield lines[i].strip(), lines[i + 1].rstrip("\n")


def parse_dxf_lines(path: Path) -> tuple[list[LineEntity], Counter]:
    entities: list[LineEntity] = []
    source_layers: Counter = Counter()
    in_entities = False
    etype: str | None = None
    pairs: list[tuple[str, str]] = []

    def flush() -> None:
        nonlocal pairs, etype
        if etype != "LINE":
            return
        values: dict[str, str] = {}
        layer = "0"
        ltype: str | None = None
        for code, value in pairs:
            if code in {"10", "20", "11", "21"}:
                values[code] = value
            elif code == "8":
                layer = value or "0"
            elif code == "6":
                ltype = value
        try:
            line = LineEntity(
                float(values["10"]),
                float(values["20"]),
                float(values["11"]),
                float(values["21"]),
                layer,
                source=path.name,
                ltype=ltype,
            )
        except (KeyError, ValueError):
            return
        entities.append(line)
        source_layers[layer] += 1

    for code, value in dxf_pairs(path):
        if code == "2" and value == "ENTITIES":
            in_entities = True
            continue
        if not in_entities:
            continue
        if code == "0":
            flush()
            if value == "ENDSEC":
                break
            etype = value
            pairs = []
        else:
            pairs.append((code, value))
    return entities, source_layers


def bbox(lines: list[LineEntity]) -> tuple[float, float, float, float]:
    if not lines:
        return (0.0, 0.0, 0.0, 0.0)
    xs = [coord for line in lines for coord in (line.x1, line.x2)]
    ys = [coord for line in lines for coord in (line.y1, line.y2)]
    return (min(xs), min(ys), max(xs), max(ys))


def line_angle(line: LineEntity) -> float:
    angle = atan2(line.y2 - line.y1, line.x2 - line.x1)
    if angle < 0:
        angle += pi
    if angle >= pi:
        angle -= pi
    return angle


def median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    if n % 2:
        return ordered[n // 2]
    return (ordered[n // 2 - 1] + ordered[n // 2]) / 2.0


def offset_candidates(cut: list[LineEntity], visible: list[LineEntity]) -> list[tuple[float, float]]:
    cb = bbox(cut)
    vb = bbox(visible)
    candidates = [
        (vb[0] - cb[0], vb[1] - cb[1]),
        (vb[2] - cb[2], vb[3] - cb[3]),
        (((vb[0] + vb[2]) - (cb[0] + cb[2])) / 2.0, ((vb[1] + vb[3]) - (cb[1] + cb[3])) / 2.0),
        (0.0, 0.0),
    ]

    cut_long = [
        (line.length, line_angle(line), line.midpoint, line)
        for line in cut
        if line.length > 150
    ]
    visible_long = [
        (line.length, line_angle(line), line.midpoint, line)
        for line in visible
        if line.length > 150
    ]
    cut_long = sorted(cut_long, key=lambda item: item[0], reverse=True)[:260]
    visible_long = sorted(visible_long, key=lambda item: item[0], reverse=True)[:550]

    hist: Counter = Counter()
    for clen, cang, cmid, _cline in cut_long:
        for vlen, vang, vmid, _vline in visible_long:
            if abs(clen - vlen) > max(20.0, 0.08 * max(clen, vlen)):
                continue
            da = abs(cang - vang)
            da = min(da, pi - da)
            if da > 0.035:
                continue
            dx = vmid[0] - cmid[0]
            dy = vmid[1] - cmid[1]
            hist[(round(dx / 10.0) * 10.0, round(dy / 10.0) * 10.0)] += 1

    candidates.extend([candidate for candidate, _count in hist.most_common(40)])
    deduped: list[tuple[float, float]] = []
    seen: set[tuple[int, int]] = set()
    for dx, dy in candidates:
        key = (round(dx), round(dy))
        if key not in seen:
            seen.add(key)
            deduped.append((dx, dy))
    return deduped


def sample_points(lines: list[LineEntity], max_lines: int = 700) -> list[tuple[float, float]]:
    ranked = sorted(
        [(line.length, line) for line in lines if line.length > 30.0],
        key=lambda item: item[0],
        reverse=True,
    )[:max_lines]
    points: list[tuple[float, float]] = []
    for length, line in ranked:
        n = max(2, min(10, int(length / 300.0) + 1))
        for i in range(n + 1):
            t = i / n
            points.append((line.x1 + (line.x2 - line.x1) * t, line.y1 + (line.y2 - line.y1) * t))
    return points


def occupancy(lines: list[LineEntity], grid: float = 20.0) -> set[tuple[int, int]]:
    occupied: set[tuple[int, int]] = set()
    for line in lines:
        length = line.length
        if length < 10:
            continue
        n = max(1, int(length / (grid / 2.0)))
        for i in range(n + 1):
            t = i / n
            x = line.x1 + (line.x2 - line.x1) * t
            y = line.y1 + (line.y2 - line.y1) * t
            gx = round(x / grid)
            gy = round(y / grid)
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    occupied.add((gx + ox, gy + oy))
    return occupied


def score_offset(cut: list[LineEntity], visible: list[LineEntity], candidate: tuple[float, float]) -> float:
    points = sample_points(cut)
    if not points:
        return 0.0
    occ = occupancy(visible)
    dx, dy = candidate
    hits = 0
    for x, y in points:
        if (round((x + dx) / 20.0), round((y + dy) / 20.0)) in occ:
            hits += 1
    return hits / len(points)


def refine_offset(
    cut: list[LineEntity],
    visible: list[LineEntity],
    rough: tuple[float, float],
) -> tuple[float, float]:
    buckets: defaultdict[tuple[int, int], list[tuple[float, float, LineEntity]]] = defaultdict(list)
    for line in visible:
        length = line.length
        if length < 80:
            continue
        buckets[(round(length / 5.0), round(line_angle(line) / 0.005))].append((length, line_angle(line), line))

    matches: list[tuple[float, float, float]] = []
    rdx, rdy = rough
    for cline in cut:
        length = cline.length
        if length < 80:
            continue
        cang = line_angle(cline)
        length_key = round(length / 5.0)
        angle_key = round(cang / 0.005)
        for lk in range(length_key - 2, length_key + 3):
            for ak in range(angle_key - 2, angle_key + 3):
                for vlen, vang, vline in buckets.get((lk, ak), []):
                    if abs(vlen - length) > 10.0:
                        continue
                    da = abs(cang - vang)
                    da = min(da, pi - da)
                    if da > 0.02:
                        continue
                    endpoint_pairs = [
                        ((vline.x1 - cline.x1, vline.y1 - cline.y1), (vline.x2 - cline.x2, vline.y2 - cline.y2)),
                        ((vline.x2 - cline.x1, vline.y2 - cline.y1), (vline.x1 - cline.x2, vline.y1 - cline.y2)),
                    ]
                    for d1, d2 in endpoint_pairs:
                        dx = (d1[0] + d2[0]) / 2.0
                        dy = (d1[1] + d2[1]) / 2.0
                        if hypot(d1[0] - d2[0], d1[1] - d2[1]) < 5.0 and hypot(dx - rdx, dy - rdy) < 80.0:
                            matches.append((dx, dy, length))

    if not matches:
        return rough

    rounded = Counter((round(dx, 3), round(dy, 3)) for dx, dy, _length in matches)
    (mode_dx, mode_dy), mode_count = rounded.most_common(1)[0]
    if mode_count >= 3:
        return (mode_dx, mode_dy)
    return (median([dx for dx, _dy, _length in matches]), median([dy for _dx, dy, _length in matches]))


def detect_offset(cut: list[LineEntity], visible: list[LineEntity]) -> tuple[float, float, float]:
    candidates = offset_candidates(cut, visible)
    scored = [(score_offset(cut, visible, candidate), candidate) for candidate in candidates]
    scored.sort(reverse=True)
    rough = scored[0][1] if scored else (0.0, 0.0)
    refined = refine_offset(cut, visible, rough)
    refined_score = score_offset(cut, visible, refined)
    if scored and scored[0][0] > refined_score + 0.05:
        return scored[0][1][0], scored[0][1][1], scored[0][0]
    return refined[0], refined[1], refined_score


def canonical_key(line: LineEntity, quantum: float = 0.5) -> tuple[tuple[int, int], tuple[int, int]]:
    p1 = (round(line.x1 / quantum), round(line.y1 / quantum))
    p2 = (round(line.x2 / quantum), round(line.y2 / quantum))
    return (p1, p2) if p1 <= p2 else (p2, p1)


def proximity_index(lines: list[LineEntity], cell: float = 120.0) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for line in lines:
        for x, y in ((line.x1, line.y1), (line.x2, line.y2), line.midpoint):
            gx = floor(x / cell)
            gy = floor(y / cell)
            for ox in (-1, 0, 1):
                for oy in (-1, 0, 1):
                    cells.add((gx + ox, gy + oy))
    return cells


def clean_lines(lines: list[LineEntity]) -> tuple[list[LineEntity], CleanStats]:
    stats = CleanStats(source_total=len(lines))
    first_pass: list[LineEntity] = []
    for line in lines:
        length = line.length
        if length < 1e-6:
            stats.zero_length += 1
            continue
        if length < 4.0:
            stats.short_lines += 1
            continue
        first_pass.append(line)

    nearby = proximity_index([line for line in first_pass if line.length >= 20.0])
    second_pass: list[LineEntity] = []
    for line in first_pass:
        if line.length >= 20.0:
            second_pass.append(line)
            continue
        mx, my = line.midpoint
        if (floor(mx / 120.0), floor(my / 120.0)) in nearby:
            second_pass.append(line)
        else:
            stats.isolated_fragments += 1

    priority = {
        "A-CUT-SECTION": 0,
        "A-STRUCTURE-FIX": 1,
        "A-VISIBLE-PROJECTION": 2,
        "A-HATCH-MATERIAL": 3,
        "A-CENTER-HIDDEN": 4,
        "A-ANNO-NOTE": 5,
    }
    unique: dict[tuple[tuple[int, int], tuple[int, int]], LineEntity] = {}
    for line in second_pass:
        key = canonical_key(line)
        existing = unique.get(key)
        if existing is None:
            unique[key] = line
            continue
        stats.duplicates += 1
        if priority.get(line.layer, 99) < priority.get(existing.layer, 99):
            unique[key] = line

    cleaned = list(unique.values())
    stats.removed_total = stats.zero_length + stats.short_lines + stats.isolated_fragments + stats.duplicates
    return cleaned, stats


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def add_line(
    lines: list[LineEntity],
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    layer: str,
    source: str = "generated",
    ltype: str | None = None,
) -> None:
    if hypot(x2 - x1, y2 - y1) >= 1.0:
        lines.append(LineEntity(x1, y1, x2, y2, layer, source=source, ltype=ltype))


def add_rect(lines: list[LineEntity], x1: float, y1: float, x2: float, y2: float, layer: str, source: str = "generated") -> None:
    add_line(lines, x1, y1, x2, y1, layer, source)
    add_line(lines, x2, y1, x2, y2, layer, source)
    add_line(lines, x2, y2, x1, y2, layer, source)
    add_line(lines, x1, y2, x1, y1, layer, source)


def horizontal_clusters(lines: list[LineEntity], b: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = b
    height = maxy - miny
    width = maxx - minx
    clusters: defaultdict[int, float] = defaultdict(float)
    for line in lines:
        length = line.length
        if length < max(250.0, width * 0.08):
            continue
        if abs(line.y2 - line.y1) > max(5.0, length * 0.02):
            continue
        y = (line.y1 + line.y2) / 2.0
        if miny + 0.08 * height <= y <= miny + 0.58 * height:
            clusters[round(y / 20.0)] += length
    return sorted(((key * 20.0, weight) for key, weight in clusters.items()), key=lambda item: -item[1])


def choose_platform(lines: list[LineEntity], b: tuple[float, float, float, float]) -> tuple[float, float, float]:
    minx, miny, maxx, maxy = b
    width = maxx - minx
    clusters = horizontal_clusters(lines, b)
    platform_y = clusters[0][0] if clusters else miny + 0.28 * (maxy - miny)
    xs: list[float] = []
    for line in lines:
        if line.length < 180.0:
            continue
        if abs(line.y2 - line.y1) <= max(5.0, line.length * 0.02) and abs(((line.y1 + line.y2) / 2.0) - platform_y) < 140.0:
            xs.extend([line.x1, line.x2])
    if len(xs) < 2:
        return minx + 0.08 * width, maxx - 0.08 * width, platform_y
    return max(minx, min(xs)), min(maxx, max(xs)), platform_y


def vertical_support_positions(lines: list[LineEntity], b: tuple[float, float, float, float], platform_x1: float, platform_x2: float) -> list[float]:
    minx, miny, maxx, maxy = b
    height = maxy - miny
    clusters: defaultdict[int, float] = defaultdict(float)
    for line in lines:
        length = line.length
        if length < height * 0.16:
            continue
        if abs(line.x2 - line.x1) > max(5.0, length * 0.02):
            continue
        x = (line.x1 + line.x2) / 2.0
        if platform_x1 - 200.0 <= x <= platform_x2 + 200.0:
            clusters[round(x / 20.0)] += length
    ranked = sorted(((key * 20.0, weight) for key, weight in clusters.items()), key=lambda item: -item[1])
    selected: list[float] = []
    min_spacing = max(450.0, (platform_x2 - platform_x1) / 14.0)
    for x, _weight in ranked:
        if all(abs(x - existing) >= min_spacing for existing in selected):
            selected.append(x)
        if len(selected) >= 10:
            break
    return sorted(selected)


def roof_profile(lines: list[LineEntity], b: tuple[float, float, float, float], bins: int = 42) -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = b
    width = maxx - minx
    height = maxy - miny
    bucket_points: list[list[float]] = [[] for _ in range(bins)]
    upper_cutoff = miny + 0.52 * height
    for line in lines:
        if line.length < 80.0:
            samples = 2
        else:
            samples = max(2, min(14, int(line.length / max(width / bins, 80.0)) + 1))
        for i in range(samples + 1):
            t = i / samples
            x = line.x1 + (line.x2 - line.x1) * t
            y = line.y1 + (line.y2 - line.y1) * t
            if y < upper_cutoff:
                continue
            idx = int(clamp((x - minx) / max(width, 1.0) * (bins - 1), 0, bins - 1))
            bucket_points[idx].append(y)

    profile: list[tuple[float, float]] = []
    last_y = maxy
    for idx, ys in enumerate(bucket_points):
        x = minx + width * idx / (bins - 1)
        if ys:
            last_y = max(ys)
        profile.append((x, last_y))

    # Fill leading empty buckets from the first populated value.
    populated = [(idx, max(ys)) for idx, ys in enumerate(bucket_points) if ys]
    if populated:
        first_idx, first_y = populated[0]
        for idx in range(first_idx):
            x = minx + width * idx / (bins - 1)
            profile[idx] = (x, first_y)
    return profile


def roof_x_range(lines: list[LineEntity], b: tuple[float, float, float, float]) -> tuple[float, float]:
    minx, miny, maxx, maxy = b
    width = maxx - minx
    height = maxy - miny
    upper_cutoff = miny + 0.52 * height
    xs: list[float] = []
    for line in lines:
        samples = max(2, min(14, int(line.length / max(width / 42.0, 80.0)) + 1))
        for i in range(samples + 1):
            t = i / samples
            x = line.x1 + (line.x2 - line.x1) * t
            y = line.y1 + (line.y2 - line.y1) * t
            if y >= upper_cutoff:
                xs.append(x)
    if len(xs) < 4:
        return minx + 0.07 * width, maxx - 0.05 * width
    return max(minx, min(xs)), min(maxx, max(xs))


def interp_profile(profile: list[tuple[float, float]], x: float) -> float:
    if not profile:
        return 0.0
    if x <= profile[0][0]:
        return profile[0][1]
    for (x1, y1), (x2, y2) in zip(profile, profile[1:]):
        if x1 <= x <= x2:
            t = (x - x1) / max(x2 - x1, 1e-9)
            return y1 + (y2 - y1) * t
    return profile[-1][1]


def add_roof_purlins(lines: list[LineEntity], b: tuple[float, float, float, float]) -> None:
    minx, miny, maxx, maxy = b
    width = maxx - minx
    height = maxy - miny
    profile = roof_profile(lines, b)
    roof_min_x, roof_max_x = roof_x_range(lines, b)
    roof_width = max(roof_max_x - roof_min_x, width * 0.25)
    start = roof_min_x + 0.04 * roof_width
    end = roof_max_x - 0.04 * roof_width
    if end <= start:
        start = minx + 0.07 * width
        end = maxx - 0.05 * width
    segments = 26
    for offset in (clamp(height * 0.03, 110.0, 180.0), clamp(height * 0.055, 210.0, 330.0)):
        prev: tuple[float, float] | None = None
        for i in range(segments + 1):
            x = start + (end - start) * i / segments
            y = interp_profile(profile, x) - offset
            if prev:
                add_line(lines, prev[0], prev[1], x, y, "A-STRUCTURE-FIX")
            prev = (x, y)

    panel_spacing = max(650.0, roof_width / 18.0)
    x = start
    while x <= end:
        y = interp_profile(profile, x)
        add_line(lines, x - 80.0, y - 130.0, x + 80.0, y - 130.0, "A-STRUCTURE-FIX")
        add_line(lines, x, y - 75.0, x, y - 240.0, "A-STRUCTURE-FIX")
        x += panel_spacing

    hatch_spacing = max(420.0, roof_width / 34.0)
    x = start
    while x <= end:
        y = interp_profile(profile, x)
        add_line(lines, x - 120.0, y - 45.0, x + 120.0, y - 70.0, "A-HATCH-MATERIAL")
        x += hatch_spacing


def add_platform_and_foundation(
    lines: list[LineEntity],
    b: tuple[float, float, float, float],
    platform_x1: float,
    platform_x2: float,
    platform_y: float,
    supports: list[float],
) -> None:
    minx, miny, _maxx, maxy = b
    height = maxy - miny
    width = platform_x2 - platform_x1
    thickness = clamp(height * 0.026, 110.0, 170.0)
    steel_drop = clamp(height * 0.018, 70.0, 130.0)
    bottom_y = platform_y - thickness
    beam_y = bottom_y - steel_drop

    add_line(lines, platform_x1, platform_y, platform_x2, platform_y, "A-STRUCTURE-FIX")
    add_line(lines, platform_x1, bottom_y, platform_x2, bottom_y, "A-STRUCTURE-FIX")
    add_line(lines, platform_x1, beam_y, platform_x2, beam_y, "A-STRUCTURE-FIX")
    add_line(lines, platform_x1, platform_y, platform_x1, bottom_y, "A-STRUCTURE-FIX")
    add_line(lines, platform_x2, platform_y, platform_x2, bottom_y, "A-STRUCTURE-FIX")

    joist_spacing = max(420.0, width / 30.0)
    x = platform_x1
    while x <= platform_x2:
        add_line(lines, x, platform_y, x, bottom_y, "A-STRUCTURE-FIX")
        add_line(lines, x - 130.0, platform_y - 24.0, x + 130.0, platform_y - 24.0, "A-HATCH-MATERIAL")
        x += joist_spacing

    pile_bottom = miny + 0.10 * height
    for x in supports:
        if platform_x1 - 50.0 <= x <= platform_x2 + 50.0:
            add_line(lines, x, beam_y, x, pile_bottom, "A-STRUCTURE-FIX")
            add_line(lines, x - 85.0, pile_bottom, x + 85.0, pile_bottom, "A-STRUCTURE-FIX")
            y = beam_y - 80.0
            while y > pile_bottom + 80.0:
                add_line(lines, x - 38.0, y, x + 38.0, y - 18.0, "A-HATCH-MATERIAL")
                y -= 105.0


def add_wall_and_railing(
    lines: list[LineEntity],
    b: tuple[float, float, float, float],
    platform_x1: float,
    platform_x2: float,
    platform_y: float,
) -> None:
    minx, miny, maxx, maxy = b
    width = maxx - minx
    height = maxy - miny
    profile = roof_profile(lines, b)

    land_x = platform_x1 + 0.09 * (platform_x2 - platform_x1)
    wall_top = min(interp_profile(profile, land_x) - 260.0, maxy - 0.12 * height)
    wall_bottom = platform_y + 70.0
    if wall_top > wall_bottom + 600.0:
        add_rect(lines, land_x - 130.0, wall_bottom, land_x + 130.0, wall_top, "A-STRUCTURE-FIX")
        add_line(lines, land_x - 45.0, wall_bottom, land_x - 45.0, wall_top, "A-STRUCTURE-FIX")
        add_line(lines, land_x + 45.0, wall_bottom, land_x + 45.0, wall_top, "A-STRUCTURE-FIX")
        y = wall_bottom + 180.0
        while y < wall_top - 120.0:
            add_line(lines, land_x - 115.0, y, land_x + 115.0, y + 48.0, "A-HATCH-MATERIAL")
            y += 220.0

    rail_x1 = platform_x2 - 0.18 * (platform_x2 - platform_x1)
    rail_x2 = min(platform_x2 - 120.0, rail_x1 + 0.16 * width)
    rail_bottom = platform_y + 40.0
    rail_top = platform_y + clamp(height * 0.18, 850.0, 1150.0)
    if rail_x2 > rail_x1 + 300.0:
        add_line(lines, rail_x1, rail_bottom, rail_x2, rail_bottom, "A-VISIBLE-PROJECTION")
        add_line(lines, rail_x1, rail_top, rail_x2, rail_top, "A-VISIBLE-PROJECTION")
        add_line(lines, rail_x1, rail_bottom, rail_x1, rail_top, "A-VISIBLE-PROJECTION")
        add_line(lines, rail_x2, rail_bottom, rail_x2, rail_top, "A-VISIBLE-PROJECTION")
        pane = rail_x1 + max(360.0, (rail_x2 - rail_x1) / 4.0)
        while pane < rail_x2 - 120.0:
            add_line(lines, pane, rail_bottom, pane, rail_top, "A-VISIBLE-PROJECTION")
            pane += max(360.0, (rail_x2 - rail_x1) / 4.0)
        x = rail_x1 + 120.0
        while x < rail_x2:
            add_line(lines, x, rail_bottom + 80.0, x + 160.0, rail_top - 80.0, "A-HATCH-MATERIAL")
            x += 420.0


def add_centerlines_and_notes(
    lines: list[LineEntity],
    texts: list[TextEntity],
    b: tuple[float, float, float, float],
    platform_y: float,
    supports: list[float],
) -> None:
    minx, miny, maxx, maxy = b
    height = maxy - miny
    profile = roof_profile(lines, b)
    for x in supports[:8]:
        top = interp_profile(profile, x) - 150.0
        add_line(lines, x, miny + 0.08 * height, x, top, "A-CENTER-HIDDEN", ltype="CENTER")

    note_x = minx
    note_y = maxy + 0.09 * height
    text_h = clamp(height * 0.018, 80.0, 130.0)
    notes = [
        "SECTION STANDARDIZED: cut, visible, fix, hatch, hidden, note layers",
        "Roof: light metal/PC panel with secondary purlins and plates",
        "Platform: treated wood/bamboo board over light steel frame",
        "Foundation: micro/helix steel piles with steel platform beams",
        "Land side: perforated acoustic panel + fiber + air cavity",
        "River side: glass/translucent guardrail interface",
    ]
    for i, note in enumerate(notes):
        texts.append(TextEntity(note_x, note_y - i * text_h * 1.35, note, text_h))

    level_y = platform_y
    add_line(lines, minx, level_y, minx + 450.0, level_y, "A-ANNO-NOTE")
    texts.append(TextEntity(minx + 500.0, level_y - text_h * 0.35, "LEVEL: platform reference", text_h * 0.85))


def add_supplemental_geometry(lines: list[LineEntity]) -> tuple[list[LineEntity], list[TextEntity]]:
    b = bbox(lines)
    platform_x1, platform_x2, platform_y = choose_platform(lines, b)
    supports = vertical_support_positions(lines, b, platform_x1, platform_x2)
    if len(supports) < 3:
        span = platform_x2 - platform_x1
        supports = [platform_x1 + span * ratio for ratio in (0.12, 0.32, 0.52, 0.72, 0.9)]

    generated = list(lines)
    texts: list[TextEntity] = []
    add_platform_and_foundation(generated, b, platform_x1, platform_x2, platform_y, supports)
    add_roof_purlins(generated, b)
    add_wall_and_railing(generated, b, platform_x1, platform_x2, platform_y)
    add_centerlines_and_notes(generated, texts, b, platform_y, supports)
    return generated, texts


def sort_group_ids(group_ids: Iterable[str]) -> list[str]:
    return sorted(group_ids, key=lambda item: (int(item) if item.isdigit() else item, item))


def scan_groups(root: Path) -> dict[str, tuple[Path, Path]]:
    dxf_files = sorted([p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".dxf"])
    groups: dict[str, dict[str, Path]] = {}
    for path in dxf_files:
        name = path.name
        name_lower = name.lower()
        is_visible = any(keyword in name_lower for keyword in VISIBLE_KEYWORDS)
        numbers = re.findall(r"\d+", name)
        if not numbers:
            continue
        group = numbers[0]
        groups.setdefault(group, {})
        if is_visible:
            groups[group]["visible"] = path
        else:
            groups[group]["cut"] = path

    matched: dict[str, tuple[Path, Path]] = {}
    for group in sort_group_ids(groups):
        cut = groups[group].get("cut")
        visible = groups[group].get("visible")
        if not cut or not visible:
            missing = []
            if not cut:
                missing.append("剖切线")
            if not visible:
                missing.append("看线")
            raise FileNotFoundError(f"第 {group} 组缺少文件: {', '.join(missing)}")
        matched[group] = (cut, visible)
    if not matched:
        raise FileNotFoundError("未找到包含数字编号的 DXF 输入组")
    return matched


def fmt(value: float) -> str:
    if abs(value) < 1e-9:
        value = 0.0
    return f"{value:.6f}".rstrip("0").rstrip(".")


def write_dxf(path: Path, lines: list[LineEntity], texts: list[TextEntity]) -> None:
    out: list[str] = []

    def add(code: int | str, value: str | int | float) -> None:
        out.append(str(code))
        if isinstance(value, float):
            out.append(fmt(value))
        else:
            out.append(str(value))

    add(0, "SECTION")
    add(2, "HEADER")
    add(9, "$ACADVER")
    # AutoCAD is strict about matching the declared DXF version to the entity
    # structure.  Use conservative R12 output so simple LINE/TEXT entities do
    # not require handles or AcDb subclass markers.
    add(1, "AC1009")
    add(0, "ENDSEC")

    add(0, "SECTION")
    add(2, "TABLES")
    add(0, "TABLE")
    add(2, "LTYPE")
    add(70, 3)
    for name, description, pattern in [
        ("CONTINUOUS", "Solid line", []),
        ("CENTER", "Center ____ _ ____ _", [25.0, -5.0, 5.0, -5.0]),
        ("HIDDEN", "Hidden __ __ __", [12.0, -6.0]),
    ]:
        add(0, "LTYPE")
        add(2, name)
        add(70, 0)
        add(3, description)
        add(72, 65)
        add(73, len(pattern))
        add(40, sum(abs(p) for p in pattern))
        for item in pattern:
            add(49, item)
            add(74, 0)
    add(0, "ENDTAB")

    add(0, "TABLE")
    add(2, "LAYER")
    add(70, len(REQUIRED_LAYERS))
    for layer in REQUIRED_LAYERS:
        style = LAYER_STYLE[layer]
        add(0, "LAYER")
        add(2, layer)
        add(70, 0)
        add(62, style["color"])
        add(6, style["ltype"])
    add(0, "ENDTAB")

    add(0, "TABLE")
    add(2, "STYLE")
    add(70, 1)
    add(0, "STYLE")
    add(2, "STANDARD")
    add(70, 0)
    add(40, 0.0)
    add(41, 1.0)
    add(50, 0.0)
    add(71, 0)
    add(42, 2.5)
    add(3, "txt")
    add(4, "")
    add(0, "ENDTAB")
    add(0, "ENDSEC")

    add(0, "SECTION")
    add(2, "ENTITIES")
    for line in lines:
        layer = line.layer if line.layer in REQUIRED_LAYERS else "A-VISIBLE-PROJECTION"
        style = LAYER_STYLE[layer]
        add(0, "LINE")
        add(8, layer)
        add(62, style["color"])
        add(6, line.ltype or style["ltype"])
        add(10, line.x1)
        add(20, line.y1)
        add(30, 0.0)
        add(11, line.x2)
        add(21, line.y2)
        add(31, 0.0)
    for text in texts:
        safe = re.sub(r"[^\x20-\x7e]", "?", text.text)
        add(0, "TEXT")
        add(8, text.layer)
        add(62, LAYER_STYLE[text.layer]["color"])
        add(10, text.x)
        add(20, text.y)
        add(30, 0.0)
        add(40, text.height)
        add(1, safe)
        add(50, 0.0)
        add(7, "STANDARD")
    add(0, "ENDSEC")
    add(0, "EOF")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def template_pairs(path: Path) -> list[tuple[str, str]]:
    raw = path.read_text(errors="ignore").splitlines()
    return [(raw[i].strip(), raw[i + 1].strip()) for i in range(0, len(raw) - 1, 2)]


def max_dxf_handle(pairs: list[tuple[str, str]]) -> int:
    handle_max = 0
    for code, value in pairs:
        if code == "5" and re.fullmatch(r"[0-9A-Fa-f]+", value):
            handle_max = max(handle_max, int(value, 16))
    return handle_max


def find_modelspace_owner(pairs: list[tuple[str, str]]) -> str:
    i = 0
    while i < len(pairs):
        code, value = pairs[i]
        if code == "0" and value == "BLOCK_RECORD":
            record: list[tuple[str, str]] = []
            j = i + 1
            while j < len(pairs) and pairs[j][0] != "0":
                record.append(pairs[j])
                j += 1
            handle = next((v for c, v in record if c == "5"), None)
            name = next((v for c, v in record if c == "2"), None)
            if handle and name and name.upper() == "*MODEL_SPACE":
                return handle
            i = j
        else:
            i += 1
    return "1F"


def handle_generator(start: int):
    value = start
    while True:
        yield f"{value:X}"
        value += 1


def update_header_handseed(section: list[tuple[str, str]], next_handle: str) -> list[tuple[str, str]]:
    updated = list(section)
    for i in range(len(updated) - 2):
        if updated[i] == ("9", "$HANDSEED") and updated[i + 1][0] == "5":
            updated[i + 1] = ("5", next_handle)
            return updated
    insert_at = len(updated) - 1
    updated[insert_at:insert_at] = [("9", "$HANDSEED"), ("5", next_handle)]
    return updated


def table_records(table: list[tuple[str, str]], record_type: str) -> set[str]:
    names: set[str] = set()
    for i, pair in enumerate(table[:-1]):
        if pair == ("0", record_type):
            j = i + 1
            while j < len(table) and table[j][0] != "0":
                if table[j][0] == "2":
                    names.add(table[j][1])
                    break
                j += 1
    return names


def table_handle(table: list[tuple[str, str]], fallback: str) -> str:
    for i, pair in enumerate(table):
        if pair == ("0", "TABLE"):
            j = i + 1
            while j < len(table) and table[j][0] != "0":
                if table[j][0] == "5":
                    return table[j][1]
                j += 1
    return fallback


def set_table_record_count(table: list[tuple[str, str]], count: int) -> list[tuple[str, str]]:
    updated = list(table)
    first_record = next((i for i, pair in enumerate(updated[1:], start=1) if pair[0] == "0"), len(updated))
    for i in range(first_record):
        if updated[i][0] == "70":
            updated[i] = ("70", str(count))
            return updated
    updated[first_record:first_record] = [("70", str(count))]
    return updated


def make_ltype_record(name: str, handle: str, owner: str) -> list[tuple[str, str]]:
    if name == "CENTER":
        description = "Center ____ _ ____ _"
        pattern = [25.0, -5.0, 5.0, -5.0]
    elif name == "HIDDEN":
        description = "Hidden __ __ __"
        pattern = [12.0, -6.0]
    else:
        description = "Solid line"
        pattern = []
    record = [
        ("0", "LTYPE"),
        ("5", handle),
        ("330", owner),
        ("100", "AcDbSymbolTableRecord"),
        ("100", "AcDbLinetypeTableRecord"),
        ("2", name),
        ("70", "0"),
        ("3", description),
        ("72", "65"),
        ("73", str(len(pattern))),
        ("40", fmt(sum(abs(item) for item in pattern))),
    ]
    for item in pattern:
        record.extend([("49", fmt(item)), ("74", "0")])
    return record


def make_layer_record(name: str, handle: str, owner: str) -> list[tuple[str, str]]:
    style = LAYER_STYLE[name]
    return [
        ("0", "LAYER"),
        ("5", handle),
        ("330", owner),
        ("100", "AcDbSymbolTableRecord"),
        ("100", "AcDbLayerTableRecord"),
        ("2", name),
        ("70", "0"),
        ("62", str(style["color"])),
        ("6", style["ltype"]),
    ]


def update_ltype_table(table: list[tuple[str, str]], handles) -> list[tuple[str, str]]:
    existing = table_records(table, "LTYPE")
    owner = table_handle(table, "5")
    insert_at = len(table) - 1
    updated = list(table)
    for name in ("CONTINUOUS", "CENTER", "HIDDEN"):
        if name not in existing:
            record = make_ltype_record(name, next(handles), owner)
            updated[insert_at:insert_at] = record
            insert_at += len(record)
            existing.add(name)
    return set_table_record_count(updated, len(table_records(updated, "LTYPE")))


def update_layer_table(table: list[tuple[str, str]], handles) -> list[tuple[str, str]]:
    existing = table_records(table, "LAYER")
    owner = table_handle(table, "2")
    insert_at = len(table) - 1
    updated = list(table)
    for name in REQUIRED_LAYERS:
        if name not in existing:
            record = make_layer_record(name, next(handles), owner)
            updated[insert_at:insert_at] = record
            insert_at += len(record)
            existing.add(name)
    return set_table_record_count(updated, len(table_records(updated, "LAYER")))


def update_tables_section(section: list[tuple[str, str]], handles) -> list[tuple[str, str]]:
    updated: list[tuple[str, str]] = []
    i = 0
    while i < len(section):
        if section[i] == ("0", "TABLE") and i + 1 < len(section):
            name = section[i + 1][1] if section[i + 1][0] == "2" else ""
            j = i + 1
            while j < len(section) and section[j] != ("0", "ENDTAB"):
                j += 1
            if j < len(section):
                table = section[i : j + 1]
                if name == "LTYPE":
                    table = update_ltype_table(table, handles)
                elif name == "LAYER":
                    table = update_layer_table(table, handles)
                updated.extend(table)
                i = j + 1
                continue
        updated.append(section[i])
        i += 1
    return updated


def r14_line_entity(line: LineEntity, handle: str, owner: str) -> list[tuple[str, str]]:
    layer = line.layer if line.layer in REQUIRED_LAYERS else "A-VISIBLE-PROJECTION"
    return [
        ("0", "LINE"),
        ("5", handle),
        ("330", owner),
        ("100", "AcDbEntity"),
        ("8", layer),
        ("100", "AcDbLine"),
        ("10", fmt(line.x1)),
        ("20", fmt(line.y1)),
        ("30", "0.0"),
        ("11", fmt(line.x2)),
        ("21", fmt(line.y2)),
        ("31", "0.0"),
    ]


def r14_text_entity(text: TextEntity, handle: str, owner: str) -> list[tuple[str, str]]:
    safe = re.sub(r"[^\x20-\x7e]", "?", text.text)[:240]
    return [
        ("0", "TEXT"),
        ("5", handle),
        ("330", owner),
        ("100", "AcDbEntity"),
        ("8", text.layer),
        ("100", "AcDbText"),
        ("10", fmt(text.x)),
        ("20", fmt(text.y)),
        ("30", "0.0"),
        ("40", fmt(text.height)),
        ("1", safe),
        ("50", "0.0"),
        ("7", "STANDARD"),
        ("100", "AcDbText"),
    ]


def make_entities_section(
    lines: list[LineEntity],
    texts: list[TextEntity],
    handles,
    owner: str,
) -> list[tuple[str, str]]:
    section: list[tuple[str, str]] = [("0", "SECTION"), ("2", "ENTITIES")]
    for line in lines:
        section.extend(r14_line_entity(line, next(handles), owner))
    for text in texts:
        section.extend(r14_text_entity(text, next(handles), owner))
    section.append(("0", "ENDSEC"))
    return section


def write_pairs(path: Path, pairs: list[tuple[str, str]]) -> None:
    lines: list[str] = []
    for code, value in pairs:
        lines.append(str(code))
        lines.append(str(value))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def split_sections(pairs: list[tuple[str, str]]) -> list[tuple[str, list[tuple[str, str]]]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    i = 0
    while i < len(pairs):
        if pairs[i] == ("0", "SECTION") and i + 1 < len(pairs) and pairs[i + 1][0] == "2":
            name = pairs[i + 1][1]
            j = i + 2
            while j < len(pairs) and pairs[j] != ("0", "ENDSEC"):
                j += 1
            if j < len(pairs):
                sections.append((name, pairs[i : j + 1]))
                i = j + 1
                continue
        if pairs[i] == ("0", "EOF"):
            sections.append(("EOF", [pairs[i]]))
        i += 1
    return sections


def write_dxf_from_template(
    path: Path,
    lines: list[LineEntity],
    texts: list[TextEntity],
    template_path: Path,
) -> None:
    base = template_pairs(template_path)
    start_handle = max_dxf_handle(base) + 1
    handles = handle_generator(start_handle)
    owner = find_modelspace_owner(base)

    sections = split_sections(base)
    rebuilt: list[tuple[str, str]] = []
    for name, section in sections:
        if name == "HEADER":
            # Reserve enough handles for new layers, linetypes, entities, and a margin.
            handseed = f"{start_handle + len(lines) + len(texts) + 128:X}"
            rebuilt.extend(update_header_handseed(section, handseed))
        elif name == "TABLES":
            rebuilt.extend(update_tables_section(section, handles))
        elif name == "ENTITIES":
            rebuilt.extend(make_entities_section(lines, texts, handles, owner))
        elif name == "EOF":
            continue
        else:
            rebuilt.extend(section)
    rebuilt.append(("0", "EOF"))
    write_pairs(path, rebuilt)


def write_dxf_with_ezdxf(path: Path, lines: list[LineEntity], texts: list[TextEntity]) -> bool:
    try:
        import ezdxf  # type: ignore
    except Exception:
        return False

    doc = ezdxf.new("R2010")
    try:
        doc.linetypes.new(
            "CENTER",
            dxfattribs={
                "description": "Center ____ _ ____ _",
                "pattern": [40.0, 25.0, -5.0, 5.0, -5.0],
            },
        )
    except Exception:
        pass
    try:
        doc.linetypes.new(
            "HIDDEN",
            dxfattribs={"description": "Hidden __ __ __", "pattern": [18.0, 12.0, -6.0]},
        )
    except Exception:
        pass

    for layer in REQUIRED_LAYERS:
        style = LAYER_STYLE[layer]
        if layer not in doc.layers:
            doc.layers.new(
                layer,
                dxfattribs={
                    "color": style["color"],
                    "linetype": style["ltype"] if style["ltype"] in doc.linetypes else "CONTINUOUS",
                    "lineweight": style["weight"],
                },
            )

    msp = doc.modelspace()
    for line in lines:
        layer = line.layer if line.layer in REQUIRED_LAYERS else "A-VISIBLE-PROJECTION"
        style = LAYER_STYLE[layer]
        msp.add_line(
            (line.x1, line.y1, 0.0),
            (line.x2, line.y2, 0.0),
            dxfattribs={
                "layer": layer,
                "color": 256,
                "linetype": "BYLAYER",
                "lineweight": style["weight"],
            },
        )
    for text in texts:
        safe = re.sub(r"[^\x20-\x7e]", "?", text.text)[:240]
        entity = msp.add_text(
            safe,
            dxfattribs={
                "layer": text.layer,
                "height": text.height,
                "color": 256,
            },
        )
        try:
            entity.set_placement((text.x, text.y, 0.0))
        except Exception:
            entity.dxf.insert = (text.x, text.y, 0.0)

    doc.header["$INSUNITS"] = 4
    doc.saveas(path)
    return True


def write_robust_dxf(
    path: Path,
    lines: list[LineEntity],
    texts: list[TextEntity],
    template_path: Path,
) -> str:
    if write_dxf_with_ezdxf(path, lines, texts):
        return "ezdxf-r2010"
    write_dxf_from_template(path, lines, texts, template_path)
    return "template-r14"


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def write_png(path: Path, width: int, height: int, rgb: bytearray) -> None:
    raw = b"".join(b"\x00" + rgb[y * width * 3 : (y + 1) * width * 3] for y in range(height))
    data = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def render_preview(path: Path, lines: list[LineEntity], texts: list[TextEntity]) -> None:
    all_lines = list(lines)
    b = bbox(all_lines)
    minx, miny, maxx, maxy = b
    for text in texts:
        minx = min(minx, text.x)
        miny = min(miny, text.y)
        maxx = max(maxx, text.x + text.height * max(len(text.text), 1) * 0.5)
        maxy = max(maxy, text.y + text.height)
    width, height = 1800, 1050
    margin = 55
    span_x = max(maxx - minx, 1.0)
    span_y = max(maxy - miny, 1.0)
    scale = min((width - 2 * margin) / span_x, (height - 2 * margin) / span_y)
    rgb = bytearray([255] * width * height * 3)

    colors = {
        "A-CUT-SECTION": (0, 0, 0),
        "A-VISIBLE-PROJECTION": (120, 120, 120),
        "A-STRUCTURE-FIX": (190, 40, 35),
        "A-HATCH-MATERIAL": (40, 140, 75),
        "A-CENTER-HIDDEN": (45, 85, 180),
        "A-ANNO-NOTE": (130, 50, 130),
    }
    thickness = {
        "A-CUT-SECTION": 2,
        "A-VISIBLE-PROJECTION": 0,
        "A-STRUCTURE-FIX": 1,
        "A-HATCH-MATERIAL": 0,
        "A-CENTER-HIDDEN": 0,
        "A-ANNO-NOTE": 0,
    }

    def to_pixel(x: float, y: float) -> tuple[int, int]:
        px = int((x - minx) * scale + margin)
        py = int(height - margin - (y - miny) * scale)
        return px, py

    def set_pixel(x: int, y: int, color: tuple[int, int, int]) -> None:
        if 0 <= x < width and 0 <= y < height:
            idx = (y * width + x) * 3
            rgb[idx] = color[0]
            rgb[idx + 1] = color[1]
            rgb[idx + 2] = color[2]

    def draw_line(line: LineEntity) -> None:
        x0, y0 = to_pixel(line.x1, line.y1)
        x1, y1 = to_pixel(line.x2, line.y2)
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        color = colors.get(line.layer, (0, 0, 0))
        thick = thickness.get(line.layer, 0)
        step = 0
        dashed = line.layer == "A-CENTER-HIDDEN"
        while True:
            if not dashed or (step // 12) % 2 == 0:
                for ox in range(-thick, thick + 1):
                    for oy in range(-thick, thick + 1):
                        set_pixel(x0 + ox, y0 + oy, color)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy
            step += 1

    for layer in [
        "A-VISIBLE-PROJECTION",
        "A-HATCH-MATERIAL",
        "A-CENTER-HIDDEN",
        "A-STRUCTURE-FIX",
        "A-CUT-SECTION",
        "A-ANNO-NOTE",
    ]:
        for line in all_lines:
            if line.layer == layer:
                draw_line(line)

    for text in texts:
        x, y = to_pixel(text.x, text.y)
        w = max(18, int(text.height * len(text.text) * 0.24 * scale))
        h = max(3, int(text.height * 0.08 * scale))
        color = colors["A-ANNO-NOTE"]
        for xx in range(x, min(width, x + w)):
            for yy in range(max(0, y - h), min(height, y + h + 1)):
                set_pixel(xx, yy, color)

    write_png(path, width, height, rgb)


def output_entity_counts(lines: list[LineEntity], texts: list[TextEntity]) -> dict[str, int]:
    counts = {layer: 0 for layer in REQUIRED_LAYERS}
    for line in lines:
        counts[line.layer] = counts.get(line.layer, 0) + 1
    for text in texts:
        counts[text.layer] = counts.get(text.layer, 0) + 1
    return counts


def validate_output(path: Path) -> tuple[dict[str, int], int, list[str]]:
    lines, _layers = parse_dxf_lines(path)
    counts = {layer: 0 for layer in REQUIRED_LAYERS}
    zero_layer = 0
    entity_layers = Counter(line.layer for line in lines)
    for layer in REQUIRED_LAYERS:
        counts[layer] = entity_layers.get(layer, 0)
    zero_layer += entity_layers.get("0", 0)

    # TEXT is not returned by parse_dxf_lines; scan entity layers for all output entities.
    in_entities = False
    current_type: str | None = None
    current_layer = "0"
    all_counts = {layer: 0 for layer in REQUIRED_LAYERS}
    all_zero = 0
    warnings: list[str] = []
    for code, value in dxf_pairs(path):
        if code == "2" and value == "ENTITIES":
            in_entities = True
            continue
        if not in_entities:
            continue
        if code == "0":
            if current_type in {"LINE", "TEXT"}:
                if current_layer == "0":
                    all_zero += 1
                elif current_layer in all_counts:
                    all_counts[current_layer] += 1
            if value == "ENDSEC":
                break
            current_type = value
            current_layer = "0"
        elif code == "8":
            current_layer = value

    for layer in REQUIRED_LAYERS:
        if all_counts[layer] <= 0:
            warnings.append(f"输出图层无实体: {layer}")
    return all_counts, all_zero, warnings


def write_group_report(result: GroupResult) -> None:
    lines = [
        f"# Standardized Section {result.group} Report",
        "",
        "## Input",
        f"- Cut file: `{result.cut_file.name}`",
        f"- Visible file: `{result.visible_file.name}`",
        f"- Source cut LINE entities: {result.source_cut_count}",
        f"- Source visible LINE entities: {result.source_visible_count}",
        f"- Cut bbox before alignment: {tuple(round(v, 3) for v in result.cut_bbox_before)}",
        f"- Visible bbox: {tuple(round(v, 3) for v in result.visible_bbox)}",
        "",
        "## Alignment",
        f"- Coordinate offset detected: {'yes' if result.offset_detected else 'no'}",
        f"- Applied translation to cut file: dx={result.dx:.3f}, dy={result.dy:.3f}",
        f"- Alignment score: {result.align_score:.3f}",
        "",
        "## Cleaning",
        f"- Removed total: {result.clean_stats.removed_total}",
        f"- Zero length: {result.clean_stats.zero_length}",
        f"- Very short: {result.clean_stats.short_lines}",
        f"- Isolated fragments: {result.clean_stats.isolated_fragments}",
        f"- Duplicates: {result.clean_stats.duplicates}",
        "",
        "## Output Layer Entity Counts",
    ]
    for layer in REQUIRED_LAYERS:
        lines.append(f"- {layer}: {result.layer_counts.get(layer, 0)}")
    lines.extend(
        [
            "",
            "## Validation",
            f"- Effective entities on layer 0: {result.zero_layer_entities}",
            f"- DXF generated: {'yes' if result.dxf_path.exists() else 'no'}",
            f"- PNG generated: {'yes' if result.png_path.exists() else 'no'}",
            f"- Report generated: yes",
            "",
            "## Manual Checks Still Recommended",
            "- CAD-side confirmation of exact material hatch density and plotting lineweights.",
            "- Architectural review of added lightweight structure against final structural design.",
            "- Dimension/level text can be replaced with project-specific annotation if required.",
        ]
    )
    if result.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend([f"- {warning}" for warning in result.warnings])
    result.report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_all_report(results: list[GroupResult]) -> None:
    path = OUT_DIR / "standardized_section_all_report.md"
    lines = [
        "# Standardized Section Batch Report",
        "",
        "| Group | Cut file | Visible file | Source entities | Offset | dx | dy | Removed | 0 layer entities | DXF | PNG | Report |",
        "|---|---|---|---:|---|---:|---:|---:|---:|---|---|---|",
    ]
    for result in results:
        source_total = result.source_cut_count + result.source_visible_count
        lines.append(
            f"| {result.group} | `{result.cut_file.name}` | `{result.visible_file.name}` | {source_total} | "
            f"{'yes' if result.offset_detected else 'no'} | {result.dx:.3f} | {result.dy:.3f} | "
            f"{result.clean_stats.removed_total} | {result.zero_layer_entities} | "
            f"{'yes' if result.dxf_path.exists() else 'no'} | {'yes' if result.png_path.exists() else 'no'} | "
            f"{'yes' if result.report_path.exists() else 'no'} |"
        )
    lines.extend(["", "## Output Layer Entity Counts"])
    for result in results:
        lines.append(f"### Group {result.group}")
        for layer in REQUIRED_LAYERS:
            lines.append(f"- {layer}: {result.layer_counts.get(layer, 0)}")
        if result.warnings:
            lines.append("- Warnings: " + "; ".join(result.warnings))
        else:
            lines.append("- Warnings: none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_group(group: str, cut_file: Path, visible_file: Path) -> GroupResult:
    cut_lines, _cut_source_layers = parse_dxf_lines(cut_file)
    visible_lines, _visible_source_layers = parse_dxf_lines(visible_file)
    if not cut_lines or not visible_lines:
        raise RuntimeError(f"第 {group} 组 DXF 没有可处理 LINE 实体")

    dx, dy, align_score = detect_offset(cut_lines, visible_lines)
    offset_detected = hypot(dx, dy) > 5.0
    aligned_cut = [line.shifted(dx, dy, "A-CUT-SECTION") for line in cut_lines]
    classified_visible = [
        LineEntity(line.x1, line.y1, line.x2, line.y2, "A-VISIBLE-PROJECTION", source=line.source, ltype=line.ltype)
        for line in visible_lines
    ]

    cleaned, clean_stats = clean_lines(aligned_cut + classified_visible)
    with_supplemental, texts = add_supplemental_geometry(cleaned)
    final_lines, supplemental_clean_stats = clean_lines(with_supplemental)
    clean_stats.duplicates += supplemental_clean_stats.duplicates
    clean_stats.short_lines += supplemental_clean_stats.short_lines
    clean_stats.zero_length += supplemental_clean_stats.zero_length
    clean_stats.isolated_fragments += supplemental_clean_stats.isolated_fragments
    clean_stats.removed_total += supplemental_clean_stats.removed_total

    dxf_path = OUT_DIR / f"standardized_section_{group}.dxf"
    png_path = OUT_DIR / f"standardized_section_{group}_preview.png"
    report_path = OUT_DIR / f"standardized_section_{group}_report.md"

    write_robust_dxf(dxf_path, final_lines, texts, visible_file)
    render_preview(png_path, final_lines, texts)
    layer_counts, zero_layer_entities, warnings = validate_output(dxf_path)
    result = GroupResult(
        group=group,
        cut_file=cut_file,
        visible_file=visible_file,
        source_cut_count=len(cut_lines),
        source_visible_count=len(visible_lines),
        cut_bbox_before=bbox(cut_lines),
        visible_bbox=bbox(visible_lines),
        dx=dx,
        dy=dy,
        offset_detected=offset_detected,
        align_score=align_score,
        clean_stats=clean_stats,
        layer_counts=layer_counts,
        zero_layer_entities=zero_layer_entities,
        dxf_path=dxf_path,
        png_path=png_path,
        report_path=report_path,
        warnings=warnings,
    )
    write_group_report(result)
    return result


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    try:
        groups = scan_groups(ROOT)
    except Exception as exc:
        print(f"输入识别失败: {exc}", file=sys.stderr)
        return 1

    print("识别到的输入文件:")
    for group in sort_group_ids(groups):
        cut, visible = groups[group]
        print(f"第 {group} 组 剖切线={cut.name} 看线={visible.name}")

    results: list[GroupResult] = []
    for group in sort_group_ids(groups):
        cut, visible = groups[group]
        result = process_group(group, cut, visible)
        results.append(result)
        print(
            f"第 {group} 组完成: dx={result.dx:.3f}, dy={result.dy:.3f}, "
            f"removed={result.clean_stats.removed_total}, zero_layer={result.zero_layer_entities}"
        )

    write_all_report(results)

    failed = False
    for result in results:
        if result.zero_layer_entities:
            failed = True
        if not result.dxf_path.exists() or not result.png_path.exists() or not result.report_path.exists():
            failed = True
        if result.warnings:
            failed = True
    if not (OUT_DIR / "standardized_section_all_report.md").exists():
        failed = True

    if failed:
        print("校验失败：请查看报告中的 warnings", file=sys.stderr)
        return 2
    print("全部输出已生成并通过脚本校验。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
