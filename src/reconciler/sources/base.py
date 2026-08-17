from typing import Protocol

from reconciler.models import SourceName, SourceQueryResult


class Source(Protocol):
    name: SourceName

    async def query(self, skus: list[str]) -> SourceQueryResult: ...
