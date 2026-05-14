#!/usr/bin/env python3
"""Send the Thermorum monthly report email to mariam.kv@thermorum.com.

Uses raw Google OAuth refresh token (no MAIA dependency).
Reads credentials.json + token.json from config/credentials/ at repo root.
"""

from __future__ import annotations

import argparse
import base64
import json
from email.mime.text import MIMEText
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

REPO_ROOT = Path(__file__).resolve().parents[1]
CREDS_DIR = REPO_ROOT / "config" / "credentials"

RECIPIENT = "mariam.kv@thermorum.com"
BASE_URL = "https://martivi-presentations.vercel.app"

MONTH_EN = ["", "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December"]
MONTH_KA = ["", "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
            "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი"]


def gmail_service():
    token_data = json.loads((CREDS_DIR / "token.json").read_text())
    creds = Credentials.from_authorized_user_info(token_data,
        scopes=["https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.compose"])
    if not creds.valid:
        creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--month", type=int, required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--to", default=RECIPIENT)
    args = p.parse_args()

    slug = MONTH_EN[args.month].lower()
    link = f"{BASE_URL}/thermorum/{slug}-{args.year}"
    subject = f"Thermorum - სოციალური მედიის რეპორტი - {MONTH_KA[args.month]} {args.year}"
    body = (
        "გამარჯობა მარიამ,\n\n"
        f"{MONTH_KA[args.month]} {args.year}-ის სოციალური მედიის რეპორტი მზადაა "
        "და ატვირთულია სერვერზე.\n\n"
        f"ლინკი: {link}\n\n"
        "რეპორტი მოიცავს Meta Ads-ისა და Google Ads-ის შედეგებს — "
        "სტატისტიკას ბრენდების მიხედვით, კრეატივებსა და კამპანიების სრულ ცხრილს.\n\n"
        "ნებისმიერი კითხვის შემთხვევაში მომწერე.\n\n"
        "წარმატებები,\n"
        "გიორგი"
    )

    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = args.to
    msg["subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    service = gmail_service()
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    print(f"Email sent to {args.to} (id={sent.get('id')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
