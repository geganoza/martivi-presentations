#!/usr/bin/env python3
"""Casa Calda monthly social-media report generator (Meta Ads only).

Reads live Meta Marketing API data for the chosen calendar month, renders
casa-calda/template.html into casa-calda/<month>-<year>.html, and prepends a
new card to casa-calda/index.html.

Usage
-----
    python3 scripts/generate_casa_calda_report.py --year 2026 --month 7
    python3 scripts/generate_casa_calda_report.py --period 2026-07
    python3 scripts/generate_casa_calda_report.py --year 2026 --month 7 --output /tmp/verify.html
    python3 scripts/generate_casa_calda_report.py --year 2026 --month 7 --email

Only stdlib is used.  Georgia (Asia/Tbilisi, UTC+4) is the display timezone.
The Meta access token is never printed.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

REPO_ROOT = Path(__file__).resolve().parents[1]
CASA_DIR = REPO_ROOT / "casa-calda"
TEMPLATE_PATH = CASA_DIR / "template.html"
INDEX_PATH = CASA_DIR / "index.html"

CREDS_PATH = Path(
    "/Users/giorginozadze/Projects/AZON/MAIA/config/credentials/meta_ads_credentials.json"
)

AD_ACCOUNT_ID = "act_2040713473241527"   # Casa Calda
FB_PAGE_ID = "391986960923797"           # Casa Calda page

GEORGIA_TZ = timezone(timedelta(hours=4))

MONTH_KA = [
    "", "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
    "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
]
MONTH_EN_LOWER = [
    "", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

# object_type → aspect ratio used in creative card embed.
ASPECT_RATIO = {
    "PHOTO": "1/1",
    "VIDEO": "9/16",
    "SHARE": "191/100",
}
DEFAULT_ASPECT = "1/1"


# --------------------------------------------------------------------------- #
# Meta API helpers
# --------------------------------------------------------------------------- #

def _load_token() -> tuple[str, str]:
    with CREDS_PATH.open() as f:
        creds = json.load(f)
    api = creds["meta_marketing_api"]["api_base_url"]
    tok = creds["meta_marketing_api"]["access_token"]
    return api, tok


API_BASE, _ACCESS_TOKEN = _load_token()


def _get(endpoint: str, params: dict) -> dict:
    """GET graph.facebook.com/<endpoint>?params (adds access_token)."""
    params = dict(params)
    params["access_token"] = _ACCESS_TOKEN
    url = f"{API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=45) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Scrub token from any error output.
        raise RuntimeError(f"Meta API {e.code}: {e.read().decode()[:400]}") from None


def _get_all(endpoint: str, params: dict) -> list[dict]:
    """GET with pagination — returns every data row."""
    rows: list[dict] = []
    page = _get(endpoint, params)
    rows.extend(page.get("data", []))
    while "paging" in page and "next" in page["paging"]:
        next_url = page["paging"]["next"]
        with urllib.request.urlopen(next_url, timeout=45) as r:
            page = json.loads(r.read().decode())
        rows.extend(page.get("data", []))
    return rows


# --------------------------------------------------------------------------- #
# Data fetch + shape
# --------------------------------------------------------------------------- #

def _month_range(year: int, month: int) -> tuple[str, str]:
    last_day = calendar.monthrange(year, month)[1]
    return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"


def _action_value(actions, action_type: str) -> int:
    if not actions:
        return 0
    for a in actions:
        if a.get("action_type") == action_type:
            try:
                return int(float(a.get("value", 0)))
            except (TypeError, ValueError):
                return 0
    return 0


def fetch_account_totals(year: int, month: int) -> dict:
    since, until = _month_range(year, month)
    data = _get(f"{AD_ACCOUNT_ID}/insights", {
        "time_range": json.dumps({"since": since, "until": until}),
        "fields": "spend,impressions,reach,clicks,ctr,cpm,cpc,actions",
        "level": "account",
    }).get("data", [])
    if not data:
        return {
            "spend": 0.0, "impressions": 0, "reach": 0, "clicks": 0,
            "ctr": 0.0, "cpm": 0.0, "cpc": 0.0,
            "post_engagement": 0, "post_reaction": 0, "comment": 0,
            "post_shares": 0, "photo_view": 0, "video_view": 0,
            "link_click": 0, "page_engagement": 0,
        }
    r = data[0]
    actions = r.get("actions") or []
    return {
        "spend":       float(r.get("spend", 0) or 0),
        "impressions": int(r.get("impressions", 0) or 0),
        "reach":       int(r.get("reach", 0) or 0),
        "clicks":      int(r.get("clicks", 0) or 0),
        "ctr":         float(r.get("ctr", 0) or 0),
        "cpm":         float(r.get("cpm", 0) or 0),
        "cpc":         float(r.get("cpc", 0) or 0),
        "post_engagement": _action_value(actions, "post_engagement"),
        "post_reaction":   _action_value(actions, "post_reaction"),
        "comment":         _action_value(actions, "comment"),
        # "post" action_type = share
        "post_shares":     _action_value(actions, "post"),
        "photo_view":      _action_value(actions, "photo_view"),
        "video_view":      _action_value(actions, "video_view"),
        "link_click":      _action_value(actions, "link_click"),
        "page_engagement": _action_value(actions, "page_engagement"),
    }


def fetch_ad_rows(year: int, month: int) -> list[dict]:
    since, until = _month_range(year, month)
    raw = _get_all(f"{AD_ACCOUNT_ID}/insights", {
        "time_range": json.dumps({"since": since, "until": until}),
        "fields": "ad_id,ad_name,campaign_name,spend,impressions,reach,clicks,ctr,cpm,cpc,actions",
        "level": "ad",
        "limit": "500",
    })
    rows = []
    for r in raw:
        spend = float(r.get("spend", 0) or 0)
        impressions = int(r.get("impressions", 0) or 0)
        reach = int(r.get("reach", 0) or 0)
        clicks = int(r.get("clicks", 0) or 0)
        if spend == 0 and impressions == 0 and reach == 0 and clicks == 0:
            continue
        rows.append({
            "ad_id":         r.get("ad_id", ""),
            "ad_name":       r.get("ad_name", ""),
            "campaign_name": r.get("campaign_name", ""),
            "spend":         spend,
            "impressions":   impressions,
            "reach":         reach,
            "clicks":        clicks,
            "ctr":           float(r.get("ctr", 0) or 0),
            "cpm":           float(r.get("cpm", 0) or 0),
            "cpc":           float(r.get("cpc", 0) or 0),
        })
    return rows


def fetch_ad_metadata() -> dict[str, dict]:
    """ad_id → {name, created_time, story_id, object_type}."""
    ads = _get_all(f"{AD_ACCOUNT_ID}/ads", {
        "fields": "id,name,created_time,creative{effective_object_story_id,object_type}",
        "limit": "500",
    })
    out: dict[str, dict] = {}
    for a in ads:
        creative = a.get("creative") or {}
        out[a["id"]] = {
            "name":         a.get("name", ""),
            "created_time": a.get("created_time", ""),
            "story_id":     creative.get("effective_object_story_id", ""),
            "object_type":  creative.get("object_type", "PHOTO"),
        }
    return out


# --------------------------------------------------------------------------- #
# Creatives (dedupe by post, sort by post created_time DESC)
# --------------------------------------------------------------------------- #

def _parse_created(ts: str) -> datetime | None:
    # Meta returns e.g. "2026-07-28T09:11:17+0000".
    if not ts:
        return None
    try:
        # Python 3.7+: %z understands "+0000".
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def _post_id_from_story(story_id: str) -> str:
    return story_id.split("_", 1)[1] if "_" in story_id else story_id


def build_creatives(ad_rows: list[dict], ad_meta: dict[str, dict]) -> list[dict]:
    """Group by story_id.  For each post:
      - canonical name + campaign_name = highest-spend variant
      - aggregate spend + impressions across every variant
      - created_time = MIN(ad.created_time) across variants (earliest use ~= post publish)
    Sort by created_time DESC.  Skip posts with no story_id.
    """
    grouped: dict[str, dict] = {}
    for row in ad_rows:
        meta = ad_meta.get(row["ad_id"], {})
        story_id = meta.get("story_id", "")
        if not story_id:
            continue
        created = _parse_created(meta.get("created_time", ""))
        if created is None:
            continue
        cur = grouped.get(story_id)
        if cur is None:
            grouped[story_id] = {
                "story_id":     story_id,
                "post_id":      _post_id_from_story(story_id),
                "object_type":  meta.get("object_type", "PHOTO") or "PHOTO",
                "created_time": created,
                "canonical_name":     row["ad_name"],
                "canonical_campaign": row["campaign_name"],
                "canonical_spend":    row["spend"],
                "spend":       row["spend"],
                "impressions": row["impressions"],
            }
        else:
            cur["spend"]       += row["spend"]
            cur["impressions"] += row["impressions"]
            # Highest-spend variant wins as canonical.
            if row["spend"] > cur["canonical_spend"]:
                cur["canonical_spend"]    = row["spend"]
                cur["canonical_name"]     = row["ad_name"]
                cur["canonical_campaign"] = row["campaign_name"]
            # Earliest ad.created_time is closest to real post publish.
            if created < cur["created_time"]:
                cur["created_time"] = created

    return sorted(grouped.values(), key=lambda c: c["created_time"], reverse=True)


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #

def _fmt_int(v) -> str:
    return f"{int(v):,}"


def _fmt_money(v) -> str:
    return f"${float(v):,.2f}"


def _fmt_pct(v) -> str:
    return f"{float(v):.2f}%"


def _fb_embed_url(story_id: str) -> str:
    page_id, post_id = story_id.split("_", 1)
    href = f"https://www.facebook.com/{page_id}/posts/{post_id}"
    return ("https://www.facebook.com/plugins/post.php?href="
            + urllib.parse.quote(href, safe="") + "&show_text=false&width=500")


def render_creatives_html(creatives: list[dict]) -> str:
    """Return the inner HTML for <div class="creatives-grid"> …

    Structure must be bit-identical to July's cards, including 8-space
    indentation and the trailing article at the end (no final newline).
    """
    parts: list[str] = []
    for c in creatives:
        aspect = ASPECT_RATIO.get(c["object_type"], DEFAULT_ASPECT)
        date_str = c["created_time"].astimezone(GEORGIA_TZ).strftime("%d %b %Y")
        embed = _fb_embed_url(c["story_id"])
        parts.append(
            '        <article class="creative-card">\n'
            '          <header class="creative-card__head">\n'
            f'            <h4 class="creative-card__name">{c["canonical_name"]}</h4>\n'
            f'            <p class="creative-card__meta">{c["canonical_campaign"]} · {date_str}</p>\n'
            '          </header>\n'
            f'          <div class="creative-card__embed" style="aspect-ratio: {aspect};">\n'
            f'            <iframe src="{embed}" loading="lazy" scrolling="no" allowfullscreen></iframe>\n'
            '          </div>\n'
            '          <footer class="creative-card__foot">\n'
            f'            <span class="creative-card__spend">{_fmt_money(c["spend"])}</span>\n'
            f'            <span class="creative-card__impr">{_fmt_int(c["impressions"])} ჩვენება</span>\n'
            '          </footer>\n'
            '        </article>'
        )
    return "\n".join(parts)


def render_ads_table_rows(ads: list[dict]) -> str:
    """Table body rows — sorted by spend DESC, matching July's shape exactly."""
    rows = sorted(ads, key=lambda a: a["spend"], reverse=True)
    parts: list[str] = []
    for a in rows:
        parts.append(
            '            <tr>\n'
            f'                <td class="ad-name">{a["ad_name"]}</td>\n'
            f'                <td class="campaign">{a["campaign_name"]}</td>\n'
            f'                <td class="num currency">{_fmt_money(a["spend"])}</td>\n'
            f'                <td class="num">{_fmt_int(a["impressions"])}</td>\n'
            f'                <td class="num">{_fmt_int(a["reach"])}</td>\n'
            f'                <td class="num">{_fmt_int(a["clicks"])}</td>\n'
            f'                <td class="num">{_fmt_pct(a["ctr"])}</td>\n'
            '            </tr>\n'
        )
    return "".join(parts)


