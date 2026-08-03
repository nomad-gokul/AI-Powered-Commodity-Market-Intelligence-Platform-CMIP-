"""HTTP routes for document upload, retrieval, deletion, and reprocessing,
plus the signed-URL file-serving route used by LocalStorageProvider."""

import math
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import ApiResponse, PageMeta, PaginatedResponse
from app.core.config import get_settings
from app.core.database import get_db_session
from app.core.exceptions import NotFoundError, UnauthorizedError
from app.modules.audit.repository import AuditLogRepository
from app.modules.audit.service import AuditService
from app.modules.auth.dependencies import get_current_user, require_permission
from app.modules.auth.models import User
from app.modules.documents.domain import UploadValidator
from app.modules.documents.models import StorageProviderKind
from app.modules.documents.queue import JobQueue
from app.modules.documents.repository import (
    DocumentRepository,
    DocumentVersionRepository,
    ProcessingJobRepository,
)
from app.modules.documents.schemas import (
    DocumentDetailRead,
    DocumentRead,
    ProcessingJobRead,
    UploadResponse,
)
from app.modules.documents.security.signing import verify_storage_key_signature
from app.modules.documents.security.virus_scan import NullVirusScanner
from app.modules.documents.service import DocumentService
from app.modules.documents.storage.factory import get_storage_provider

router = APIRouter(prefix="/documents", tags=["Documents"])
jobs_router = APIRouter(prefix="/processing-jobs", tags=["Processing Jobs"])


async def _iter_upload_file(
    file: UploadFile, *, chunk_size: int = 1024 * 1024
) -> AsyncIterator[bytes]:
    while chunk := await file.read(chunk_size):
        yield chunk


def get_document_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    request: Request,
) -> DocumentService:
    settings = get_settings()
    job_queue: JobQueue = request.app.state.arq_pool
    return DocumentService(
        document_repo=DocumentRepository(session),
        version_repo=DocumentVersionRepository(session),
        job_repo=ProcessingJobRepository(session),
        audit_service=AuditService(AuditLogRepository(session)),
        storage=get_storage_provider(),
        storage_provider_kind=StorageProviderKind(settings.storage_provider),
        job_queue=job_queue,
        upload_validator=UploadValidator(
            allowed_extensions=settings.upload_allowed_extensions,
            max_file_size_bytes=settings.upload_max_file_size_bytes,
        ),
        virus_scanner=NullVirusScanner(),
        max_documents_per_user=settings.upload_max_documents_per_user,
        signed_url_expire_seconds=settings.storage_signed_url_expire_seconds,
        processing_max_retries=settings.processing_max_retries,
    )


@router.post(
    "/upload",
    response_model=ApiResponse[UploadResponse],
    status_code=201,
    dependencies=[Depends(require_permission("documents:upload"))],
)
async def upload_document(
    service: Annotated[DocumentService, Depends(get_document_service)],
    current_user: Annotated[User, Depends(get_current_user)],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[UploadResponse]:
    document, job = await service.upload(
        uploaded_by=current_user.id,
        original_filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        stream=_iter_upload_file(file),
    )
    return ApiResponse(
        data=UploadResponse(
            document=DocumentRead.model_validate(document),
            job=ProcessingJobRead.model_validate(job),
        )
    )


@router.get(
    "",
    response_model=PaginatedResponse[DocumentRead],
    dependencies=[Depends(require_permission("documents:read"))],
)
async def list_documents(
    service: Annotated[DocumentService, Depends(get_document_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[DocumentRead]:
    documents, total = await service.list_documents(
        uploaded_by=None, offset=(page - 1) * page_size, limit=page_size
    )
    return PaginatedResponse(
        data=[DocumentRead.model_validate(d) for d in documents],
        meta=PageMeta(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=max(1, math.ceil(total / page_size)),
        ),
    )


@router.get("/files/{key}")
async def download_signed_file(key: str, expires: int, signature: str) -> StreamingResponse:
    """Serves a LocalStorageProvider object given a valid HMAC-signed URL
    (see storage/local.py's signed_url()). Deliberately not gated by
    require_permission/a bearer token - the signature itself is the
    authorization, the same trust model as an S3 presigned URL."""
    settings = get_settings()
    if not verify_storage_key_signature(key, expires, signature, secret=settings.jwt_secret_key):
        raise UnauthorizedError("Invalid or expired download link")
    storage = get_storage_provider()
    if not await storage.exists(key):
        raise NotFoundError("File not found")
    return StreamingResponse(storage.stream_download(key), media_type="application/octet-stream")


@router.get(
    "/{document_id}",
    response_model=ApiResponse[DocumentDetailRead],
    dependencies=[Depends(require_permission("documents:read"))],
)
async def get_document(
    document_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[DocumentDetailRead]:
    document = await service.get_document(document_id)
    download_url = await service.get_download_url(document)
    detail = DocumentDetailRead(
        **DocumentRead.model_validate(document).model_dump(), download_url=download_url
    )
    return ApiResponse(data=detail)


@router.delete(
    "/{document_id}",
    status_code=204,
    dependencies=[Depends(require_permission("documents:delete"))],
)
async def delete_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> None:
    await service.delete_document(document_id, deleted_by=current_user.id)


@router.post(
    "/{document_id}/reprocess",
    response_model=ApiResponse[ProcessingJobRead],
    status_code=202,
    dependencies=[Depends(require_permission("documents:reprocess"))],
)
async def reprocess_document(
    document_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[ProcessingJobRead]:
    job = await service.reprocess_document(document_id, requested_by=current_user.id)
    return ApiResponse(data=ProcessingJobRead.model_validate(job))


@jobs_router.get(
    "/{job_id}",
    response_model=ApiResponse[ProcessingJobRead],
    dependencies=[Depends(require_permission("documents:read"))],
)
async def get_processing_job(
    job_id: uuid.UUID,
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> ApiResponse[ProcessingJobRead]:
    job = await service.get_job(job_id)
    return ApiResponse(data=ProcessingJobRead.model_validate(job))
