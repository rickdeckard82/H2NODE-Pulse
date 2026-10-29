"""Run local checks without pretending that mocks validate PostgreSQL integration."""

import os
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
(root / "work").mkdir(exist_ok=True)
env = {
    **os.environ,
    "APP_ENV": "test",
    "DJANGO_SECRET_KEY_FILE": str(root / "secrets/django_secret_key.txt"),
    "POSTGRES_PASSWORD_FILE": str(root / "secrets/postgres_password.txt"),
    "POSTGRES_HOST": "127.0.0.1",
    "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
}


def run(*args, overrides=None):
    subprocess.run(
        [sys.executable, *args],
        cwd=root / "backend",
        env={**env, **(overrides or {})},
        check=True,
    )


run("-m", "ruff", "check", ".")
run("-m", "ruff", "format", "--check", ".")
run("manage.py", "check")
run("manage.py", "test", "core")
run(
    "manage.py",
    "spectacular",
    "--file",
    "../work/openapi-check.yaml",
    "--validate",
    "--fail-on-warn",
)
if (root / "work/openapi-check.yaml").read_text(encoding="utf-8") != (
    root / "docs/openapi.yaml"
).read_text(encoding="utf-8"):
    raise SystemExit("OpenAPI changed: regenerate and review docs/openapi.yaml")
run(
    "manage.py",
    "check",
    "--deploy",
    "--fail-level",
    "WARNING",
    overrides={
        "APP_ENV": "production",
        "DJANGO_CSRF_TRUSTED_ORIGINS": "https://suporte.empresa.example",
    },
)
print("Local backend checks passed. PostgreSQL integration requires Docker separately.")