def _round_display(v: float) -> float:
    """Round to 2 decimals then trim insignificant trailing zeros for JSON.

    json.dumps prints 49.20 as 49.2 and 49.63 stays 49.63, which is the shape
    used inside the July chart-data arrays."""
    return round(float(v), 2)


def chart_arrays(ad_rows: list[dict]) -> dict:
    top_spend = sorted(ad_rows, key=lambda a: a["spend"], reverse=True)[:10]
    top_clicks = sorted(ad_rows, key=lambda a: a["clicks"], reverse=True)[:10]
    return {
        "spend_labels":  [a["ad_name"] for a in top_spend],
        "spend_data":    [_round_display(a["spend"]) for a in top_spend],
        "clicks_labels": [a["ad_name"] for a in top_clicks],
        "clicks_data":   [int(a["clicks"]) for a in top_clicks],
    }


# --------------------------------------------------------------------------- #
# Full report
# --------------------------------------------------------------------------- #

def render_report(year: int, month: int) -> tuple[str, dict]:
    print(f"[1/5] Fetching account totals for {year}-{month:02d}…")
    totals = fetch_account_totals(year, month)

    print("[2/5] Fetching ad rows…")
    ad_rows = fetch_ad_rows(year, month)
    print(f"      {len(ad_rows)} ads with activity")

    print("[3/5] Fetching ad metadata (creatives)…")
    ad_meta = fetch_ad_metadata()

    print("[4/5] Building creatives (dedupe + sort by created_time DESC)…")
    creatives = build_creatives(ad_rows, ad_meta)
    print(f"      {len(creatives)} unique posts")

    since, until = _month_range(year, month)
    charts = chart_arrays(ad_rows)

    values = {
        "month_label_ka":  f"{year} წლის {MONTH_KA[month]}",
        "period_since":    since,
        "period_until":    until,
        "ads_count":       len(ad_rows),

        "spend_display":       _fmt_money(totals["spend"]),
        "impressions_display": _fmt_int(totals["impressions"]),
        "reach_display":       _fmt_int(totals["reach"]),
        "clicks_display":      _fmt_int(totals["clicks"]),
        "ctr_display":         _fmt_pct(totals["ctr"]),
        "cpm_display":         _fmt_money(totals["cpm"]),
        "cpc_display":         _fmt_money(totals["cpc"]),
        "engagement_display":  _fmt_int(totals["post_engagement"]),

        "reactions_display":       _fmt_int(totals["post_reaction"]),
        "comments_display":        _fmt_int(totals["comment"]),
        "shares_display":          _fmt_int(totals["post_shares"]),
        "photo_views_display":     _fmt_int(totals["photo_view"]),
        "video_views_display":     _fmt_int(totals["video_view"]),
        "link_clicks_display":     _fmt_int(totals["link_click"]),
        "page_engagement_display": _fmt_int(totals["page_engagement"]),

        "creatives_html":  render_creatives_html(creatives),
        "ads_table_rows":  render_ads_table_rows(ad_rows),

        "spend_chart_labels":  json.dumps(charts["spend_labels"],  ensure_ascii=False),
        "spend_chart_data":    json.dumps(charts["spend_data"]),
        "clicks_chart_labels": json.dumps(charts["clicks_labels"], ensure_ascii=False),
        "clicks_chart_data":   json.dumps(charts["clicks_data"]),
    }

    print("[5/5] Rendering template…")
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.format(**values)

    summary = {
        "spend": totals["spend"],
        "impressions": totals["impressions"],
        "clicks": totals["clicks"],
        "ads_count": len(ad_rows),
        "creatives_count": len(creatives),
    }
    return html, summary


