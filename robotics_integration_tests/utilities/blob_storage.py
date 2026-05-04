import time
from datetime import datetime, timedelta
from typing import Dict, List

from azure.storage.blob import BlobServiceClient
from loguru import logger


def wait_until_all_expected_files_uploaded(
    container_name: str,
    connection_string: str,
    expected_file_count: int,
    timeout: int = 60,
) -> None:

    start_time = datetime.now()
    while True:
        current_count: int = count_files_in_container(container_name, connection_string)
        if current_count >= expected_file_count:
            return
        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise TimeoutError(
                f"Timeout waiting for {expected_file_count} files in container '{container_name}'. "
                f"Only {current_count} files found."
            )
        time.sleep(1)


def wait_for_all_mission_blobs(
    container_name: str,
    connection_string: str,
    mission_blob_expectations: Dict[str, int],
    timeout: int = 60,
) -> None:
    """Poll a single blob container until each mission run has the expected
    number of blobs, or *timeout* seconds have elapsed.

    Blob paths follow the pattern ``{date}__{plant}__{name}__{mission_run_id}/...``,
    so each blob can be attributed to a mission run by checking whether its
    path contains the mission run ID.

    *mission_blob_expectations* maps mission run IDs to their expected blob
    counts. Entries with expected count 0 are verified **after** all positive
    expectations are met, to ensure no unexpected blobs were uploaded.
    """
    positive: Dict[str, int] = {
        mid: count
        for mid, count in mission_blob_expectations.items()
        if count > 0
    }
    zero: List[str] = [
        mid for mid, count in mission_blob_expectations.items() if count == 0
    ]

    remaining: Dict[str, int] = dict(positive)
    start_time: datetime = datetime.now()

    while remaining:
        if datetime.now() - start_time > timedelta(seconds=timeout):
            counts = {
                mid: count_blobs_for_mission(container_name, connection_string, mid)
                for mid in remaining
            }
            raise TimeoutError(
                f"Timeout waiting for mission blobs within {timeout}s. "
                f"Still waiting for: {remaining}. Current counts: {counts}"
            )

        for mission_run_id, expected_count in list(remaining.items()):
            current_count: int = count_blobs_for_mission(
                container_name, connection_string, mission_run_id
            )
            if current_count >= expected_count:
                logger.info(
                    f"Mission run '{mission_run_id}' has {current_count}/{expected_count} expected blobs"
                )
                del remaining[mission_run_id]
            else:
                logger.info(
                    f"Mission run '{mission_run_id}' has {current_count}/{expected_count} blobs, waiting..."
                )

        if remaining:
            time.sleep(1)

    for mission_run_id in zero:
        current_count = count_blobs_for_mission(
            container_name, connection_string, mission_run_id
        )
        if current_count != 0:
            raise AssertionError(
                f"Mission run '{mission_run_id}' expected 0 blobs but found {current_count}"
            )
        logger.info(
            f"Mission run '{mission_run_id}' correctly has 0 blobs"
        )


def count_blobs_for_mission(
    container_name: str,
    connection_string: str,
    mission_run_id: str,
) -> int:
    """Count blobs in *container_name* whose path contains *mission_run_id*."""
    service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = service_client.get_container_client(container_name)

    count = 0
    for blob in container_client.list_blobs():
        if mission_run_id in blob.name:
            count += 1

    return count


def count_files_in_container(
    container_name: str,
    connection_string: str,
) -> int:
    service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = service_client.get_container_client(container_name)

    count = 0
    for _ in container_client.list_blobs():
        count += 1

    return count
