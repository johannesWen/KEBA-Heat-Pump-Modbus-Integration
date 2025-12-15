"""Run tests with trace coverage and emit an SVG badge.

This script avoids third-party dependencies by using the stdlib ``trace``
module to calculate a lightweight coverage percentage for the integration
code under ``custom_components``. It executes pytest, counts executed lines,
computes the percentage, and writes ``assets/coverage.svg``.
"""

from __future__ import annotations

import json
import sys
import trace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
TARGET_PACKAGE = PROJECT_ROOT / "custom_components"
BADGE_PATH = PROJECT_ROOT / "assets" / "coverage.svg"
SUMMARY_PATH = PROJECT_ROOT / "coverage_summary.json"


def _run_tests_with_trace() -> dict[str, dict[int, int]]:
    tracer = trace.Trace(
        count=True,
        trace=False,
        ignoredirs=[sys.prefix, sys.exec_prefix],
    )
    exit_code = tracer.runfunc(pytest.main, ["-q"])
    if exit_code != 0:
        raise SystemExit(exit_code)
    counts: dict[str, dict[int, int]] = {}
    for (filename, lineno), hit_count in tracer.results().counts.items():
        counts.setdefault(filename, {})[lineno] = hit_count
    return counts


def _compute_coverage(counts: dict[str, dict[int, int]]) -> float:
    total = 0
    covered = 0

    for filename, line_hits in counts.items():
        path = Path(filename)
        if path.suffix != ".py":
            continue
        try:
            path.relative_to(PROJECT_ROOT)
        except ValueError:
            continue

        if TARGET_PACKAGE not in path.parents and path != TARGET_PACKAGE:
            continue

        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue

        file_total = len(lines)
        file_covered = sum(1 for i in range(1, file_total + 1) if line_hits.get(i))
        total += file_total
        covered += file_covered

    if total == 0:
        return 0.0

    return round((covered / total) * 100, 1)


def _color_for_coverage(percent: float) -> str:
    if percent >= 90:
        return "#4c1"  # bright green
    if percent >= 80:
        return "#97CA00"
    if percent >= 70:
        return "#dfb317"
    if percent >= 60:
        return "#fe7d37"
    return "#e05d44"


def _build_badge_svg(percent: float) -> str:
    percent_text = f"{percent:.1f}%" if percent % 1 else f"{int(percent)}%"
    color = _color_for_coverage(percent)
    label = "coverage"

    label_width = 62
    value_width = 54
    total_width = label_width + value_width

    return f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{total_width}" height="20" role="img" aria-label="{label}: {percent_text}">
  <linearGradient id="smooth" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="round">
    <rect width="{total_width}" height="20" rx="3" fill="#fff"/>
  </mask>
  <g mask="url(#round)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#smooth)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{label_width / 2}" y="15" fill="#010101" fill-opacity=".3">{label}</text>
    <text x="{label_width / 2}" y="14">{label}</text>
    <text x="{label_width + value_width / 2}" y="15" fill="#010101" fill-opacity=".3">{percent_text}</text>
    <text x="{label_width + value_width / 2}" y="14">{percent_text}</text>
  </g>
</svg>
"""


def main() -> None:
    counts = _run_tests_with_trace()
    percent = _compute_coverage(counts)
    BADGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BADGE_PATH.write_text(_build_badge_svg(percent), encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps({"coverage": percent}, indent=2), encoding="utf-8")
    print(f"Coverage: {percent}% written to {BADGE_PATH}")


if __name__ == "__main__":
    main()
