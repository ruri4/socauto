"""Versioned asynchronous job management endpoints."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlmodel import Session

from socauto.api.errors import ErrorResponse, api_error
from socauto.api.schemas.jobs import JobCreate, JobListResponse, JobResponse, JobRetry
from socauto.db.claims import LostClaimError, cancel_job
from socauto.db.engine import get_request_session
from socauto.db.jobs import DuplicateJobError, InvalidJobTransitionError, JobConflictError
from socauto.db.models import JobState
from socauto.services.accounts import AccountNotFoundError
from socauto.services.jobs import (
    AccountUnavailableError,
    JobNotFoundError,
    RetryConfirmationRequiredError,
    get_job,
    list_jobs,
    retry_job,
    submit_job,
)

router = APIRouter(
    prefix="/v1/jobs",
    tags=["jobs"],
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
Database = Annotated[Session, Depends(get_request_session)]


@contextmanager
def _job_errors() -> Iterator[None]:
    try:
        yield
    except JobNotFoundError:
        raise api_error(404, "job_not_found", "Job not found") from None
    except AccountNotFoundError:
        raise api_error(404, "account_not_found", "Account not found") from None
    except AccountUnavailableError:
        raise api_error(
            409, "account_unavailable", "An active TikTok account is required"
        ) from None
    except DuplicateJobError as error:
        raise api_error(
            409,
            "duplicate_job",
            "A job already exists for this destination and URL",
            existing_job_id=str(error.existing_job_id),
        ) from None
    except RetryConfirmationRequiredError:
        raise api_error(
            409,
            "duplicate_risk_acknowledgement_required",
            "Review TikTok before retrying; acknowledge_duplicate_risk must be true",
        ) from None
    except InvalidJobTransitionError:
        raise api_error(
            409, "invalid_job_state", "The job state does not allow this operation"
        ) from None
    except JobConflictError, LostClaimError:
        raise api_error(
            409, "job_changed", "Job changed concurrently; refresh before retrying"
        ) from None


@router.post("", response_model=JobResponse, status_code=202)
def create(request: JobCreate, response: Response, db: Database) -> JobResponse:
    """Queue one X video for private TikTok publication. No upstream work runs in this request."""
    with _job_errors():
        job = submit_job(
            db,
            source_url=request.source_url,
            destination_account_id=request.destination_account_id,
            caption_override=request.caption_override,
        )
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return JobResponse.model_validate(job)


@router.get("", response_model=JobListResponse)
def listing(
    db: Database,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    state: JobState | None = None,
    destination_account_id: UUID | None = None,
) -> JobListResponse:
    """Newest first, with ID tie-breaking; total uses the same optional filters."""
    jobs, total = list_jobs(
        db, offset=offset, limit=limit, state=state, destination_account_id=destination_account_id
    )
    return JobListResponse(
        items=[JobResponse.model_validate(job) for job in jobs],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/{job_id}", response_model=JobResponse)
def detail(job_id: UUID, db: Database) -> JobResponse:
    with _job_errors():
        return JobResponse.model_validate(get_job(db, job_id))


@router.post("/{job_id}/retry", response_model=JobResponse, status_code=202)
def retry(
    job_id: UUID,
    response: Response,
    db: Database,
    request: JobRetry | None = None,
) -> JobResponse:
    """Requeue a failed job, reusing retained media. Unknown outcomes require explicit consent."""
    with _job_errors():
        job = retry_job(
            db,
            job_id,
            acknowledge_duplicate_risk=(request.acknowledge_duplicate_risk if request else False),
        )
    response.headers["Location"] = f"/v1/jobs/{job.id}"
    return JobResponse.model_validate(job)


@router.delete("/{job_id}", response_model=JobResponse, responses={202: {"model": JobResponse}})
def cancel(job_id: UUID, response: Response, db: Database) -> JobResponse:
    """Cancel, do not delete history. A running download drains; uploading/posted jobs conflict."""
    with _job_errors():
        try:
            job = cancel_job(db, job_id)
        except LookupError:
            raise JobNotFoundError from None
    response.status_code = 202 if job.state is JobState.DOWNLOADING else 200
    return JobResponse.model_validate(job)
