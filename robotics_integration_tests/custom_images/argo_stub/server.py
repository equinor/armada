"""Stand-in for the Argo Workflows trigger services in front of the analyzers.

SARA triggers an analysis step by POSTing to a per-workflow ``TriggerUrl``. In
production that reaches an Argo event source which submits a workflow; the
workflow then reports back to SARA over three callbacks:

    PUT /api/workflow/{workflowId}/started
    PUT /api/workflow/{workflowId}/result
    PUT /api/workflow/{workflowId}/exited

This server accepts any trigger, records the payload, optionally writes an
output blob so downstream assertions can dereference it, and drives those three
callbacks. It exists so the integration tests can exercise the whole analysis
chain -- step ordering, gate skipping, result handlers and the resulting MQTT
messages -- without running PyTorch analyzers or an Argo installation.

Endpoints:
    POST /trigger/<name>  Accept a trigger. <name> is ignored; the workflow type
                          is read from the payload, exactly as the real event
                          sources do.
    POST /behaviour       Set per-workflow-type behaviour (see Behaviour below).
    GET  /triggers        Every trigger payload received, in arrival order.
    GET  /callbacks       Every callback made to SARA, in arrival order.
    POST /reset           Clear recorded triggers, callbacks and behaviour.
    GET  /health          200 once the server is up.

Behaviour is keyed by workflow type, with "*" as the fallback:

    {
      "rain-drop": {
        "result": {"rain": true},
        "exit_status": "Succeeded",
        "trigger_status": 200,
        "raw_result": null,
        "delay_seconds": 0,
        "write_output_blob": true
      }
    }
"""

import json
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional

import requests

try:
    from azure.storage.blob import BlobServiceClient
except ImportError:  # pragma: no cover - the image always installs it
    BlobServiceClient = None  # type: ignore[assignment]

SARA_BASE_URL: str = os.environ.get("SARA_BASE_URL", "").rstrip("/")
TOKEN_URL: str = os.environ.get("TOKEN_URL", "")
CLIENT_ID: str = os.environ.get("CLIENT_ID", "")
CLIENT_SECRET: str = os.environ.get("CLIENT_SECRET", "")
TOKEN_SCOPE: str = os.environ.get("TOKEN_SCOPE", "")
# JSON object mapping storage account name -> Azurite connection string.
BLOB_CONNECTION_STRINGS: Dict[str, str] = json.loads(
    os.environ.get("BLOB_CONNECTION_STRINGS", "{}")
)

# Result payloads that satisfy each handler's expected shape. A test overrides
# whichever of these it cares about via POST /behaviour.
DEFAULT_RESULTS: Dict[str, Dict[str, Any]] = {
    "anonymizer": {"isPersonInImage": False},
    "rain-drop": {"rain": False},
    "fencilla": {"isBreak": False, "confidence": 0.9, "warning": None},
    "cloe": {"oilLevel": 0.5, "confidence": 0.95, "warning": None},
    "thermal-reading": {"temperature": 42.0, "confidence": 1.0},
    "copy-raw-to-visualized": {},
}

_triggers: List[dict] = []
_callbacks: List[dict] = []
_behaviour: Dict[str, dict] = {}
_lock = threading.Lock()


def _log(message: str) -> None:
    print(f"[argo-stub] {message}", flush=True)


def _behaviour_for(workflow_type: str) -> dict:
    with _lock:
        specific = dict(_behaviour.get("*", {}))
        specific.update(_behaviour.get(workflow_type, {}))
        return specific


def _access_token() -> Optional[str]:
    """Mint a token for the SARA callbacks.

    The callbacks require the WorkflowStatus.Write role; the realm grants it to
    the integration-tests service account.
    """
    if not TOKEN_URL:
        return None
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "scope": TOKEN_SCOPE,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def _put(path: str, body: Any, token: Optional[str]) -> None:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{SARA_BASE_URL}{path}"
    response = requests.put(url, json=body, headers=headers, timeout=30)
    with _lock:
        _callbacks.append(
            {
                "path": path,
                "body": body,
                "status_code": response.status_code,
            }
        )
    _log(f"PUT {path} -> {response.status_code}")
    response.raise_for_status()


def _write_output_blob(location: Optional[dict]) -> None:
    """Create the blob SARA told us to write to, so tests can assert it exists.

    Best effort: a missing connection string for the account means the test is
    not asserting on that account's contents.
    """
    if not location or BlobServiceClient is None:
        return

    account = location.get("storageAccount") or location.get("StorageAccount")
    container = location.get("blobContainer") or location.get("BlobContainer")
    blob_name = location.get("blobName") or location.get("BlobName")
    if not (account and container and blob_name):
        return

    connection_string = BLOB_CONNECTION_STRINGS.get(account)
    if not connection_string:
        _log(f"No connection string for account '{account}', skipping blob write")
        return

    service = BlobServiceClient.from_connection_string(connection_string)
    try:
        service.create_container(container)
    except Exception:
        pass  # Already exists.

    service.get_blob_client(container=container, blob=blob_name).upload_blob(
        b"argo-stub output", overwrite=True
    )
    _log(f"Wrote output blob {account}/{container}/{blob_name}")


