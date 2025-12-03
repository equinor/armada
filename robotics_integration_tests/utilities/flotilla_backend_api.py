import time
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import requests
from loguru import logger
from requests import Response

from robotics_integration_tests.utilities.authentication import (
    retrieve_access_token_for_integration_tests_app,
)


def _add_headers() -> Dict[str, str]:
    access_token: str = retrieve_access_token_for_integration_tests_app()
    headers = {"Authorization": f"Bearer {access_token}"}
    return headers


def _list_database_entries(backend_url: str, request_path: str) -> List[Dict]:
    response: Response = requests.get(
        f"{backend_url}/{request_path}", headers=_add_headers()
    )
    response.raise_for_status()
    return response.json()


def get_inspection_area_id_for_installation(backend_url: str, installation_code: str):
    response: Response = requests.get(
        f"{backend_url}/inspectionAreas/installation/{installation_code}",
        headers=_add_headers(),
    )
    inspection_areas_for_installation: List[Dict] = response.json()
    inspection_area_id: str = inspection_areas_for_installation[0]["id"]
    return inspection_area_id


def set_current_inspection_area_for_robot(
    backend_url: str, inspection_area_id: str, robot_id: str
):
    response: Response = requests.patch(
        f"{backend_url}/robots/{robot_id}/currentInspectionArea/{inspection_area_id}",
        headers=_add_headers(),
    )


def schedule_echo_mission(
    backend_url: str, robot_id: str, mission_id: str, installation_code: str
) -> Dict:
    try:
        response: Dict = schedule_mission(
            backend_url=backend_url,
            robot_id=robot_id,
            mission_id=mission_id,
            installation_code=installation_code,
        )
        return response
    except Exception as e:
        logger.exception(f"Failed to schedule mission")
        raise e


def schedule_mission(
    backend_url: str, robot_id: str, mission_id: str, installation_code: str
) -> Dict:
    payload: Dict = {
        "robotId": robot_id,
        "missionSourceId": mission_id,
        "installationCode": installation_code,
    }
    url: str = f"{backend_url}/missions"
    response: Response = requests.post(
        url,
        json=payload,
        headers=_add_headers(),
    )
    if not response.ok:
        body = response.text
        try:
            problem = response.json()
        except Exception:
            problem = None
        raise AssertionError(
            f"POST {url} returned {response.status_code}\n"
            f"Request payload:\n{payload}\n"
            f"Response headers: {dict(response.headers)}\n"
            f"Response body:\n{body}\n"
            f"Parsed JSON (if any):\n{problem}"
        )
    response.raise_for_status()
    return response.json()


def get_robot_by_name(backend_url: str, name: str) -> Dict:
    response: Response = requests.get(
        f"{backend_url}/robots",
        headers=_add_headers(),
    )
    response.raise_for_status()

    robots: List[Dict] = response.json()

    for robot in robots:
        if robot.get("name") == name:
            return robot
    raise RuntimeError(f"Robot with name '{name}' not found")


def is_robot_status(backend_url: str, robot_name: str, expected_status: str) -> bool:
    robot: Dict = get_robot_by_name(backend_url=backend_url, name=robot_name)
    current_status: str = robot.get("status")
    if current_status != expected_status:
        return False
    return True


def get_mission_run_by_id(backend_url: str, mission_run_id: str) -> Dict:
    response: Response = requests.get(
        f"{backend_url}/missions/runs/{mission_run_id}",
        headers=_add_headers(),
    )
    response.raise_for_status()
    return response.json()


def is_mission_run_status(
    backend_url: str, mission_run_id: str, expected_status: str
) -> bool:
    mission_run: Dict = get_mission_run_by_id(
        backend_url=backend_url, mission_run_id=mission_run_id
    )
    current_status: str = mission_run.get("status")
    if current_status != expected_status:
        return False
    return True


def add_access_role_to_database(
    backend_url: str, access_level: str, installation_code: str, role_name: str
):
    response: Response = requests.post(
        f"{backend_url}/access-roles",
        json={
            "installationCode": installation_code,
            "roleName": role_name,
            "accessLevel": access_level,
        },
        headers=_add_headers(),
    )
    response.raise_for_status()


