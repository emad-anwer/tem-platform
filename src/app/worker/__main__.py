"""Run the arq worker process."""

from arq import run_worker

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.worker.settings import WorkerSettings

if __name__ == "__main__":
    # Initialise logging before any other import side-effects emit records.
    settings = get_settings()
    setup_logging(settings.log_level)

    run_worker(WorkerSettings)
