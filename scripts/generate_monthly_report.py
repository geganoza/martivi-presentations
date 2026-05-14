#!/usr/bin/env python3
"""
Thermorum Monthly Social Media Report Generator

Generates a monthly performance report for ALL Thermorum brands covering
Meta Ads (Facebook/Instagram) and Google Ads (Display campaigns),
including Facebook post embeds and Google display ad previews.

Usage:
    python scripts/generate_monthly_report.py --month 1 --year 2026
    python scripts/generate_monthly_report.py --month 2 --year 2026
"""

import argparse
import calendar
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# =============================================================================
# CONFIGURATION
# =============================================================================

CREDENTIALS_DIR = Path(__file__).parent.parent / "config" / "credentials"
OUTPUT_DIR = Path(__file__).parent.parent / "workspace" / "reports"

# Load Meta credentials
with open(CREDENTIALS_DIR / "meta_ads_credentials.json") as f:
    meta_creds = json.load(f)

META_API_BASE = meta_creds["meta_marketing_api"]["api_base_url"]
META_ACCESS_TOKEN = meta_creds["meta_marketing_api"]["access_token"]
THERMORUM_ACCOUNT_ID = meta_creds["ad_accounts"]["thermorum"]["full_id"]

# Load Google Ads credentials
with open(CREDENTIALS_DIR / "google_ads_credentials.json") as f:
    google_creds = json.load(f)

GOOGLE_CUSTOMER_ID = google_creds["ad_accounts"]["thermorum"]["customer_id"]

# Thermorum Facebook Page ID
THERMORUM_PAGE_ID = "483547718503422"

# Month names for display
MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
]

# Campaign -> Brand mapping
BRAND_MAPPING = {
    "SIME": "SIME",
    "Danfoss": "Danfoss",
    "DAB": "DAB",
    "MACRO": "MACRO",
    "Macro": "MACRO",
    "Tesy": "Tesy",
    "Caleffi": "Caleffi",
    "Thermorum": "Thermorum",
    "Awareness": "Thermorum",
    "Santa": "Thermorum",
    "კონცენსაციური": "Thermorum",
    "მითია": "Thermorum",
    "Showroom": "Thermorum",
}

# Brand descriptions for Google Ads creative cards
BRAND_DESCRIPTIONS = {
    "THERMORUM": {"title": "THERMORUM | THERMORUM - Climate Systems", "short": "THERMORUM", "desc": "Hight Quality Climate Systems from Europe"},
    "SIME": {"title": "SIME | SIME - Made in Italy", "short": "SIME", "desc": "50 Year Exelence from Italy"},
    "DAB": {"title": "DAB | DAB - Made in Italy", "short": "DAB", "desc": "50 Year Exelence from Italy"},
    "Danfoss": {"title": "Danfoss | Danfoss - Made in Denmark", "short": "Danfoss", "desc": "90 Year Excellence from Denmark"},
    "MACRO": {"title": "MACRO | MACRO Gas Boiler", "short": "MACRO", "desc": "Wifi Gas Boilers from MACRO"},
    "Tesy": {"title": "Tesy | Tesy - Made in Europe", "short": "Tesy", "desc": "Bring Warmth into Your Room"},
    "Caleffi": {"title": "Caleffi | Caleffi - Made in Italy", "short": "Caleffi", "desc": "Quality Valves from Italy"},
}


# =============================================================================
# META ADS API FUNCTIONS
# =============================================================================

def meta_api_request(endpoint: str, params: dict, retries: int = 3) -> dict:
    """Make a request to the Meta Marketing API with retry logic."""
    params["access_token"] = META_ACCESS_TOKEN
    url = f"{META_API_BASE}/{endpoint}?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.loads(response.read().decode())
        except (ConnectionResetError, urllib.error.URLError, TimeoutError) as e:
            if attempt < retries - 1:
                wait = 5 * (attempt + 1)
                print(f"    Connection error, retrying in {wait}s... ({e})")
                time.sleep(wait)
            else:
                raise


def fetch_meta_ads_monthly(year: int, month: int) -> list[dict]:
    """Fetch all ads data for the given month (all brands)."""
    last_day = calendar.monthrange(year, month)[1]
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day:02d}"

    print(f"  Fetching Meta Ads for {start_date} to {end_date}...")

    params = {
        "time_range": json.dumps({"since": start_date, "until": end_date}),
        "fields": "ad_name,reach,impressions,frequency,actions,cpm,cost_per_action_type,spend",
        "level": "ad",
        "limit": "500",
    }

    result = meta_api_request(f"{THERMORUM_ACCOUNT_ID}/insights", params)
    ads = result.get("data", [])

    # Handle pagination
    while "paging" in result and "next" in result["paging"]:
        next_url = result["paging"]["next"]
        with urllib.request.urlopen(next_url) as response:
            result = json.loads(response.read().decode())
            ads.extend(result.get("data", []))

    print(f"  Found {len(ads)} ads")
    return ads


def fetch_meta_ad_details() -> list[dict]:
    """Fetch ad details including creative and post info."""
    params = {
        "fields": "id,name,effective_status,creative{id,effective_object_story_id,object_type,thumbnail_url,video_id}",
        "limit": "500",
    }
    result = meta_api_request(f"{THERMORUM_ACCOUNT_ID}/ads", params)
    ads = result.get("data", [])

    # Handle pagination
    while "paging" in result and "next" in result["paging"]:
        next_url = result["paging"]["next"]
        with urllib.request.urlopen(next_url) as response:
            result = json.loads(response.read().decode())
            ads.extend(result.get("data", []))

    print(f"  Found {len(ads)} ad details")
    return ads


def get_facebook_embed_url(story_id: str) -> str:
    """Generate Facebook embed URL from story ID."""
    if not story_id or "_" not in story_id:
        return ""
    page_id, post_id = story_id.split("_", 1)
    permalink = f"https://www.facebook.com/permalink.php?story_fbid={post_id}&id={page_id}"
    encoded = urllib.parse.quote(permalink, safe="")
    return f"https://www.facebook.com/plugins/post.php?href={encoded}&width=500&show_text=true"


