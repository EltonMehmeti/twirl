from pathlib import Path
from typing import Protocol

from starlette.requests import Request


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> tuple[bytes, str] | None: ...
    def url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


def _content_type(key: str) -> str:
    return "image/webp" if key.endswith(".webp") else "application/octet-stream"


class LocalStorage:
    """Disk storage for development. Served by a static mount at /media."""

    def __init__(self, root: Path, base_url: str = "/media") -> None:
        self.root = Path(root).resolve()
        self.base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("storage key escapes the root")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> tuple[bytes, str] | None:
        path = self._path(key)
        return (path.read_bytes(), _content_type(key)) if path.is_file() else None

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


class MemoryStorage:
    """In-process storage for tests."""

    def __init__(self, base_url: str = "/media") -> None:
        self.base_url = base_url.rstrip("/")
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        return self.objects.get(key)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class S3Storage:
    """S3-compatible object storage (Neon Object Storage, Cloudflare R2). The app serves objects."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        region: str = "auto",
        base_url: str = "/media",
    ) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self.base_url = base_url.rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            # Neon Object Storage and R2 need path-style addressing and SigV4.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            CacheControl="public, max-age=31536000, immutable",
        )

    def get(self, key: str) -> tuple[bytes, str] | None:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey:
            return None
        return obj["Body"].read(), obj.get("ContentType") or _content_type(key)

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


def build_storage(settings) -> "Storage":
    if settings.storage_backend == "s3":
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            region=settings.s3_region,
        )
    if settings.storage_backend == "memory":
        return MemoryStorage()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    return LocalStorage(settings.media_root, "/media")


def get_storage(request: Request) -> Storage:
    return request.app.state.storage
