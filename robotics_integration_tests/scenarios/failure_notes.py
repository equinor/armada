"""Notes that tell which robot a failure belongs to."""

from contextlib import contextmanager
from typing import Dict, Iterator


@contextmanager
def naming_the_robot_of_each_mission_run(
    robot_name_by_mission_run_id: Dict[str, str],
) -> Iterator[None]:
    """Blob and mission run failures name only the mission run ID."""
    try:
        yield
    except Exception as error:
        robots: str = ", ".join(
            f"{mission_run_id} is {robot_name}'s"
            for mission_run_id, robot_name in robot_name_by_mission_run_id.items()
        )
        error.add_note(f"Mission runs: {robots or 'none scheduled'}")
        raise
