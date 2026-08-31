import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

import requests
from loguru import logger
from requests import Response

from robotics_integration_tests.custom_containers.stream_logging_docker_container import (
    StreamLoggingDockerContainer,
)
from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication import (
    retrieve_access_token_for_integration_tests_app,
)


def _add_headers() -> Dict[str, str]:
    access_token: str = retrieve_access_token_for_integration_tests_app(
        settings.SARA_SCOPE
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    return headers


def _list_database_entries(backend_url: str, request_path: str) -> List[Dict]:
    logger.info(f"Listing database entries for path: {backend_url}/{request_path}")
    response: Response = requests.get(
        f"{backend_url}/{request_path}", headers=_add_headers()
    )
    response.raise_for_status()
    return response.json()


def wait_for_sara_to_be_responsive(sara_url: str, timeout: int = 60) -> None:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Sara was not responsive within the given timeout {timeout} seconds"
            )

        try:
            analysis_groups: List[Dict] = _list_database_entries(
                backend_url=sara_url, request_path="api/analysis-group"
            )
        except Exception as e:
            logger.warning(
                f"Backend is not responsive yet, will retry until timeout... Exception: {e}"
            )
            time.sleep(1)
            continue

        if len(analysis_groups) >= 0:
            logger.info("Sara is responsive")
            return


def _logs_to_text(logs: Any) -> str:
    if logs is None:
        return ""
    if isinstance(logs, str):
        return logs
    if isinstance(logs, (bytes, bytearray)):
        return logs.decode("utf-8", errors="replace")
    if isinstance(logs, (list, tuple)):
        return "\n".join(_logs_to_text(part) for part in logs)
    return str(logs)


def wait_for_sara_logs(
    container: StreamLoggingDockerContainer, log_message: str, timeout: int = 60
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if log_message in _logs_to_text(container.get_logs()):
            return
        time.sleep(1)
    raise AssertionError(f"Did not find log line within {timeout}s: {log_message}")


def wait_for_sara_log_count(
    container: StreamLoggingDockerContainer,
    log_message: str,
    expected_count: int,
    timeout: int = 60,
) -> None:
    """Poll until a log line has occurred exactly expected_count times.

    Waiting for a count rather than a single occurrence is what lets a caller
    assert that SARA did *not* act on something: wait for the log line that
    proves every message has been processed, then assert the count of the
    action itself.
    """
    deadline = time.time() + timeout
    count = 0
    while time.time() < deadline:
        count = _logs_to_text(container.get_logs()).count(log_message)
        if count >= expected_count:
            break
        time.sleep(1)

    if count != expected_count:
        raise AssertionError(
            f"Expected SARA to log '{log_message}' exactly {expected_count} times "
            f"within {timeout}s, but it occurred {count} times"
        )


def list_inspection_records(
    sara_url: str, installation_code: str = "", page_size: int = 200
) -> List[Dict]:
    params: Dict[str, Any] = {"PageSize": page_size}
    if installation_code:
        params["InstallationCode"] = installation_code

    response: Response = requests.get(
        f"{sara_url}/api/inspection-record",
        params=params,
        headers=_add_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["items"]


def wait_for_inspection_records_for_mission(
    sara_url: str,
    mission_run_id: str,
    expected_count: int,
    installation_code: str = "",
    timeout: int = 120,
) -> List[Dict]:
    """Poll until SARA has an inspection record per inspection in the mission.

    Records carry the Flotilla mission run id as ``flotillaMissionId``, which is
    the id ISAR was given when the mission was dispatched.
    """
    deadline = time.time() + timeout
    records: List[Dict] = []
    while time.time() < deadline:
        records = [
            record
            for record in list_inspection_records(sara_url, installation_code)
            if record.get("flotillaMissionId") == mission_run_id
        ]
        if len(records) >= expected_count:
            return records
        time.sleep(2)

    raise AssertionError(
        f"Expected {expected_count} inspection records for mission "
        f"{mission_run_id} within {timeout}s, found {len(records)}"
    )


def get_inspection_record(sara_url: str, inspection_id: str) -> Dict:
    """Fetch one record with its full analysis / run / workflow tree."""
    response: Response = requests.get(
        f"{sara_url}/api/inspection-record/inspection-id/{inspection_id}",
        headers=_add_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_analysis(record: Dict, analysis_type: str) -> Dict:
    for analysis in record.get("analyses", []):
        if analysis.get("analysisType") == analysis_type:
            return analysis
    raise AssertionError(
        f"Inspection record {record.get('inspectionId')} has no '{analysis_type}' "
        f"analysis; it has {[a.get('analysisType') for a in record.get('analyses', [])]}"
    )


def get_latest_run(record: Dict, analysis_type: str) -> Dict:
    runs = get_analysis(record, analysis_type).get("runs", [])
    if not runs:
        raise AssertionError(
            f"Analysis '{analysis_type}' on inspection record "
            f"{record.get('inspectionId')} has no runs"
        )
    return max(runs, key=lambda run: run.get("runNumber", 0))


def get_workflows_in_order(run: Dict) -> List[Dict]:
    return sorted(run.get("workflows", []), key=lambda w: w.get("stepNumber", 0))


def wait_for_analysis_run_status(
    sara_url: str,
    inspection_id: str,
    analysis_type: str,
    expected_status: str,
    timeout: int = 180,
) -> Dict:
    """Poll until the newest run of an analysis reaches a terminal status.

    Returns the run, so a caller can go on to assert on its workflows.
    """
    deadline = time.time() + timeout
    last_status = "<no run yet>"
    while time.time() < deadline:
        try:
            run = get_latest_run(
                get_inspection_record(sara_url, inspection_id), analysis_type
            )
            last_status = run.get("status", "")
            if last_status == expected_status:
                return run
        except (AssertionError, requests.RequestException) as error:
            last_status = f"<{error}>"
        time.sleep(2)

    raise AssertionError(
        f"Analysis '{analysis_type}' on inspection {inspection_id} was "
        f"'{last_status}' after {timeout}s, expected '{expected_status}'"
    )


def get_visualization_location(sara_url: str, inspection_id: str) -> Tuple[int, Any]:
    """Return the status code and body of the visualization-location endpoint.

    The status is the assertion: 200 succeeded, 202 still running, 422 failed,
    404 no record or no visualization workflow.
    """
    response: Response = requests.get(
        f"{sara_url}/api/inspection-record/inspection-id/{inspection_id}"
        f"/visualization-location",
        headers=_add_headers(),
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def wait_for_visualization_location_status(
    sara_url: str, inspection_id: str, expected_status_code: int, timeout: int = 180
) -> Any:
    deadline = time.time() + timeout
    status_code = 0
    body: Any = None
    while time.time() < deadline:
        status_code, body = get_visualization_location(sara_url, inspection_id)
        if status_code == expected_status_code:
            return body
        time.sleep(2)

    raise AssertionError(
        f"Visualization location for inspection {inspection_id} returned "
        f"{status_code} after {timeout}s, expected {expected_status_code}: {body}"
    )


def retry_workflow(sara_url: str, workflow_id: str) -> None:
    response: Response = requests.post(
        f"{sara_url}/api/workflow/id/{workflow_id}/retry",
        headers=_add_headers(),
        timeout=30,
    )
    response.raise_for_status()
