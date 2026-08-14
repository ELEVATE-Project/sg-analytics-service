from qdrant_client import QdrantClient
from ..core.config import settings

_client: QdrantClient | None = None


def get_qdrant_client() -> QdrantClient:
    """Returns a lazily-initialized Qdrant client configured from settings."""
    global _client
    if _client is None:
        _client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)
    return _client


class LazyQdrantClient:
    """Proxy so `from ..database.qdrant import qdrant_client` stays valid
    but the real connection is only opened on first attribute access."""
    def __getattr__(self, name):
        return getattr(get_qdrant_client(), name)


qdrant_client = LazyQdrantClient()
