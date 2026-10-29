"""Integration checks for an isolated development Compose project. Preserves volumes."""

import json
import subprocess
import time
import urllib.request
from urllib.error import HTTPError


def compose(*args):
    return subprocess.check_output(["docker", "compose", *args], text=True).strip()


config = json.loads(compose("config", "--format", "json"))
assert config["services"]["api"]["environment"]["APP_ENV"] == "development", (
    "Run this restart/persistence test only against the development project"
)
port = config["services"]["gateway"]["ports"][0]["published"]
url = f"http://127.0.0.1:{port}/api/v1/health/ready/"


def ready():
    for _ in range(30):
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status == 200 and json.load(response)["status"] == "ready":
                    return
        except (OSError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Gateway/API/PostgreSQL did not become ready")


ready()
base_url = f"http://127.0.0.1:{port}/api/v1/auth"
with urllib.request.urlopen(f"{base_url}/csrf/", timeout=5) as response:
    assert response.headers["Cache-Control"] == "no-store"
    assert json.load(response)["csrfToken"]
for request in [
    urllib.request.Request(f"{base_url}/me/"),
    urllib.request.Request(
        f"{base_url}/login/", data=b"{}", headers={"Content-Type": "application/json"}
    ),
]:
    try:
        urllib.request.urlopen(request, timeout=5)
    except HTTPError as error:
        assert error.code == 403
    else:
        raise AssertionError("Anonymous profile or login without CSRF was accepted")
print("Identity HTTP smoke passed: CSRF bootstrap, protected profile and login CSRF.")
before = compose(
    "exec",
    "-T",
    "api",
    "python",
    "manage.py",
    "shell",
    "-c",
    "from django.db import connection; "
    "c=connection.cursor(); c.execute('SELECT count(*) FROM django_migrations'); "
    "print(c.fetchone()[0])",
).splitlines()[-1]
assert int(before) > 0
# Docker's database cluster system identifier detects unintended volume replacement.
cluster_before = compose(
    "exec",
    "-T",
    "db",
    "psql",
    "-U",
    "postgres",
    "-Atc",
    "SELECT system_identifier FROM pg_control_system()",
)
compose("restart", "db", "api", "worker", "gateway")
ready()
cluster_after = compose(
    "exec",
    "-T",
    "db",
    "psql",
    "-U",
    "postgres",
    "-Atc",
    "SELECT system_identifier FROM pg_control_system()",
)
assert cluster_before == cluster_after, "Database cluster changed after restart"
after = compose(
    "exec",
    "-T",
    "api",
    "python",
    "manage.py",
    "shell",
    "-c",
    "from django.db import connection; "
    "c=connection.cursor(); c.execute('SELECT count(*) FROM django_migrations'); "
    "print(c.fetchone()[0])",
).splitlines()[-1]
assert before == after
assert compose("exec", "-T", "api", "id", "-u") != "0"
assert compose("exec", "-T", "gateway", "id", "-u") != "0"
print("Docker smoke passed: readiness, migrations, restart, persisted cluster, non-root runtimes.")
