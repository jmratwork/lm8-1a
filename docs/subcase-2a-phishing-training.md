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

**Step 1 — Create self-paced phishing courses (Instructor → Platform)**

The instructor logs into the GoPhish Admin Panel and the LMS Course Portal:

1. **GoPhish Admin Panel** (`http://phishing-simulator.internal:3333/`)
   - Log in with credentials from `/opt/phishing-simulator/admin_credentials.txt`
   - Go to **Account Settings** → generate an API key (needed for result export)
   - Create an **Email Template** (a sample template is pre-loaded as
     `IT Security Compliance Notice`; customise as needed)
   - Create a **Landing Page** capturing the trainee's click (redirect to
     `http://lms.internal:8080/#exercise` after capture)
   - Create a **Sending Profile** — the `MailHog Lab Relay` profile is
     pre-configured pointing to `mail-relay.internal:1025`
   - Create a **Group** with trainee email addresses
     (use `trainee01@phishing-lab.internal`, `trainee02@phishing-lab.internal`)
   - Create a **Campaign** using the above components

2. **LMS Course Portal** (`http://lms.internal:8080/`)
   - Verify that the three theory modules are accessible to trainees
   - Course content is served from `/srv/lms/` on `rep-practical-labs`
   - To update content: SSH to `rep-practical-labs` and edit files under `/srv/lms/`

**Step 2 — Publish content (Platform → Instructor)**

- GoPhish campaign moves to `Ready` status
- Verify with a test send via MailHog WebUI (`http://mail-relay.internal:8025/`)
- Confirm the LMS portal resolves from a trainee workstation

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

The instructor launches the GoPhish campaign. GoPhish dispatches simulated
phishing emails via MailHog to each trainee's lab inbox. Trainees view
their inbox at:
```
http://mail-relay.internal:8025/
```
MailHog captures all email so no messages leave the sandbox.

---

### Phase 3 — Assessment and Feedback

**Step 5 — Perform detection (Trainee → Platform)**

Trainees inspect the phishing email, identify red flags using the checklists
in the LMS, and submit a detection report via the **Practical Exercise** tab
in the LMS portal.

**Step 6 — Score actions vs objectives (Platform internal)**

GoPhish automatically records per-trainee events:
- Email opened (tracked via pixel)
- Phishing link clicked
- Credentials submitted on landing page
- Email reported (via Report button if configured)

The composite score is computed from:
- Detection accuracy: 40% (red flags documented in LMS report)
- Report completeness: 30% (all checklist items addressed)
- Time-to-report: 20%
- No phishing link clicked: +10% bonus

**Step 7 — Feedback + improvement areas (Platform → Trainee)**

Trainees view personalised feedback directly in the LMS portal's **Practical
Exercise** tab after submitting their report. Feedback includes score,
missed indicators, and module recommendations.

**Step 8 — Cohort performance metrics (Platform → Instructor)**

The Grafana Reporting Workspace displays aggregate cohort metrics:
```
http://reporting.internal:3000/
```
The instructor can also export raw campaign results using the provided script:

```bash
# From instructor-console or phishing-simulator host
export GOPHISH_API_KEY=<api-key-from-gophish-account-settings>
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

The OS password for the `ubuntu` user on `instructor-console` is hardcoded in
`group_vars/instructor_console.yml` as `Instructor#Lab2a`. No environment variable
needs to be exported. This is acceptable only because this is a disposable lab
environment; **never reuse this value in real or shared infrastructure**.

### Key Variables

Override in `group_vars/` or `host_vars/` as needed:

```yaml
# phishing-simulator
phishing_simulator_admin_port: 3333
phishing_simulator_phishing_port: 80
phishing_simulator_smtp_host: 10.20.10.60
phishing_simulator_smtp_port: 1025
phishing_simulator_from_address: "security-team@phishing-lab.internal"

# mail-relay
mail_relay_smtp_port: 1025
mail_relay_ui_port: 8025

# lms-content
lms_content_port: 8080
lms_content_web_root: /srv/lms
```

---

## First-Run Checklist

- [ ] Sandbox provisioned and all VMs reachable
- [ ] GoPhish admin credentials read from `/opt/phishing-simulator/admin_credentials.txt`
- [ ] GoPhish admin password changed on first login
- [ ] API key generated in GoPhish Account Settings
- [ ] `MailHog Lab Relay` sending profile visible in GoPhish (pre-configured)
- [ ] Test phishing email sent and visible in MailHog WebUI
- [ ] LMS portal accessible from trainee workstations
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
