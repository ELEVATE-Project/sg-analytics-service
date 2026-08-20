from qdrant_client import QdrantClient
from qdrant_client import AsyncQdrantClient
from ..core.config import settings

_client: QdrantClient | None = None
_async_client: AsyncQdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Returns a lazily-initialized synchronous Qdrant client configured from settings."""
    global _client
    if _client is None:
        _client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    return _client


def get_async_qdrant_client() -> AsyncQdrantClient:
    """Returns a lazily-initialized async Qdrant client configured from settings."""
    global _async_client
    if _async_client is None:
        _async_client = AsyncQdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=20.0)
    return _async_client


class LazyQdrantClient:
    """Proxy so `from ..database.qdrant import qdrant_client` stays valid
    but the real connection is only opened on first attribute access."""
    def __getattr__(self, name):
        return getattr(get_qdrant_client(), name)


qdrant_client = LazyQdrantClient()
