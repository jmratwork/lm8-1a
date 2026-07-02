#!/usr/bin/env python3
"""
PUC2-Sub Case 2a — Phishing Campaign Launcher (Gate 1 one-shot)

Builds everything a GoPhish campaign needs and launches it, so the instructor
does not have to click through Email Templates / Landing Pages / Users & Groups /
New Campaign in the UI. This is ADDITIVE: the manual UI flow still works.

Via the GoPhish API (admin :3333, header Authorization: <api_key>) it:
  1. Creates/updates an email template from the EXACT contents of
     phishing_email_template.html (the training answer literals URGENT,
     SEC-2024-11 and the {{.RId}} tracking token are preserved verbatim).
  2. Ensures a minimal landing page exists (no credential capture).
  3. Creates/updates the recipient group from the configured roster.
  4. Creates a campaign referencing template + page + the EXISTING sending
     profile "MailHog Lab Relay" + the group, and LAUNCHES it.

Template / page / group are reused by name (idempotent). Only the campaign is
(re)created; a timestamp suffix keeps its name unique so re-runs never collide.

Stdlib only (matches the reporting-workspace scoring scripts).

Usage:
  python3 launch_campaign.py [--name <campaign_name>] [--dry-run]

Config file (JSON, rendered by Ansible): /opt/phishing-simulator/launch_campaign.json
API key file (0600, written by the playbook): /opt/phishing-simulator/gophish_api_key

Optional env vars:
  GOPHISH_HOST      default: http://127.0.0.1:3333
  GOPHISH_API_KEY   default: read from GOPHISH_API_KEY_FILE
  GOPHISH_API_KEY_FILE  default: /opt/phishing-simulator/gophish_api_key
  LAUNCH_CONFIG     default: /opt/phishing-simulator/launch_campaign.json
  TEMPLATE_FILE     default: /opt/phishing-simulator/phishing_email_template.html
"""

import argparse
import json
import os
import sys
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GOPHISH_HOST = os.environ.get("GOPHISH_HOST", "http://127.0.0.1:3333")
API_KEY_FILE = os.environ.get("GOPHISH_API_KEY_FILE", "/opt/phishing-simulator/gophish_api_key")
CONFIG_FILE = os.environ.get("LAUNCH_CONFIG", "/opt/phishing-simulator/launch_campaign.json")
TEMPLATE_FILE = os.environ.get("TEMPLATE_FILE", "/opt/phishing-simulator/phishing_email_template.html")


