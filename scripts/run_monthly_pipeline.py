#!/usr/bin/env python3
"""End-to-end pipeline for the monthly Thermorum report (CI version).

Steps:
  1. Generate HTML via generate_monthly_report.py for the previous calendar month
  2. Stage thermorum/<month>-<year>.html
  3. Prepend a new card to index.html (idempotent)

The workflow commits + pushes the changes (Vercel auto-deploys on push),
then calls send_report_email.py.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "generate_monthly_report.py"
INDEX = REPO_ROOT / "index.html"
THERMORUM_DIR = REPO_ROOT / "thermorum"
# generate_monthly_report.py hardcodes OUTPUT_DIR = parent / workspace / reports
GENERATED_DIR = REPO_ROOT / "workspace" / "reports"

MONTH_EN = ["", "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december"]
MONTH_EN_CAP = [m.capitalize() for m in MONTH_EN]


def previous_month(today: dt.date) -> tuple[int, int]:
    first = today.replace(day=1)
    last_prev = first - dt.timedelta(days=1)
    return last_prev.month, last_prev.year


def run_generator(month: int, year: int) -> Path:
    cmd = [sys.executable, str(GENERATOR), "--month", str(month), "--year", str(year)]
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    src = GENERATED_DIR / f"thermorum_{MONTH_EN[month]}_{year}_report.html"
    if not src.exists():
        raise SystemExit(f"Generator did not produce: {src}")
    return src


def stage(src: Path, month: int, year: int) -> Path:
    dst = THERMORUM_DIR / f"{MONTH_EN[month]}-{year}.html"
    shutil.copyfile(src, dst)
    print(f"Staged: {dst.relative_to(REPO_ROOT)}")
    return dst


def update_index(month: int, year: int) -> None:
    html = INDEX.read_text(encoding="utf-8")
    href = f"/thermorum/{MONTH_EN[month]}-{year}"
    if href in html:
        print(f"index.html already lists {href}; no change.")
        return
    card = (
        f'        <a href="{href}" class="card">\n'
        f'            <div class="client">Thermorum</div>\n'
        f'            <h3>Social Media Report</h3>\n'
        f'            <div class="date">{MONTH_EN_CAP[month]} {year}</div>\n'
        f'            <div class="type">Monthly · Meta Ads + Google Ads</div>\n'
        f'        </a>\n'
    )
    anchor = '    <div class="presentations">\n'
    if anchor not in html:
        raise SystemExit("index.html anchor not found")
    html = html.replace(anchor, anchor + card, 1)
    INDEX.write_text(html, encoding="utf-8")
    print(f"index.html updated with card: {href}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--month", type=int)
    p.add_argument("--year", type=int)
    args = p.parse_args()

    month, year = (args.month, args.year) if args.month and args.year \
        else previous_month(dt.date.today())

    print(f"=== Thermorum Monthly Pipeline: {MONTH_EN_CAP[month]} {year} ===")
    src = run_generator(month, year)
    stage(src, month, year)
    update_index(month, year)
    print("Pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
