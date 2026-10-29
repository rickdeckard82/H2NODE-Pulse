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
    for name in ("api", "db", "worker", "migrate"):
        assert not services[name].get("ports"), f"Unexpected exposed port: {name}"
    ports = services["gateway"]["ports"]
    assert len(ports) == 1
    assert ports[0]["host_ip"] != "0.0.0.0"
    assert config["networks"]["private"]["internal"]
    assert services["api"]["read_only"]
    assert services["worker"]["read_only"]
    assert services["db"]["volumes"]
    for service in services.values():
        assert not service.get("image", "").endswith(":latest")
    print(f"Topology valid: {', '.join(files)}")


verify(["compose.yaml"])
verify(["compose.yaml", "compose.production.yaml"])
