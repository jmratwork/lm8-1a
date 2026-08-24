# Provisioning guide — PUC2-Sub Case 2a

This guide explains how to deploy the CyberRangeCZ infrastructure for the
Phishing Attack Training Scenario. The process has two phases: importing the
topology into KYPO/CRCZ and configuring the virtual machines with Ansible.

## 1. Import the topology in KYPO/CRCZ

1. Sign in to the KYPO portal with an account that can create sandboxes.
2. Upload `provisioning/case-2a/topology.yml`. The topology creates:
   - REP backend servers (`rep-scheduler`, `rep-live-session`, `rep-quiz-engine`, `rep-practical-labs`)
   - Phishing simulation host (`phishing-simulator`) and mail relay (`mail-relay`)
   - Instructor console and trainee workstations on the `rep-frontend` network
   - Reporting workspace on the `analytics-zone` network
3. Deploy the sandbox and wait for KYPO/CRCZ to report all machines as reachable.

## 2. Prepare credentials

1. Duplicate `inventory.sample` and rename it to `inventory.ini`.
2. Keep the hostnames and IP addresses defined by the topology.
3. Export credentials as environment variables before executing Ansible:

```bash
export ANSIBLE_PASSWORD_INSTRUCTOR='...'
export ANSIBLE_PASSWORD_PHISHING_SIMULATOR='...'
export ANSIBLE_PASSWORD_MAIL_RELAY='...'
export ANSIBLE_PASSWORD_REPORTING_WORKSPACE='...'
export ANSIBLE_PASSWORD_TRAINEE_01='...'
export ANSIBLE_PASSWORD_TRAINEE_02='...'
```

> **Note:** The OS password for the `ubuntu` user on `instructor-console` is hardcoded
> in `group_vars/instructor_console.yml` (`Instructor#Lab2a`). This is intentional for
> this disposable lab environment. Do **not** reuse this value in real or shared
> infrastructure.

Or store secrets in an Ansible Vault file and reference it with `--vault-password-file`.

## 3. System prerequisites

Install the base utilities on the control node:

```bash
sudo apt-get update && sudo apt-get install -y wget
python3 -m pip install --upgrade pip
python3 -m pip install virtualbmc
```

## 4. Install Ansible dependencies

```bash
python3 -m pip install --upgrade ansible
python3 -m pip install pywinrm          # WinRM for Windows hosts
python3 -m pip install passlib[bcrypt]  # Required by password_hash filter (mandatory on Python 3.13+; crypt removed)
ansible-galaxy collection install -r provisioning/collections.yml
```

Use `pip install "pywinrm[credssp]"` if the sandbox requires CredSSP delegation.
Windows hosts require WinRM over TLS (port 5986); set
`ansible_winrm_server_cert_validation=ignore` in the inventory for lab environments.

## 5. Execute the playbook

```bash
provisioning/run_playbook.sh inventory.ini
```

The wrapper installs `ansible.windows` and `community.general` from
`provisioning/collections.yml` before running `provisioning/playbook.yml`.

The playbook applies the following roles in order:

| Play | Target hosts | Roles applied |
|------|-------------|---------------|
| /etc/hosts | all Linux nodes | inline tasks |
| Windows basic config | trainee workstations | `windows` |
| REP core services | rep-* backend nodes | `rep-core` |
| LMS course portal | rep-practical-labs | `lms-content` |
| Phishing simulator | phishing-simulator | `phishing-simulator` |
| Mail relay | mail-relay | `mail-relay` |
| Reporting workspace | reporting-workspace | `reporting-workspace` |
| Instructor console | instructor-console | `instructor-console` |
| Trainee workstations | trainee-workstation-01/02 | `trainee-workstation` |

## 6. Post-deployment verification

| Check | Command / URL |
|-------|--------------|
| All hosts reachable | `ansible all -i inventory.ini -m ping` |
| GoPhish running | `http://phishing-simulator.internal:3333/` |
| MailHog SMTP + WebUI | `http://mail-relay.internal:8025/` |
| LMS course portal | `http://lms.internal:8080/` |
| Grafana dashboard | `http://reporting.internal:3000/` |
| Initial GoPhish creds | `cat /opt/phishing-simulator/admin_credentials.txt` (on phishing-simulator host) |

## 7. First-run instructor checklist

**Do not create a campaign by hand.** The deploy launches it (Gate 1) and the
`rep-finalize.timer` scores and delivers feedback (Gate 2). Building a second
campaign in the GoPhish UI would send every trainee a duplicate email and break
the "exactly one message in your inbox" answer at L12. The whole instructor
workflow is *deploy → verify green → hand out the URLs*:

1. Ansible `PLAY RECAP`: every host `failed=0 unreachable=0`.
2. The content guardrails passed in the log (LMS index literals, directory-TLD
   mismatch, MailHog SMTP profile, email template literals).
3. **One phishing email per trainee** in `http://mail-relay.internal:8025/` —
   proof the Gate 1 auto-launch fired.
4. `systemctl status rep-finalize.timer` on `reporting-workspace` shows
   `active (waiting)` — Gate 2 is armed.
5. `http://reporting.internal:3000/` opens the REP Overview dashboard **without
   logging in** (trainees read it anonymously at L26/L27).
6. LMS portal reachable from a trainee workstation.

See [subcase-2a-phishing-training.md](subcase-2a-phishing-training.md) for the
manual overrides (`LAUNCH_CAMPAIGN`, `FINALIZE_FEEDBACK`, …) and the toggles that
turn either gate off, if you deliberately want the manual flow.

## 8. Export campaign results *(optional)*

The deploy persists the GoPhish API key, so there is nothing to generate or
export for normal operation — Grafana is fed by the Gate 2 pipeline. Export raw
campaign results only if you want them outside the dashboard:

```bash
# Run from instructor-console or phishing-simulator.
# The deploy already persists the key; export it only when running this standalone.
export GOPHISH_API_KEY=<api-key>
provisioning/case-2a/scripts/export_gophish_results.sh <campaign_id>
```

## Troubleshooting

```bash
# GoPhish container logs
ssh phishing-simulator
docker logs gophish

# MailHog container logs
ssh mail-relay
docker logs mailhog

# LMS nginx config test
ssh rep-practical-labs
nginx -t && curl http://127.0.0.1:8080/

# PostgreSQL status
ssh reporting-workspace
systemctl status postgresql
sudo -u postgres psql -c "\l"
```
