from qdrant_client import QdrantClient
from ..config import settings

def get_qdrant_client() -> QdrantClient:
    """Returns a Qdrant client configured from settings."""
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

# Create a global instance that can be imported
qdrant_client = get_qdrant_client()
