"""Records ISAR's MQTT output as a diagnostic trace of state transitions.

Flotilla's REST API only ever shows a robot's *current* status, so polling it can
only catch states the robot rests in. Every transient state — ``Stopping``,
``GoingToLockdown``, ``Pausing`` — is missed unless the poll happens to land
inside it, which is a race. ISAR, however, republishes its status on every state
machine iteration, so subscribing to the broker yields the complete ordered trace
of everything the robot went through.

No test asserts on the trace. It is dumped per robot on fixture teardown, to show
what the robots actually did when an assertion against Flotilla fails.
"""

import json
import ssl
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from loguru import logger

# ISAR publishes everything under isar/<isar-id>/..., and the `isar` broker user
# is granted `readwrite isar/#` by the broker's access_control file.
ISAR_TOPIC_FILTER = "isar/#"

_CONNECT_TIMEOUT_SECONDS = 30


class MqttRecorder:
    """Subscribes to ISAR's status topics and records each robot's transitions.

    Consecutive duplicate statuses are collapsed. ISAR republishes its status on
    every state machine iteration (roughly ten times a second), so without this a
    trace would be tens of thousands of entries long and unreadable.
    """

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port

        self._lock = threading.Lock()
        self._connected = threading.Event()
        self._state_traces: Dict[str, List[str]] = {}
        self._temp_dir: Optional[tempfile.TemporaryDirectory] = None

        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            protocol=mqtt.MQTTv5,
        )
        self._client.username_pw_set(username, password)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

    def start(self, ca_certificate: str) -> "MqttRecorder":
        self._temp_dir = tempfile.TemporaryDirectory(prefix="armada-mqtt-ca-")
        ca_path: Path = Path(self._temp_dir.name) / "ca-cert.pem"
        ca_path.write_text(ca_certificate)

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
        # isar/<isar-id>/<topic-name>[/<entity-id>]
        topic_parts: List[str] = message.topic.split("/")
        if len(topic_parts) < 3 or topic_parts[2] != "status":
            return

        try:
            payload: Dict = json.loads(message.payload.decode())
        except ValueError:
            logger.warning(f"MQTT recorder could not decode payload on {message.topic}")
            return

        robot_name: Optional[str] = payload.get("robot_name")
        status: Optional[str] = payload.get("status")
        if robot_name is None or status is None:
            return

        with self._lock:
            trace: List[str] = self._state_traces.setdefault(robot_name, [])
            if not trace or trace[-1] != status:
                trace.append(status)

    def state_trace(self, robot_name: str) -> List[str]:
        """Ordered ISAR statuses seen for *robot_name*, duplicates collapsed."""
        with self._lock:
            return list(self._state_traces.get(robot_name, []))

    def recorded_robot_names(self) -> List[str]:
        with self._lock:
            return sorted(self._state_traces)