def add_plant_to_database(
    backend_url: str, installation_code: str, name: str, plant_code: str
):
    response: Response = requests.post(
        f"{backend_url}/plants",
        json={
            "installationCode": installation_code,
            "plantCode": plant_code,
            "name": name,
        },
        headers=_add_headers(),
    )
    response.raise_for_status()


def add_inspection_area_to_database(
    backend_url: str, installation_code: str, name: str, plant_code: str, polygon: Dict
):
    response: Response = requests.post(
        f"{backend_url}/inspectionAreas",
        json={
            "installationCode": installation_code,
            "plantCode": plant_code,
            "name": name,
            "areaPolygon": polygon,
        },
        headers=_add_headers(),
    )
    response.raise_for_status()


def add_installation_to_database(
    backend_url: str, installation_code: str, name: str
) -> None:
    response: Response = requests.post(
        f"{backend_url}/installations",
        json={"installationCode": installation_code, "name": name},
        headers=_add_headers(),
    )
    response.raise_for_status()

def add_robot_model_to_database(
    backend_url: str
) -> None:
    response: Response = requests.post(
        f"{backend_url}/robot-models",
        json={"robotType": "Robot"},
        headers=_add_headers(),
    )
    response.raise_for_status()

def wait_for_backend_to_be_responsive(backend_url: str, timeout: int = 60) -> None:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Backend was not responsive within the given timeout {timeout} seconds"
            )

        try:
            robot_models: List[Dict] = _list_database_entries(
                backend_url=backend_url, request_path="robot-models"
            )
        except Exception:
            logger.warning("Backend is not responsive yet, will retry until timeout...")
            time.sleep(1)
            continue

        if len(robot_models) >= 0:
            logger.info("Backend is responsive")
            return


# Populate default installations
default_installations: List[Tuple[str, str]] = [
    ("HUA", "Huldra"),
    ("KAA", "Kårstø"),
    ("NLS", "Northern Lights"),
]

# Populate default plants
default_plants: List[Tuple[str, str, str]] = [
    ("HUA", "HUA", "Huldra"),
    ("KAA", "KAA", "Kårstø"),
    ("NLS", "NLS", "Northern Lights"),
]

default_area_polygon = {
    "zmin": 0,
    "zmax": 10000000,
    "positions": [
        {
            "x": 0,
            "y": 0,
        },
        {
            "x": 0,
            "y": 10000000,
        },
        {
            "x": 10000000,
            "y": 0,
        },
        {
            "x": 10000000,
            "y": 10000000,
        },
    ],
}

# Populate default inspection areas
default_inspection_areas: List[Tuple[str, str, str, Dict]] = [
    ("HUA", "HUA", "Huldra Area", default_area_polygon),
    ("KAA", "KAA", "Kårstø Area", default_area_polygon),
    ("NLS", "NLS", "Northern Lights Area", default_area_polygon),
]

# Populate default access roles
default_access_roles: List[Tuple[str, str, str]] = [
    ("HUA", "Role.User.HUA", "USER"),
    ("KAA", "Role.User.KAA", "USER"),
    ("NLS", "Role.User.NLS", "USER"),
]


def populate_database_with_minimum_models(backend_url: str) -> None:
    add_robot_model_to_database(backend_url=backend_url)

    for installation_code, name in default_installations:
        add_installation_to_database(
            backend_url=backend_url, installation_code=installation_code, name=name
        )

    for plant_code, installation_code, name in default_plants:
        add_plant_to_database(
            backend_url=backend_url,
            installation_code=installation_code,
            name=name,
            plant_code=plant_code,
        )

    for installation_code, plant_code, name, polygon in default_inspection_areas:
        add_inspection_area_to_database(
            backend_url=backend_url,
            installation_code=installation_code,
            name=name,
            plant_code=plant_code,
            polygon=polygon,
        )

    for installation_code, role_name, access_level in default_access_roles:
        add_access_role_to_database(
            backend_url=backend_url,
            access_level=access_level,
            installation_code=installation_code,
            role_name=role_name,
        )


