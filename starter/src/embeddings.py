"""Choose a real embedding provider (API or local) and implement this contract."""
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


class MyEmbedder:
    """OpenAI embeddings adapter. Errors from the API are raised, never replaced by mock vectors.

    Queries and documents are embedded the same way (OpenAI models need no query/document prefix).
    Reads OPENAI_API_KEY from the environment.
    """

    _KNOWN_DIMENSIONS = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}
    _BATCH_SIZE = 100

    def __init__(self, model_name: str) -> None:
        if not model_name:
            raise ValueError("EMBEDDING_MODEL is empty; set it in starter/.env")
        from openai import OpenAI  # imported here so other modules do not require the SDK

        self.model_name = model_name
        self._client = OpenAI()  # raises if OPENAI_API_KEY is missing
        self.total_tokens = 0
        known = self._KNOWN_DIMENSIONS.get(model_name)
        self.dimensions = known if known else len(self._embed(["dimension probe"])[0])

    def _embed(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self._BATCH_SIZE):
            batch = texts[start:start + self._BATCH_SIZE]
            response = self._client.embeddings.create(model=self.model_name, input=batch)
            self.total_tokens += response.usage.total_tokens
            vectors.extend(item.embedding for item in sorted(response.data, key=lambda d: d.index))
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._embed(texts)
        if len(vectors) != len(texts) or any(len(v) != self.dimensions for v in vectors):
            raise RuntimeError("embedding API returned an unexpected number or size of vectors")
        return vectors

    def embed_query(self, question: str) -> list[float]:
        return self.embed_documents([question])[0]
