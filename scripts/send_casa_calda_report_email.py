#!/usr/bin/env python3
"""Send a Casa Calda monthly-report notification email over SMTP.

Reads env:
  CASA_CALDA_REPORT_RECIPIENT  (required — the To: address)
  SMTP_HOST                    (required)
  SMTP_PORT                    (default 587)
  SMTP_USER                    (required)
  SMTP_PASSWORD                (required)
  SENDER_EMAIL                 (default: reports@casacalda.com)

Usage:
  python3 scripts/send_report_email.py --year 2026 --month 7
  python3 scripts/send_report_email.py --period 2026-07

Uses stdlib only (smtplib + email.message).  Does not print credentials or
env values on failure.  Sends a UTF-8 plain-text message with a Georgian
subject + body pointing to https://reports.casacalda.com/casa-calda/<slug>.
"""

from __future__ import annotations

import argparse
import os
import re
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

MONTH_KA = [
    "", "იანვარი", "თებერვალი", "მარტი", "აპრილი", "მაისი", "ივნისი",
    "ივლისი", "აგვისტო", "სექტემბერი", "ოქტომბერი", "ნოემბერი", "დეკემბერი",
]
MONTH_EN_LOWER = [
    "", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

REPORTS_BASE = "https://reports.casacalda.com"
DEFAULT_SENDER = "reports@casacalda.com"


def _parse_period(period: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", period)
    if not m:
        raise argparse.ArgumentTypeError(f"invalid --period: {period!r} (want YYYY-MM)")
    return int(m.group(1)), int(m.group(2))


def build_message(year: int, month: int, sender: str, recipient: str) -> EmailMessage:
    slug = f"{MONTH_EN_LOWER[month]}-{year}"
    month_ka = f"{MONTH_KA[month]} {year}"
    subject = f"REPORT — Casa Calda — {month_ka} სოციალური მედიის ანგარიში მზადაა"
    body = (
        "მოგესალმებით,\n\n"
        f"{month_ka}-ის სოციალური მედიის ანგარიში ხელმისაწვდომია აქ:\n"
        f"{REPORTS_BASE}/casa-calda/{slug}\n\n"
        "დამატებითი კითხვების შემთხვევაში დაგვიკავშირდით.\n\n"
        "Casa Calda × Martivi Digital"
    )
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="casacalda.com")
    msg.set_content(body, subtype="plain", charset="utf-8")
    return msg


def send(msg: EmailMessage) -> None:
    host = os.environ.get("SMTP_HOST") or ""
    port_raw = os.environ.get("SMTP_PORT") or ""
    port = int(port_raw) if port_raw.strip() else 587
    user = os.environ.get("SMTP_USER") or ""
    password = os.environ.get("SMTP_PASSWORD") or ""
    if not host or not user or not password:
        missing = [k for k, v in (("SMTP_HOST", host), ("SMTP_USER", user), ("SMTP_PASSWORD", password)) if not v]
        raise SystemExit(f"missing env: {', '.join(missing)} — add them as GitHub secrets")

    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.ehlo()
            s.login(user, password)
            s.send_message(msg)


def main() -> int:
    p = argparse.ArgumentParser(description="Send Casa Calda monthly report email")
    p.add_argument("--year", type=int)
    p.add_argument("--month", type=int)
    p.add_argument("--period", type=str, help="alternative: YYYY-MM")
    p.add_argument("--to", type=str, help="override CASA_CALDA_REPORT_RECIPIENT")
    p.add_argument("--dry-run", action="store_true",
                   help="print the composed message and exit without sending")
    args = p.parse_args()

    if args.period:
        year, month = _parse_period(args.period)
    else:
        if not args.year or not args.month:
            p.error("--year and --month required (or --period YYYY-MM)")
        year, month = args.year, args.month
    if not 1 <= month <= 12:
        p.error("--month must be 1..12")

    recipient = args.to or os.environ.get("CASA_CALDA_REPORT_RECIPIENT")
    if not recipient:
        print("CASA_CALDA_REPORT_RECIPIENT not set and --to not supplied; skipping.",
              file=sys.stderr)
        return 0

    # Sender: SENDER_EMAIL env → SMTP_USER (the auth'd mailbox) → DEFAULT_SENDER.
    # Aligning From with the SMTP-auth'd mailbox is what passes SPF cleanly.
    sender = (os.environ.get("SENDER_EMAIL") or "").strip() \
             or (os.environ.get("SMTP_USER") or "").strip() \
             or DEFAULT_SENDER
    msg = build_message(year, month, sender, recipient)

    if args.dry_run:
        print(f"From: {sender}")
        print(f"To:   {recipient}")
        print(f"Subject: {msg['Subject']}")
        print("---")
        print(msg.get_content())
        return 0

    send(msg)
    print(f"Sent to {recipient} — {msg['Subject']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
