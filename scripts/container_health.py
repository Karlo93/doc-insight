"""HTTP liveness, consumer heartbeat, or relay process liveness inside a container."""

import os
import socket
from pathlib import Path
from urllib.request import urlopen


def check() -> None:
    app = os.environ["DI_CONTAINER_APP"]
    if app == "worker":
        from redis import Redis

        with Redis.from_url(os.environ["DI_REDIS_URL"], socket_timeout=3) as client:
            if client.ttl(f"di:worker:{socket.gethostname()}") <= 0:
                raise RuntimeError("Worker heartbeat expired")
    elif os.environ.get("DI_CONTAINER_ROLE") == "relay":
        # The relay has no HTTP/heartbeat contract; this is liveness only.
        if b"relay" not in Path("/proc/1/cmdline").read_bytes().split(b"\0"):
            raise RuntimeError("Relay process is absent")
    else:
        port = {"gateway": 8000, "ingest": 8001, "query": 8002}[app]
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=3) as response:  # nosec B310
            if response.status != 200:
                raise RuntimeError("HTTP process is unhealthy")


if __name__ == "__main__":
    check()
