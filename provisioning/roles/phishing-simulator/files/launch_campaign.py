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

Template / page / group are reused by name (idempotent). The campaign is created
once under a stable name; an idempotency guard skips the launch when a campaign
with that name already exists, so redeploys and re-runs never send a second email
(this also keeps the L12 = 1 expectation intact).

GoPhish uses a PERSISTENT volume, so its database survives redeploys. The launcher
tolerates residual/phantom objects: a duplicate-name collision on create never
aborts the deploy — template/page/group are reused or recreated under a unique
suffixed name, and a reserved campaign row is treated like the guard (skip, no
second email).

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


class GoPhishError(Exception):
    """A GoPhish API call returned an HTTP error.

    Raised instead of aborting the whole process so callers can decide whether a
    particular failure is recoverable (e.g. a duplicate-key error against a
    persistent GoPhish database) or fatal.
    """

    def __init__(self, code, method, path, detail):
        self.code = code
        self.method = method
        self.path = path
        self.detail = detail or ""
        super().__init__(f"GoPhish HTTP {code} on {method} {path}: {self.detail}")


# Substrings GoPhish uses when a create collides with the unique-name index on a
# persistent volume. A genuine duplicate is reported with a message such as
# "Template name already in use". Matching is case-insensitive.
#
# NOTE: the generic 500 "Error inserting template into database" is deliberately
# NOT a marker here. GoPhish returns that SAME message when template VALIDATION
# fails (it renders the template against a sample context, so a Go-template
# action referencing a field GoPhish does not provide -- even inside an HTML
# comment -- makes the insert fail). That is not a name collision and must not be
# "recovered" as one; treating it as a duplicate only masks the real problem.
_DUPLICATE_MARKERS = ("already in use", "unique", "already exists", "duplicate")

# Fields GoPhish exposes to a template's Go-template context. Any {{...}} action
# in the HTML that references something outside this set fails validation.
_GOPHISH_TEMPLATE_FIELDS = (
    ".FirstName", ".LastName", ".Email", ".Position", ".URL", ".RId",
    ".From", ".TrackingURL", ".BaseURL", ".Tracker",
)


