"""Records ISAR's MQTT output so tests can assert on state transitions.

Flotilla's REST API only ever shows a robot's *current* status, so polling it can
only catch states the robot rests in. Every transient state — ``Stopping``,
``GoingToLockdown``, ``Pausing`` — is missed unless the poll happens to land
inside it, which is a race. ISAR, however, republishes its status on every state
machine iteration, so subscribing to the broker yields the complete ordered trace
of everything the robot went through.

That is what makes the grouped multi-robot tests possible: several robots run
different scenarios against one stack, and each is verified from its own trace.
"""

import json
import ssl
import tarfile
import tempfile
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from loguru import logger
from testcontainers.core.container import DockerContainer

# Absolute path of the CA certificate inside the flotilla-broker image. The
# broker's mosquitto.conf refers to it relatively; the image has no WORKDIR, so
# the effective location is the filesystem root.
BROKER_CA_CERT_CONTAINER_PATH = "/mosquitto/config/certs/ca-cert.pem"

# ISAR publishes everything under isar/<isar-id>/..., and the `isar` broker user
# is granted `readwrite isar/#` by the broker's access_control file.
ISAR_TOPIC_FILTER = "isar/#"

_CONNECT_TIMEOUT_SECONDS = 30


def _extract_ca_certificate(broker: DockerContainer, destination: Path) -> Path:
    """Copy the broker's CA certificate out of its container.

    The certificate lives in the flotilla repository, not this one, so it has to
    be read from the image at run time rather than checked in and kept in sync.
    """
    bits, _ = broker.get_wrapped_container().get_archive(BROKER_CA_CERT_CONTAINER_PATH)

    tar_path: Path = destination / "ca-cert.tar"
    with open(tar_path, "wb") as tar_file:
        for chunk in bits:
            tar_file.write(chunk)

    import tarfile

    with tarfile.open(tar_path) as tar:
        member = tar.getmember("ca-cert.pem")
        extracted = tar.extractfile(member)
        if extracted is None:
            raise RuntimeError(
                f"Could not read {BROKER_CA_CERT_CONTAINER_PATH} from the broker "
                "container; the MQTT recorder cannot establish a TLS connection."
            )
        ca_path: Path = destination / "ca-cert.pem"
        ca_path.write_bytes(extracted.read())

    return ca_path