# --------------------------------------------------------------------------- #
# index.html updater
# --------------------------------------------------------------------------- #

def _card_impressions_short(imp: int) -> str:
    if imp >= 1000:
        return f"{round(imp / 1000)}K"
    return _fmt_int(imp)


def update_index(year: int, month: int, summary: dict) -> None:
    href = f"/casa-calda/{MONTH_EN_LOWER[month]}-{year}"
    html = INDEX_PATH.read_text(encoding="utf-8")

    if f'href="{href}"' in html:
        print(f"index.html already has card for {href} — refreshing values.")
        # Rewrite the existing card's stats.
        card_re = re.compile(
            rf'(<a href="{re.escape(href)}" class="card">.*?</a>)',
            re.DOTALL,
        )
        new_card = _build_card(href, year, month, summary)
        html = card_re.sub(new_card, html, count=1)
    else:
        anchor = '    <div class="presentations">\n'
        if anchor not in html:
            raise SystemExit("index.html: <div class=\"presentations\"> anchor not found")
        new_card = _build_card(href, year, month, summary) + "\n"
        html = html.replace(anchor, anchor + "        " + new_card, 1)

    INDEX_PATH.write_text(html, encoding="utf-8")
    print(f"index.html updated: card for {href}")


def _build_card(href: str, year: int, month: int, summary: dict) -> str:
    spend  = _fmt_money(summary["spend"])
    imp    = _card_impressions_short(summary["impressions"])
    clicks = _fmt_int(summary["clicks"])
    return (
        f'<a href="{href}" class="card">\n'
        f'            <div class="client">Casa Calda</div>\n'
        f'            <div class="month">{year} წლის {MONTH_KA[month]}</div>\n'
        f'            <div class="stats">\n'
        f'                <div class="stat"><span class="v">{spend}</span><span class="k">ხარჯი</span></div>\n'
        f'                <div class="stat"><span class="v">{imp}</span><span class="k">ჩვენებები</span></div>\n'
        f'                <div class="stat"><span class="v">{clicks}</span><span class="k">დაწკაპ.</span></div>\n'
        f'            </div>\n'
        f'        </a>'
    )


