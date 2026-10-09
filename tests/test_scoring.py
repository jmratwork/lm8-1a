"""Checks for the Gate 2 scoring engine (score_campaign.py).

GoPhish timestamps carry nanoseconds. The engine used to parse them with
strptime's %f, which stops at six digits, so no timestamp parsed: time to report
was always N/A and a perfect report scored 80/100 instead of 100.
"""
import importlib.util
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "provisioning/roles/reporting-workspace/files/score_campaign.py"


@pytest.fixture(scope="module")
def scoring():
    """Load the script without a PostgreSQL driver: only its pure helpers run here."""
    stubs = {}
    if importlib.util.find_spec("psycopg2") is None:
        extras = types.ModuleType("psycopg2.extras")
        extras.execute_values = None
        psycopg2 = types.ModuleType("psycopg2")
        psycopg2.extras = extras
        stubs = {"psycopg2": psycopg2, "psycopg2.extras": extras}
    saved = {name: sys.modules.get(name) for name in stubs}
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("score_campaign", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


@pytest.mark.parametrize(
    "value, expected",
    [
        # what GoPhish's API actually returns: RFC 3339 with nanoseconds
        ("2026-10-09T14:15:30.948201247Z", datetime(2026, 10, 9, 14, 15, 30, 948201, timezone.utc)),
        ("2026-10-09T14:15:30Z", datetime(2026, 10, 9, 14, 15, 30, tzinfo=timezone.utc)),
        ("2026-10-09T14:15:30.5Z", datetime(2026, 10, 9, 14, 15, 30, 500000, timezone.utc)),
        ("2026-10-09T16:15:30.948201247+02:00", datetime(2026, 10, 9, 14, 15, 30, 948201, timezone.utc)),
    ],
)
def test_parses_gophish_timestamps(scoring, value, expected):
    assert scoring._parse_dt(value) == expected


@pytest.mark.parametrize("value", [None, "", "yesterday", "2026-10-09 14:15:30"])
def test_unparseable_timestamps_are_none(scoring, value):
    assert scoring._parse_dt(value) is None


def test_a_prompt_report_earns_the_time_points(scoring):
    sent = datetime(2026, 10, 9, 14, 11, 30, tzinfo=timezone.utc)
    reported = sent + timedelta(minutes=4)
    stamp = lambda dt: dt.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")
    email = "trainee01@cynet.lab"
    result = {"email": email, "status": "Email Opened", "reported": True, "send_date": stamp(sent)}
    events = {email: [{"email": email, "message": "Email Reported", "time": stamp(reported)}]}

    score = scoring._score(result, events, 1, "Security Compliance Drill")

    assert score["time_to_report_minutes"] == pytest.approx(4.0, abs=0.01)
    assert score["score_time_to_report"] == 20
    assert score["score_total"] == 100
