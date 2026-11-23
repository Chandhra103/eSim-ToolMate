from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class AgentClientError(RuntimeError):
    pass


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        old = urllib.parse.urlparse(request.full_url)
        new = urllib.parse.urlparse(urllib.parse.urljoin(request.full_url, newurl))
        old_port = old.port or (443 if old.scheme == "https" else 80)
        new_port = new.port or (443 if new.scheme == "https" else 80)
        same_origin = old.scheme == new.scheme and old.hostname == new.hostname and old_port == new_port
        local_upgrade = old.scheme == "http" and old.hostname in {"localhost", "127.0.0.1", "::1"} and new.scheme == "https" and new.hostname == old.hostname
        if not (same_origin or local_upgrade):
            raise urllib.error.URLError("Refusing an unsafe or cross-origin Local Agent redirect")
        if new.username or new.password or new.scheme not in {"https", "http"}:
            raise urllib.error.URLError("Refusing a Local Agent redirect with unsafe URL components")
        if new.scheme == "http" and new.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise urllib.error.URLError("Refusing plaintext redirect outside localhost")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def validate_backend_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("Backend URL must use HTTPS (HTTP is allowed only for localhost testing).")
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Backend URL must be a valid origin/base path without embedded credentials, query, or fragment.")
    return url.rstrip("/")


class AgentClient:
    def __init__(self, backend_url: str, timeout: int = 15):
        self.backend_url = validate_backend_url(backend_url)
        self.timeout = timeout

    def _request(self, path: str, body: dict, token: str | None = None) -> dict:
        url = self.backend_url + path
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.build_opener(_SafeRedirectHandler()).open(request, timeout=self.timeout) as response:
                result = json.loads(response.read(1024 * 1024 + 1))
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise AgentClientError(f"Backend returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AgentClientError(f"Could not securely communicate with the backend: {exc}") from exc
        if not isinstance(result, dict):
            raise AgentClientError("Backend response was not a JSON object.")
        return result

    def _get(self, path: str, token: str) -> dict:
        request = urllib.request.Request(
            self.backend_url + path,
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.build_opener(_SafeRedirectHandler()).open(request, timeout=self.timeout) as response:
                result = json.loads(response.read(1024 * 1024 + 1))
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode("utf-8", errors="replace")
            raise AgentClientError(f"Backend returned HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AgentClientError(f"Could not securely communicate with the backend: {exc}") from exc
        if not isinstance(result, dict):
            raise AgentClientError("Backend response was not a JSON object.")
        return result

    def pair(self, pairing_secret: str, device_id: str, device_name: str, system: dict) -> dict:
        return self._request("/api/local-agents/pair", {
            "pairing_secret": pairing_secret,
            "device_id": device_id,
            "device_name": device_name,
            "operating_system": system.get("operating_system", "Unknown"),
            "architecture": system.get("architecture", "Unknown"),
            "os_release": system.get("os_release", "Unknown"),
        })

    def report(self, device_id: str, token: str, report: dict) -> dict:
        return self._request(f"/api/local-agents/{device_id}/report", report, token)

    def heartbeat(self, device_id: str, token: str, scanned_at: str | None = None) -> dict:
        return self._request(f"/api/local-agents/{device_id}/heartbeat", {"scanned_at": scanned_at}, token)

    def next_operation(self, device_id: str, token: str) -> dict | None:
        result = self._get(f"/api/local-agents/{device_id}/operations/next", token)
        job = result.get("job")
        if job is not None and not isinstance(job, dict):
            raise AgentClientError("Backend returned an invalid operation job.")
        return job

    def complete_operation(self, device_id: str, token: str, job_id: str, status: str, message: str) -> dict:
        return self._request(
            f"/api/local-agents/{device_id}/operations/{job_id}/result",
            {"status": status, "message": message[:4000]},
            token,
        )
