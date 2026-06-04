#!/usr/bin/env python3
"""
PUC2-Sub Case 2a — Feedback Delivery Engine

Reads trainee scores from the rep_reporting PostgreSQL database and:
  1. Sends a personalised HTML feedback email to each trainee via Mailpit SMTP.
  2. Writes an HTML feedback page per trainee to OUTPUT_DIR for LMS publication.

The feedback includes:
  - Overall score and traffic-light status
  - Component score breakdown
  - Missed detection indicators
  - Targeted module recommendations

Prerequisites:
  Run score_campaign.py first to populate trainee_scores for the campaign.

Usage:
  python3 deliver_feedback.py <campaign_id>

Optional env vars:
  SMTP_HOST    default: mail-relay.internal
  SMTP_PORT    default: 1025
  SMTP_FROM    default: training-platform@phishing-lab.internal
  OUTPUT_DIR   default: /tmp/rep-feedback
  DB_HOST / DB_PORT / DB_NAME / DB_USER / DB_PASS  (same defaults as score_campaign.py)
"""

import argparse
import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    sys.exit("psycopg2 not available. Install with: apt-get install python3-psycopg2")

SMTP_HOST  = os.environ.get("SMTP_HOST",  "mail-relay.internal")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "1025"))
SMTP_FROM  = os.environ.get("SMTP_FROM",  "training-platform@phishing-lab.internal")
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/tmp/rep-feedback"))

DB_DSN = {
    "host":     os.environ.get("DB_HOST",   "localhost"),
    "port":     int(os.environ.get("DB_PORT", "5432")),
    "dbname":   os.environ.get("DB_NAME",   "rep_reporting"),
    "user":     os.environ.get("DB_USER",   "rep_reporting"),
    "password": os.environ.get("DB_PASS",   "changeme"),
}

_TRAFFIC_COLORS = {
    "green": ("#2e7d32", "Detected — Excellent"),
    "amber": ("#e65100", "Partial Detection"),
    "red":   ("#c62828", "At Risk"),
}


def _get_scores(campaign_id):
    conn = psycopg2.connect(**DB_DSN)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM trainee_scores WHERE campaign_id = %s ORDER BY score_total DESC",
                (campaign_id,),
            )
            return cur.fetchall()
    finally:
        conn.close()


def _recommendations(score):
    recs = []
    if score["clicked"]:
        recs.append((
            "Module 2 — Content Red Flags",
            "You clicked the phishing link. Review how to identify suspicious URLs "
            "before interacting with them. In a real attack this would have compromised your credentials.",
        ))
        recs.append((
            "Module 3 — Attachments &amp; Reporting",
            "Practise the golden rule: when in doubt, do NOT click. Report first, "
            "then investigate with IT Security support.",
        ))
    if not score["reported"]:
        recs.append((
            "Module 1 — Sender Analysis",
            "The phishing email was not reported. Review sender red flags: display-name "
            "spoofing, typosquatted domains, and Reply-To mismatches.",
        ))
        recs.append((
            "Module 2 — Content Red Flags",
            "Review urgency cues, grammatical errors, and look-alike branding — these "
            "are the most common indicators present in this exercise.",
        ))
    if score["reported"] and score["score_report_completeness"] < 30:
        recs.append((
            "Module 3 — Attachments &amp; Reporting",
            "An incident report was not fully recorded by the platform. Ensure you use "
            "the GoPhish 'Report Phishing' button or the REP incident form.",
        ))
    if score["reported"] and score["time_to_report_minutes"] and score["time_to_report_minutes"] > 30:
        recs.append((
            "General — Response Speed",
            f"Your report arrived {score['time_to_report_minutes']:.0f} minutes after delivery. "
            "Target: under 5 minutes. Faster detection limits attacker dwell time.",
        ))
    if not recs:
        recs.append((
            "Outstanding performance",
            "No improvement areas identified. You correctly identified and reported "
            "the phishing attempt with no link click and within the target time window.",
        ))
    return recs


def _missed_indicators(score):
    items = []
    if not score["reported"]:
        items.append("Phishing email not reported via GoPhish button or REP incident form.")
    if score["clicked"]:
        items.append("Phishing link clicked — credential-harvesting page was reached.")
    if score["submitted_data"]:
        items.append("Credentials submitted on the phishing landing page.")
    if score["time_to_report_minutes"] and score["time_to_report_minutes"] > 30:
        items.append(
            f"Time to report: {score['time_to_report_minutes']:.0f} min "
            "(objective: &le;5 min)."
        )
    return items


