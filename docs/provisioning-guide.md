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
export INSTRUCTOR_CONSOLE_PASSWORD='...'   # OS password for ubuntu on instructor-console
export ANSIBLE_PASSWORD_PHISHING_SIMULATOR='...'
export ANSIBLE_PASSWORD_MAIL_RELAY='...'
export ANSIBLE_PASSWORD_REPORTING_WORKSPACE='...'
export ANSIBLE_PASSWORD_TRAINEE_01='...'
export ANSIBLE_PASSWORD_TRAINEE_02='...'
```

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

1. Open `http://phishing-simulator.internal:3333/` and log in with credentials from
   `/opt/phishing-simulator/admin_credentials.txt`
2. Change the admin password immediately
3. Generate an API key under **Account Settings**
4. Verify the **MailHog Lab Relay** sending profile is present
5. Create a phishing campaign using:
   - Template: `IT Security Compliance Notice` (pre-loaded)
   - Sending profile: `MailHog Lab Relay`
   - Landing page: redirect to `http://lms.internal:8080/#exercise` after capture
6. Send a test email and verify it appears in `http://mail-relay.internal:8025/`
7. Confirm LMS portal is accessible from trainee workstations

## 8. Export campaign results

```bash
# Run from instructor-console or phishing-simulator
export GOPHISH_API_KEY=<api-key-from-account-settings>
provisioning/case-2a/scripts/export_gophish_results.sh <campaign_id>
```

Results are saved as JSON and can be ingested into the Grafana reporting workspace.

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