def _read_api_key():
    key = os.environ.get("GOPHISH_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(API_KEY_FILE, encoding="utf-8") as fh:
            key = fh.read().strip()
    except OSError as exc:
        sys.exit(
            f"Cannot read GoPhish API key from {API_KEY_FILE}: {exc}.\n"
            "  The provisioning playbook writes it there (mode 0600). Re-run the\n"
            "  phishing-simulator provisioning, or export GOPHISH_API_KEY."
        )
    if not key:
        sys.exit(f"GoPhish API key file {API_KEY_FILE} is empty.")
    return key


def _load_config():
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        sys.exit(f"Cannot read launch config {CONFIG_FILE}: {exc}")
    except json.JSONDecodeError as exc:
        sys.exit(f"Launch config {CONFIG_FILE} is not valid JSON: {exc}")


def _read_template_html():
    try:
        with open(TEMPLATE_FILE, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        sys.exit(f"Cannot read phishing email template {TEMPLATE_FILE}: {exc}")


class GoPhish:
    def __init__(self, host, api_key):
        self.host = host.rstrip("/")
        self.api_key = api_key

    def _request(self, method, path, body=None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = Request(
            f"{self.host}{path}",
            data=data,
            method=method,
            headers={
                "Authorization": self.api_key,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(req, timeout=20) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            sys.exit(f"GoPhish HTTP {exc.code} on {method} {path}: {detail}")
        except URLError as exc:
            sys.exit(f"Cannot reach GoPhish at {self.host}: {exc.reason}")

    def get(self, path):
        return self._request("GET", path)

    def post(self, path, body):
        return self._request("POST", path, body)

    def put(self, path, body):
        return self._request("PUT", path, body)

    def find_by_name(self, collection, name):
        for item in self.get(f"/api/{collection}/") or []:
            if item.get("name") == name:
                return item
        return None


def _upsert(api, collection, name, body, dry_run):
    """Create the named object, or update it in place if it already exists."""
    existing = api.find_by_name(collection, name)
    if existing:
        if dry_run:
            print(f"    [dry-run] would UPDATE {collection[:-1]} '{name}' (id {existing['id']})")
            return existing
        merged = dict(body)
        merged["id"] = existing["id"]
        api.put(f"/api/{collection}/{existing['id']}", merged)
        print(f"    updated existing {collection[:-1]} '{name}' (id {existing['id']})")
        return existing
    if dry_run:
        print(f"    [dry-run] would CREATE {collection[:-1]} '{name}'")
        return {"name": name}
    created = api.post(f"/api/{collection}/", body)
    print(f"    created {collection[:-1]} '{name}' (id {created.get('id', '?')})")
    return created


def main():
    ap = argparse.ArgumentParser(description="Launch a GoPhish phishing campaign for the cohort.")
    ap.add_argument("--name", help="Override the base campaign name.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would happen without creating or launching anything.")
    args = ap.parse_args()

    cfg = _load_config()
    api = GoPhish(GOPHISH_HOST, _read_api_key())

    campaign_base = args.name or cfg["campaign_name"]
    template_name = cfg["template_name"]
    page_name = cfg["page_name"]
    group_name = cfg["group_name"]
    smtp_name = cfg["smtp_profile_name"]
    subject = cfg.get("subject", "")
    url = cfg.get("url", "http://phishing-simulator.internal")
    trainees = cfg.get("trainees", [])

    if not trainees:
        sys.exit("Roster is empty (phishing_simulator_trainees). Nothing to target.")

    html = _read_template_html()

    print(f"[*] GoPhish : {GOPHISH_HOST}")
    print(f"[*] Roster  : {len(trainees)} recipient(s)")
    if args.dry_run:
        print("[*] DRY-RUN: no objects will be created and no campaign will be launched.\n")

    # 1) Email template — HTML preserved verbatim from the reference file.
    print(f"[1/4] Email template '{template_name}' ...")
    _upsert(api, "templates", template_name, {
        "name": template_name,
        "subject": subject,
        "html": html,
        "text": "",
    }, args.dry_run)

    # 2) Landing page — minimal, no credential capture.
    print(f"[2/4] Landing page '{page_name}' ...")
    _upsert(api, "pages", page_name, {
        "name": page_name,
        "html": (
            "<html><head><title>Compliance Verification</title></head>"
            "<body><h2>Security Compliance Verification</h2>"
            "<p>Your compliance status has been recorded. You may close this window.</p>"
            "</body></html>"
        ),
        "capture_credentials": False,
        "capture_passwords": False,
    }, args.dry_run)

    # 3) Recipient group from the roster.
    print(f"[3/4] Recipient group '{group_name}' ...")
    _upsert(api, "groups", group_name, {
        "name": group_name,
        "targets": [
            {
                "first_name": t.get("first_name", ""),
                "last_name": t.get("last_name", ""),
                "email": t.get("email", ""),
                "position": t.get("position", ""),
            }
            for t in trainees
        ],
    }, args.dry_run)

    # Sending profile must already exist (pre-configured by the role).
    if not args.dry_run and api.find_by_name("smtp", smtp_name) is None:
        sys.exit(
            f"Sending profile '{smtp_name}' not found in GoPhish. It should have "
            "been pre-configured by the phishing-simulator role."
        )

    # 4) Campaign — always (re)created with a unique name, then launched.
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    campaign_name = f"{campaign_base} {stamp}"
    print(f"[4/4] Campaign '{campaign_name}' -> launching ...")
    if args.dry_run:
        print(f"    [dry-run] would CREATE & LAUNCH campaign '{campaign_name}'")
        print(f"      template={template_name} page={page_name} "
              f"smtp={smtp_name} group={group_name} url={url}")
        print("\n[dry-run] Nothing was created. Re-run without --dry-run to launch.")
        return

    campaign = api.post("/api/campaigns/", {
        "name": campaign_name,
        "template": {"name": template_name},
        "page": {"name": page_name},
        "smtp": {"name": smtp_name},
        "url": url,
        "groups": [{"name": group_name}],
    })

    cid = campaign.get("id", "?")
    print("\n" + "=" * 52)
    print(f"  CAMPAIGN LAUNCHED — CAMPAIGN ID: {cid}")
    print(f"  Name : {campaign_name}")
    print(f"  Next : run FINALIZE_FEEDBACK {cid}  (or FINALIZE_FEEDBACK to auto-detect)")
    print("=" * 52)


if __name__ == "__main__":
    main()