def _run_workflow(payload: dict) -> None:
    """Drive the started/result/exited callbacks for one triggered workflow."""
    workflow_id = payload.get("workflowId")
    workflow_type = payload.get("workflowType", "")
    behaviour = _behaviour_for(workflow_type)

    delay = float(behaviour.get("delay_seconds", 0))
    if delay:
        time.sleep(delay)

    try:
        token = _access_token()

        _put(
            f"/api/workflow/{workflow_id}/started",
            {"argoWorkflowName": f"stub-{workflow_type}-{workflow_id}"},
            token,
        )

        output_location = payload.get("outputBlobStorageLocation")
        if behaviour.get("write_output_blob", True):
            _write_output_blob(output_location)

        if "raw_result" in behaviour and behaviour["raw_result"] is not None:
            # Deliberately malformed, to exercise SARA's fail-closed gate handling.
            result_json = behaviour["raw_result"]
        else:
            result = dict(DEFAULT_RESULTS.get(workflow_type, {}))
            result.update(behaviour.get("result", {}))
            # Every handler that produces a visualization or feeds the next step
            # reads the output location back out of the result document.
            result.setdefault("outputBlobStorageLocation", output_location)
            if workflow_type == "anonymizer":
                result.setdefault(
                    "preProcessedBlobStorageLocation",
                    (payload.get("extras") or {}).get(
                        "preProcessedBlobStorageLocation"
                    ),
                )
            result_json = json.dumps(result)

        _put(f"/api/workflow/{workflow_id}/result", {"resultJson": result_json}, token)

        exit_status = behaviour.get("exit_status", "Succeeded")
        exited_body: Dict[str, Any] = {"exitStatus": exit_status}
        if exit_status != "Succeeded":
            exited_body["errorMessage"] = behaviour.get(
                "error_message", "argo-stub was configured to fail this workflow"
            )
        _put(f"/api/workflow/{workflow_id}/exited", exited_body, token)

    except Exception:
        _log(f"Workflow {workflow_id} ({workflow_type}) callbacks failed:")
        _log(traceback.format_exc())


class Handler(BaseHTTPRequestHandler):
    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}

    def _respond(self, status: int, body: Any = None) -> None:
        self.send_response(status)
        if body is not None:
            encoded = json.dumps(body).encode()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        else:
            self.end_headers()

    def do_POST(self) -> None:
        if self.path.startswith("/trigger"):
            payload = self._read_json()
            workflow_type = payload.get("workflowType", "")
            with _lock:
                _triggers.append(payload)
            _log(
                f"Trigger for workflow type '{workflow_type}' "
                f"(id {payload.get('workflowId')})"
            )

            behaviour = _behaviour_for(workflow_type)
            trigger_status = int(behaviour.get("trigger_status", 200))
            if trigger_status >= 400:
                # Simulate Argo being unreachable or rejecting the submission.
                # SARA marks the workflow, and the whole run, as failed.
                self._respond(trigger_status, {"error": "argo-stub rejected trigger"})
                return

            threading.Thread(
                target=_run_workflow, args=(payload,), daemon=True
            ).start()
            self._respond(trigger_status, {"accepted": True})

        elif self.path == "/behaviour":
            payload = self._read_json()
            with _lock:
                for workflow_type, config in payload.items():
                    _behaviour.setdefault(workflow_type, {}).update(config)
            self._respond(200, {"behaviour": _behaviour})

        elif self.path == "/reset":
            with _lock:
                _triggers.clear()
                _callbacks.clear()
                _behaviour.clear()
            self._respond(200, {"reset": True})

        else:
            self._respond(404)

    def do_PUT(self) -> None:
        self.do_POST()

    def do_GET(self) -> None:
        if self.path == "/triggers":
            with _lock:
                self._respond(200, list(_triggers))
        elif self.path == "/callbacks":
            with _lock:
                self._respond(200, list(_callbacks))
        elif self.path == "/health":
            self._respond(200, {"status": "healthy"})
        else:
            self._respond(404)

    def log_message(self, format, *args) -> None:  # noqa: A002
        pass


if __name__ == "__main__":
    _log(f"Argo stub listening on :8080, SARA at '{SARA_BASE_URL}'")
    HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
