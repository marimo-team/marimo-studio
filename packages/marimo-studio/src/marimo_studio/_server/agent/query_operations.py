"""Per-binding query operation ordering and idempotency state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QueryOperationStatus(str, Enum):
    NEW = "new"
    PENDING = "pending"
    COMMITTED = "committed"
    SUPERSEDED = "superseded"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class QueryOperationClaim:
    client_id: str
    session_id: str
    binding_generation: int
    operation_id: str
    fingerprint: str
    query_generation: int
    status: QueryOperationStatus


@dataclass(frozen=True)
class _QueryOperation:
    fingerprint: str
    query_generation: int


@dataclass
class QueryOperationState:
    highest_generation: int = -1
    active: set[tuple[str, int, int]] = field(default_factory=set)
    pending: dict[str, _QueryOperation] = field(default_factory=dict)
    released: dict[str, _QueryOperation] = field(default_factory=dict)
    committed: dict[str, _QueryOperation] = field(default_factory=dict)

    def reset(self) -> None:
        self.highest_generation = -1
        self.active.clear()
        self.pending.clear()
        self.released.clear()
        self.committed.clear()

    def claim(
        self,
        *,
        client_id: str,
        session_id: str,
        binding_generation: int,
        operation_id: str,
        fingerprint: str,
        query_generation: int,
    ) -> QueryOperationClaim:
        requested = _QueryOperation(fingerprint, query_generation)
        committed = self.committed.get(operation_id)
        if committed is not None:
            return self._claim(
                client_id,
                session_id,
                binding_generation,
                operation_id,
                requested,
                (
                    QueryOperationStatus.COMMITTED
                    if committed == requested
                    else QueryOperationStatus.CONFLICT
                ),
            )
        pending = self.pending.get(operation_id)
        if pending is not None:
            return self._claim(
                client_id,
                session_id,
                binding_generation,
                operation_id,
                requested,
                (
                    QueryOperationStatus.PENDING
                    if pending == requested
                    else QueryOperationStatus.CONFLICT
                ),
            )
        released = self.released.get(operation_id)
        if released is not None:
            if released != requested:
                return self._claim(
                    client_id,
                    session_id,
                    binding_generation,
                    operation_id,
                    requested,
                    QueryOperationStatus.CONFLICT,
                )
            self.released.pop(operation_id)
            if query_generation < self.highest_generation:
                self._retain(self.committed, operation_id, released)
                return self._claim(
                    client_id,
                    session_id,
                    binding_generation,
                    operation_id,
                    requested,
                    QueryOperationStatus.SUPERSEDED,
                )
            self.pending[operation_id] = released
            return self._claim(
                client_id,
                session_id,
                binding_generation,
                operation_id,
                requested,
                QueryOperationStatus.NEW,
            )
        if query_generation < self.highest_generation:
            self._retain(self.committed, operation_id, requested)
            return self._claim(
                client_id,
                session_id,
                binding_generation,
                operation_id,
                requested,
                QueryOperationStatus.SUPERSEDED,
            )
        if query_generation == self.highest_generation:
            return self._claim(
                client_id,
                session_id,
                binding_generation,
                operation_id,
                requested,
                QueryOperationStatus.CONFLICT,
            )
        self.highest_generation = query_generation
        self.pending[operation_id] = requested
        return self._claim(
            client_id,
            session_id,
            binding_generation,
            operation_id,
            requested,
            QueryOperationStatus.NEW,
        )

    def commit(self, claim: QueryOperationClaim) -> bool:
        operation = _QueryOperation(claim.fingerprint, claim.query_generation)
        if (
            claim.status is not QueryOperationStatus.NEW
            or self.pending.get(claim.operation_id) != operation
        ):
            self.release(claim)
            return False
        self.pending.pop(claim.operation_id)
        self._retain(self.committed, claim.operation_id, operation)
        return True

    def release(self, claim: QueryOperationClaim) -> None:
        operation = _QueryOperation(claim.fingerprint, claim.query_generation)
        if (
            claim.status is QueryOperationStatus.NEW
            and self.pending.get(claim.operation_id) == operation
        ):
            self.pending.pop(claim.operation_id)
            self._retain(self.released, claim.operation_id, operation)

    def acquire(self, claim: QueryOperationClaim) -> bool:
        identity = self.identity(claim)
        if (
            claim.status is not QueryOperationStatus.NEW
            or self.pending.get(claim.operation_id)
            != _QueryOperation(claim.fingerprint, claim.query_generation)
            or identity in self.active
        ):
            return False
        self.active.add(identity)
        return True

    def finish(self, claim: QueryOperationClaim) -> None:
        self.active.discard(self.identity(claim))

    @staticmethod
    def identity(claim: QueryOperationClaim) -> tuple[str, int, int]:
        return (
            claim.operation_id,
            claim.binding_generation,
            claim.query_generation,
        )

    @staticmethod
    def _claim(
        client_id: str,
        session_id: str,
        binding_generation: int,
        operation_id: str,
        operation: _QueryOperation,
        status: QueryOperationStatus,
    ) -> QueryOperationClaim:
        return QueryOperationClaim(
            client_id=client_id,
            session_id=session_id,
            binding_generation=binding_generation,
            operation_id=operation_id,
            fingerprint=operation.fingerprint,
            query_generation=operation.query_generation,
            status=status,
        )

    @staticmethod
    def _retain(
        operations: dict[str, _QueryOperation],
        operation_id: str,
        operation: _QueryOperation,
    ) -> None:
        operations.pop(operation_id, None)
        operations[operation_id] = operation
        if len(operations) > 256:
            oldest = next(iter(operations))
            operations.pop(oldest)
