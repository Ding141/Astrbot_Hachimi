from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LocalApiClient(httpx.Client):
    def request(self, method, url, **kwargs):
        headers = httpx.Headers(kwargs.pop("headers", None))
        if method.upper() not in {"GET", "HEAD", "OPTIONS"} and "origin" not in headers:
            headers["Origin"] = str(self.base_url).rstrip("/")
        return super().request(method, url, headers=headers, **kwargs)


@pytest.fixture
def client(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    log_path = tmp_path / "api.log"
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(tmp_path / "isolated-home"),
        "DATABASE_PATH": str(tmp_path / "test.sqlite3"),
        "BACKUP_DIR": str(tmp_path / "backups"),
        "WEB_PASSWORD": "isolated-test-password",
        "SESSION_SECRET": "isolated-test-session-secret" * 3,
        "SERVICE_API_TOKEN": "isolated-test-service-token",
        "ASTRBOT_API_KEY": "",
        "COOKIE_SECURE": "false",
        "TIMEZONE": "Asia/Shanghai",
        "WEATHER_LOCATION_NAME": "",
        "WEATHER_LATITUDE": "",
        "WEATHER_LONGITUDE": "",
        "NEWS_RSS_URLS": "",
        "PYTHONPATH": str(PROJECT_ROOT),
        "PYTHONUNBUFFERED": "1",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }
    with log_path.open("wb") as log_stream:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "personal_assistant.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=log_stream,
            stderr=subprocess.STDOUT,
        )
        test_client = LocalApiClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=5
        )
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(
                        f"isolated API test server exited: {log_path.read_text(errors='replace')}"
                    )
                try:
                    if test_client.get("/healthz").status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.05)
            else:
                raise RuntimeError(
                    f"isolated API test server did not start: {log_path.read_text(errors='replace')}"
                )
            yield test_client
        finally:
            test_client.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def login(client: httpx.Client) -> httpx.Client:
    response = client.post(
        "/api/v1/auth/login",
        json={"password": "isolated-test-password"},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def authenticated_client(client):
    return login(client)
