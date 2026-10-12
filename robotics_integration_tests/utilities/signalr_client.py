"""A SignalR listener for Flotilla's hub, so tests can assert what the operator
UI would actually have received.

Flotilla is the only service that pushes to the browser. SARA has no hub of its
own: it publishes to MQTT, Flotilla's MqttEventHandler picks the message up and
re-emits it on the hub. Everything the frontend reacts to therefore crosses this
connection, and anything asserted over REST alone can pass while the UI stays
stale.

The hub places each connection in one group per installation code the token is
allowed to write to (SignalRHub.OnConnectedAsync in equinor/flotilla), so this
listener only sees events for installations the integration-tests client holds a
role for. That is HUA, KAA and NLS; see custom_realms/robotics-realm.json.
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, List, Optional

from loguru import logger
from pysignalr.client import SignalRClient
from pysignalr.messages import CompletionMessage

from robotics_integration_tests.settings.settings import settings
from robotics_integration_tests.utilities.authentication import (
    retrieve_access_token_for_integration_tests_app,
)

# Every label the suite listens for. pysignalr dispatches by name, so a label
# absent here is silently dropped rather than buffered.
#
# These strings are a contract with two independent codebases and are duplicated
# rather than derived: the sender is a C# literal (Api/Services/SignalRService.cs
# callers) and the receiver a TypeScript enum (SignalREventLabels in
# frontend/src/contexts/SignalRContext.tsx). Note "Visulization" is misspelled on
# both sides in flotilla; correcting it here alone would break the match.
MISSION_RUN_UPDATED = "Mission run updated"
ANALYSIS_RESULT_READY = "Analysis Result Ready"
INSPECTION_VISUALIZATION_READY = "Inspection Visulization Ready"

SUBSCRIBED_LABELS = [
    MISSION_RUN_UPDATED,
    ANALYSIS_RESULT_READY,
    INSPECTION_VISUALIZATION_READY,
]

# The hub sends (username, message); the frontend ignores the first argument.
_MESSAGE_ARGUMENT_INDEX = 1


@dataclass(frozen=True)
class SignalREvent:
    label: str
    message: str


class SignalRListener:
    """Buffers hub events from a background thread.

    pysignalr is asyncio-only while the tests are synchronous, so the client runs
    its own event loop on a daemon thread and the buffer is guarded by a lock.
    """

    def __init__(self, backend_url: str) -> None:
        # pysignalr speaks the WebSocket transport only; it does not negotiate
        # down to SSE or long polling, so the URL has to carry the ws scheme.
        self._hub_url = f"{backend_url}/hub".replace("http://", "ws://", 1).replace(
            "https://", "wss://", 1
        )
        self._events: List[SignalREvent] = []
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._connected = threading.Event()
        self._client: Optional[SignalRClient] = None
        self._task: Optional[asyncio.Task] = None

    def _record(self, label: str) -> Callable:
        # pysignalr awaits every callback, so this must be a coroutine function.
        async def handler(arguments: List) -> None:
            message = (
                arguments[_MESSAGE_ARGUMENT_INDEX]
                if len(arguments) > _MESSAGE_ARGUMENT_INDEX
                else ""
            )
            # Mission run payloads are several kilobytes and arrive on every task
            # transition, so log only enough to follow the sequence.
            logger.info(f"SignalR event '{label}' received: {str(message)[:200]}")
            with self._lock:
                self._events.append(SignalREvent(label=label, message=str(message)))

        return handler

    async def _run(self) -> None:
        # The token has to be supplied twice. pysignalr only applies
        # access_token_factory during the handshake, which happens *after* it
        # POSTs to /hub/negotiate; passing it as a static header too is what
        # authenticates that first request. The factory still earns its place on
        # reconnects, where the original token may have expired.
        token = retrieve_access_token_for_integration_tests_app(settings.FLOTILLA_SCOPE)
        client = SignalRClient(
            self._hub_url,
            headers={"Authorization": f"Bearer {token}"},
            access_token_factory=lambda: retrieve_access_token_for_integration_tests_app(
                settings.FLOTILLA_SCOPE
            ),
        )
        self._client = client
        self._task = asyncio.current_task()

        async def on_open() -> None:
            logger.info(f"SignalR connection to {self._hub_url} opened")
            self._connected.set()

        async def on_error(message: CompletionMessage) -> None:
            logger.error(f"SignalR error: {message.error}")

        client.on_open(on_open)
        client.on_error(on_error)
        for label in SUBSCRIBED_LABELS:
            client.on(label, self._record(label))

        await client.run()

    def _thread_main(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run())
        except asyncio.CancelledError:
            logger.info("SignalR listener cancelled")
        except Exception as exception:  # noqa: BLE001 - the listener must not fail a test
            logger.warning(
                f"SignalR listener stopped: {type(exception).__name__}: {exception}"
            )
        finally:
            # Drain before closing. pysignalr leaves the websocket keepalive task
            # pending, and closing the loop out from under it turns teardown into
            # a wall of "Event loop is closed" warnings that obscures real output.
            try:
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                loop.close()

    def start(self, timeout: int = 60) -> "SignalRListener":
        self._thread = threading.Thread(target=self._thread_main, daemon=True)
        self._thread.start()
        if not self._connected.wait(timeout=timeout):
            raise TimeoutError(
                f"SignalR connection to {self._hub_url} was not established "
                f"within {timeout}s"
            )
        return self

    def stop(self) -> None:
        # Cancel the client coroutine rather than stopping the loop, so that
        # _thread_main keeps control and can drain its own pending tasks.
        if self._loop is not None and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
        if self._thread is not None:
            self._thread.join(timeout=10)

    def events(self, label: Optional[str] = None) -> List[SignalREvent]:
        with self._lock:
            snapshot = list(self._events)
        if label is None:
            return snapshot
        return [event for event in snapshot if event.label == label]

    def clear(self) -> None:
        """Drop everything buffered so far.

        Call before provoking an event when an earlier phase of the test has
        already produced events with the same label.
        """
        with self._lock:
            self._events.clear()


def _summarise(events: List[SignalREvent]) -> str:
    """Mission run payloads are kilobytes each; keep failure output readable."""
    return ", ".join(f"{event.label}: {event.message[:120]}" for event in events)


def wait_for_signalr_event(
    listener: SignalRListener,
    label: str,
    predicate: Optional[Callable[[SignalREvent], bool]] = None,
    timeout: int = 60,
) -> SignalREvent:
    """Poll the buffer until a matching event arrives, or fail.

    Polling rather than awaiting: the event may already have been buffered
    before the call, and the tests are synchronous.
    """
    start_time: datetime = datetime.now()

    while True:
        for event in listener.events(label=label):
            if predicate is None or predicate(event):
                return event

        if datetime.now() - start_time > timedelta(seconds=timeout):
            raise TimeoutError(
                f"Timeout waiting {timeout}s for SignalR event '{label}'. "
                f"Received: {_summarise(listener.events())}"
            )

        time.sleep(1)


def assert_no_signalr_event(
    listener: SignalRListener,
    label: str,
    predicate: Optional[Callable[[SignalREvent], bool]] = None,
    settle_time: int = 15,
    message: str = "",
) -> None:
    """Assert no matching event arrives within *settle_time*.

    Proving a negative, so this can only ever be a best effort: it is a
    deliberate trade of runtime against confidence. Pass ``settle_time=0`` when
    an earlier call in the same test has already waited.
    """
    if settle_time:
        time.sleep(settle_time)

    matching = [
        event
        for event in listener.events(label=label)
        if predicate is None or predicate(event)
    ]
    if matching:
        raise AssertionError(
            message
            or f"Expected no SignalR event '{label}', but received: "
            f"{_summarise(matching)}"
        )


def carries_inspection_id(inspection_id: str) -> Callable[[SignalREvent], bool]:
    """Match an analysis-result or visualization event by inspection id."""

    def predicate(event: SignalREvent) -> bool:
        try:
            return json.loads(event.message).get("inspectionId") == inspection_id
        except json.JSONDecodeError:
            return False

    return predicate


def mission_run_reached(
    mission_run_id: str, status: str
) -> Callable[[SignalREvent], bool]:
    """Match a mission run update by id and status.

    Parses rather than substring-matching: the payload nests a robot object with
    a "status" of its own, so a naive search for '"status":"Successful"' would
    match the robot's state instead of the mission run's.
    """

    def predicate(event: SignalREvent) -> bool:
        try:
            payload = json.loads(event.message)
        except json.JSONDecodeError:
            return False
        return payload.get("id") == mission_run_id and payload.get("status") == status

    return predicate
    logger.info(f"No SignalR event '{label}' arrived within {settle_time}s, as expected")
