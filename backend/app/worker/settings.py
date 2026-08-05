"""ARQ worker process entrypoint: `arq app.worker.settings.WorkerSettings`.

max_tries is set generously high (well above any realistic
processing_max_retries) so ARQ's own retry ceiling never fires before our
own DB-tracked retry policy in worker/tasks.py does - see that module's
docstring for why retry/backoff/give-up is owned there, not here.
"""

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

# A standalone `arq` process only imports what this module's chain pulls
# in - unlike the API process (which imports every module's router/models
# via app.main) or the test suite (where many modules are already loaded
# in the same process). Document.uploaded_by is a ForeignKey("users.id"),
# so SQLAlchemy needs auth.models registered on Base.metadata before any
# query runs, or FK resolution fails with "could not find table 'users'"
# the first time a worker process actually queries a Document - a real,
# reproducible failure caught by running the real docker-compose stack,
# not a theoretical concern. Mirrors alembic/env.py's same requirement.
from app.modules.audit import models as audit_models  # noqa: F401
from app.modules.auth import models as auth_models  # noqa: F401
from app.worker.context import build_worker_context
from app.worker.tasks import (
    generate_embeddings_task,
    process_document,
    run_extraction,
    run_graph_rebuild,
    run_trust_pipeline,
)

logger = get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging()
    ctx.update(build_worker_context())
    logger.info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("worker_stopped")


class WorkerSettings:
    functions = [
        process_document,
        run_extraction,
        run_trust_pipeline,
        run_graph_rebuild,
        generate_embeddings_task,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 25
    # 1800s (30min): generous enough to cover run_extraction's worst case
    # (entity_extraction/table_extraction each individually budget up to
    # 900s - see pipeline.py) as well as process_document's ingestion run.
    job_timeout = 1800
