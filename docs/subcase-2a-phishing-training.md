# PUC2-Sub Case 2a — Phishing Attack Training Scenario

## Overview

Staff members undergo comprehensive training in identifying phishing campaigns
through a hands-on educational platform. The Training Instructor develops
self-paced courses focused on recognising phishing techniques. Trainees access
the platform and engage in practical exercises designed to assess their ability
to scrutinise sender information, analyse email content for red flags, verify
attachments for legitimacy, and report suspicious emails using organisational
protocols.

Upon completion, trainees receive evaluation feedback including scores and
suggestions for further learning.

---

## Architecture

### Networks

| Network | CIDR | Purpose | Trainee-accessible |
|---------|------|---------|-------------------|
| rep-backend | 10.20.10.0/24 | Platform services | No |
| rep-frontend | 10.20.20.0/24 | Trainee workstations + instructor | Yes |
| analytics-zone | 10.20.30.0/24 | Grafana reporting | No |

### Hosts

| Host | IP | Role | Key Service |
|------|----|------|-------------|
| rep-scheduler | 10.20.10.10 | REP scheduling microservice | nginx (port 80) |
| rep-live-session | 10.20.10.20 | REP live delivery | nginx (port 80) |
| rep-quiz-engine | 10.20.10.30 | REP quiz engine | nginx (port 80) |
| rep-practical-labs | 10.20.10.40 | REP labs + **LMS portal** | nginx (port 80 + **8080**) |
| **phishing-simulator** | 10.20.10.50 | **GoPhish** | Admin: 3333, Phishing: 80 |
| **mail-relay** | 10.20.10.60 | **MailHog** | SMTP: 1025, WebUI: 8025 |
| instructor-console | 10.20.20.10 | Instructor workstation | tmux + browser shortcuts |
| trainee-workstation-01 | 10.20.20.50 | Trainee 1 (Windows 10) | REP Collector agent |
| trainee-workstation-02 | 10.20.20.60 | Trainee 2 (Windows 10) | REP Collector agent |
| reporting-workspace | 10.20.30.10 | Grafana + PostgreSQL | Grafana: 3000 |

---

## Internal URLs

| Service | URL | Who accesses it |
|---------|-----|-----------------|
| LMS Course Portal | `http://lms.internal:8080/` | Trainees + Instructor |
| Trainee Inbox (MailHog) | `http://mail-relay.internal:8025/` | Trainees |
| GoPhish Admin Panel | `http://phishing-simulator.internal:3333/` | Instructor only |
| Grafana Dashboard | `http://reporting.internal:3000/` | Instructor |

---

## Training Flow (UML Sequence)

### Phase 1 — Training Setup

**Step 1 — Provision the platform (Deploy → Platform)**

The Ansible deployment provisions everything and leaves the platform ready for
trainees. **No manual instructor setup is required:**

1. **GoPhish** (`http://phishing-simulator.internal:3333/`)
   - GoPhish is deployed with a clean, writable database, and its admin API key
     is persisted automatically by the deploy — there is nothing to generate or
     export by hand.
   - The `MailHog Lab Relay` sending profile is pre-configured, pointing to
     `mail-relay.internal:1025`.
   - The **email template** (`IT Security Compliance Notice`), **landing page**
     (`Compliance Verification Landing`), recipient **group** (`Cohort Trainees`,
     built from the configured roster `trainee01@cynet.lab`,
     `trainee02@cynet.lab`) and **campaign** (`Security Compliance Drill`) are all
     created by the auto-launch automation (`launch_campaign.py`). The instructor
     no longer builds them by hand.
   - Admin credentials for the optional UI are in
     `/opt/phishing-simulator/admin_credentials.txt`.

2. **LMS Course Portal** (`http://lms.internal:8080/`)
   - The three theory modules are served from `/srv/lms/` on `rep-practical-labs`
     by the `lms-content` role.
   - To update content: SSH to `rep-practical-labs` and edit files under `/srv/lms/`.

> **Optional / override:** the manual GoPhish UI flow still works. Open the admin
> panel with `OPEN_GOPHISH_ADMIN` to inspect or customise the template, landing
> page, group or campaign. This is not required for a normal deploy.

**Step 2 — Platform ready (Platform → Trainee)**

- On deploy the campaign is **auto-launched** (Gate 1) and moves to `In progress`;
  one phishing email per trainee is already waiting in Mailpit.
- The deploy fails green only after asserting GoPhish is operational (API key
  recovered, `MailHog Lab Relay` SMTP profile present).
