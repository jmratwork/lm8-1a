#!/usr/bin/env python3
"""
PUC2-Sub Case 2a — Phishing Training Scoring Engine

Fetches GoPhish campaign results, computes per-trainee scores against the
learning objectives defined in training_linear.json (Step 6), and upserts
results into the rep_reporting PostgreSQL database for Grafana visualisation.

Scoring model:
  detection_accuracy      40 pts  trainee reported the phishing email
  report_completeness     30 pts  incident report submitted (GoPhish reported flag)
  time_to_report          20 pts  inversely proportional to minutes between send and report
  no_click_bonus          10 pts  trainee never clicked the phishing link

Traffic light:
  green   total >= 70
  amber   total 40–69
  red     total < 40

Usage:
  export GOPHISH_API_KEY=<key>          # GoPhish admin → Account Settings → API Key
  python3 score_campaign.py <campaign_id>

Optional env vars:
  GOPHISH_HOST  default: http://phishing-simulator.internal:3333
  DB_HOST       default: localhost
  DB_PORT       default: 5432
  DB_NAME       default: rep_reporting
  DB_USER       default: rep_reporting
  DB_PASS       default: changeme
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    import psycopg2
    from psycopg2.extras import execute_values
except ImportError:
    sys.exit("psycopg2 not available. Install with: apt-get install python3-psycopg2")

GOPHISH_HOST = os.environ.get("GOPHISH_HOST", "http://phishing-simulator.internal:3333")
GOPHISH_API_KEY = os.environ.get("GOPHISH_API_KEY", "")
DB_DSN = {
    "host":     os.environ.get("DB_HOST",   "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME",   "rep_reporting"),
    "user":     os.environ.get("DB_USER",   "rep_reporting"),
    "password": os.environ.get("DB_PASS",   "changeme"),
}


def _api_get(path):
    req = Request(f"{GOPHISH_HOST}{path}", headers={"Authorization": GOPHISH_API_KEY})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())
    except HTTPError as exc:
        sys.exit(f"GoPhish returned HTTP {exc.code} for {path}")
    except URLError as exc:
        sys.exit(f"Cannot reach GoPhish at {GOPHISH_HOST}: {exc.reason}")


def _parse_dt(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _score(result, events_by_email, campaign_id, campaign_name):
    """Apply the training_linear.json scoring model to one GoPhish result."""
    email     = result.get("email", "")
    status    = result.get("status", "")
    reported  = result.get("reported", False)
    send_date = _parse_dt(result.get("send_date"))

    events = events_by_email.get(email, [])

    clicked = submitted = False
    reported_at = None
    for ev in events:
        msg = ev.get("message", "")
        if msg in ("Clicked Link", "Submitted Data"):
            clicked = True
        if msg == "Submitted Data":
            submitted = True
        if msg == "Email Reported" and reported_at is None:
            reported_at = _parse_dt(ev.get("time"))

    # — detection accuracy (40 pts) —
    if reported:
        s_detection = 40
    elif status == "Email Opened" and not clicked:
        s_detection = 20
    elif status == "Email Sent":
        s_detection = 10
    else:
        s_detection = 0

    # — report completeness (30 pts) —
    s_report = 30 if reported else 0

    # — time-to-report (20 pts) —
    time_minutes = None
    if reported and reported_at and send_date:
        time_minutes = round((reported_at - send_date).total_seconds() / 60, 2)
        if time_minutes <= 5:
            s_time = 20
        elif time_minutes <= 15:
            s_time = 15
        elif time_minutes <= 30:
            s_time = 10
        else:
            s_time = 5
    else:
        s_time = 0

    # — no-click bonus (10 pts) —
    s_no_click = 10 if not clicked else 0

    total = s_detection + s_report + s_time + s_no_click

    if total >= 70:
        traffic_light = "green"
    elif total >= 40:
        traffic_light = "amber"
    else:
        traffic_light = "red"

    return {
        "campaign_id":               campaign_id,
        "campaign_name":             campaign_name,
        "email":                     email,
        "first_name":                result.get("first_name", ""),
        "last_name":                 result.get("last_name", ""),
        "status":                    status,
        "reported":                  reported,
        "clicked":                   clicked,
        "submitted_data":            submitted,
        "send_date":                 send_date,
        "reported_at":               reported_at,
        "time_to_report_minutes":    time_minutes,
        "score_detection_accuracy":  s_detection,
        "score_report_completeness": s_report,
        "score_time_to_report":      s_time,
        "score_no_click_bonus":      s_no_click,
        "score_total":               total,
        "traffic_light":             traffic_light,
    }


_UPSERT_SQL = """
INSERT INTO trainee_scores (
    campaign_id, campaign_name, email, first_name, last_name,
    status, reported, clicked, submitted_data,
    send_date, reported_at, time_to_report_minutes,
    score_detection_accuracy, score_report_completeness,
    score_time_to_report, score_no_click_bonus, score_total,
    traffic_light, scored_at
) VALUES %s
ON CONFLICT (campaign_id, email) DO UPDATE SET
    campaign_name               = EXCLUDED.campaign_name,
    first_name                  = EXCLUDED.first_name,
    last_name                   = EXCLUDED.last_name,
    status                      = EXCLUDED.status,
    reported                    = EXCLUDED.reported,
    clicked                     = EXCLUDED.clicked,
    submitted_data              = EXCLUDED.submitted_data,
    send_date                   = EXCLUDED.send_date,
    reported_at                 = EXCLUDED.reported_at,
    time_to_report_minutes      = EXCLUDED.time_to_report_minutes,
    score_detection_accuracy    = EXCLUDED.score_detection_accuracy,
    score_report_completeness   = EXCLUDED.score_report_completeness,
    score_time_to_report        = EXCLUDED.score_time_to_report,
    score_no_click_bonus        = EXCLUDED.score_no_click_bonus,
    score_total                 = EXCLUDED.score_total,
    traffic_light               = EXCLUDED.traffic_light,
    scored_at                   = EXCLUDED.scored_at
