"""Reproducible browser tests with a separate tmpfs PostgreSQL project."""

import base64
import json
import secrets
import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parent.parent
work = root / "work"
work.mkdir(exist_ok=True)
fixture = work / "e2e-fixture.json"
fixture.write_text(
    json.dumps(
        {
            "password": secrets.token_urlsafe(32),
            "mfa": {
                name: base64.b32encode(secrets.token_bytes(20)).decode()
                for name in ["tech", "admin", "manager"]
            },
        }
    )
)
command = [
    "docker",
    "compose",
    "-p",
    "pulse-e2e",
    "-f",
    "compose.yaml",
    "-f",
    "compose.e2e.yaml",
]


def run(*args):
    subprocess.run([*command, *args], check=True, cwd=root)


try:
    run("up", "-d", "--wait", "--wait-timeout", "180", "gateway")
    run(
        "run",
        "--rm",
        "--no-deps",
        "-v",
        f"{fixture}:/tmp/e2e-fixture.json:ro",
        "-v",
        f"{root / 'tests/seed_e2e.py'}:/tmp/seed_e2e.py:ro",
        "migrate",
        "python",
        "manage.py",
        "shell",
        "-c",
        "exec(open('/tmp/seed_e2e.py').read())",
    )
    subprocess.run(
        [shutil.which("npx"), "playwright", "test"], cwd=root / "frontend", check=True
    )
finally:
    run("down")
    fixture.unlink(missing_ok=True)
