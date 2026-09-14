"""Publishes MQTT messages into the test broker as if a service had sent them.

Used to stand in for a service the suite does not run. There is no Argo in the
test environment, so SARA never completes a workflow and never publishes an
analysis result of its own; injecting the message here exercises everything
downstream of it -- Flotilla's deserialisation, inspection lookup and SignalR
broadcast -- which is where the operator-visible behaviour is decided.

The payload is built by hand rather than imported, on purpose. It is a copy of
what SARA puts on the wire (api/MQTT/IsarInspectionResult.cs and MqttPublisher.cs
in equinor/sara), so if the two drift apart the test is supposed to notice.
"""

import json
import ssl
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import paho.mqtt.client as mqtt
from loguru import logger

from robotics_integration_tests.utilities.mqtt_credentials import MqttCredentials

ANALYSIS_RESULT_AVAILABLE_TOPIC = "sara/analysis_result_available"
VISUALIZATION_AVAILABLE_TOPIC = "sara/visualization_available"

# The broker's access_control (broker/mosquitto/config/access_control in
# equinor/flotilla) only grants write on the sara/ topics to this user.
SARA_MQTT_USER = "sara"

_PUBLISH_TIMEOUT_SECONDS = 10


def publish_mqtt_message(
    broker_host: str,
    broker_port: int,
    credentials: MqttCredentials,
    topic: str,
    payload: Dict,
    username: str = SARA_MQTT_USER,
) -> None:
    """Publish one message to the test broker over TLS, then disconnect."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.username_pw_set(username, credentials.passwords[username])

    # The broker certificate is issued for the in-network alias, but the test
    # reaches it on localhost through a published port, so the hostname can
    # never match. Verify the chain against the generated CA and waive only the
    # hostname check.
    with tempfile.TemporaryDirectory() as directory:
        ca_file = Path(directory) / "ca.crt"
        ca_file.write_text(credentials.ca_certificate)
        client.tls_set(ca_certs=str(ca_file), cert_reqs=ssl.CERT_REQUIRED)
        client.tls_insecure_set(True)

        client.connect(broker_host, broker_port)
        client.loop_start()
        try:
            message_info = client.publish(topic, json.dumps(payload), qos=1)
            message_info.wait_for_publish(timeout=_PUBLISH_TIMEOUT_SECONDS)
            if not message_info.is_published():
                raise TimeoutError(
                    f"Publishing to '{topic}' was not acknowledged by the broker "
                    f"within {_PUBLISH_TIMEOUT_SECONDS}s"
                )
            logger.info(f"Published to '{topic}': {payload}")
        finally:
            client.loop_stop()
            client.disconnect()


def build_analysis_result_payload(
    inspection_ids: List[str],
    analysis_type: str,
    analysis_group_id: Optional[str] = None,
) -> Dict:
    """A sara/analysis_result_available message as SARA emits it.

    Every key is snake_case except ``analysisType``, which is camelCase in
    SARA's model and so on the wire. That inconsistency is reproduced
    deliberately.

    ``analysis_type`` is a free-form string on SARA's side, taken straight from
    ``workflow.WorkflowType`` -- the keys under ``Analysis:Workflows`` in SARA's
    appsettings.json, such as "fencilla", "cloe" or "thermal-reading".
    """
    return {
        "inspection_ids": inspection_ids,
        "analysis_group_id": analysis_group_id,
        "workflow_id": str(uuid.uuid4()),
        "analysis_run_id": str(uuid.uuid4()),
        "analysis_id": str(uuid.uuid4()),
        "analysisType": analysis_type,
    }


def publish_analysis_result(
    broker_host: str,
    broker_port: int,
    credentials: MqttCredentials,
    inspection_ids: List[str],
    analysis_type: str,
    analysis_group_id: Optional[str] = None,
) -> Dict:
    payload = build_analysis_result_payload(
        inspection_ids=inspection_ids,
        analysis_type=analysis_type,
        analysis_group_id=analysis_group_id,
    )
    publish_mqtt_message(
        broker_host=broker_host,
        broker_port=broker_port,
        credentials=credentials,
        topic=ANALYSIS_RESULT_AVAILABLE_TOPIC,
        payload=payload,
    )
    return payload


def build_visualization_available_payload(inspection_id: str) -> Dict:
    """A sara/visualization_available message as SARA emits it.

    Unlike the analysis result, every field here is snake_case and none is an
    enum, so SARA's model and Flotilla's agree exactly.
    """
    return {
        "inspection_id": inspection_id,
        "workflow_id": str(uuid.uuid4()),
        "analysis_run_id": str(uuid.uuid4()),
        "analysis_id": str(uuid.uuid4()),
    }


def publish_visualization_available(
    broker_host: str,
    broker_port: int,
    credentials: MqttCredentials,
    inspection_id: str,
) -> Dict:
    payload = build_visualization_available_payload(inspection_id=inspection_id)
    publish_mqtt_message(
        broker_host=broker_host,
        broker_port=broker_port,
        credentials=credentials,
        topic=VISUALIZATION_AVAILABLE_TOPIC,
        payload=payload,
    )
    return payload
