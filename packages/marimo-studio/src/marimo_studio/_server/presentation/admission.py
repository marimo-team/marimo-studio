"""Carry one signed native-session expectation to Marimo's connector."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

NATIVE_SESSION_ADMISSION_SCOPE_KEY = "marimo_studio.native_session_admission"


@dataclass
class NativeSessionAdmission:
    expected_claim: object | None
    file_key: str
    mode: Literal["fresh", "current"]
    notebook: str
    runtime_session_id: str
    binding_current: Callable[[], bool] | None = None
    on_accept: Callable[[object], None] | None = None
    on_reject: Callable[[], None] | None = None
    on_close: Callable[[], asyncio.Task[None] | None] | None = None
    lifetime_owner: object | None = None
    replay_on_reconnect: bool = False
    force_reject_binding: bool = False
    rejected: bool = False
    settled: bool = False
