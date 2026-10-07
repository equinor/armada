from unittest.mock import Mock, call
from uuid import UUID

import pytest
import requests

from robotics_integration_tests import conftest as fixtures
from robotics_integration_tests.custom_containers.isar import (
    create_isar_robot_container,
)
from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities import flotilla_backend_api as api
from robotics_integration_tests.utilities.mqtt_credentials import MqttCredentials


@pytest.fixture
def robot_container():
    return create_isar_robot_container(
        network=Mock(),
        openid_config_url="http://keycloak/realms/robotics/.well-known/openid-configuration",
        mqtt_credentials=MqttCredentials("", "", "", {"isar": "test-password"}),
        name="FixtureRobot",
        alias="isar_fixture",
        port=3456,
        test_id="test-run",
    )


@pytest.fixture
def provisioning(monkeypatch):
    calls = Mock()
    monkeypatch.setattr(api.requests, "post", calls.post)
    calls.post.return_value = calls.response
    calls.response.json.return_value = {"id": "registered-robot"}
    monkeypatch.setattr(
        api, "retrieve_access_token_for_integration_tests_app", calls.token
    )
    calls.token.return_value = "test-token"
    for name in (
        "get_inspection_area_id_for_installation",
        "set_current_inspection_area_for_robot",
        "wait_for_inspection_area_to_be_updated_on_robot",
        "wait_for_robot_status",
    ):
        monkeypatch.setattr(api, name, getattr(calls, name))
    calls.get_inspection_area_id_for_installation.return_value = "inspection-area"
    return calls


def test_registers_container_identity_before_area_assignment_and_readiness(
    robot_container, provisioning, monkeypatch
):
    mapped_port = Mock(side_effect=AssertionError("Must not use host-mapped port"))
    monkeypatch.setattr(robot_container, "get_exposed_port", mapped_port)

    assert api.setup_robot_in_flotilla("http://backend", robot_container) == (
        "registered-robot",
        "HUA",
    )
    isar_id = robot_container.env["ISAR_ISAR_ID"]
    assert str(UUID(isar_id)) == isar_id
    assert provisioning.mock_calls == [
        call.token(settings.FLOTILLA_SCOPE),
        call.post(
            "http://backend/robots",
            json={
                "name": "FixtureRobot",
                "isarId": isar_id,
                "robotType": "Robot",
                "serialNumber": "0001",
                "currentInstallationCode": "HUA",
                "documentation": [],
                "host": "isar_fixture",
                "port": 3456,
                "robotCapabilities": [
                    "take_thermal_image",
                    "take_image",
                    "take_video",
                    "take_thermal_video",
                    "record_audio",
                    "take_co2_measurement",
                    "take_acoustic_measurement",
                ],
                "status": "Offline",
            },
            headers={"Authorization": "Bearer test-token"},
            timeout=30,
        ),
        call.response.raise_for_status(),
        call.response.json(),
        call.get_inspection_area_id_for_installation(
            backend_url="http://backend", installation_code="HUA"
        ),
        call.set_current_inspection_area_for_robot(
            backend_url="http://backend",
            inspection_area_id="inspection-area",
            robot_id="registered-robot",
        ),
        call.wait_for_inspection_area_to_be_updated_on_robot(
            backend_url="http://backend", robot_id="registered-robot"
        ),
        call.wait_for_robot_status(
            backend_url="http://backend",
            robot_name="FixtureRobot",
            expected_status="Home",
        ),
    ]
    mapped_port.assert_not_called()


@pytest.mark.parametrize("status_code", [400, 401, 403, 500])
def test_registration_errors_stop_setup_immediately(
    robot_container, provisioning, status_code
):
    response = requests.Response()
    response.status_code = status_code
    response.url = "http://backend/robots"
    provisioning.post.return_value = response

    with pytest.raises(requests.HTTPError) as error:
        api.setup_robot_in_flotilla("http://backend", robot_container)

    assert error.value.response is response
    provisioning.post.assert_called_once()
    provisioning.get_inspection_area_id_for_installation.assert_not_called()
    provisioning.wait_for_robot_status.assert_not_called()


def test_registration_timeout_is_not_retried(robot_container, provisioning):
    provisioning.post.side_effect = requests.Timeout("registration timed out")
    with pytest.raises(requests.Timeout, match="registration timed out"):
        api.setup_robot_in_flotilla("http://backend", robot_container)
    provisioning.post.assert_called_once()
    provisioning.get_inspection_area_id_for_installation.assert_not_called()


@pytest.mark.parametrize(
    "fixture_name, expected_names",
    [
        ("armada_with_single_successful_robot", [settings.ISAR_ROBOT_NAME]),
        ("armada_with_single_failing_robot", [settings.ISAR_ROBOT_NAME]),
        (
            "armada_with_multiple_robots",
            [
                "MissionOkThenHome",
                "MissionOkThenLost",
                "MissionFailThenHome",
                "MissionFailThenLost",
            ],
        ),
    ],
)
def test_all_robot_fixtures_register_distinct_container_identities(
    monkeypatch, provisioning, fixture_name, expected_names
):
    monkeypatch.setattr(StreamLoggingDockerContainer, "start", lambda self: self)
    monkeypatch.setattr(StreamLoggingDockerContainer, "stop", lambda self: None)
    monkeypatch.setattr(fixtures, "wait_for_port_mapping_to_be_available", Mock())
    monkeypatch.setattr(fixtures, "_assert_robots_require_authentication", Mock())
    monkeypatch.setattr(
        fixtures, "_blob_connection_strings", lambda armada: ("data", "metadata")
    )
    armada = Mock(robots={}, test_id="test-run")
    armada.flotilla_backend.backend_url = "http://backend"
    armada.mqtt_credentials = MqttCredentials("", "", "", {"isar": "test-password"})
    provisioning.response.json.side_effect = [
        {"id": f"robot-{index}"} for index in range(len(expected_names))
    ]
    fixture = getattr(fixtures, fixture_name).__wrapped__(armada)
    try:
        assert next(fixture) is armada
        payloads = [
            request.kwargs["json"] for request in provisioning.post.call_args_list
        ]
        assert [payload["name"] for payload in payloads] == expected_names
        assert len({payload["isarId"] for payload in payloads}) == len(expected_names)
        assert len({payload["host"] for payload in payloads}) == len(expected_names)
        for index, payload in enumerate(payloads):
            robot = armada.robots[payload["name"]]
            assert payload["isarId"] == robot.container.env["ISAR_ISAR_ID"]
            assert payload["host"] == robot.alias
            assert payload["port"] == robot.port == settings.ISAR_ROBOT_PORT
            assert payload["currentInstallationCode"] == robot.installation_code
            assert robot.robot_id == f"robot-{index}"
    finally:
        fixture.close()


@pytest.mark.parametrize("method", ["get", "patch"])
def test_inspection_area_http_errors_are_not_silently_ignored(monkeypatch, method):
    response = requests.Response()
    response.status_code = 403
    response.url = "http://backend/inspection-area"
    monkeypatch.setattr(api, "_add_headers", lambda: {})
    monkeypatch.setattr(api.requests, method, Mock(return_value=response))

    with pytest.raises(requests.HTTPError):
        if method == "get":
            api.get_inspection_area_id_for_installation("http://backend", "HUA")
        else:
            api.set_current_inspection_area_for_robot(
                "http://backend", "area", "robot"
            )