def _render_html(score):
    name = f"{score['first_name']} {score['last_name']}".strip() or score["email"]
    color, label = _TRAFFIC_COLORS.get(score["traffic_light"], ("#555", "Unknown"))
    recs = _recommendations(score)
    missed = _missed_indicators(score)

    rec_items = "".join(
        f"<li><strong>{r[0]}</strong><br>"
        f"<span style='font-size:13px;color:#555;line-height:1.6;'>{r[1]}</span></li>"
        for r in recs
    )
    missed_items = (
        "".join(f"<li>{m}</li>" for m in missed)
        if missed
        else "<li style='color:#2e7d32;'>None — all objectives met.</li>"
    )

    ttr = (
        f"{score['time_to_report_minutes']:.0f} min"
        if score["time_to_report_minutes"] is not None
        else "N/A"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1.0">
  <title>Feedback &mdash; {name}</title>
  <style>
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{font-family:Arial,sans-serif;background:#f0f2f5;color:#222;padding:20px;}}
    .wrap{{max-width:680px;margin:0 auto;}}
    .card{{background:#fff;border-radius:6px;padding:24px 28px;
           box-shadow:0 1px 4px rgba(0,0,0,.1);margin-bottom:16px;}}
    h1{{color:#1a3a5c;font-size:20px;margin-bottom:4px;}}
    h2{{color:#1a3a5c;font-size:15px;margin:0 0 12px;padding-bottom:6px;border-bottom:1px solid #eee;}}
    .total{{font-size:52px;font-weight:bold;text-align:center;color:{color};line-height:1;}}
    .status{{text-align:center;font-size:17px;color:{color};font-weight:bold;margin:6px 0 0;}}
    .row{{display:flex;justify-content:space-between;padding:7px 0;
          border-bottom:1px solid #f4f4f4;font-size:14px;}}
    .row:last-child{{border-bottom:none;}}
    .pts{{font-weight:bold;}}
    ul.recs{{list-style:none;padding:0;}}
    ul.recs li{{padding:10px 14px;background:#fff8e1;border-left:4px solid #f9a825;
                margin-bottom:8px;font-size:14px;}}
    ul.missed{{padding-left:18px;margin:0;}}
    ul.missed li{{font-size:14px;line-height:1.7;color:#c62828;}}
    .btn{{display:inline-block;background:#1a3a5c;color:#fff;padding:10px 22px;
          border-radius:4px;text-decoration:none;font-size:14px;margin-top:14px;}}
    .meta{{color:#666;font-size:13px;margin-top:4px;}}
  </style>
</head>
<body>
<div class="wrap">

  <div class="card">
    <h1>Phishing Awareness Training &mdash; Personal Feedback</h1>
    <p class="meta">Campaign: {score['campaign_name']}</p>
    <p class="meta">Trainee: {name} &nbsp;&bull;&nbsp; Email: {score['email']}</p>
  </div>

  <div class="card">
    <h2>Overall Score</h2>
    <div class="total">{int(score['score_total'])}<span style="font-size:24px;color:#555;">/100</span></div>
    <div class="status">{label}</div>
  </div>

  <div class="card">
    <h2>Score Breakdown</h2>
    <div class="row">
      <span>Detection Accuracy <span style="color:#888;font-size:12px;">(max 40 pts)</span></span>
      <span class="pts">{int(score['score_detection_accuracy'])}</span>
    </div>
    <div class="row">
      <span>Report Completeness <span style="color:#888;font-size:12px;">(max 30 pts)</span></span>
      <span class="pts">{int(score['score_report_completeness'])}</span>
    </div>
    <div class="row">
      <span>Time to Report <span style="color:#888;font-size:12px;">(max 20 pts &mdash; yours: {ttr})</span></span>
      <span class="pts">{int(score['score_time_to_report'])}</span>
    </div>
    <div class="row">
      <span>No-Click Bonus <span style="color:#888;font-size:12px;">(max 10 pts)</span></span>
      <span class="pts">{int(score['score_no_click_bonus'])}</span>
    </div>
  </div>

  <div class="card">
    <h2>Missed Indicators</h2>
    <ul class="missed">{missed_items}</ul>
  </div>

  <div class="card">
    <h2>Recommended Study Areas</h2>
    <ul class="recs">{rec_items}</ul>
    <a class="btn" href="http://lms.internal:8080/">Return to LMS &rarr;</a>
  </div>

</div>
</body>
</html>"""


def _send_email(score, html_body):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"[Training Platform] Your Phishing Awareness Score — "
        f"{int(score['score_total'])}/100 ({score['traffic_light'].capitalize()})"
    )
    msg["From"] = SMTP_FROM
    msg["To"]   = score["email"]
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
        smtp.sendmail(SMTP_FROM, [score["email"]], msg.as_string())


def _safe_filename(email):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", email) + ".html"


def main():
    ap = argparse.ArgumentParser(
        description="Deliver personalised feedback for a scored campaign."
    )
    ap.add_argument("campaign_id", type=int, help="GoPhish campaign ID (must already be scored)")
    args = ap.parse_args()

    print(f"[*] Reading scores for campaign {args.campaign_id} ...")
    scores = _get_scores(args.campaign_id)
    if not scores:
        sys.exit(
            f"No scores found for campaign {args.campaign_id}.\n"
            "  Run score_campaign.py first to compute and store scores."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    sent = written = errors = 0

    for score in scores:
        name = f"{score['first_name']} {score['last_name']}".strip() or score["email"]
        html = _render_html(score)

        out_path = OUTPUT_DIR / _safe_filename(score["email"])
        out_path.write_text(html, encoding="utf-8")
        written += 1

        try:
            _send_email(score, html)
            icon = {"green": "[G]", "amber": "[A]", "red": "[R]"}.get(score["traffic_light"], "[?]")
            print(f"  {icon}  {name:<28} {int(score['score_total']):>3}/100  → {score['email']}")
            sent += 1
        except Exception as exc:
            print(f"  [!] Email failed for {score['email']}: {exc}", file=sys.stderr)
            errors += 1

    print(f"\n[+] {sent} email(s) sent via {SMTP_HOST}:{SMTP_PORT}")
    print(f"[+] {written} HTML page(s) written to {OUTPUT_DIR}")
    if errors:
        print(f"[!] {errors} email error(s) — verify SMTP_HOST and SMTP_PORT")
    print(
        "\nTo publish feedback pages to the LMS, run from instructor-console:\n"
        "  PUBLISH_FEEDBACK"
    )


if __name__ == "__main__":
    main()
