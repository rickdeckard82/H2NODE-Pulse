"""Stage-1 worker lifecycle; no notification processing before stage 5."""

import signal
import time
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Run infrastructure heartbeat (notification handlers not implemented yet)"

    def handle(self, *args, **options):
        stopping = False

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        heartbeat = Path("/tmp/pulse-worker-heartbeat")
        self.stdout.write("Worker foundation started; notification handlers not yet implemented.")
        while not stopping:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            heartbeat.touch()
            for _ in range(10):
                if stopping:
                    break
                time.sleep(1)
        heartbeat.unlink(missing_ok=True)