- The LMS portal resolves from a trainee workstation.

---

### Phase 2 — Trainee Executes Scenario

**Step 3 — Launch phishing learning module (Trainee → Platform)**

Trainees open the LMS Course Portal from their browser:
```
http://lms.internal:8080/
```
They read Modules 1–3 (sender analysis, content red flags, attachments &
reporting) and click **Start Practical Exercise**.

**Step 4 — Deliver simulated phishing emails/pages (Platform → Trainee)**

The GoPhish campaign is **auto-launched during deployment** (Gate 1): GoPhish
dispatches one simulated phishing email per trainee via MailHog automatically —
the instructor does not launch it by hand. Trainees view their inbox at:
```
http://mail-relay.internal:8025/
```
Mailpit (MailHog) captures all email so no messages leave the sandbox. Because it
is a single shared relay, each trainee filters the inbox by their own recipient
address.

---

### Phase 3 — Assessment and Feedback

**Step 5 — Perform detection (Trainee → Platform)**

Trainees inspect the phishing email, identify red flags using the checklists
in the LMS, and submit a detection report via the **Practical Exercise** tab
in the LMS portal.

**Step 6 — Score actions vs objectives (Platform internal)**

GoPhish records per-trainee events (email opened via pixel, phishing link
clicked, credentials submitted on the landing page, email reported). A systemd
timer on `reporting-workspace` (`rep-finalize.timer`, ~every 5 min, idempotent)
runs the Gate 2 pipeline unattended — **score → deliver → publish**
(`rep_finalize.sh`). The instructor no longer runs scoring by hand.

The composite score is computed from:
- Detection accuracy: 40% (red flags documented in LMS report)
- Report completeness: 30% (all checklist items addressed)
- Time-to-report: 20%
- No phishing link clicked: +10% bonus

**Step 7 — Feedback + improvement areas (Platform → Trainee)**

Feedback does **not** appear in the "Practical Exercise" tab. The Gate 2 timer
delivers it automatically in two places:

- **(a) Score email in Mailpit (L24):** each trainee receives a personalised
  scoring email in their inbox at `http://mail-relay.internal:8025/`.
- **(b) Per-trainee feedback page (L25):** an HTML page is published under
  `http://lms.internal:8080/feedback/` (`.../feedback/<your-email>.html`) and is
  reachable from the **My Feedback** tab in the LMS portal.

Feedback includes the score, missed indicators and module recommendations. It
refreshes on the timer's cadence (~5 min), so a trainee who reaches this step
early simply waits and refreshes.

**Step 8 — Cohort performance metrics (Platform → Instructor)**

The Grafana Reporting Workspace displays aggregate cohort metrics at
`http://reporting.internal:3000/`, including the **Score Component Averages**
panel (L26) and the **Trainee Scores** panel (L27). Grafana is refreshed by the
same Gate 2 auto-finalize timer.

The GoPhish API key is persisted automatically by the deploy, so there is nothing
to export for normal operation. *(Optional)* to pull raw campaign results by hand:

```bash
# Optional — from instructor-console or phishing-simulator host.
# The deploy already persists the key; export it only if running this standalone.
export GOPHISH_API_KEY=<api-key>
./provisioning/case-2a/scripts/export_gophish_results.sh <campaign_id>
```

---

## Ansible Provisioning

### Roles Applied Per Host

| Host | Roles |
|------|-------|
| rep-scheduler, rep-live-session, rep-quiz-engine, rep-practical-labs | `rep-core` |
| rep-practical-labs | `rep-core`, `lms-content` |
| phishing-simulator | `phishing-simulator` |
| mail-relay | `mail-relay` |
| reporting-workspace | `reporting-workspace` (incl. PostgreSQL) |
| instructor-console | `instructor-console` |
| trainee-workstation-01/02 | `windows`, `trainee-workstation` |

### Instructor Console Password

The OS password for the `ubuntu` user on `instructor-console` is `Instructor#Lab2a`.
It is applied as a pre-generated SHA-512 hash hardcoded directly in the task
`"Set instructor console user password"` in
`provisioning/roles/instructor-console/tasks/main.yml`. No environment variable
needs to be exported and no runtime hashing library is required on the control node.
This approach is acceptable only because this is a disposable lab environment;
**never reuse this value in real or shared infrastructure**.

### Key Variables

Override in `group_vars/` or `host_vars/` as needed:

