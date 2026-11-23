from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import time
import uuid
from datetime import UTC, datetime

from local_agent import config
from local_agent.client import AgentClient, AgentClientError
from local_agent.detector import scan_report
from local_agent.operations import SUPPORTED_TOOLS, execute_operation

DEFAULT_SCAN_INTERVAL = 1800
HEARTBEAT_INTERVAL = 60


def scan_is_due(last_scan: float | None, now: float, interval: int) -> bool:
    return last_scan is None or now - last_scan >= interval


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="esim-toolmate-agent", description="Secure local software detection agent")
    parser.add_argument("--backend", default=os.environ.get("ESIM_TOOLMATE_BACKEND_URL"), help="HTTPS FastAPI base URL")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pair", help="Pair this device using the server pairing secret")
    scan = sub.add_parser("scan", help="Run a manual local scan and securely upload the result")
    scan.add_argument("--json", action="store_true", help="Print the local scan report as JSON")
    run = sub.add_parser("run", help="Run initial scan and scheduled scans/heartbeats in the background")
    run.add_argument("--interval", type=int, default=DEFAULT_SCAN_INTERVAL, help="Scan interval in seconds (minimum 300)")
    return parser


def _client(url: str | None) -> AgentClient:
    if not url:
        raise ValueError("Set --backend or ESIM_TOOLMATE_BACKEND_URL to the FastAPI HTTPS base URL.")
    return AgentClient(url)


def _pair(url: str) -> None:
    current = config.load()
    device_id = current.get("device_id") or str(uuid.uuid4())
    system = scan_report(current.get("minimum_versions"))
    secret = getpass.getpass("Server pairing secret (input hidden): ").strip()
    if len(secret) < 32:
        raise ValueError("The pairing secret must be at least 32 characters.")
    client = _client(url)
    response = client.pair(secret, device_id, socket.gethostname()[:120], system)
    token = response.get("access_token")
    if not isinstance(token, str) or len(token) < 32:
        raise AgentClientError("Pairing response did not contain a valid device access token.")
    current.update({"device_id": device_id, "access_token": token, "backend_url": client.backend_url})
    config.save(current)
    print("Device paired. The one-time response token was saved using the platform's protected config store.")


def _scan(url: str | None, print_json: bool = False) -> dict:
    current = config.load()
    report = scan_report(current.get("minimum_versions"))
    if print_json:
        print(json.dumps(report, indent=2))
    if not current.get("device_id") or not current.get("access_token"):
        if print_json:
            return report
        raise ValueError("This device is not paired. Run `python -m local_agent --backend <URL> pair` first.")
    client = _client(url or current.get("backend_url"))
    client.report(current["device_id"], current["access_token"], report)
    print(f"Scan uploaded: {len(report['tools'])} tools; scanned at {report['scanned_at']}.")
    return report


def _process_operation(job: dict, client: AgentClient, current: dict) -> dict | None:
    try:
        job_id = str(uuid.UUID(str(job.get("job_id", ""))))
    except (ValueError, AttributeError):
        print("Ignoring a Local Agent job with an invalid identifier.")
        return None
    tool_id = job.get("tool_id")
    operation = job.get("operation")
    if tool_id not in SUPPORTED_TOOLS or operation not in {"verify", "install", "update", "uninstall"}:
        return {"job_id": job_id, "status": "unsupported", "message": "The requested tool or operation is not allowlisted by this Local Agent."}

    if operation == "verify":
        report = scan_report(current.get("minimum_versions"))
        client.report(current["device_id"], current["access_token"], report)
        result = next(item for item in report["tools"] if item["id"] == tool_id)
        status = "completed" if result["status"] in {"Installed", "Outdated"} and result.get("version") else "failed"
        return {"job_id": job_id, "status": status, "message": f"Local verification: {result['status']}; version {result.get('version') or 'unknown'}."}

    tool_name = next((item["name"] for item in scan_report(current.get("minimum_versions"))["tools"] if item["id"] == tool_id), tool_id)
    print(f"\nLocal approval required: {operation} {tool_name}.")
    print("This operation runs on this computer using an allowlisted package manager. No shell command is accepted from the server.")
    try:
        answer = input("Approve on this computer? [y/N]: ").strip().casefold()
    except EOFError:
        answer = ""
    if answer not in {"y", "yes"}:
        return {"job_id": job_id, "status": "denied", "message": "Operation denied or no interactive local approval was available."}

    result = execute_operation(tool_id, operation)
    report_message = ""
    try:
        report = scan_report(current.get("minimum_versions"))
        client.report(current["device_id"], current["access_token"], report)
    except (AgentClientError, OSError, ValueError) as exc:
        report_message = f" Local scan upload is pending; the next scheduled scan will retry. ({exc})"
    status = "completed" if result.status == "success" else result.status
    return {"job_id": job_id, "status": status, "message": (result.message + report_message)[:4000]}


def _deliver_pending(client: AgentClient, current: dict, pending: dict) -> bool:
    try:
        client.complete_operation(
            current["device_id"], current["access_token"], pending["job_id"],
            pending["status"], pending["message"],
        )
    except AgentClientError as exc:
        if "HTTP 409" in str(exc):
            print(f"Local operation {pending['job_id']} is no longer pending on the server; discarding the stale result.")
            return True
        raise
    print(f"Local operation {pending['job_id']} reported: {pending['status']}.")
    return True


def _run(url: str | None, interval: int) -> None:
    if interval < 300:
        raise ValueError("Scheduled scan interval must be at least 300 seconds.")
    current = config.load()
    if not current.get("device_id") or not current.get("access_token"):
        raise ValueError("This device is not paired. Run the pair command first.")
    backend = url or current.get("backend_url")
    client = _client(backend)
    last_scan: float | None = None
    pending_completion: dict | None = None
    print("Local Agent running. Press Ctrl+C to stop.")
    while True:
        now = time.monotonic()
        try:
            if scan_is_due(last_scan, now, interval):
                report = scan_report(current.get("minimum_versions"))
                client.report(current["device_id"], current["access_token"], report)
                last_scan = now
                print(f"Scan uploaded at {report['scanned_at']}.")
            else:
                client.heartbeat(current["device_id"], current["access_token"], datetime.now(UTC).isoformat())
            if pending_completion:
                if _deliver_pending(client, current, pending_completion):
                    pending_completion = None
            else:
                job = client.next_operation(current["device_id"], current["access_token"])
                if job:
                    pending_completion = _process_operation(job, client, current)
                    if pending_completion and _deliver_pending(client, current, pending_completion):
                        pending_completion = None
        except (AgentClientError, OSError, ValueError) as exc:
            print(f"Agent communication/detection warning: {exc}")
        time.sleep(HEARTBEAT_INTERVAL)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "pair":
            _pair(args.backend)
        elif args.command == "scan":
            _scan(args.backend, args.json)
        elif args.command == "run":
            _run(args.backend, args.interval)
    except KeyboardInterrupt:
        print("Local Agent stopped.")
    except (ValueError, AgentClientError, OSError) as exc:
        print(f"Local Agent error: {exc}")
        return 2
    return 0
