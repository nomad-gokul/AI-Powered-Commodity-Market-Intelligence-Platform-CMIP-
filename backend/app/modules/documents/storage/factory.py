"""Selects the configured StorageProvider. The rest of the app never
constructs LocalStorageProvider/S3StorageProvider directly - this is the
single place STORAGE_PROVIDER is read."""

from functools import lru_cache

from app.core.config import Settings, get_settings
from app.modules.documents.models import StorageProviderKind
from app.modules.documents.storage.base import StorageProvider
from app.modules.documents.storage.local import LocalStorageProvider
from app.modules.documents.storage.s3 import S3StorageProvider


def build_storage_provider(settings: Settings) -> StorageProvider:
    provider = StorageProviderKind(settings.storage_provider)
    if provider is StorageProviderKind.LOCAL:
        return LocalStorageProvider(
            root_dir=settings.storage_local_root, signing_secret=settings.jwt_secret_key
        )
    if provider is StorageProviderKind.S3:
        return S3StorageProvider(
            bucket=settings.storage_s3_bucket,
            region=settings.storage_s3_region,
            endpoint_url=settings.storage_s3_endpoint_url,
            access_key_id=settings.storage_s3_access_key_id,
            secret_access_key=settings.storage_s3_secret_access_key,
        )
    raise ValueError(f"Unsupported storage provider: {provider}")


@lru_cache
def get_storage_provider() -> StorageProvider:
    return build_storage_provider(get_settings())
