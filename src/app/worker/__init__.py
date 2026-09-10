# Worker package.
#
# Entry points:
#   python -m app.worker          — run the arq worker process
#
# Public surface (used by job modules):
#   from app.worker.context import bind_job_context, clear_job_context
