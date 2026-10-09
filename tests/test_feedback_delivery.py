"""Checks for the Gate 2 feedback delivery and the inbox it writes to.

rep-finalize.timer runs deliver_feedback.py every 5 minutes. When every run
emailed every trainee, the shared Mailpit relay filled up and evicted the GoPhish
phishing email that L12-L18 and L22 ask about. These tests pin the two guards
against that: delivery only emails feedback that changed, and Mailpit keeps more
than its default 500 messages.
"""
import copy
import importlib.util
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "provisioning/roles/reporting-workspace/files/deliver_feedback.py"
MAILPIT_DEFAULT_CAP = 500


@pytest.fixture(scope="module")
def deliver_feedback():
    """Load the script without a PostgreSQL driver: only its pure helpers run here."""
    stubs = {}
    if importlib.util.find_spec("psycopg2") is None:
        extras = types.ModuleType("psycopg2.extras")
        extras.RealDictCursor = object
        psycopg2 = types.ModuleType("psycopg2")
        psycopg2.extras = extras
        psycopg2.Error = Exception
        stubs = {"psycopg2": psycopg2, "psycopg2.extras": extras}
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("deliver_feedback", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.fixture
def unreported_score():
    """What score_campaign.py stores for a trainee who has not acted yet."""
    return {
        "campaign_id": 1,
        "campaign_name": "Security Compliance Drill",
        "email": "trainee01@cynet.lab",
        "first_name": "Trainee",
        "last_name": "One",
        "status": "Email Sent",
        "reported": False,
        "clicked": False,
        "submitted_data": False,
        "time_to_report_minutes": None,
        "score_detection_accuracy": 10,
        "score_report_completeness": 0,
        "score_time_to_report": 0,
        "score_no_click_bonus": 10,
        "score_total": 20,
        "traffic_light": "red",
    }


def signature_of(module, score):
    return module._signature(module._subject(score), module._render_html(score))


def test_feedback_rendering_is_deterministic(deliver_feedback, unreported_score):
    """Anything run-dependent in the email (a timestamp, a nonce) would make every
    run look like new feedback and bring the flood back."""
    assert signature_of(deliver_feedback, unreported_score) == signature_of(
        deliver_feedback, copy.deepcopy(unreported_score)
    )


def test_unchanged_feedback_is_not_emailed_again(deliver_feedback, unreported_score):
    signature = signature_of(deliver_feedback, unreported_score)

    assert deliver_feedback._needs_delivery(signature, None), "first feedback must be emailed"
    assert not deliver_feedback._needs_delivery(signature, signature), (
        "the timer re-emailed feedback the trainee already has"
    )
    assert deliver_feedback._needs_delivery(signature, signature, force=True)


def test_a_new_score_is_emailed(deliver_feedback, unreported_score):
    reported = dict(
        unreported_score,
        status="Email Reported",
        reported=True,
        time_to_report_minutes=4.0,
        score_detection_accuracy=40,
        score_report_completeness=30,
        score_time_to_report=20,
        score_total=100,
        traffic_light="green",
    )
    assert deliver_feedback._needs_delivery(
        signature_of(deliver_feedback, reported), signature_of(deliver_feedback, unreported_score)
    )


def test_the_delivery_ledger_is_created_with_the_schema(deliver_feedback):
    tasks = yaml.safe_load(
        (REPO_ROOT / "provisioning/roles/reporting-workspace/tasks/install_postgresql.yml").read_text(
            encoding="utf-8"
        )
    )
    names = [task["name"] for task in tasks]
    ledger = next(
        (i for i, task in enumerate(tasks) if "feedback_deliveries" in str(task.get("ansible.builtin.command"))),
        None,
    )
    grants = names.index("Grant reporting user access to all tables and sequences")

    assert ledger is not None, "deliver_feedback.py needs the feedback_deliveries table"
    assert ledger < grants, "create the ledger before the grants so rep_reporting can write it"

    ddl = tasks[ledger]["ansible.builtin.command"]["cmd"]
    for column in ("campaign_id", "email", "signature"):
        assert column in ddl
    assert "PRIMARY KEY (campaign_id, email)" in ddl, "the ledger's upsert relies on this key"


def test_mailpit_keeps_more_than_its_default_cap():
    defaults = yaml.safe_load(
        (REPO_ROOT / "provisioning/roles/mail-relay/defaults/main.yml").read_text(encoding="utf-8")
    )
    compose = (REPO_ROOT / "provisioning/roles/mail-relay/templates/docker-compose.yml.j2").read_text(
        encoding="utf-8"
    )

    assert "MP_MAX_MESSAGES" in compose and "mail_relay_max_messages" in compose
    cap = int(defaults["mail_relay_max_messages"])
    assert cap == 0 or cap > MAILPIT_DEFAULT_CAP, (
        f"A cap of {cap} lets the shared relay evict the phishing email trainees analyse"
    )