def derive_campaign(ad_name: str) -> str:
    """Derive campaign/brand name from ad name."""
    for keyword, brand in BRAND_MAPPING.items():
        if keyword.lower() in ad_name.lower():
            return brand
    return "Thermorum"


# =============================================================================
# GOOGLE ADS API FUNCTIONS
# =============================================================================

def fetch_google_campaigns_monthly(year: int, month: int) -> list[dict]:
    """Fetch Google Ads campaigns for the given month."""
    try:
        from google.ads.googleads.client import GoogleAdsClient

        config = {
            "developer_token": google_creds["google_ads_api"]["developer_token"],
            "client_id": google_creds["google_ads_api"]["client_id"],
            "client_secret": google_creds["google_ads_api"]["client_secret"],
            "refresh_token": google_creds["google_ads_api"]["refresh_token"],
            "use_proto_plus": True,
        }

        client = GoogleAdsClient.load_from_dict(config)
        ga_service = client.get_service("GoogleAdsService")

        last_day = calendar.monthrange(year, month)[1]
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{last_day:02d}"

        print(f"  Fetching Google Ads for {start_date} to {end_date}...")

        query = f"""
            SELECT
                campaign.id,
                campaign.name,
                campaign.status,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.cost_micros
            FROM campaign
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
              AND campaign.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """

        campaigns = []
        response = ga_service.search_stream(customer_id=GOOGLE_CUSTOMER_ID, query=query)

        for batch in response:
            for row in batch.results:
                cost = row.metrics.cost_micros / 1_000_000
                clicks = row.metrics.clicks
                avg_cpc = row.metrics.average_cpc / 1_000_000

                campaigns.append({
                    "campaign_id": str(row.campaign.id),
                    "campaign_name": row.campaign.name,
                    "status": row.campaign.status.name.lower(),
                    "impressions": row.metrics.impressions,
                    "clicks": clicks,
                    "ctr": row.metrics.ctr * 100,
                    "average_cpc": avg_cpc,
                    "spend": cost,
                })

        print(f"  Found {len(campaigns)} Google campaigns")
        return campaigns

    except Exception as e:
        print(f"  Error fetching Google Ads data: {e}")
        return []


def fetch_google_ad_creatives_monthly(year: int, month: int) -> list[dict]:
    """Fetch Google Ads creative assets for the month with image URLs."""
    try:
        from google.ads.googleads.client import GoogleAdsClient

        config = {
            "developer_token": google_creds["google_ads_api"]["developer_token"],
            "client_id": google_creds["google_ads_api"]["client_id"],
            "client_secret": google_creds["google_ads_api"]["client_secret"],
            "refresh_token": google_creds["google_ads_api"]["refresh_token"],
            "use_proto_plus": True,
        }

        client = GoogleAdsClient.load_from_dict(config)
        ga_service = client.get_service("GoogleAdsService")

        last_day = calendar.monthrange(year, month)[1]
        start_date = f"{year}-{month:02d}-01"
        end_date = f"{year}-{month:02d}-{last_day:02d}"

        print("  Fetching Google Ad creatives...")

        # First fetch ALL image assets for URL lookup
        asset_urls = {}
        asset_names = {}
        all_asset_query = """
            SELECT
                asset.resource_name,
                asset.name,
                asset.image_asset.full_size.url
            FROM asset
            WHERE asset.type = 'IMAGE'
        """
        try:
            asset_response = ga_service.search_stream(customer_id=GOOGLE_CUSTOMER_ID, query=all_asset_query)
            for batch in asset_response:
                for row in batch.results:
                    if row.asset.image_asset.full_size.url:
                        asset_urls[row.asset.resource_name] = row.asset.image_asset.full_size.url
                        asset_names[row.asset.resource_name] = row.asset.name
        except Exception as e:
            print(f"    Warning: Could not fetch asset URLs: {e}")

        # Categorize assets by brand and format based on name
        brand_portrait_assets = {}
        for resource_name, name in asset_names.items():
            if resource_name in asset_urls:
                if '960x1200' in name or '9x16' in name or '9:16' in name:
                    # Extract brand from asset name
                    name_upper = name.upper()
                    for brand in ["SIME", "DAB", "DANFOSS", "MACRO", "TESY", "CALEFFI", "THERMORUM"]:
                        if brand in name_upper:
                            if brand not in brand_portrait_assets:
                                brand_portrait_assets[brand] = []
                            brand_portrait_assets[brand].append(asset_urls[resource_name])
                            break

        # Query for ad group ads with their assets
        query = f"""
            SELECT
                campaign.name,
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                ad_group_ad.ad.responsive_display_ad.marketing_images,
                ad_group_ad.ad.responsive_display_ad.square_marketing_images,
                ad_group_ad.ad.responsive_display_ad.headlines,
                ad_group_ad.ad.responsive_display_ad.descriptions,
                metrics.impressions,
                metrics.cost_micros
            FROM ad_group_ad
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
              AND ad_group_ad.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
            LIMIT 30
        """

        creatives = []
        seen_campaigns = set()
        response = ga_service.search_stream(customer_id=GOOGLE_CUSTOMER_ID, query=query)

        for batch in response:
            for row in batch.results:
                campaign_name = row.campaign.name
                # Deduplicate by campaign name
                if campaign_name in seen_campaigns:
                    continue
                seen_campaigns.add(campaign_name)

                ad = row.ad_group_ad.ad
                rda = ad.responsive_display_ad

                square_images = []
                landscape_images = []
                portrait_images = []

                if rda.square_marketing_images:
                    for img in rda.square_marketing_images:
                        if hasattr(img, 'asset') and img.asset in asset_urls:
                            square_images.append(asset_urls[img.asset])

                if rda.marketing_images:
                    for img in rda.marketing_images:
                        if hasattr(img, 'asset') and img.asset in asset_urls:
                            landscape_images.append(asset_urls[img.asset])

                # Find portrait from name-based detection
                campaign_upper = campaign_name.upper()
                for brand, urls in brand_portrait_assets.items():
                    if brand in campaign_upper:
                        portrait_images = urls[:1]
                        break

                headlines = [h.text for h in rda.headlines] if rda.headlines else []
                descriptions = [d.text for d in rda.descriptions] if rda.descriptions else []

                creatives.append({
                    "campaign_name": campaign_name,
                    "ad_id": str(ad.id),
                    "ad_name": ad.name or campaign_name,
                    "headlines": headlines,
                    "descriptions": descriptions,
                    "square_images": square_images[:1],
                    "landscape_images": landscape_images[:1],
                    "portrait_images": portrait_images[:1],
                    "impressions": row.metrics.impressions,
                    "spend": row.metrics.cost_micros / 1_000_000,
                })

        print(f"  Found {len(creatives)} Google creatives")
        return creatives

    except Exception as e:
        print(f"  Error fetching Google Ads creatives: {e}")
        return []


