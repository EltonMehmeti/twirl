from pathlib import Path
from typing import Protocol

from starlette.requests import Request


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Disk storage for development and the pilot. Swap for an R2 implementation later."""

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

    def url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)


def get_storage(request: Request) -> Storage:
    return request.app.state.storage
