# Worker package.
#
# Entry points:
#   python -m app.worker          — run the arq worker process
#
# Job context is established by @tenant_job (app.core.auth.job_context),
# which also sets the Principal contextvar and resets both in a finally.
# There is intentionally no second helper for this.
