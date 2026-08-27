from __future__ import annotations

import asyncio


async def wait_for_event(event: asyncio.Event, *, timeout: float = 1) -> None:
    """Wait for a test-driver event with a bounded failure."""
    await asyncio.wait_for(event.wait(), timeout=timeout)
