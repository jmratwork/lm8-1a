# lm8-1a — PUC2-Sub Case 2a: Phishing Attack Training Scenario

This repository contains all the materials required to run the practical exercises of
**PUC2-Sub Case 2a** on the **CyberRangeCZ** platform. The scenario trains staff to
identify phishing campaigns through a self-paced hands-on educational platform.

## Scenario overview

Staff members undergo comprehensive training in identifying phishing campaigns.
The Training Instructor develops self-paced courses focused on recognising phishing
techniques. Trainees access the platform and engage in practical exercises designed
to assess their ability to:

- Scrutinise sender information for inconsistencies
- Analyse email content for red flags (grammatical errors, urgent requests)
- Verify attachments for legitimacy
- Report suspicious emails using organisational protocols

Upon completion, trainees receive evaluation feedback including scores and suggestions
for further learning.

## Training flow (3 phases, 8 steps)

See the UML sequence diagram for the full actor interaction. In brief:

| Phase | Steps | Description |
|-------|-------|-------------|
| **Training setup** | 1–2 | Instructor creates self-paced phishing courses and publishes content |
| **Trainee executes scenario** | 3–4 | Trainee launches phishing module; platform delivers simulated phishing emails/pages |
| **Assessment & feedback** | 5–8 | Trainee performs detection; platform scores, delivers feedback, reports cohort metrics to instructor |

The scenario is defined by **two artefacts**: this repository (which builds and
operates the range) and the training definition imported into CyberRangeCZ (the
30 levels a trainee works through). The definition is kept out of this
repository because it contains every answer and solution; place it here as
`V*_puc2_sub_case_2a_phishing_training.json` to run the checks against it.
`training_linear.json` is the machine-readable map between the two,
consumed by the scoring pipeline. There is no separate instructor runbook — the
instructor workflow lives in
[docs/subcase-2a-phishing-training.md](docs/subcase-2a-phishing-training.md),
which also carries the UML step ↔ artefact mapping.

## Key files

| File / directory | Purpose |
|-----------------|---------|
| `topology.yml` | CyberRangeCZ sandbox topology (hosts, networks, router mappings) |
| `training_linear.json` | Machine-readable UML step map — 3 phases, 8 steps, actors, tools, success criteria; consumed by the scoring pipeline |
| `V*_puc2_sub_case_2a_phishing_training.json` | Trainee-facing training definition imported into CyberRangeCZ — 30 levels with tasks, answers, hints and solutions. **Not tracked here** (it carries every answer); drop the current version in this directory to validate it |
| `provisioning/playbook.yml` | Main Ansible playbook orchestrating all roles |
| `provisioning/roles/` | Ansible roles for each platform component |
| `provisioning/case-2a/` | Scenario-specific topology and helper scripts |
| `docs/subcase-2a-phishing-training.md` | Detailed deployment and operational guide |
| `group_vars/trainees.yml` | Shared variables for trainee workstations |
| `inventory.sample` | Inventory template — load secrets via Ansible Vault or environment variables |

## Infrastructure summary

| Component | Host | IP | Technology |
|-----------|------|----|-----------|
| LMS course portal | rep-practical-labs | 10.20.10.40 | Nginx (port 8080) |
| Phishing simulator | phishing-simulator | 10.20.10.50 | GoPhish (Docker) |
| Mail relay | mail-relay | 10.20.10.60 | MailHog (Docker) |
| Instructor console | instructor-console | 10.20.20.10 | Ubuntu + tmux |
| Trainee workstations | trainee-workstation-01/02 | 10.20.20.50–60 | Windows 10 |
| Reporting dashboard | reporting-workspace | 10.20.30.10 | Grafana + PostgreSQL |

See `docs/subcase-2a-phishing-training.md` for the full architecture description and
first-run checklist.

![CYNET Activity Diagram](docs/figures/cynet-activity.png)

## Deploying

```bash
# 1. Copy and fill the inventory
cp inventory.sample inventory.ini
# Edit inventory.ini with real host addresses and credentials

# 2. Run the provisioning playbook
provisioning/run_playbook.sh inventory.ini
```

See `docs/subcase-2a-phishing-training.md` for prerequisites and step-by-step instructions.

## Validating the repository

```bash
pip install -r requirements-dev.txt
pytest
```

The tests verify that `training_linear.json` is structurally valid and sequential,
that the topology files only reference defined hosts, networks, and routers, and
that every answer in the training definition is still backed by what the Ansible
roles actually deploy (LMS content, phishing sender TLD, email template literals,
Grafana panel titles and layout).

## Credential management

Replace password placeholders in `inventory.sample` using Ansible Vault files or
exported environment variables. Never commit real credentials to the repository.

## Licence

The content is provided strictly for educational purposes.