# =============================================================================
# DATA PROCESSING
# =============================================================================

def get_action_value(actions: list[dict], action_type: str) -> int:
    """Extract value from actions array by action_type."""
    if not actions:
        return 0
    for action in actions:
        if action["action_type"] == action_type:
            return int(action["value"])
    return 0


def process_meta_ads(ads: list[dict], ad_details: list[dict]) -> tuple[list[dict], dict]:
    """Process Meta ads data, derive campaigns, and calculate totals."""
    # Build details lookup
    details_lookup = {}
    for ad in ad_details:
        details_lookup[ad["name"]] = {
            "id": ad.get("id", ""),
            "status": ad.get("effective_status", "unknown").lower().replace("_", " "),
            "story_id": "",
            "creative_id": "",
            "has_video": False,
            "object_type": "PHOTO",
        }
        if "creative" in ad and ad["creative"]:
            creative = ad["creative"]
            details_lookup[ad["name"]]["story_id"] = creative.get("effective_object_story_id", "")
            details_lookup[ad["name"]]["creative_id"] = creative.get("id", "")
            details_lookup[ad["name"]]["object_type"] = creative.get("object_type", "PHOTO")
            details_lookup[ad["name"]]["has_video"] = bool(creative.get("video_id"))

    processed = []
    totals = {"reach": 0, "impressions": 0, "spend": 0, "post_engagement": 0}

    for ad in ads:
        reach = int(ad.get("reach", 0))
        impressions = int(ad.get("impressions", 0))
        spend = float(ad.get("spend", 0))

        if reach == 0 and spend == 0:
            continue

        post_eng = get_action_value(ad.get("actions", []), "post_engagement")
        details = details_lookup.get(ad["ad_name"], {
            "id": "", "status": "unknown", "story_id": "", "creative_id": "", "has_video": False, "object_type": "PHOTO"
        })

        embed_url = get_facebook_embed_url(details["story_id"])
        campaign = derive_campaign(ad["ad_name"])

        # Detect photo vs video
        video_view = get_action_value(ad.get("actions", []), "video_view")
        post_format = "photo"
        ad_name_lower = ad["ad_name"].lower()
        object_type = details.get("object_type", "PHOTO")
        if details["has_video"]:
            post_format = "video"
        elif object_type == "STATUS":
            post_format = "video"
        elif "video" in ad_name_lower or "reel" in ad_name_lower:
            post_format = "video"
        elif video_view > 1000:
            post_format = "video"

        processed.append({
            "ad_name": ad["ad_name"],
            "campaign": campaign,
            "ad_id": details["id"],
            "story_id": details["story_id"],
            "embed_url": embed_url,
            "post_format": post_format,
            "reach": reach,
            "impressions": impressions,
            "cpm": float(ad.get("cpm", 0)),
            "post_engagement": post_eng,
            "spend": spend,
        })

        totals["reach"] += reach
        totals["impressions"] += impressions
        totals["spend"] += spend
        totals["post_engagement"] += post_eng

    # Sort by spend descending
    processed.sort(key=lambda x: x["spend"], reverse=True)
    return processed, totals


MONTH_KEYWORDS = {
    1: ["january", "jan "],
    2: ["february", "feb "],
    3: ["march", "mar "],
    4: ["april", "apr "],
    5: ["may "],
    6: ["june", "jun "],
    7: ["july", "jul "],
    8: ["august", "aug "],
    9: ["september", "sep "],
    10: ["october", "oct "],
    11: ["november", "nov "],
    12: ["december", "dec "],
}


def filter_campaigns_by_month(campaigns: list[dict], month: int) -> list[dict]:
    """Filter campaigns to exclude zero-spend old campaigns from other months.

    Keeps campaigns that:
    - Have spend > 0 (actually spent money in the report period)
    - OR have no month reference and no spend data (Google creatives)

    Removes campaigns with $0 spend that reference a different month.
    """
    other_keywords = []
    for m, kws in MONTH_KEYWORDS.items():
        if m != month:
            other_keywords.extend(kws)

    filtered = []
    for c in campaigns:
        spend = c.get("spend", -1)  # -1 for items without spend (creatives)
        name_lower = c["campaign_name"].lower() + " "
        has_other_month = any(kw in name_lower for kw in other_keywords)

        # Keep if: has real spend, OR doesn't reference another month
        if spend > 0:
            filtered.append(c)
        elif not has_other_month:
            filtered.append(c)

    return filtered


def process_google_campaigns(campaigns: list[dict]) -> tuple[list[dict], dict]:
    """Process Google campaigns and calculate totals."""
    totals = {"impressions": 0, "clicks": 0, "spend": 0}

    for c in campaigns:
        totals["impressions"] += c["impressions"]
        totals["clicks"] += c["clicks"]
        totals["spend"] += c["spend"]

    if totals["impressions"] > 0:
        totals["ctr"] = (totals["clicks"] / totals["impressions"]) * 100
    else:
        totals["ctr"] = 0

    if totals["clicks"] > 0:
        totals["avg_cpc"] = totals["spend"] / totals["clicks"]
    else:
        totals["avg_cpc"] = 0

    return campaigns, totals


