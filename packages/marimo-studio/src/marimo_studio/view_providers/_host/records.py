"""Records owned by installed provider discovery and conformance."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderProvenance:
    """Identify the installed provider code used for one publication."""

    key: str
    distribution: str
    version: str
    api_version: int
    build_fingerprint: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "distribution": self.distribution,
            "version": self.version,
            "api_version": self.api_version,
            "build_fingerprint": self.build_fingerprint,
        }
