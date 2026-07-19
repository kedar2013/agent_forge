"""A Temporal-backed durable-execution spine — deliberately separate from
`app.reliability` (that package's checkpointing resumes one ADK chat turn
via ADK's own resumability + Postgres; this orchestrates a genuinely
long-running, multi-step business process with real side effects, able to
survive a WORKER PROCESS crash between steps, not just an API-request
crash). See the module docstrings in `workflows.py`/`activities.py` for the
worked example (the same reservation-demo saga `app.reliability.
compensation` already proves in-process, now durably orchestrated).

Nothing in this package is imported by `app.main` — every module here (and
`temporalio` itself) is only ever imported lazily, from inside a request
handler or the standalone worker script, so a checkout that never installs
the `temporal` extra or sets TEMPORAL_ENABLED=true never needs any of it
to boot.
"""