# =============================================================================
# BRAND INFO FOR GOOGLE CREATIVES
# =============================================================================

def get_brand_info(campaign_name: str) -> dict:
    """Get brand info (title, description) for Google Ad creative cards."""
    name_upper = campaign_name.upper()
    for brand_key, info in BRAND_DESCRIPTIONS.items():
        if brand_key.upper() in name_upper:
            return info
    return BRAND_DESCRIPTIONS["THERMORUM"]


# =============================================================================
# HTML GENERATION
# =============================================================================

# SVG constants
META_LOGO_SVG = '<svg class="platform-logo" viewBox="0 0 50 20" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="metaGrad" x1="0%" y1="100%" x2="100%" y2="0%"><stop offset="0%" stop-color="#0668E1"/><stop offset="50%" stop-color="#7319E8"/><stop offset="100%" stop-color="#F70A8D"/></linearGradient></defs><text x="0" y="16" font-family="Montserrat, sans-serif" font-size="18" font-weight="800" fill="url(#metaGrad)">Meta</text></svg>'

GOOGLE_LOGO_SVG = '<svg class="platform-logo" viewBox="0 0 272 92" xmlns="http://www.w3.org/2000/svg"><path fill="#4285F4" d="M115.75 47.18c0 12.77-9.99 22.18-22.25 22.18s-22.25-9.41-22.25-22.18C71.25 34.32 81.24 25 93.5 25s22.25 9.32 22.25 22.18zm-9.74 0c0-7.98-5.79-13.44-12.51-13.44S80.99 39.2 80.99 47.18c0 7.9 5.79 13.44 12.51 13.44s12.51-5.55 12.51-13.44z"/><path fill="#EA4335" d="M163.75 47.18c0 12.77-9.99 22.18-22.25 22.18s-22.25-9.41-22.25-22.18c0-12.85 9.99-22.18 22.25-22.18s22.25 9.32 22.25 22.18zm-9.74 0c0-7.98-5.79-13.44-12.51-13.44s-12.51 5.46-12.51 13.44c0 7.9 5.79 13.44 12.51 13.44s12.51-5.55 12.51-13.44z"/><path fill="#FBBC05" d="M209.75 26.34v39.82c0 16.38-9.66 23.07-21.08 23.07-10.75 0-17.22-7.19-19.66-13.07l8.48-3.53c1.51 3.61 5.21 7.87 11.17 7.87 7.31 0 11.84-4.51 11.84-13v-3.19h-.34c-2.18 2.69-6.38 5.04-11.68 5.04-11.09 0-21.25-9.66-21.25-22.09 0-12.52 10.16-22.26 21.25-22.26 5.29 0 9.49 2.35 11.68 4.96h.34v-3.61h9.25zm-8.56 20.92c0-7.81-5.21-13.52-11.84-13.52-6.72 0-12.35 5.71-12.35 13.52 0 7.73 5.63 13.36 12.35 13.36 6.63 0 11.84-5.63 11.84-13.36z"/><path fill="#4285F4" d="M225 3v65h-9.5V3h9.5z"/><path fill="#34A853" d="M262.02 54.48l7.56 5.04c-2.44 3.61-8.32 9.83-18.48 9.83-12.6 0-22.01-9.74-22.01-22.18 0-13.19 9.49-22.18 20.92-22.18 11.51 0 17.14 9.16 18.98 14.11l1.01 2.52-29.65 12.28c2.27 4.45 5.8 6.72 10.75 6.72 4.96 0 8.4-2.44 10.92-6.14zm-23.27-7.98l19.82-8.23c-1.09-2.77-4.37-4.7-8.23-4.7-4.95 0-11.84 4.37-11.59 12.93z"/><path fill="#EA4335" d="M35.29 41.41V32H67c.31 1.64.47 3.58.47 5.68 0 7.06-1.93 15.79-8.15 22.01-6.05 6.3-13.78 9.66-24.02 9.66C16.32 69.35.36 53.89.36 34.91.36 15.93 16.32.47 35.3.47c10.5 0 17.98 4.12 23.6 9.49l-6.64 6.64c-4.03-3.78-9.49-6.72-16.97-6.72-13.86 0-24.7 11.17-24.7 25.03 0 13.86 10.84 25.03 24.7 25.03 8.99 0 14.11-3.61 17.39-6.89 2.66-2.66 4.41-6.46 5.1-11.65l-22.49.01z"/></svg>'

FOOTER_BRAND = '<div class="brand"><span class="yellow">MARTIVI</span> <span class="blue">DIGITAL</span></div>'