"""


def _ingest(scores):
    conn = psycopg2.connect(**DB_DSN)
    try:
        with conn:
            with conn.cursor() as cur:
                rows = [
                    (
                        s["campaign_id"], s["campaign_name"],
                        s["email"], s["first_name"], s["last_name"],
                        s["status"], s["reported"], s["clicked"], s["submitted_data"],
                        s["send_date"], s["reported_at"], s["time_to_report_minutes"],
                        s["score_detection_accuracy"], s["score_report_completeness"],
                        s["score_time_to_report"], s["score_no_click_bonus"], s["score_total"],
                        s["traffic_light"], datetime.now(timezone.utc),
                    )
                    for s in scores
                ]
                execute_values(cur, _UPSERT_SQL, rows)
    finally:
        conn.close()


def _print_summary(scores):
    n         = len(scores)
    detected  = sum(1 for s in scores if s["reported"])
    clicked   = sum(1 for s in scores if s["clicked"])
    avg_score = sum(s["score_total"] for s in scores) / n if n else 0

    print("\n=== Cohort Summary ===")
    print(f"  Trainees scored    : {n}")
    print(f"  Detected (reported): {detected}/{n}  ({100 * detected // n if n else 0}%)")
    print(f"  Clicked phishing   : {clicked}/{n}")
    print(f"  Average score      : {avg_score:.1f}/100")
    print()

    icons = {"green": "[G]", "amber": "[A]", "red": "[R]"}
    for s in sorted(scores, key=lambda x: x["score_total"], reverse=True):
        icon = icons.get(s["traffic_light"], "[?]")
        name = f"{s['first_name']} {s['last_name']}".strip() or s["email"]
        print(f"  {icon}  {name:<28} {s['score_total']:>3}/100  {s['status']}")


def main():
    ap = argparse.ArgumentParser(description="Score a GoPhish campaign and ingest into PostgreSQL.")
    ap.add_argument("campaign_id", type=int, help="GoPhish campaign ID")
    args = ap.parse_args()

    if not GOPHISH_API_KEY:
        sys.exit(
            "GOPHISH_API_KEY is not set.\n"
            "  Retrieve it from GoPhish admin panel → Account Settings → API Key\n"
            "  export GOPHISH_API_KEY=<key>"
        )

    cid = args.campaign_id
    print(f"[*] Fetching campaign {cid} from {GOPHISH_HOST} ...")
    campaign = _api_get(f"/api/campaigns/{cid}/")
    campaign_name = campaign.get("name", f"Campaign {cid}")
    print(f"[*] Campaign : {campaign_name}")

    results  = campaign.get("results", [])
    timeline = campaign.get("timeline", [])

    events_by_email = defaultdict(list)
    for ev in timeline:
        email = ev.get("email", "")
        if email:
            events_by_email[email].append(ev)

    if not results:
        sys.exit("No results found in this campaign. Ensure the campaign has been launched.")

    print(f"[*] Scoring {len(results)} trainee(s) ...")
    scores = [_score(r, events_by_email, cid, campaign_name) for r in results]

    print("[*] Ingesting scores into PostgreSQL ...")
    _ingest(scores)
    print(f"[+] {len(scores)} record(s) upserted into trainee_scores")

    _print_summary(scores)


if __name__ == "__main__":
    main()
