from types import SimpleNamespace
from typing import Dict, List

import pytest

from robotics_integration_tests.scenarios import steps
from robotics_integration_tests.scenarios.steps import (
    Condition,
    RobotContext,
    RobotScenario,
    Step,
    advance_each_robot_through_its_own_steps,
    do,
    robot_is,
    wait_for,
    when,
)


class FakeFlotilla:
    """Robot statuses that only change when a step acts on the robot."""

    def __init__(self, statuses: Dict[str, str]) -> None:
        self.statuses: Dict[str, str] = dict(statuses)
        self.actions: List[str] = []

    def set_status(self, status: str):
        def action(context: RobotContext) -> None:
            self.actions.append(f"{context.robot.name}->{status}")
            self.statuses[context.robot.name] = status

        return action


@pytest.fixture
def flotilla(monkeypatch) -> FakeFlotilla:
    fake = FakeFlotilla({"A": "Home", "B": "Home"})
    monkeypatch.setattr(steps, "POLL_INTERVAL_IN_SECONDS", 0)
    monkeypatch.setattr(
        steps.flotilla, "get_robot_statuses", lambda backend_url: dict(fake.statuses)
    )
    return fake


def _armada(*names: str) -> SimpleNamespace:
    return SimpleNamespace(
        flotilla_backend=SimpleNamespace(backend_url="http://flotilla"),
        robots={name: SimpleNamespace(name=name, robot_id=name) for name in names},
    )


def _scenario(name: str, scenario_steps: List[Step], **settings) -> RobotScenario:
    return RobotScenario(name=name, steps=scenario_steps, **settings)


def test_each_robot_advances_through_its_own_steps(flotilla) -> None:
    roster = [
        _scenario(
            "A",
            [
                do(flotilla.set_status("Paused")),
                when(robot_is("Paused"), flotilla.set_status("Home")),
                wait_for(robot_is("Home")),
            ],
        ),
        _scenario("B", [wait_for(robot_is("Home"))]),
    ]

    contexts = advance_each_robot_through_its_own_steps(
        armada=_armada("A", "B"), roster=roster
    )

    assert flotilla.actions == ["A->Paused", "A->Home"]
    assert contexts["A"].observed_statuses == ["Home", "Paused", "Home"]
    assert contexts["B"].observed_statuses == ["Home"]


def test_a_stalled_robot_does_not_hold_back_the_others(flotilla) -> None:
    roster = [
        _scenario(
            "A",
            [wait_for(robot_is("Lockdown"))],
            step_timeout_in_seconds=0.05,
            drives_isar_through="Home -> Lockdown",
        ),
        _scenario("B", [do(flotilla.set_status("Paused"))]),
    ]

    with pytest.raises(AssertionError) as error:
        advance_each_robot_through_its_own_steps(
            armada=_armada("A", "B"), roster=roster
        )

    assert flotilla.actions == ["B->Paused"]
    message = str(error.value)
    assert "1 of 2 robots failed" in message
    assert "A: step 1 of 1: 'robot is Lockdown' was not met within 0.05s" in message
    assert "Statuses observed: ['Home']" in message
    assert "Meant to drive ISAR through: Home -> Lockdown" in message


def test_every_failing_robot_is_reported(flotilla) -> None:
    def rejected(context: RobotContext) -> None:
        raise RuntimeError("409 Conflict")

    roster = [
        _scenario("A", [do(rejected), wait_for(robot_is("Home"))]),
        _scenario("B", [wait_for(robot_is("Lockdown"), timeout_in_seconds=0.05)]),
    ]

    with pytest.raises(AssertionError) as error:
        advance_each_robot_through_its_own_steps(
            armada=_armada("A", "B"), roster=roster
        )

    message = str(error.value)
    assert "A: step 1 of 2: rejected failed: 409 Conflict" in message
    assert "B: step 1 of 1" in message


def test_a_condition_that_raises_is_retried(flotilla) -> None:
    attempts: List[int] = []

    def flaky(context: RobotContext) -> bool:
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("not written to the database yet")
        return True

    roster = [_scenario("A", [wait_for(Condition("flaky", flaky))])]

    advance_each_robot_through_its_own_steps(armada=_armada("A"), roster=roster)

    assert len(attempts) == 3


def test_a_status_that_can_pass_between_two_polls_cannot_be_waited_for() -> None:
    with pytest.raises(ValueError, match="'Stopping' can pass between two polls"):
        robot_is("Stopping")