def wait_for_database_to_be_populated(backend_url: str, timeout: int = 60) -> None:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Database is not populated within the given timeout {timeout} seconds"
            )

        try:
            installations: List[Dict] = _list_database_entries(
                backend_url=backend_url, request_path="installations"
            )
            plants: List[Dict] = _list_database_entries(
                backend_url=backend_url, request_path="plants"
            )
            inspection_areas: List[Dict] = _list_database_entries(
                backend_url=backend_url, request_path="inspectionAreas"
            )
            access_roles: List[Dict] = _list_database_entries(
                backend_url=backend_url, request_path="access-roles"
            )
        except Exception:
            logger.warning(
                "Database has not been populated yet, will retry until timeout..."
            )
            time.sleep(1)
            continue

        if (
            len(installations) == len(default_installations)
            and len(plants) == len(default_plants)
            and len(inspection_areas) == len(default_inspection_areas)
            and len(access_roles) == len(default_access_roles)
        ):
            logger.info(
                "Database has been populated with default installations, plants, inspection areas and access roles"
            )
            return


def setup_robot_in_flotilla(backend_url: str, robot_name: str) -> Tuple[str, str]:

    wait_for_robot_to_be_populated_in_database(
        backend_url=backend_url,
        robot_name=robot_name,
    )
    robot: Dict = get_robot_by_name(
        backend_url=backend_url,
        name=robot_name,
    )
    installation_code_for_robot: str = robot.get("currentInstallation").get(
        "installationCode"
    )
    robot_id: str = robot.get("id")

    inspection_area_id: str = get_inspection_area_id_for_installation(
        backend_url=backend_url,
        installation_code=installation_code_for_robot,
    )

    set_current_inspection_area_for_robot(
        backend_url=backend_url,
        inspection_area_id=inspection_area_id,
        robot_id=robot_id,
    )
    wait_for_inspection_area_to_be_updated_on_robot(
        backend_url=backend_url, robot_id=robot_id
    )
    return robot_id, installation_code_for_robot


def wait_for_inspection_area_to_be_updated_on_robot(
    backend_url: str, robot_id: str, timeout: int = 60
) -> None:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Inspection area on robot {robot_id} is not updated within the given timeout {timeout} seconds"
            )

        try:
            robot: Dict = requests.get(
                f"{backend_url}/robots/{robot_id}",
                headers=_add_headers(),
            ).json()
        except Exception:
            logger.warning(
                f"Failed to retrieve robot with ID {robot_id}, will retry until timeout..."
            )
            time.sleep(1)
            continue

        if robot.get("currentInspectionAreaId") is not None:
            logger.info(
                f"Inspection area on robot {robot_id} has been updated to {robot.get('currentInspectionArea')}"
            )
            return
        else:
            logger.info(f"Inspection area on robot {robot_id} is not updated yet")
            time.sleep(1)
            continue


def wait_for_robot_to_be_populated_in_database(
    backend_url: str, robot_name: str, timeout: int = 60
) -> None:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Robot '{robot_name}' was not populated in the database within the given timeout {timeout} seconds"
            )

        try:
            robot: Dict = get_robot_by_name(backend_url=backend_url, name=robot_name)
        except Exception:
            logger.warning(f"Failed to retrieve robot {robot_name} from the database")
            time.sleep(1)
            continue

        if robot.get("name") == robot_name:
            logger.info(
                f"Robot with name '{robot_name}' has been populated in the database"
            )
            return

        logger.info(
            f"Robot with name '{robot_name}' is not populated in the database yet"
        )
        time.sleep(1)
        continue