def _is_duplicate_error(err):
    """True if a GoPhishError looks like a recoverable duplicate-name collision."""
    detail = err.detail.lower()
    return any(marker in detail for marker in _DUPLICATE_MARKERS)


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
            # Recoverable at the caller (e.g. duplicate name); do NOT kill the
            # process here — a 500 on one object must not abort the whole deploy.
            raise GoPhishError(exc.code, method, path, detail) from exc
        except URLError as exc:
            # GoPhish unreachable is genuinely unrecoverable for this run.
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
    """Create the named object, or update it in place if it already exists.

    Returns the name EFFECTIVELY used (the requested name, or a unique suffixed
    variant). Resilient to residual GoPhish state on a persistent volume: if the
    create collides with a name that find_by_name did not return (a phantom row),
    the deploy is never aborted — the object is either reused or recreated under
    a unique fallback name.
    """
    singular = collection[:-1]
    existing = api.find_by_name(collection, name)
    if existing:
        if dry_run:
            print(f"    [dry-run] would UPDATE {singular} '{name}' (id {existing['id']})")
            return name
        merged = dict(body)
        merged["id"] = existing["id"]
        api.put(f"/api/{collection}/{existing['id']}", merged)
        print(f"    updated existing {singular} '{name}' (id {existing['id']})")
        return name
    if dry_run:
        print(f"    [dry-run] would CREATE {singular} '{name}'")
        return name

    try:
        created = api.post(f"/api/{collection}/", body)
        print(f"    created {singular} '{name}' (id {created.get('id', '?')})")
        return name
    except GoPhishError as err:
        if not _is_duplicate_error(err):
            # Not a name collision. For templates, GoPhish validates by rendering
            # the HTML, so a bad Go-template action (a {{...}} referencing a field
            # outside GoPhish's context) surfaces here as the generic 500 "Error
            # inserting template into database". Abort with an actionable hint
            # instead of mislabelling it a duplicate and looping into recovery.
            if singular == "template":
                sys.exit(
                    f"GoPhish rejected the {singular} '{name}' "
                    f"(HTTP {err.code}: {err.detail}).\n"
                    "  This is NOT a duplicate-name collision. GoPhish validates a\n"
                    "  template by rendering it, so any {{...}} Go-template action\n"
                    "  referencing a field it does not provide -- even inside an HTML\n"
                    "  comment -- makes the insert fail. Review the email template\n"
                    "  content and keep only GoPhish fields: "
                    f"{', '.join(_GOPHISH_TEMPLATE_FIELDS)}."
                )
            raise
        # The name is taken in the GoPhish DB but find_by_name did not surface it.
        print(f"    {singular} '{name}' create hit a duplicate (HTTP {err.code}); recovering ...")
        # a) It may be visible now -> update it in place and keep the same name.
        existing = api.find_by_name(collection, name)
        if existing:
            merged = dict(body)
            merged["id"] = existing["id"]
            api.put(f"/api/{collection}/{existing['id']}", merged)
            print(f"    reused existing {singular} '{name}' (id {existing['id']})")
            return name
        # b) Phantom row -> create under a unique, suffixed name (content is
        #    unchanged; only the GoPhish object name gets the suffix).
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        unique_name = f"{name} (deploy {stamp})"
        body = dict(body)
        body["name"] = unique_name
        created = api.post(f"/api/{collection}/", body)
        print(f"    created {singular} under fallback name '{unique_name}' "
              f"(id {created.get('id', '?')})")
        return unique_name


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

    # The campaign must reference whatever names the upserts actually used, which
    # may be suffixed fallbacks if GoPhish's persistent DB had phantom rows.
    # 1) Email template — HTML preserved verbatim from the reference file.
    print(f"[1/4] Email template '{template_name}' ...")
    template_eff = _upsert(api, "templates", template_name, {
        "name": template_name,
        "subject": subject,
        "html": html,
        "text": "",
    }, args.dry_run)

    # 2) Landing page — minimal, no credential capture.
    print(f"[2/4] Landing page '{page_name}' ...")
    page_eff = _upsert(api, "pages", page_name, {
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
    group_eff = _upsert(api, "groups", group_name, {
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

    # 4) Campaign — created once under a STABLE name (no timestamp) and launched.
    #    A stable name lets the idempotency guard below detect a prior launch.
    campaign_name = campaign_base
    print(f"[4/4] Campaign '{campaign_name}' -> launching ...")
    if args.dry_run:
        print(f"    [dry-run] would CREATE & LAUNCH campaign '{campaign_name}'")
        print(f"      template={template_eff} page={page_eff} "
              f"smtp={smtp_name} group={group_eff} url={url}")
        print("\n[dry-run] Nothing was created. Re-run without --dry-run to launch.")
        return

    # Idempotency guard against double-send: if a campaign with this name already
    # exists (e.g. a redeploy, or a manual re-run of LAUNCH_CAMPAIGN), do NOT
    # create or relaunch it — a second campaign would fire a second phishing
    # email at the whole roster and could break the L12 = 1 expectation.
    existing_campaign = api.find_by_name("campaigns", campaign_name)
    if existing_campaign:
        print(f"    campaign already exists (id {existing_campaign['id']}); skipping launch")
        return

    # The campaign references the EFFECTIVE object names (may be suffixed
    # fallbacks). Unlike template/page/group, a duplicate campaign is NOT
    # recreated under a new name: a phantom/reserved campaign row the guard above
    # missed still means a campaign exists, so we skip the launch (exit 0) rather
    # than send a second email.
    try:
        campaign = api.post("/api/campaigns/", {
            "name": campaign_name,
            "template": {"name": template_eff},
            "page": {"name": page_eff},
            "smtp": {"name": smtp_name},
            "url": url,
            "groups": [{"name": group_eff}],
        })
    except GoPhishError as err:
        if _is_duplicate_error(err):
            print(f"    campaign '{campaign_name}' already reserved in GoPhish; "
                  "skipping launch")
            return
        raise

    cid = campaign.get("id", "?")
    print("\n" + "=" * 52)
    print(f"  CAMPAIGN LAUNCHED — CAMPAIGN ID: {cid}")
    print(f"  Name : {campaign_name}")
    print(f"  Next : run FINALIZE_FEEDBACK {cid}  (or FINALIZE_FEEDBACK to auto-detect)")
    print("=" * 52)


if __name__ == "__main__":
    try:
        main()
    except GoPhishError as err:
        # A non-recoverable API error (recoverable duplicates are handled inline).
        # Exit with a clear message instead of a traceback so the deploy log is
        # readable.
        sys.exit(str(err))
