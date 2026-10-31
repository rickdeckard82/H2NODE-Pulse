"""Exercise identity/tickets on an ephemeral PostgreSQL cluster, never the app database."""

import subprocess

command = ["docker", "compose", "-f", "compose.yaml", "-f", "compose.test.yaml"]
try:
    subprocess.run(
        [*command, "up", "-d", "--wait", "--wait-timeout", "600", "antimalware"],
        check=True,
    )
    subprocess.run([*command, "up", "-d", "--wait", "identity-db"], check=True)
    subprocess.run(
        [
            *command,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "POSTGRES_DB=test_pulse",
            "identity-tests",
            "python",
            "manage.py",
            "migrate",
            "--noinput",
        ],
        check=True,
    )
    subprocess.run(
        [
            *command,
            "run",
            "--rm",
            "--no-deps",
            "-e",
            "PGHOST=identity-db",
            "-e",
            "PGDATABASE=test_pulse",
            "db-permissions",
        ],
        check=True,
    )
    subprocess.run([*command, "run", "--rm", "--no-deps", "identity-tests"], check=True)
finally:
    subprocess.run([*command, "stop", "identity-db"], check=True)
    subprocess.run([*command, "rm", "-f", "identity-db"], check=True)