def generate_html_report(
    meta_ads: list[dict],
    meta_totals: dict,
    google_campaigns: list[dict],
    google_totals: dict,
    google_creatives: list[dict],
    month: int,
    year: int,
) -> str:
    """Generate the HTML report matching December 2025 template."""

    period = f"{MONTH_NAMES[month]} {year}"

    def fmt(n):
        return f"{n:,.0f}"

    def fmt_money(n):
        return f"${n:,.2f}"

    # --- Meta Table Rows ---
    meta_rows = ""
    for ad in meta_ads:
        meta_rows += f'            <tr><td>{ad["ad_name"]}</td><td>{ad["campaign"]}</td><td class="num">{fmt(ad["reach"])}</td><td class="num">{fmt(ad["impressions"])}</td><td class="num">{fmt(ad["post_engagement"])}</td><td class="num">${ad["cpm"]:.2f}</td><td class="num currency">${ad["spend"]:.0f}</td></tr>\n'

    # --- Google Table Rows ---
    google_rows = ""
    for c in google_campaigns:
        google_rows += f'            <tr><td>{c["campaign_name"]}</td><td class="num">{fmt(c["impressions"])}</td><td class="num">{fmt(c["clicks"])}</td><td class="num">{c["ctr"]:.2f}%</td><td class="num">${c["average_cpc"]:.2f}</td><td class="num currency">{fmt_money(c["spend"])}</td></tr>\n'

    # --- Meta Chart Data ---
    top_imp = sorted(meta_ads, key=lambda x: x["impressions"], reverse=True)[:10]
    top_reach = sorted(meta_ads, key=lambda x: x["reach"], reverse=True)[:10]
    meta_imp_labels = json.dumps([a["ad_name"][:25] for a in top_imp])
    meta_imp_data = [a["impressions"] for a in top_imp]
    meta_reach_labels = json.dumps([a["ad_name"][:25] for a in top_reach])
    meta_reach_data = [a["reach"] for a in top_reach]

    # --- Google Chart Data ---
    top_g_imp = sorted(google_campaigns, key=lambda x: x["impressions"], reverse=True)[:10]
    top_g_clicks = sorted(google_campaigns, key=lambda x: x["clicks"], reverse=True)[:10]
    g_imp_labels = json.dumps([c["campaign_name"][:30] for c in top_g_imp]) if top_g_imp else '["No data"]'
    g_imp_data = [c["impressions"] for c in top_g_imp] if top_g_imp else [0]
    g_click_labels = json.dumps([c["campaign_name"][:30] for c in top_g_clicks]) if top_g_clicks else '["No data"]'
    g_click_data = [c["clicks"] for c in top_g_clicks] if top_g_clicks else [0]

    # --- Meta Preview Slides (separate photo and video) ---
    ads_with_embeds = [ad for ad in meta_ads if ad.get("embed_url")]
    photo_ads = [ad for ad in ads_with_embeds if ad.get("post_format") == "photo"]
    video_ads = [ad for ad in ads_with_embeds if ad.get("post_format") == "video"]
    meta_preview_slides = ""

    # Photo slides: 4 per slide (2x2 grid)
    for i in range(0, len(photo_ads), 4):
        batch = photo_ads[i:i+4]
        start_num = i + 1
        end_num = min(i + 4, len(photo_ads))

        cards = ""
        for ad in batch:
            cards += f'''
        <div class="preview-card">
            <div class="header">
                <h4>{ad["ad_name"]}</h4>
                <span class="spend">${ad["spend"]:.2f}</span>
            </div>
            <div class="iframe-wrap photo">
                <iframe src="{ad["embed_url"]}" scrolling="no" frameborder="0" allowfullscreen="true" allow="autoplay; clipboard-write; encrypted-media; picture-in-picture; web-share"></iframe>
            </div>
        </div>'''

        meta_preview_slides += f'''
<!-- Slide: Meta Photo Ads ({start_num}-{end_num} of {len(photo_ads)}) -->
<div class="slide">
    <div class="section-header">
        {META_LOGO_SVG}
        <h2>Photo Ads ({start_num}-{end_num} of {len(photo_ads)})</h2>
    </div>
    <div class="preview-grid">{cards}
    </div>
    <div class="footer">{FOOTER_BRAND}<div>{period}</div></div>
</div>
'''

    # Video slides: 2 per slide (side by side)
    for i in range(0, len(video_ads), 2):
        batch = video_ads[i:i+2]
        start_num = i + 1
        end_num = min(i + 2, len(video_ads))
        is_single = len(batch) == 1

        cards = ""
        for ad in batch:
            cards += f'''
        <div class="preview-card">
            <div class="header">
                <h4>{ad["ad_name"]}</h4>
                <span class="spend">${ad["spend"]:.2f}</span>
            </div>
            <div class="iframe-wrap video">
                <iframe src="{ad["embed_url"]}" scrolling="no" frameborder="0" allowfullscreen="true" allow="autoplay; clipboard-write; encrypted-media; picture-in-picture; web-share"></iframe>
            </div>
        </div>'''

        grid_class = "preview-grid videos single" if is_single else "preview-grid videos"
        meta_preview_slides += f'''
<!-- Slide: Meta Video Ads ({start_num}-{end_num} of {len(video_ads)}) -->
<div class="slide">
    <div class="section-header">
        {META_LOGO_SVG}
        <h2>Video Ads ({start_num}-{end_num} of {len(video_ads)})</h2>
    </div>
    <div class="{grid_class}">{cards}
    </div>
    <div class="footer">{FOOTER_BRAND}<div>{period}</div></div>
</div>
'''

    # --- Google Creative Slides ---
    google_creative_slides = ""
    if google_creatives:
        for i in range(0, len(google_creatives), 3):
            batch = google_creatives[i:i+3]
            start_num = i + 1
            end_num = min(i + 3, len(google_creatives))

            sections = ""
            for creative in batch:
                brand_info = get_brand_info(creative["campaign_name"])
                headline = creative["headlines"][0] if creative["headlines"] else brand_info["title"]
                description = creative["descriptions"][0] if creative["descriptions"] else brand_info["desc"]
                short_name = brand_info["short"]
                sq_img = creative["square_images"][0] if creative["square_images"] else ""
                ls_img = creative["landscape_images"][0] if creative["landscape_images"] else ""
                pt_img = creative["portrait_images"][0] if creative.get("portrait_images") else ""

                format_items = ""
                if sq_img:
                    format_items += f'''
            <div class="format-item"><div class="format-label">square</div>
                <div class="g-card sq"><img src="{sq_img}"><div class="content"><span class="ad-tag">Ad</span><h5>{headline}</h5><p>{description}</p></div></div>
            </div>'''
                if ls_img:
                    format_items += f'''
            <div class="format-item"><div class="format-label">landscape</div>
                <div class="g-card ls"><img src="{ls_img}"><div class="content"><span class="ad-tag">Ad</span><h5>{headline}</h5><p>{description}</p></div></div>
            </div>'''
                if pt_img:
                    format_items += f'''
            <div class="format-item"><div class="format-label">portrait</div>
                <div class="g-card pt"><img src="{pt_img}"><div class="content"><span class="ad-tag">Ad</span><h5>{short_name}</h5><p>{description}</p></div></div>
            </div>'''

                if not format_items:
                    format_items = f'''
            <div class="format-item"><div class="format-label">Display Ad</div>
                <div class="g-card sq"><div class="content"><span class="ad-tag">Ad</span><h5>{headline}</h5><p>{description}</p></div></div>
            </div>'''

                sections += f'''
    <div class="google-section">
        <h4>{creative["campaign_name"]}</h4>
        <div class="stats">Impressions: <span>{fmt(creative["impressions"])}</span> | Spend: <span>{fmt_money(creative["spend"])}</span></div>
        <div class="formats-row">{format_items}
        </div>
    </div>'''

            google_creative_slides += f'''
<!-- Slide: Google Creatives ({start_num}-{end_num} of {len(google_creatives)}) -->
<div class="slide">
    <div class="section-header">
        {GOOGLE_LOGO_SVG}
        <h2>Ad Creatives ({start_num}-{end_num} of {len(google_creatives)})</h2>
    </div>{sections}
    <div class="footer">{FOOTER_BRAND}<div>{period}</div></div>
</div>
'''

    # --- Assemble Full HTML ---
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Thermorum - {period} Social Media Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: 'Montserrat', sans-serif; background: #191919; color: white; }}
        .slide {{ min-height: 100vh; padding: 50px 60px; display: flex; flex-direction: column; border-bottom: 3px solid #262626; position: relative; }}
        .title-slide {{ justify-content: center; align-items: center; text-align: center; background: linear-gradient(135deg, #0c0c0c 0%, #191919 100%); }}
        .title-slide h1 {{ font-size: 72px; font-weight: 800; margin-bottom: 20px; letter-spacing: 4px; }}
        .title-slide h1 .yellow {{ color: #ffc711; }}
        .title-slide h1 .cyan {{ color: #3cc5ee; }}
        .title-slide h2 {{ font-size: 28px; color: #888; margin-bottom: 40px; }}
        .title-slide .period {{ font-size: 22px; color: #3cc5ee; border: 2px solid #3cc5ee; padding: 12px 35px; border-radius: 50px; }}
        .section-header {{ display: flex; align-items: center; gap: 20px; margin-bottom: 25px; }}
        .section-header h2 {{ font-size: 28px; font-weight: 700; text-transform: uppercase; letter-spacing: 2px; }}
        .platform-logo {{ height: 28px; width: auto; }}
        .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 25px; }}
        .stat-card {{ background: #262626; border-radius: 12px; padding: 22px; text-align: center; border-left: 4px solid #ffc711; }}
        .stat-card.cyan {{ border-left-color: #3cc5ee; }}
        .stat-card .value {{ font-size: 32px; font-weight: 800; color: #ffc711; }}
        .stat-card.cyan .value {{ color: #3cc5ee; }}
        .stat-card .label {{ font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 1px; margin-top: 5px; }}

        table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-bottom: 25px; background: #1e1e1e; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
        thead {{ background: linear-gradient(135deg, #262626 0%, #1a1a1a 100%); }}
        th {{ padding: 16px 14px; text-align: left; font-size: 11px; text-transform: uppercase; color: #ffc711; border-bottom: 2px solid #ffc711; font-weight: 700; letter-spacing: 0.5px; }}
        th:first-child {{ border-radius: 12px 0 0 0; }}
        th:last-child {{ border-radius: 0 12px 0 0; }}
        tbody tr {{ transition: background 0.2s ease; }}
        td {{ padding: 14px; border-bottom: 1px solid #2a2a2a; }}
        tbody tr:last-child td {{ border-bottom: none; }}
        tbody tr:last-child td:first-child {{ border-radius: 0 0 0 12px; }}
        tbody tr:last-child td:last-child {{ border-radius: 0 0 12px 0; }}
        tr:hover {{ background: rgba(255,199,17,0.08); }}
        tr:nth-child(even) {{ background: rgba(255,255,255,0.02); }}
        tr:nth-child(even):hover {{ background: rgba(255,199,17,0.08); }}
        .num {{ text-align: right; font-family: 'SF Mono', 'Courier New', monospace; font-weight: 600; }}
        .currency {{ color: #3cc5ee; font-weight: 700; font-size: 14px; }}

        .chart-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 25px; margin-top: 25px; }}
        .chart-container {{ background: linear-gradient(135deg, #262626 0%, #1e1e1e 100%); border-radius: 12px; padding: 25px; box-shadow: 0 4px 20px rgba(0,0,0,0.25); border: 1px solid #333; }}
        .preview-grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 15px; flex: 1; }}
        .preview-grid.videos {{ grid-template-columns: repeat(2, 1fr); }}
        .preview-grid.videos.single {{ grid-template-columns: 1fr; max-width: 50%; margin: 0 auto; }}
        .preview-card {{ background: #f5f5f5; border-radius: 10px; padding: 10px; overflow: hidden; }}
        .preview-card .header {{ display: flex; justify-content: space-between; margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid #ddd; }}
        .preview-card h4 {{ font-size: 10px; color: #333; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 600; }}
        .preview-card .spend {{ color: #0066cc; font-weight: 700; font-size: 12px; }}
        .preview-card .iframe-wrap {{ width: 100%; overflow: hidden; border-radius: 8px; position: relative; }}
        .preview-card .iframe-wrap.photo {{ aspect-ratio: 4/5; max-width: 80%; margin: 0 auto; }}
        .preview-card .iframe-wrap.video {{ aspect-ratio: 9/16; }}
        .preview-card iframe {{ position: absolute; top: 0; left: 0; width: 100%; height: 115%; border: none; }}
        .google-section {{ background: #262626; border-radius: 12px; padding: 20px; margin-bottom: 20px; }}
        .google-section h4 {{ font-size: 14px; margin-bottom: 3px; }}
        .google-section .stats {{ font-size: 11px; color: #888; margin-bottom: 15px; }}
        .google-section .stats span {{ color: #3cc5ee; }}
        .formats-row {{ display: flex; gap: 20px; flex-wrap: wrap; justify-content: center; }}
        .format-item {{ text-align: center; }}
        .format-label {{ font-size: 10px; color: #ffc711; text-transform: uppercase; margin-bottom: 8px; }}
        .g-card {{ background: #1e1e1e; border-radius: 8px; overflow: hidden; color: #fff; box-shadow: 0 4px 12px rgba(0,0,0,0.3); }}
        .g-card img {{ width: 100%; display: block; object-fit: cover; }}
        .g-card .content {{ padding: 10px; }}
        .g-card .ad-tag {{ background: #333; color: #888; font-size: 9px; padding: 2px 5px; border-radius: 3px; display: inline-block; margin-bottom: 4px; }}
        .g-card h5 {{ font-size: 11px; color: #ffc711; margin-bottom: 3px; }}
        .g-card p {{ font-size: 9px; color: #ccc; }}
        .sq {{ width: 180px; }} .sq img {{ height: 180px; }}
        .ls {{ width: 250px; }} .ls img {{ height: 131px; }}
        .pt {{ width: 140px; }} .pt img {{ height: 233px; }}
        .footer {{ position: absolute; bottom: 20px; left: 60px; right: 60px; display: flex; justify-content: space-between; font-size: 10px; color: #555; }}
        .footer .brand {{ font-weight: 700; }}
        .footer .brand .yellow {{ color: #ffc711; }}
        .footer .brand .blue {{ color: #3cc5ee; font-weight: 300; }}

        @media print {{
            * {{ -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; color-adjust: exact !important; }}
            html, body {{ width: 1920px; margin: 0; padding: 0; background: #191919; }}
            .slide {{ width: 1920px; height: auto !important; min-height: auto !important; max-height: none !important; page-break-after: always; page-break-inside: avoid; break-after: page; break-inside: avoid; overflow: visible !important; box-sizing: border-box; padding-bottom: 60px; }}
            .slide:last-child {{ page-break-after: avoid; }}
            .footer {{ position: relative !important; bottom: auto !important; margin-top: 40px; }}
            .iframe-wrap {{ display: none; }}
            .preview-card::after {{ content: "View on web version"; color: #666; font-size: 14px; display: block; text-align: center; padding: 20px; }}
        }}
    </style>
</head>
<body>

<!-- Slide 1: Title -->
<div class="slide title-slide">
    <h1 style="color: #ffc711;">THERMORUM</h1>
    <h2>Social Media Performance Report</h2>
    <div class="period">{period}</div>
    <div style="position: absolute; bottom: 40px; font-size: 16px; letter-spacing: 1px;">by <span style="color: #ffc711; font-weight: 700;">MARTIVI</span> <span style="color: #3cc5ee; font-weight: 300;">DIGITAL</span></div>
</div>

<!-- Slide 2: Meta Overview -->
<div class="slide">
    <div class="section-header">
        {META_LOGO_SVG}
        <h2>Performance Overview</h2>
    </div>
    <div class="stats-grid">
        <div class="stat-card"><div class="value">{fmt(meta_totals["reach"])}</div><div class="label">Total Reach</div></div>
        <div class="stat-card cyan"><div class="value">{fmt(meta_totals["impressions"])}</div><div class="label">Total Impressions</div></div>
        <div class="stat-card"><div class="value">{fmt(meta_totals["post_engagement"])}</div><div class="label">Post Engagements</div></div>
        <div class="stat-card cyan"><div class="value">${meta_totals["spend"]:,.0f}</div><div class="label">Total Spend</div></div>
    </div>
    <table>
        <thead>
            <tr><th>Ad Name</th><th>Campaign</th><th class="num">Reach</th><th class="num">Impressions</th><th class="num">Engagements</th><th class="num">CPM</th><th class="num">Spend</th></tr>
        </thead>
        <tbody>
{meta_rows}        </tbody>
    </table>
    <div class="chart-row">
        <div class="chart-container"><canvas id="metaImpressions"></canvas></div>
        <div class="chart-container"><canvas id="metaReach"></canvas></div>
    </div>
    <div class="footer">{FOOTER_BRAND}<div>{period}</div></div>
</div>

<!-- Slide 3: Google Overview -->
<div class="slide">
    <div class="section-header">
        {GOOGLE_LOGO_SVG}
        <h2>Performance Overview</h2>
    </div>
    <div class="stats-grid">
        <div class="stat-card"><div class="value">{fmt(google_totals.get("impressions", 0))}</div><div class="label">Total Impressions</div></div>
        <div class="stat-card cyan"><div class="value">{fmt(google_totals.get("clicks", 0))}</div><div class="label">Total Clicks</div></div>
        <div class="stat-card"><div class="value">{google_totals.get("ctr", 0):.2f}%</div><div class="label">Avg. CTR</div></div>
        <div class="stat-card cyan"><div class="value">{fmt_money(google_totals.get("spend", 0))}</div><div class="label">Total Spend</div></div>
    </div>
    <table>
        <thead>
            <tr><th>Campaign</th><th class="num">Impressions</th><th class="num">Clicks</th><th class="num">CTR</th><th class="num">Avg. CPC</th><th class="num">Spend</th></tr>
        </thead>
        <tbody>
{google_rows}        </tbody>
    </table>
    <div class="chart-row">
        <div class="chart-container"><canvas id="googleImpressions"></canvas></div>
        <div class="chart-container"><canvas id="googleClicks"></canvas></div>
    </div>
    <div class="footer">{FOOTER_BRAND}<div>{period}</div></div>
</div>

{meta_preview_slides}
{google_creative_slides}

<script>
Chart.defaults.color = '#888';
Chart.defaults.borderColor = 'rgba(255,199,17,0.1)';
const Y = '#ffc711', C = '#3cc5ee';

// Meta: Top Ads by Impressions
new Chart(document.getElementById('metaImpressions'), {{
    type: 'bar',
    data: {{
        labels: {meta_imp_labels},
        datasets: [{{ label: 'Impressions', data: {meta_imp_data}, backgroundColor: Y, borderRadius: 6, borderSkipped: false }}]
    }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: true, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'Top Ads by Impressions', font: {{ family: 'Montserrat', size: 14, weight: 'bold' }}, color: Y, padding: {{ bottom: 15 }}}}}},
        scales: {{ x: {{ grid: {{ color: '#333' }}, ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }}}}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }}}}}}}}
    }}
}});

// Meta: Top Ads by Reach
new Chart(document.getElementById('metaReach'), {{
    type: 'bar',
    data: {{
        labels: {meta_reach_labels},
        datasets: [{{ label: 'Reach', data: {meta_reach_data}, backgroundColor: C, borderRadius: 6, borderSkipped: false }}]
    }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: true, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'Top Ads by Reach', font: {{ family: 'Montserrat', size: 14, weight: 'bold' }}, color: C, padding: {{ bottom: 15 }}}}}},
        scales: {{ x: {{ grid: {{ color: '#333' }}, ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }}}}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }}}}}}}}
    }}
}});

// Google: Campaigns by Impressions
new Chart(document.getElementById('googleImpressions'), {{
    type: 'bar',
    data: {{
        labels: {g_imp_labels},
        datasets: [{{ label: 'Impressions', data: {g_imp_data}, backgroundColor: Y, borderRadius: 6, borderSkipped: false }}]
    }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: true, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'Campaigns by Impressions', font: {{ family: 'Montserrat', size: 14, weight: 'bold' }}, color: Y, padding: {{ bottom: 15 }}}}}},
        scales: {{ x: {{ grid: {{ color: '#333' }}, ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }}}}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }}}}}}}}
    }}
}});

// Google: Campaigns by Clicks
new Chart(document.getElementById('googleClicks'), {{
    type: 'bar',
    data: {{
        labels: {g_click_labels},
        datasets: [{{ label: 'Clicks', data: {g_click_data}, backgroundColor: C, borderRadius: 6, borderSkipped: false }}]
    }},
    options: {{ indexAxis: 'y', responsive: true, maintainAspectRatio: true, plugins: {{ legend: {{ display: false }}, title: {{ display: true, text: 'Campaigns by Clicks', font: {{ family: 'Montserrat', size: 14, weight: 'bold' }}, color: C, padding: {{ bottom: 15 }}}}}},
        scales: {{ x: {{ grid: {{ color: '#333' }}, ticks: {{ callback: v => v >= 1000 ? (v/1000)+'K' : v }}}}, y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 10 }}}}}}}}
    }}
}});
</script>
</body>
</html>'''

    return html


# =============================================================================
# MAIN
# =============================================================================

def generate_report(month: int, year: int):
    """Main function to generate a monthly report."""
    period = f"{MONTH_NAMES[month]} {year}"
    month_lower = MONTH_NAMES[month].lower()
    output_file = OUTPUT_DIR / f"thermorum_{month_lower}_{year}_report.html"

    print(f"\n{'='*60}")
    print(f"  Generating Thermorum {period} Report")
    print(f"{'='*60}\n")

    # 1. Fetch Meta Ads data
    print("[1/5] Fetching Meta Ads insights...")
    meta_raw = fetch_meta_ads_monthly(year, month)

    # 2. Fetch Meta ad details (for embed URLs)
    print("[2/5] Fetching Meta ad details...")
    meta_details = fetch_meta_ad_details()

    # 3. Process Meta data
    print("[3/5] Processing Meta data...")
    meta_ads, meta_totals = process_meta_ads(meta_raw, meta_details)
    # Filter Meta ads to only those matching the report month
    meta_ads_before = len(meta_ads)
    meta_ads = filter_campaigns_by_month(
        [{"campaign_name": a["ad_name"], **a} for a in meta_ads], month
    )
    # Remove the temporary campaign_name key
    for a in meta_ads:
        del a["campaign_name"]
    if len(meta_ads) < meta_ads_before:
        # Recalculate totals after filtering
        meta_totals = {"reach": 0, "impressions": 0, "spend": 0, "post_engagement": 0}
        for a in meta_ads:
            meta_totals["reach"] += a["reach"]
            meta_totals["impressions"] += a["impressions"]
            meta_totals["spend"] += a["spend"]
            meta_totals["post_engagement"] += a["post_engagement"]
    print(f"  {len(meta_ads)} ads ({meta_ads_before - len(meta_ads)} filtered from other months), Total spend: ${meta_totals['spend']:.2f}")

    # 4. Fetch Google Ads data
    print("[4/5] Fetching Google Ads data...")
    google_raw = fetch_google_campaigns_monthly(year, month)
    google_before = len(google_raw)
    google_raw = filter_campaigns_by_month(google_raw, month)
    google_campaigns, google_totals = process_google_campaigns(google_raw)
    print(f"  {len(google_campaigns)} campaigns ({google_before - len(google_campaigns)} filtered from other months), Total spend: ${google_totals['spend']:.2f}")

    # 5. Fetch Google Ad creatives
    print("[5/5] Fetching Google Ad creatives...")
    google_creatives = fetch_google_ad_creatives_monthly(year, month)
    google_creatives = filter_campaigns_by_month(google_creatives, month)

    # Generate HTML
    print("\nGenerating HTML report...")
    html = generate_html_report(
        meta_ads=meta_ads,
        meta_totals=meta_totals,
        google_campaigns=google_campaigns,
        google_totals=google_totals,
        google_creatives=google_creatives,
        month=month,
        year=year,
    )

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\nReport saved to: {output_file}")
    print(f"  Meta Ads: {len(meta_ads)} ads | ${meta_totals['spend']:.0f} spend")
    print(f"  Google Ads: {len(google_campaigns)} campaigns | ${google_totals['spend']:.0f} spend")
    print(f"  Meta Previews: {len([a for a in meta_ads if a.get('embed_url')])} embeds")
    print(f"  Google Creatives: {len(google_creatives)} creatives")
    print(f"\nDone!")

    return output_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Thermorum monthly social media report")
    parser.add_argument("--month", "-m", type=int, required=True, help="Month number (1-12)")
    parser.add_argument("--year", "-y", type=int, required=True, help="Year (e.g. 2026)")
    args = parser.parse_args()

    if args.month < 1 or args.month > 12:
        print("Error: Month must be between 1 and 12")
        exit(1)

    generate_report(args.month, args.year)
