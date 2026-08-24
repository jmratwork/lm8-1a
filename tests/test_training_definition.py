"""Structural and coupling checks for the CyberRangeCZ training definition.

The training definition is trainee-facing and the Ansible roles are what build
the environment it asks about. Those two drift apart silently: an edit to an LMS
page, the phishing template, the Grafana dashboard or the sender address can
leave a level with no valid answer, and nothing fails until a cohort is stuck.

These tests turn that coupling into a check. Levels are named with the display
numbering the portal shows a trainee (``L<n>`` where ``n = order + 1``), which is
the convention used in the docs and in the Ansible guardrail messages too.
"""
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LEVEL_COUNT = 30


def display(order):
    """Portal level number for a 0-indexed ``order``."""
    return order + 1


@pytest.fixture(scope="module")
def training_definition():
    """The training definition is not tracked here: it carries every answer and
    solution, and is imported into CyberRangeCZ directly. Drop the current
    version in the repository root to check it against what these roles deploy."""
    matches = sorted(REPO_ROOT.glob("V*_puc2_sub_case_2a_phishing_training.json"))
    if not matches:
        pytest.skip(
            "No training definition in the repository root; place the current "
            "V*_puc2_sub_case_2a_phishing_training.json there to check its answers "
            "against what these roles deploy"
        )
    assert len(matches) == 1, (
        f"Expected exactly one training definition in the repository root, found: "
        f"{[m.name for m in matches]}. Keep only the version you are deploying."
    )
    return json.loads(matches[0].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def levels(training_definition):
    """Levels keyed by ``order``."""
    return {level["order"]: level for level in training_definition["levels"]}


def answer(levels, order):
    return levels[order]["answer"]


def read_text(relative_path):
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def load_yaml(relative_path):
    return yaml.safe_load(read_text(relative_path))


def tld(address):
    return address.rsplit(".", 1)[-1]


# --- structure --------------------------------------------------------------


def test_levels_are_complete_and_sequential(training_definition, levels):
    assert len(training_definition["levels"]) == LEVEL_COUNT
    assert sorted(levels) == list(range(LEVEL_COUNT)), "Level order must be 0..29 with no gaps"

    for order, level in sorted(levels.items()):
        assert level["title"].strip(), f"L{display(order)} has no title"
        assert level["level_type"] in {
            "INFO_LEVEL",
            "ACCESS_LEVEL",
            "TRAINING_LEVEL",
            "ASSESSMENT_LEVEL",
        }


def test_training_levels_carry_an_answer_and_a_solution(levels):
    for order, level in sorted(levels.items()):
        if level["level_type"] != "TRAINING_LEVEL":
            continue
        assert str(level.get("answer", "")).strip(), f"L{display(order)} has no answer"
        assert level.get("solution", "").strip(), f"L{display(order)} has no solution"
        assert str(level["answer"]) in level["solution"], (
            f"L{display(order)} solution text does not state its own answer"
        )


def test_assessment_levels_have_answerable_questions(levels):
    for order, level in sorted(levels.items()):
        if level["level_type"] != "ASSESSMENT_LEVEL":
            continue
        questions = level["questions"]
        assert questions, f"L{display(order)} has no questions"
        for question in questions:
            if level["assessment_type"] == "QUESTIONNAIRE":
                continue
            correct = [c for c in question.get("choices", []) if c.get("correct")]
            assert correct, (
                f"L{display(order)} question {question['order']} has no correct choice"
            )


# --- coupling: LMS portal content -------------------------------------------


def test_lms_index_backs_its_dependent_answers(levels):
    """L4, L5, L9, L19 and L25 read their answers off the LMS index page."""
    index = read_text("provisioning/roles/lms-content/templates/course-index.html.j2")

    assert len(re.findall(r'class="score-item"', index)) == int(answer(levels, 3)), (
        "L4 counts the Assessment Scoring cells on the LMS index"
    )
    assert answer(levels, 4).capitalize() in index, "L5 answer missing from the LMS index"
    assert answer(levels, 8) in index, "L9 answer missing from the LMS index"
    assert answer(levels, 18) in index, "L19 answer missing from the LMS index"
    assert f"mail-relay.internal:{answer(levels, 24)}" in index, (
        "L25 reads the Mailpit port off the LMS index"
    )


def test_mailpit_port_matches_the_deployed_relay(levels):
    defaults = load_yaml("provisioning/roles/mail-relay/defaults/main.yml")
    assert str(defaults["mail_relay_ui_port"]) == answer(levels, 24), (
        "L25 answer and the deployed Mailpit UI port disagree"
    )


# --- coupling: phishing sender and the corporate directory -------------------


def test_sender_tld_is_the_l13_answer(levels):
    defaults = load_yaml("provisioning/roles/phishing-simulator/defaults/main.yml")
    assert tld(defaults["phishing_simulator_from_address"]) == answer(levels, 12), (
        "L13 asks for the TLD of the phishing sender; change one, change the other"
    )


def test_directory_tld_keeps_l20_a_mismatch(levels):
    directory_page = read_text("provisioning/roles/lms-content/tasks/main.yml")
    directory_addresses = set(re.findall(r"security@[A-Za-z0-9.-]+", directory_page))
    assert directory_addresses, "Corporate directory IT Security entry not found"

    phishing = load_yaml("provisioning/roles/phishing-simulator/defaults/main.yml")
    phishing_tld = tld(phishing["phishing_simulator_from_address"])

    mismatching = all(tld(address) != phishing_tld for address in directory_addresses)
    assert (answer(levels, 19) == "MISMATCH") == mismatching, (
        f"L20 answers {answer(levels, 19)} but the directory {directory_addresses} vs "
        f"the phishing sender TLD .{phishing_tld} says otherwise"
    )


def test_lms_mirror_of_the_sender_stays_in_sync():
    """The lms-content role mirrors the sender so its own guardrail can check it."""
    lms = load_yaml("provisioning/roles/lms-content/defaults/main.yml")
    phishing = load_yaml("provisioning/roles/phishing-simulator/defaults/main.yml")
    assert lms["lms_content_phishing_from_address"] == phishing["phishing_simulator_from_address"]


# --- coupling: the phishing email itself ------------------------------------


def test_phishing_email_backs_l14_l15_l18(levels):
    template = read_text("provisioning/roles/phishing-simulator/files/phishing-email.html")

    assert answer(levels, 13) in template, "L14 reads the URGENT heading off the email"
    assert answer(levels, 17) in template, "L18 reads the policy code off the email"
    assert "{{.RId}}" in template, (
        "L15 asks for the GoPhish tracking parameter; the template must keep the RId token"
    )


# --- coupling: the Grafana cohort dashboard ---------------------------------


def grafana_panels():
    """(title, gridPos) for each panel in the REP Overview dashboard template."""
    dashboard = read_text("provisioning/roles/reporting-workspace/templates/dashboard.json.j2")
    pairs = re.findall(r'"title":\s*"([^"]+)".*?"gridPos":\s*(\{[^}]*\})', dashboard, re.S)
    return [(title, json.loads(grid)) for title, grid in pairs if "{{" not in title]


def test_grafana_panel_titles_are_the_l26_l27_answers(levels):
    titles = [title for title, _ in grafana_panels()]
    assert answer(levels, 25) in titles, "L26 answer is not a panel title on the dashboard"
    assert answer(levels, 26) in titles, "L27 answer is not a panel title on the dashboard"


def test_l26_panel_is_still_the_bottom_right_one(levels):
    """L26 identifies its panel by position, so the layout is part of the answer."""
    panels = grafana_panels()
    bottom_row = max(grid["y"] for _, grid in panels)
    bottom_right = max(
        (p for p in panels if p[1]["y"] == bottom_row), key=lambda p: p[1]["x"]
    )
    assert bottom_right[0] == answer(levels, 25), (
        f"L26 asks for the bottom-right panel; the dashboard now puts "
        f"'{bottom_right[0]}' there"
    )


def test_l27_panel_still_spans_the_full_width(levels):
    """L27's hint points at the wide table in the middle of the dashboard."""
    panels = dict(grafana_panels())
    assert panels[answer(levels, 26)]["w"] == 24


def test_grafana_is_readable_without_the_admin_login(training_definition):
    """L26/L27 send trainees to Grafana. Either anonymous Viewer access is on and
    no credentials belong in the training definition, or it is off and the levels
    must say how to log in."""
    reporting = load_yaml("provisioning/roles/reporting-workspace/defaults/main.yml")
    grafana_ini = read_text("provisioning/roles/reporting-workspace/templates/grafana.ini.j2")
    blob = json.dumps(training_definition, ensure_ascii=False)

    assert "[auth.anonymous]" in grafana_ini, "grafana.ini template lost its anonymous-auth section"

    if reporting["reporting_workspace_grafana_anonymous_viewer"]:
        assert reporting["reporting_workspace_grafana_anonymous_org_role"] == "Viewer", (
            "Anonymous access must stay read-only; trainees would otherwise be able "
            "to edit the instructor's cohort dashboard"
        )
        assert reporting["reporting_workspace_grafana_admin_password"] not in blob, (
            "Anonymous Viewer access is enabled, so the training definition must not "
            "hand trainees the shared Grafana admin credentials"
        )
    else:
        assert reporting["reporting_workspace_grafana_admin_user"] in blob, (
            "Anonymous access is disabled, so L26/L27 must tell trainees how to log in"
        )


# --- anti-regression: the automated gates must not resurface as manual steps -


MANUAL_GATE_COMMANDS = ("LAUNCH_CAMPAIGN", "FINALIZE_FEEDBACK", "PUBLISH_FEEDBACK", "SCORE_CAMPAIGN")

# Naming a console command is only half the problem: "once the instructor scores
# the campaign" says the same thing without naming one, and reads to a trainee as
# a step that will never happen. Matched tightly enough that the negated form
# ("the instructor no longer runs scoring by hand") does not trip it.
MANUAL_GATE_PHRASE = re.compile(
    r"instructor\s+(?:will\s+)?(?:runs?|scores?|launches|publishes|sends|creates)\b",
    re.IGNORECASE,
)


def manual_gate_offenders(content):
    """Every way ``content`` still tells a reader to wait for a human gate."""
    offenders = [command for command in MANUAL_GATE_COMMANDS if command in content]
    offenders += sorted({match.group(0) for match in MANUAL_GATE_PHRASE.finditer(content)})
    return offenders


def automation_is_enabled():
    phishing = load_yaml("provisioning/roles/phishing-simulator/defaults/main.yml")
    reporting = load_yaml("provisioning/roles/reporting-workspace/defaults/main.yml")
    return (
        phishing["phishing_simulator_auto_launch"] is True
        and reporting["reporting_workspace_auto_finalize"] is True
    )


@pytest.mark.parametrize(
    "wording, is_offending",
    [
        # Historical regressions this detector exists to catch.
        ("once the instructor runs <strong>PUBLISH_FEEDBACK</strong> from the console", True),
        ("The instructor will run `FINALIZE_FEEDBACK` once all trainees have submitted", True),
        ("within 5 minutes once the instructor scores the campaign", True),
        # Legitimate wording that must not trip it.
        ("The instructor no longer runs scoring by hand", False),
        ("cohort metrics are reported to the instructor via Grafana", False),
        ("Scoring runs automatically on a short cycle", False),
    ],
)
def test_manual_gate_detector_recognises_the_wordings_it_is_for(wording, is_offending):
    assert bool(manual_gate_offenders(wording)) is is_offending


def test_training_definition_describes_the_automated_flow(training_definition):
    """Gate 1 and Gate 2 run unattended; no level may tell a trainee to wait for
    an instructor command that nobody is going to type."""
    if not automation_is_enabled():
        pytest.skip("Automation toggles are off; the manual gate flow is expected")

    offenders = manual_gate_offenders(json.dumps(training_definition, ensure_ascii=False))
    assert not offenders, (
        f"Training definition still points trainees at a manual gate ({offenders}) "
        f"while the deploy automates it"
    )


@pytest.mark.parametrize(
    "trainee_facing_file",
    [
        "provisioning/roles/lms-content/templates/course-index.html.j2",
        "provisioning/roles/lms-content/tasks/main.yml",
        "provisioning/roles/instructor-console/templates/lms-content/wrapper.html.j2",
    ],
)
def test_trainee_facing_pages_describe_the_automated_flow(trainee_facing_file):
    if not automation_is_enabled():
        pytest.skip("Automation toggles are off; the manual gate flow is expected")

    offenders = manual_gate_offenders(read_text(trainee_facing_file))
    assert not offenders, (
        f"{trainee_facing_file} tells trainees to wait for a manual step ({offenders}), "
        f"but the deploy runs those gates automatically"
    )
