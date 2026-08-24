import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def training_data():
    training_file = REPO_ROOT / "training_linear.json"
    with training_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def test_training_linear_structure(training_data):
    assert isinstance(training_data, dict)
    for key in ("name", "description", "modules"):
        assert key in training_data, f"Missing key '{key}' in training file"

    modules = training_data["modules"]
    assert isinstance(modules, list) and modules, "Modules list must not be empty"

    for module in modules:
        assert set(module.keys()) >= {"id", "title", "phases"}
        assert module["id"]
        assert module["title"].strip()
        phases = module["phases"]
        assert isinstance(phases, list) and phases

        steps = []
        for phase in phases:
            assert set(phase.keys()) >= {"name", "activities"}
            assert phase["name"].strip()
            activities = phase["activities"]
            assert isinstance(activities, list) and activities
            for activity in activities:
                assert set(activity.keys()) >= {"step", "description", "tools"}
                steps.append(activity["step"])
                assert isinstance(activity["step"], int)
                assert activity["description"].strip()
                tools = activity["tools"]
                assert isinstance(tools, list) and tools
                for tool in tools:
                    assert isinstance(tool, str) and tool.strip()

        sorted_steps = sorted(steps)
        expected_steps = list(range(1, len(sorted_steps) + 1))
        assert sorted_steps == expected_steps, (
            f"Module {module['id']} steps should be sequential starting at 1"
        )


@pytest.fixture(scope="module")
def topology_data():
    topology_file = REPO_ROOT / "topology.yml"
    with topology_file.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_topology_components_are_consistent(topology_data):
    assert "name" in topology_data

    components = topology_data.get("components")
    if not components:
        pytest.skip("Topology file does not declare component metadata")

    assert isinstance(components, dict)

    for component, attrs in components.items():
        assert "purpose" in attrs and attrs["purpose"].strip()
        integrations = attrs.get("integrations", [])
        assert isinstance(integrations, list)
        for target in integrations:
            assert target in components, (
                f"Component '{component}' integrates with unknown target '{target}'"
            )


@pytest.mark.parametrize(
    "topology_path",
    [REPO_ROOT / "provisioning" / "case-2a" / "topology.yml"],
)
def test_provisioning_topologies(topology_path):
    if not topology_path.exists():
        pytest.skip(f"Topology definition {topology_path.name} not present in repository")

    with topology_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    for key in ("name", "hosts", "routers", "networks", "net_mappings", "router_mappings"):
        assert key in data, f"Missing '{key}' in {topology_path.name}"

    hosts = {host["name"] for host in data["hosts"]}
    routers = {router["name"] for router in data["routers"]}
    networks = {net["name"] for net in data["networks"]}

    assert len(hosts) == len(data["hosts"]), "Duplicate host names detected"
    assert len(routers) == len(data["routers"]), "Duplicate router names detected"
    assert len(networks) == len(data["networks"]), "Duplicate network names detected"

    for mapping in data["net_mappings"]:
        assert mapping["host"] in hosts, (
            f"Mapping references unknown host '{mapping['host']}' in {topology_path.name}"
        )
        assert mapping["network"] in networks, (
            f"Mapping references unknown network '{mapping['network']}' in {topology_path.name}"
        )

    for mapping in data["router_mappings"]:
        assert mapping["router"] in routers, (
            f"Router mapping references unknown router '{mapping['router']}' in {topology_path.name}"
        )
        assert mapping["network"] in networks, (
            f"Router mapping references unknown network '{mapping['network']}' in {topology_path.name}"
        )


def load_yaml(relative_path):
    target = REPO_ROOT / relative_path
    with target.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_instructor_console_shortcut_validation_handles_empty_list():
    tasks = load_yaml("provisioning/roles/instructor-console/tasks/main.yml")
    matching = [
        task
        for task in tasks
        if task.get("name") == "Verify instructor console shortcuts are executable"
    ]

    assert matching, "Expected instructor console shortcut validation task to exist"

    task = matching[0]

    assert task.get("when") == "instructor_console_shortcuts | length > 0"
    assert task.get("loop") == "{{ instructor_console_shortcuts }}"

    command = task.get("ansible.builtin.command")
    assert isinstance(command, str) and "item.name" in command

    loop_control = task.get("loop_control", {})
    assert loop_control.get("label") == "{{ item.name | upper }}"

    failed_when = task.get("failed_when")
    assert isinstance(failed_when, str)
    assert "stdout | trim != 'function'" in failed_when


def test_reporting_workspace_healthcheck_defaults_expose_fallbacks():
    defaults = load_yaml("provisioning/roles/reporting-workspace/defaults/main.yml")
    healthcheck = defaults["reporting_workspace_healthcheck"]

    assert "status_code_alternatives" in healthcheck
    assert isinstance(healthcheck["status_code_alternatives"], list)
    assert "failed_when_non_json" in healthcheck
    assert healthcheck["failed_when_non_json"].strip()


def test_reporting_workspace_repo_defaults_include_grafana_oss():
    defaults = load_yaml("provisioning/roles/reporting-workspace/defaults/main.yml")
    repositories = defaults["reporting_workspace_grafana_repositories"]

    assert isinstance(repositories, list) and repositories, "Repository defaults should include Grafana OSS"

    grafana_repo = repositories[0]
    assert grafana_repo["name"] == "grafana_oss"

    apt_key = grafana_repo["apt_key"]
    assert apt_key["url"].endswith("/gpg.key")
    assert apt_key["keyring"].endswith("/grafana.gpg")

    apt_repository = grafana_repo["apt_repository"]
    assert "apt.grafana.com" in apt_repository["repo"]
    assert "signed-by" in apt_repository["repo"]
    assert apt_repository["update_cache"] is True


def test_reporting_workspace_health_task_handles_non_json_payloads():
    tasks = load_yaml("provisioning/roles/reporting-workspace/tasks/main.yml")
    health_tasks = [task for task in tasks if task.get("name") == "Validate Grafana is responding"]

    assert health_tasks, "Health validation task should exist"
    health_task = health_tasks[0]

    uri_config = health_task["ansible.builtin.uri"]
    status_code_expr = uri_config["status_code"]
    assert "status_code_alternatives" in status_code_expr

    failed_when = health_task["failed_when"]
    assert isinstance(failed_when, list) and len(failed_when) == 2
    assert "reporting_workspace_health.json is not defined" in failed_when[0]
    assert "failed_when_non_json" in failed_when[0]
    assert "reporting_workspace_health.json is defined" in failed_when[1]


def test_reporting_workspace_repo_setup_precedes_package_install():
    tasks = load_yaml("provisioning/roles/reporting-workspace/tasks/main.yml")

    repo_tasks = [
        (index, task)
        for index, task in enumerate(tasks)
        if task.get("name") == "Configure Grafana repositories"
    ]

    assert repo_tasks, "Repository configuration task should be defined"

    repo_index, repo_task = repo_tasks[0]
    install_index = next(
        index for index, task in enumerate(tasks) if task.get("name") == "Install Grafana package"
    )

    assert repo_index < install_index, "Repository configuration must run before package installation"
    assert repo_task.get("loop") == "{{ reporting_workspace_grafana_repositories }}"

    included = repo_task.get("ansible.builtin.include_tasks")
    assert included == "configure_grafana_repository.yml", (
        "Repository configuration should delegate to the per-repository task file"
    )

    steps = load_yaml(f"provisioning/roles/reporting-workspace/tasks/{included}")
    assert any("ansible.builtin.apt_repository" in step for step in steps), (
        "Repository task file should configure package repositories"
    )
