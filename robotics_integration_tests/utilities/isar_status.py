"""The vocabulary ISAR publishes on its MQTT status topic.

Mirrors ``IsarStatus`` in ``isar/src/isar/models/status.py``. Duplicated rather
than imported because the integration tests run against ISAR as a container and
deliberately do not depend on the ISAR Python package.

Note that this vocabulary is *coarser* than ISAR's internal state machine: several
states collapse onto one status in ``state_to_status``. In particular:

* ``Stopping``, ``StoppingDueToMaintenance``, ``StoppingGoToLockdown``,
  ``StoppingGoToRecharge``, ``StoppingPausedMission`` and
  ``StoppingPausedReturnHome`` all publish :data:`STOPPING`.
* ``Lockdown`` and ``LockdownWithMission`` both publish :data:`LOCKDOWN`.
* ``GoingToLockdown`` and ``GoingToLockdownWithMission`` both publish
  :data:`GOING_TO_LOCKDOWN`.
* ``Monitor``, ``Resuming``, ``ResumingReturnHome``, ``UnknownStatus`` and
  ``StoppingUnknownMission`` fall through to :data:`BUSY`.

So a status trace proves *which family* of state was entered, not which member.
Tests distinguish the members by combining the trace with the mission outcome
reported by Flotilla — for example, a lockdown that resumes its mission on
release must end Successful, which a mission-less lockdown never can.
"""

AVAILABLE = "available"
RETURN_HOME_PAUSED = "returnhomepaused"
PAUSED = "paused"
BUSY = "busy"
HOME = "home"
OFFLINE = "offline"
RETURNING_HOME = "returninghome"
INTERVENTION_NEEDED = "interventionneeded"
RECHARGING = "recharging"
RECHARGING_WITH_MISSION = "rechargingwithmission"
LOCKDOWN = "lockdown"
GOING_TO_LOCKDOWN = "goingtolockdown"
GOING_TO_RECHARGING = "goingtorecharging"
GOING_TO_RECHARGING_WITH_MISSION = "goingtorechargingwithmission"
MAINTENANCE = "maintenance"
PAUSING = "pausing"
PAUSING_RETURN_HOME = "pausingreturnhome"
STOPPING = "stopping"
STOPPING_RETURN_HOME = "stoppingreturnhome"
