#!/usr/bin/env python3
"""Operational smoke test for QEngin notebook execution."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.token = None

    def request(self, method: str, path: str, payload: dict | None = None):
        data = None
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with self.opener.open(req, timeout=60) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, dict(resp.headers), body

    def login(self, username: str, password: str):
        status, _, body = self.request("POST", "/auth/login", {"username": username, "password": password})
        if status != 200:
            raise RuntimeError(f"login failed: {status} {body}")
        payload = json.loads(body)
        self.token = payload["token"]
        return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Example: https://miro.gantor.ir/engine")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", required=True)
    parser.add_argument("--topic", default="Hormuz energy shipping outlook")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--exercise-cancel",
        action="store_true",
        help="Start a second notebook run and verify the operator cancel path.",
    )
    args = parser.parse_args()

    client = Client(args.base_url)
    print("login...")
    client.login(args.username, args.password)

    print("create notebook...")
    status, _, body = client.request("POST", "/wizard/quick-notebook", {"topic": args.topic})
    if status not in (200, 201):
        raise RuntimeError(f"quick-notebook failed: {status} {body}")
    created = json.loads(body)
    notebook = created["notebook"]
    notebook_id = notebook["id"]
    print(f"created notebook={notebook_id} title={notebook['title']}")

    print("start run...")
    status, _, body = client.request("POST", f"/notebooks/{notebook_id}/run")
    if status not in (200, 202):
        raise RuntimeError(f"run failed: {status} {body}")
    print(body)

    deadline = time.time() + args.timeout
    complete = False
    next_index = 0
    while time.time() < deadline:
        status, _, body = client.request("GET", f"/notebooks/{notebook_id}/status")
        if status != 200:
            raise RuntimeError(f"status failed: {status} {body}")
        payload = json.loads(body)
        print(f"status={payload['status']} progress={payload.get('progress')} stage={payload.get('current_stage')}")

        log_status, _, log_body = client.request("GET", f"/notebooks/{notebook_id}/logs?from={next_index}")
        if log_status == 200:
            log_payload = json.loads(log_body)
            for item in log_payload.get("logs", []):
                print(f"log {item.get('stage')} :: {item.get('message')}")
            next_index = log_payload.get("next_index", next_index)

        if payload["status"] in ("complete", "failed"):
            complete = True
            break
        time.sleep(3)

    if not complete:
        raise RuntimeError("notebook execution timed out")

    status, _, body = client.request("GET", f"/notebooks/{notebook_id}/results")
    if status not in (200, 202):
        raise RuntimeError(f"results failed: {status} {body}")
    results = json.loads(body)
    if not results.get("results_ready"):
        raise RuntimeError(f"results not ready: {body}")

    diagnostics_status, _, diagnostics_body = client.request("GET", f"/notebooks/{notebook_id}/diagnostics")
    if diagnostics_status != 200:
        raise RuntimeError(f"diagnostics failed: {diagnostics_status} {diagnostics_body}")
    diagnostics = json.loads(diagnostics_body)
    if "pipeline" not in diagnostics or "execution" not in diagnostics:
        raise RuntimeError(f"diagnostics payload incomplete: {diagnostics_body}")
    print(
        "diagnostics ok"
        f" pipeline={len(diagnostics.get('pipeline', []))}"
        f" sources={diagnostics.get('source_summary', {}).get('count', 0)}"
    )

    for fmt in ("json", "markdown", "html"):
        export_status, headers, export_body = client.request(
            "GET",
            f"/notebooks/{notebook_id}/export?{urllib.parse.urlencode({'format': fmt})}",
        )
        if export_status != 200:
            raise RuntimeError(f"export {fmt} failed: {export_status}")
        print(f"export {fmt} ok content-type={headers.get('Content-Type')} bytes={len(export_body.encode('utf-8'))}")

    if args.exercise_cancel:
        print("create cancel notebook...")
        status, _, body = client.request(
            "POST",
            "/notebooks",
            {
                "title": "Cancel path validation",
                "config": {
                    "topic": f"{args.topic} :: cancel validation",
                    "analysis_mode": "operational-watch",
                    "analysis_depth": "standard",
                    "llm_model": "cl-claude-haiku-4-5-20251001",
                    "source_limit": 8,
                },
            },
        )
        if status not in (200, 201):
            raise RuntimeError(f"cancel notebook create failed: {status} {body}")
        cancel_notebook = json.loads(body)
        cancel_id = cancel_notebook["id"]
        print(f"cancel notebook={cancel_id}")

        status, _, body = client.request("POST", f"/notebooks/{cancel_id}/run")
        if status not in (200, 202):
            raise RuntimeError(f"cancel run start failed: {status} {body}")
        time.sleep(1.5)

        status, _, body = client.request("POST", f"/notebooks/{cancel_id}/cancel")
        if status not in (200, 202):
            raise RuntimeError(f"cancel request failed: {status} {body}")
        payload = json.loads(body)
        print(f"cancel requested: {payload.get('cancel_requested')}")

        cancel_deadline = time.time() + min(args.timeout, 90)
        cancelled = False
        while time.time() < cancel_deadline:
            status, _, body = client.request("GET", f"/notebooks/{cancel_id}/status")
            if status != 200:
                raise RuntimeError(f"cancel status failed: {status} {body}")
            payload = json.loads(body)
            print(
                f"cancel-status={payload['status']} progress={payload.get('progress')}"
                f" stage={payload.get('current_stage')} cancel_requested={payload.get('cancel_requested')}"
            )
            if payload["status"] == "cancelled":
                cancelled = True
                break
            if payload["status"] in ("complete", "failed"):
                raise RuntimeError(f"cancel path ended in unexpected state: {payload['status']}")
            time.sleep(2)

        if not cancelled:
            raise RuntimeError("cancel path timed out")

        status, _, body = client.request("GET", f"/notebooks/{cancel_id}/logs")
        if status != 200:
            raise RuntimeError(f"cancel logs failed: {status} {body}")
        log_payload = json.loads(body)
        if not any(item.get("stage") == "cancelled" for item in log_payload.get("logs", [])):
            raise RuntimeError("cancelled log entry missing")
        print("cancel flow ok")

    print("smoke test ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