```yaml
# phishing-simulator
phishing_simulator_admin_port: 3333
phishing_simulator_phishing_port: 80
phishing_simulator_smtp_host: 10.20.10.60
phishing_simulator_smtp_port: 1025
# Phishing sender. Its TLD (.net) is the L13 answer and MUST differ from the
# corporate directory's TLD (company-corp.com) so L20 stays MISMATCH.
phishing_simulator_from_address: "security@company-corp.net"
# Gate 1: auto-launch the campaign on deploy. false = fully manual (LAUNCH_CAMPAIGN).
phishing_simulator_auto_launch: true

# reporting-workspace
# Gate 2: install the systemd timer that runs score -> deliver -> publish (~5 min).
# false = fully manual (FINALIZE_FEEDBACK).
reporting_workspace_auto_finalize: true

# mail-relay
mail_relay_smtp_port: 1025
mail_relay_ui_port: 8025

# lms-content
lms_content_port: 8080
lms_content_web_root: /srv/lms
```

---

## Operation (hands-free)

The scenario runs itself. There are **no mandatory instructor steps during
execution**: the phishing email is delivered at deploy time (Gate 1 auto-launch),
and feedback is refreshed by the `rep-finalize.timer` on `reporting-workspace`
(Gate 2, ~every 5 min: score → deliver → publish).

**Instructor workflow:**

1. Deploy the sandbox with Ansible (see the
   [provisioning guide](provisioning-guide.md)).
2. Verify the deploy is green (see the *Verify green* checklist below).
3. Hand the trainees the quick-start (LMS + inbox URLs).

That's it — no campaign launch, no scoring run by hand.

> Mailpit is a single shared relay: trainees must filter the inbox by their own
> recipient address (this matches the phishing-delivery and feedback level wording).

### Manual overrides / contingency (not required)

If you disable the automation or need to re-run a stage by hand, the
`instructor-console` aliases are still available:

| Alias | What it does |
|-------|--------------|
| `LAUNCH_CAMPAIGN` | Re-run Gate 1. Idempotent: guarded on the campaign name, so it never sends a second email. |
| `FINALIZE_FEEDBACK [id]` | Re-run the whole Gate 2 pipeline (auto-detects the campaign if no id is given). |
| `SCORE_CAMPAIGN <id>` | Gate 2 step 1 only — score the campaign. |
| `DELIVER_FEEDBACK <id>` | Gate 2 step 2 only — email the scores and build the feedback pages. |
| `PUBLISH_FEEDBACK` | Gate 2 step 3 only — publish the feedback pages under `http://lms.internal:8080/feedback/`. |
| `PUBLISH_LMS` | Rebuild and redeploy the LMS index page. |

**Automation toggles (both default `true`; set to `false` for the fully manual flow):**

- `phishing_simulator_auto_launch` — Gate 1 auto-launch on deploy.
- `reporting_workspace_auto_finalize` — Gate 2 auto-finalize timer.

## Verify green (post-deploy)

After the deploy, confirm the automation actually ran end to end:

- [ ] Ansible `PLAY RECAP` shows `failed=0` for every host in the topology
      (see the **Hosts** table above)
- [ ] The four content-guardrail asserts pass (phishing email template literals
      and the sender-TLD / directory-TLD mismatch)
- [ ] **One phishing email per trainee is present in Mailpit**
      (`http://mail-relay.internal:8025/`) — proof the Gate 1 auto-launch fired
- [ ] `rep-finalize.timer` is active on `reporting-workspace`
      (`systemctl status rep-finalize.timer`) — Gate 2 auto-finalize is armed
- [ ] LMS portal accessible from trainee workstations (`http://lms.internal:8080/`)
- [ ] Grafana dashboard visible at `http://reporting.internal:3000/`
- [ ] Trainee workstations can resolve `lms.internal` and `mail-relay.internal`

---

## Troubleshooting

**GoPhish container not starting**
```bash
ssh phishing-simulator
docker logs gophish
```

**MailHog not receiving email**
```bash
# Verify MailHog is running
ssh mail-relay
docker ps
docker logs mailhog

# Test SMTP directly
echo "Subject: test" | sendmail -S mail-relay.internal:1025 test@test.internal
```

**LMS portal not accessible**
```bash
ssh rep-practical-labs
nginx -t           # Check nginx config syntax
systemctl status nginx
curl http://127.0.0.1:8080/
```

**PostgreSQL / Grafana datasource error**
```bash
ssh reporting-workspace
systemctl status postgresql
sudo -u postgres psql -c "\l"   # List databases
```
