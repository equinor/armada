"""Mission status values ISAR publishes on its MQTT mission topic.

Mirrors ``MissionStatus`` in ``isar/src/robot_interface/models/mission/status.py``.
Duplicated rather than imported because the integration tests run ISAR as a
container and deliberately do not depend on the ISAR Python package.
"""

NOT_STARTED = "not_started"
IN_PROGRESS = "in_progress"
PAUSED = "paused"
FAILED = "failed"
CANCELLED = "cancelled"
SUCCESSFUL = "successful"
PARTIALLY_SUCCESSFUL = "partially_successful"
