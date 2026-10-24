"""Signed-out gap report (acquisition front door). Owned by W2. Contract: docs/CONTRACTS.md §7.4.

No auth for the report. Rate-limited to 5 reports per client IP per hour. Nothing is persisted
until a signed-in user claims it (POST /public/claim), which works with any sign-in method.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..ai.gateway import BudgetExceeded, ModelError
from ..core.interview_text import InputError
from ..core.job_fetch import JobFetchError, fetch_job_page
from ..core.jsonutil import JSONExtractionError
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..schemas_engagement import ClaimIn, ClaimOut, GapReportIn, JobUrlIn, JobUrlOut, PublicReport
from ..services import public_report as svc
from ..services import analytics

log = logging.getLogger("mindmesh.public")
router = APIRouter(prefix="/public", tags=["public"])


@router.post("/gap-report", response_model=PublicReport)
async def gap_report(body: GapReportIn, request: Request):
    ip = svc.request_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
    decision = svc.check_ip(ip)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "You've made several reports in the last hour. Please wait a while, or sign up to keep going.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    try:
        report = await run_in_threadpool(svc.build_report, svc.public_gateway(), body.resume_text, body.job_text)
    except InputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except BudgetExceeded as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc), headers={"Retry-After": "300"}) from exc
    except ModelError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is temporarily unavailable. Please try again shortly.") from exc
    except (JSONExtractionError, ValueError) as exc:
        log.warning("public gap report failed: %s", type(exc).__name__)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "We couldn't read those texts this time. Check both and try again.") from exc
    return PublicReport.model_validate(report)


@router.post("/job-from-url", response_model=JobUrlOut)
async def job_from_url(body: JobUrlIn, request: Request):
    """Fetch a job ad from a link so the visitor doesn't have to copy it. No model call; nothing stored."""
    ip = svc.request_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
    decision = svc.job_url_limiter.hit(f"job-url:{ip}")
    if not decision.allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "You've imported several links in the last hour. Paste the job ad text instead.",
                            headers={"Retry-After": str(decision.retry_after)})
    try:
        page = await run_in_threadpool(fetch_job_page, body.url)
    except JobFetchError as exc:
        log.info("job link import refused: %s", type(exc.__cause__).__name__ if exc.__cause__ else "rule")
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return JobUrlOut(text=page.text, title=page.title, company=page.company)


@router.post("/claim", response_model=ClaimOut)
def claim_report(body: ClaimIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Save a signed-out report to the signed-in user as a role prep. Single-use: a token works once."""
    prep_id = svc.claim(body.report_token, user.id, db)
    if prep_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That report has expired. Make a new one from the welcome page.")
    analytics.record(db, user, "gap_report_ready", {"source": "claim"})
    return ClaimOut(prep_id=prep_id)



@router.get("/shared-plans/{token}")
def shared_plan(token: str, request: Request, db: Session = Depends(get_db)):
    """A prep plan someone shared (read-only, no account). 404 for unknown, revoked or expired links."""
    from ..jobs import system_context
    from ..services import sharing

    ip = svc.request_ip(request.client.host if request.client else None, request.headers.get("x-forwarded-for"))
    if not svc.share_view_limiter.hit(f"share:{ip}").allowed:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests. Try again later.")
    with system_context():  # no user here: the unguessable token is the access check
        view = sharing.public_view(db, token)
        db.commit()
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link has expired or was turned off.")
    return view