class MqttRecorder:
    """Subscribes to ISAR's topics and records status and mission transitions.

    Consecutive duplicate statuses are collapsed. ISAR republishes its status on
    every state machine iteration (roughly ten times a second), so without this a
    trace would be tens of thousands of entries long and unreadable in a failure
    message.
    """

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password

        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._state_traces: Dict[str, List[str]] = {}
        self._mission_traces: Dict[str, List[str]] = {}
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self, broker: DockerContainer) -> "MqttRecorder":
        self._temp_dir = tempfile.TemporaryDirectory(prefix="armada-mqtt-ca-")
        ca_path: Path = _extract_ca_certificate(broker, Path(self._temp_dir.name))

        self._client.tls_set(ca_certs=str(ca_path), tls_version=ssl.PROTOCOL_TLS_CLIENT)
        # The broker's certificate is issued for the in-network alias "broker",
        # but the test process reaches it as localhost on a mapped port, so the
        # hostname will never match. The CA is still verified.
        self._client.tls_insecure_set(True)

        self._client.connect(self._host, self._port)
        self._client.loop_start()

        if not self._connected.wait(timeout=_CONNECT_TIMEOUT_SECONDS):
            raise RuntimeError(
                f"MQTT recorder failed to connect to {self._host}:{self._port} "
                f"within {_CONNECT_TIMEOUT_SECONDS}s."
            )

        logger.info(f"MQTT recorder subscribed to '{ISAR_TOPIC_FILTER}'")
        return self

    def stop(self) -> None:
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001 - teardown must not mask a test failure
            logger.warning("MQTT recorder failed to disconnect cleanly")
        if self._temp_dir is not None:
            self._temp_dir.cleanup()
            self._temp_dir = None

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            logger.error(f"MQTT recorder connection refused: {reason_code}")
            return
        client.subscribe(ISAR_TOPIC_FILTER, qos=1)
        self._connected.set()

    def _on_message(self, client, userdata, message) -> None:
        topic_parts: List[str] = message.topic.split("/")
        # isar/<isar-id>/<topic-name>[/<entity-id>]
        if len(topic_parts) < 3:
            return
        topic_name: str = topic_parts[2]

        if topic_name not in ("status", "mission"):
            return

        try:
            payload: Dict = json.loads(message.payload.decode())
        except ValueError, UnicodeDecodeError:
            logger.warning(f"MQTT recorder could not decode payload on {message.topic}")
            return

        status = payload.get("status")
        if status is None:
            return

        with self._lock:
            if topic_name == "status":
                key = payload.get("robot_name")
                trace = self._state_traces.setdefault(key, [])
            else:
                key = payload.get("mission_id")
                trace = self._mission_traces.setdefault(key, [])

            if key is None:
                return
            if not trace or trace[-1] != status:
                trace.append(status)

    def state_trace(self, robot_name: str) -> List[str]:
        """Ordered ISAR statuses seen for *robot_name*, duplicates collapsed."""
        with self._lock:
            return list(self._state_traces.get(robot_name, []))

    def mission_status_trace(self, mission_id: str) -> List[str]:
        """Ordered mission statuses seen for *mission_id*, duplicates collapsed."""
        with self._lock:
            return list(self._mission_traces.get(mission_id, []))

    def recorded_robot_names(self) -> List[str]:
        with self._lock:
            return sorted(self._state_traces)

    def wait_for_state(
        self, robot_name: str, expected_state: str, timeout: int = 120
    ) -> None:
        """Block until *robot_name* has been observed in *expected_state*.

        Unlike Flotilla polling this cannot miss a state the robot has already
        passed through, so it is safe to call after the fact.
        """
        deadline: datetime = datetime.now() + timedelta(seconds=timeout)
        while datetime.now() < deadline:
            if expected_state in self.state_trace(robot_name):
                return
            time.sleep(0.5)

        raise AssertionError(
            f"Robot '{robot_name}' was never observed in state '{expected_state}' "
            f"within {timeout}s. Observed trace: {self.state_trace(robot_name)}"
        )

    def wait_for_mission_status(
        self, mission_id: str, expected_status: str, timeout: int = 120
    ) -> None:
        deadline: datetime = datetime.now() + timedelta(seconds=timeout)
        while datetime.now() < deadline:
            if expected_status in self.mission_status_trace(mission_id):
                return
            time.sleep(0.5)

        raise AssertionError(
            f"Mission '{mission_id}' never reached status '{expected_status}' within "
            f"{timeout}s. Observed trace: {self.mission_status_trace(mission_id)}"
        )

    def assert_visited_in_order(
        self, robot_name: str, expected_states: List[str]
    ) -> None:
        """Assert *expected_states* appear in the trace, in order.

        This is a subsequence check rather than an equality check: unrelated
        states are allowed in between. Asserting the exact trace would make every
        test fail the moment ISAR gains a state that is irrelevant to it.
        """
        trace: List[str] = self.state_trace(robot_name)

        remaining: List[str] = list(expected_states)
        for state in trace:
            if remaining and state == remaining[0]:
                remaining.pop(0)

        if remaining:
            matched = len(expected_states) - len(remaining)
            raise AssertionError(
                f"Robot '{robot_name}' did not pass through the expected states in "
                f"order.\n"
                f"  Expected (as a subsequence): {expected_states}\n"
                f"  Matched the first {matched}, then failed to find: {remaining[0]}\n"
                f"  Observed trace: {trace}"
            )

        logger.info(f"Robot '{robot_name}' passed through {expected_states} in order")
