"""Check rendered Compose topology without printing environment or secrets."""

import json
import subprocess


def verify(files):
    command = ["docker", "compose"]
    for file in files:
        command.extend(["-f", file])
    command.extend(["config", "--format", "json"])
    config = json.loads(subprocess.check_output(command))
    services = config["services"]
    for name in ("api", "db", "worker", "migrate", "db-permissions", "antimalware"):
        assert not services[name].get("ports"), f"Unexpected exposed port: {name}"
    ports = services["gateway"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] != "0.0.0.0"
    assert config["networks"]["private"]["internal"]
    assert services["api"]["read_only"]
    assert services["worker"]["read_only"]
    assert services["db"]["volumes"]
    for name in ("api", "worker"):
        assert services[name]["environment"]["POSTGRES_USER"] == "pulse_runtime"
        assert services[name]["environment"]["BOOTSTRAP_ADMIN_ENABLED"] == "false"
        assert services[name]["environment"]["BOOTSTRAP_ADMIN_PASSWORD"] == ""
        assert "postgres_password" not in {
            s["source"] for s in services[name]["secrets"]
        }
        assert "postgres_admin_password" not in {
            s["source"] for s in services[name]["secrets"]
        }
    assert services["migrate"]["environment"]["POSTGRES_USER"] == "pulse"
    for service in services.values():
        assert not service.get("image", "").endswith(":latest")
    print(f"Topology valid: {', '.join(files)}")


verify(["compose.yaml"])
verify(["compose.yaml", "compose.production.yaml"])
