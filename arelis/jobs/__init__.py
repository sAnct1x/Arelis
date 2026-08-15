"""Saved prompts that run unattended and mail you the answer."""

from arelis.jobs.store import (
    Job,
    JobError,
    delete_job,
    describe_days,
    get_job,
    load_jobs,
    make_job_id,
    normalize_days,
    normalize_time,
    record_run,
    save_jobs,
    upsert_job,
)

__all__ = [
    "Job",
    "JobError",
    "delete_job",
    "describe_days",
    "get_job",
    "load_jobs",
    "make_job_id",
    "normalize_days",
    "normalize_time",
    "record_run",
    "save_jobs",
    "upsert_job",
]
