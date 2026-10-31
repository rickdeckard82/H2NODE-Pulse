"""Generate local development configuration without overwriting existing secrets."""

import base64
import secrets
import shutil
from pathlib import Path

root = Path(__file__).resolve().parent.parent
folder = root / "secrets"
folder.mkdir(mode=0o700, exist_ok=True)
for name in (
    "postgres_password",
    "postgres_admin_password",
    "postgres_runtime_password",
    "django_secret_key",
    "identity_key",
):
    path = folder / f"{name}.txt"
    if not path.exists():
        with path.open("x", encoding="utf-8") as stream:
            stream.write(
                base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
                if name == "identity_key"
                else secrets.token_urlsafe(64)
            )
        # Directory 0700 protects host access. Mounted files must be readable by
        # non-root runtime UIDs; local Compose does not remap bind-secret ownership.
        path.chmod(0o444)
if not (root / ".env").exists():
    shutil.copyfile(root / ".env.example", root / ".env")
print("Configuration ready. Secrets preserved; no secret values printed.")
