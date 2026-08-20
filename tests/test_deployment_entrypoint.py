from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DeploymentEntrypointTests(unittest.TestCase):
    def test_legacy_render_start_command_serves_health_endpoint(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]

        environment = os.environ.copy()
        environment.update({"HOST": "127.0.0.1", "PORT": str(port)})
        process = subprocess.Popen(
            [sys.executable, "server.py"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(
                        "Legacy Render start command exited before becoming healthy:\n"
                        f"stdout:\n{stdout}\nstderr:\n{stderr}"
                    )
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health",
                        timeout=0.5,
                    ) as response:
                        payload = json.loads(response.read())
                    self.assertEqual(response.status, 200)
                    self.assertEqual(payload, {"ok": True, "hasData": True})
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                self.fail("Legacy Render start command did not become healthy within 10 seconds")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.communicate()


if __name__ == "__main__":
    unittest.main()