# --------------------------------------------------------------------------- #
# Optional email step
# --------------------------------------------------------------------------- #

def maybe_send_email(year: int, month: int) -> None:
    import os
    if not os.environ.get("CASA_CALDA_REPORT_RECIPIENT"):
        print("--email set but CASA_CALDA_REPORT_RECIPIENT unset; skipping.")
        return
    import subprocess
    helper = REPO_ROOT / "scripts" / "send_casa_calda_report_email.py"
    subprocess.run(
        [sys.executable, str(helper), "--year", str(year), "--month", str(month)],
        check=True,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _parse_period(period: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", period)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid --period: {period!r} (want YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


def main() -> int:
    p = argparse.ArgumentParser(description="Casa Calda monthly report generator")
    p.add_argument("--year", type=int)
    p.add_argument("--month", type=int)
    p.add_argument("--period", type=str, help="alternative to --year/--month, YYYY-MM")
    p.add_argument("--output", type=Path, help="override output path (default: casa-calda/<month>-<year>.html)")
    p.add_argument("--skip-index", action="store_true", help="don't touch casa-calda/index.html")
    p.add_argument("--email", action="store_true", help="send email after generation (needs CASA_CALDA_REPORT_RECIPIENT)")
    args = p.parse_args()

    if args.period:
        year, month = _parse_period(args.period)
    else:
        if not args.year or not args.month:
            p.error("--year and --month required (or --period YYYY-MM)")
        year, month = args.year, args.month

    if not 1 <= month <= 12:
        p.error("--month must be 1..12")

    html, summary = render_report(year, month)

    if args.output:
        out_path = args.output
    else:
        out_path = CASA_DIR / f"{MONTH_EN_LOWER[month]}-{year}.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html.splitlines())} lines)")
    print(f"  spend=${summary['spend']:.2f}  impressions={summary['impressions']:,}"
          f"  clicks={summary['clicks']}  ads={summary['ads_count']}  posts={summary['creatives_count']}")

    if not args.output and not args.skip_index:
        update_index(year, month, summary)

    if args.email:
        maybe_send_email(year, month)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
