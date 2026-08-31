"""Record MQTT traffic so tests can assert on it directly.

The broker carries the contract between ISAR, Flotilla and SARA, but until now
the suite could only observe it indirectly -- by waiting for Flotilla to change
some database state, or by grepping SARA's container logs. Both are proxies, and
neither can show that a message was *not* sent.

This subscribes as the ``flotilla`` broker user, which the access control file in
equinor/flotilla grants read on ``isar/#`` and ``sara/#`` -- everything the
system publishes.

As with every other assertion in this suite, the waits here are bounded polls.
"""

import json
import ssl
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import paho.mqtt.client as mqtt
from loguru import logger


class RecordedMessage:
    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.raw_payload = payload
        self.received_at = time.time()

    @property
    def payload(self) -> Any:
        """The payload as JSON, or the raw string when it is not JSON."""
        try:
            return json.loads(self.raw_payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.raw_payload.decode("utf-8", errors="replace")

    def __repr__(self) -> str:
        return f"RecordedMessage(topic={self.topic!r}, payload={self.payload!r})"


class MqttRecorder:
    """Subscribes to the broker and keeps every message it receives."""

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"armada-recorder-{time.time()}",
        )
        self._client.username_pw_set(username, password)
        # The broker listens with TLS on 1883, and its certificate is issued for
        # the in-network alias "broker". The recorder connects from the host via
        # a mapped port, so the name can never match. Encrypt but do not verify:
        # flotilla and sara do the same, and this is a test-only observer.
        self._client.tls_set(cert_reqs=ssl.CERT_NONE)
        self._client.tls_insecure_set(True)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message

        self._host = host
        self._port = port
        self._messages: List[RecordedMessage] = []
        self._lock = threading.Lock()
        self._connected = threading.Event()

    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code != 0:
            logger.error(f"MQTT recorder failed to connect: {reason_code}")
            return
        # The flotilla broker user may read exactly these two trees.
        client.subscribe([("isar/#", 1), ("sara/#", 1)])
        self._connected.set()

    def _on_message(self, client, userdata, message) -> None:
        with self._lock:
            self._messages.append(RecordedMessage(message.topic, message.payload))

    def start(self, timeout: int = 30) -> None:
        self._client.connect(self._host, self._port, keepalive=60)
        self._client.loop_start()
        if not self._connected.wait(timeout):
            raise RuntimeError(
                f"MQTT recorder did not connect to {self._host}:{self._port} "
                f"within {timeout}s"
            )
        logger.info(f"MQTT recorder connected to {self._host}:{self._port}")

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def messages(self, topic_filter: str = "") -> List[RecordedMessage]:
        """Recorded messages, optionally those whose topic contains a substring."""
        with self._lock:
            recorded = list(self._messages)
        if not topic_filter:
            return recorded
        return [message for message in recorded if topic_filter in message.topic]

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def wait_for_message(
        self,
        topic_filter: str,
        predicate: Optional[Callable[[RecordedMessage], bool]] = None,
        timeout: int = 120,
    ) -> RecordedMessage:
        """Block until a matching message arrives, and return it."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            for message in self.messages(topic_filter):
                if predicate is None or predicate(message):
                    return message
            time.sleep(1)

        seen = sorted({message.topic for message in self.messages()})
        raise AssertionError(
            f"No message on a topic containing '{topic_filter}' within {timeout}s. "
            f"Topics seen: {seen}"
        )

    def assert_no_message(self, topic_filter: str) -> None:
        """Assert nothing has been published on a topic.

        Only meaningful once the test has waited for something that proves the
        traffic it cares about has already been delivered.
        """
        matching = self.messages(topic_filter)
        assert not matching, (
            f"Expected no message on a topic containing '{topic_filter}', "
            f"but got {[m.topic for m in matching]}"
        )

    def payloads_for(self, topic_filter: str) -> List[Dict]:
        return [message.payload for message in self.messages(topic_filter)]