def wait_for_mission_run_status(
    backend_url: str, mission_run_id: str, expected_status: str, timeout: int = 60
) -> Dict:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Mission run '{mission_run_id}' did not reach status '{expected_status}' within the given timeout "
                f"{timeout} seconds"
            )

        try:
            mission_run: Dict = get_mission_run_by_id(
                backend_url=backend_url, mission_run_id=mission_run_id
            )
        except Exception:
            logger.warning(
                f"Failed to retrieve mission run with ID {mission_run_id}, most likely because it has not been written "
                f"to the database yet, will retry..."
            )
            time.sleep(1)
            continue

        current_status: str = mission_run.get("status")
        if current_status == expected_status:
            logger.info(
                f"Mission run with ID '{mission_run_id}' has reached expected status '{expected_status}'"
            )
            return mission_run
        else:
            logger.info(
                f"Mission run with ID '{mission_run_id}' is in status '{current_status}', "
                f"waiting for status '{expected_status}'"
            )
            time.sleep(1)
            continue


def wait_for_second_task_status_of_mission_run(
    backend_url: str, mission_run_id: str, expected_status: str, timeout: int = 60
) -> Dict:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Second task in mission with ID '{mission_run_id}' did not reach status '{expected_status}' within the given timeout "
                f"{timeout} seconds"
            )

        try:
            mission_run: Dict = get_mission_run_by_id(
                backend_url=backend_url, mission_run_id=mission_run_id
            )
        except Exception:
            logger.warning(
                f"Failed to retrieve mission run with ID {mission_run_id}, most likely because it has not been written "
                f"to the database yet, will retry..."
            )
            time.sleep(1)
            continue

        tasks: List = mission_run.get("tasks")
        first_task_status: str = tasks[1].get("status")
        if first_task_status == expected_status:
            logger.info(
                f"Second task in mission with ID '{mission_run_id}' has reached expected status '{expected_status}'"
            )
            return tasks[1]
        else:
            logger.info(
                f"Second task in mission run with ID '{mission_run_id}' is in status '{first_task_status}', "
                f"waiting for status '{expected_status}'"
            )
            time.sleep(1)
            continue


def wait_for_robot_status(
    backend_url: str, robot_name: str, expected_status: str, timeout: int = 60
) -> Dict:
    start_time: datetime = datetime.now()
    while True:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise RuntimeError(
                f"Robot '{robot_name}' did not reach status '{expected_status}' within the given timeout {timeout} seconds"
            )

        try:
            robot: Dict = get_robot_by_name(backend_url=backend_url, name=robot_name)
        except Exception:
            logger.warning(
                f"Failed to retrieve robot with name {robot_name}, will retry until timeout..."
            )
            time.sleep(1)
            continue

        current_status: str = robot.get("status")
        if current_status == expected_status:
            logger.info(
                f"Robot with name '{robot_name}' has reached expected status '{expected_status}'"
            )
            return robot
        else:
            logger.info(
                f"Robot with name '{robot_name}' is in status '{current_status}', waiting for status '{expected_status}'"
            )
            time.sleep(1)
            continue


def pause_mission(backend_url: str, robot_id: str) -> None:
    url: str = f"{backend_url}/robots/{robot_id}/pause"
    response: Response = requests.post(
        url,
        headers=_add_headers(),
    )
    if not response.ok:
        body = response.text
        try:
            problem = response.json()
        except Exception:
            problem = None
        raise AssertionError(
            f"POST {url} returned {response.status_code}\n"
            f"Response headers: {dict(response.headers)}\n"
            f"Response body:\n{body}\n"
            f"Parsed JSON (if any):\n{problem}"
        )
    response.raise_for_status()


def resume_mission(backend_url: str, robot_id: str) -> None:
    url = str(f"{backend_url}/robots/{robot_id}/resume")
    response: Response = requests.post(
        url,
        headers=_add_headers(),
    )
    if not response.ok:
        body = response.text
        try:
            problem = response.json()
        except Exception:
            problem = None
        raise AssertionError(
            f"POST {url} returned {response.status_code}\n"
            f"Response headers: {dict(response.headers)}\n"
            f"Response body:\n{body}\n"
            f"Parsed JSON (if any):\n{problem}"
        )
    response.raise_for_status()
