import time
from datetime import datetime, timedelta

from azure.storage.blob import BlobServiceClient


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
