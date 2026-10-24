"""Registers the `jobs` table with db.load_all_models(). The model lives in app/jobs.py (workstream F)."""
from .jobs import Job

__all__ = ["Job"]
