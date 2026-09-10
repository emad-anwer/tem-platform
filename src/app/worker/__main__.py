"""Worker process entrypoint.

    python -m app.worker

Logging is configured before arq's event loop starts so the very first line
the process emits is structured JSON, not a bare print or a stdlib log record.

arq.run_worker() blocks until SIGTERM or SIGINT is received, then:
  1. Stops pulling new jobs from the queue.
  2. Waits for in-flight jobs to finish (up to ``job_timeout`` seconds).
  3. Calls ``WorkerSettings.on_shutdown``.
  4. Exits cleanly.

The compose.yaml ``stop_grace_period: 300s`` matches ``job_timeout`` so that
``docker compose stop worker`` gives the worker the full window to drain before
Docker escalates to SIGKILL.
"""

from arq import run_worker

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.worker.settings import WorkerSettings

if __name__ == "__main__":
    # Initialise logging before any other import side-effects emit records.
    settings = get_settings()
    setup_logging(settings.log_level)

    run_worker(WorkerSettings)
