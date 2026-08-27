from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from marimo_studio._server.development import routes as dev
from marimo_studio._server.development.coordinator import SourcePoll

from ..app_helpers import configured


def _payload(event: bytes) -> dict[str, object]:
    return cast(dict[str, object], json.loads(event.split(b"data: ", 1)[1]))


def test_view_catalog_change_publishes_current_presentation(
    notebook_path: Path,
) -> None:
    studio = configured(notebook_path)

    class Subscription:
        generation = 1

        def __init__(self) -> None:
            self.release_change = asyncio.Event()
            self._delivered = False

        async def poll(self) -> SourcePoll | None:
            if self._delivered:
                await asyncio.Future()
            await self.release_change.wait()
            self._delivered = True
            return SourcePoll(2, dev.SourceChange("views", ()))

        async def close(self) -> None:
            return

    subscription = Subscription()

    class Development:
        def __init__(self) -> None:
            self.publications: list[int] = []

        async def subscribe(
            self,
            _studio: object,
            view_name: str,
        ) -> Subscription:
            assert view_name == "dashboard"
            return subscription

        async def baseline(
            self,
            view_name: str,
            generation: int,
            _operation: object,
        ) -> dict[str, object]:
            assert (view_name, generation) == ("dashboard", 1)
            return {"schema": 1, "revision": "presentation-before"}

        async def project_catalog(
            self,
            _studio: object,
            view_name: str,
        ) -> SimpleNamespace:
            assert view_name == "dashboard"
            return SimpleNamespace(
                inspection=object(),
                input_id="input-dashboard",
                generation=1,
            )

        async def publish(
            self,
            view_name: str,
            generation: int,
            _operation: object,
            *,
            warmup: bool = False,
        ) -> tuple[dict[str, object], str, str]:
            assert (view_name, warmup) == ("dashboard", False)
            self.publications.append(generation)
            revision = (
                "presentation-before"
                if generation == 1
                else "presentation-after-catalog-change"
            )
            return (
                {"schema": 1, "profile": "development", "phase": "ready"},
                revision,
                "artifact-current",
            )

    async def exercise() -> tuple[list[int], list[dict[str, object]]]:
        development = Development()
        stream = dev.change_events(
            studio,
            view_name="dashboard",
            development=cast(Any, development),
        )
        try:
            ready = _payload(await anext(stream))
            assert ready["revision"] == "presentation-before"
            initial_build = _payload(await anext(stream))
            assert initial_build["kind"] == "build"
            assert initial_build["revision"] == "presentation-before"

            subscription.release_change.set()
            events: list[dict[str, object]] = []
            while not any(event["kind"] == "presentation" for event in events):
                events.append(_payload(await anext(stream)))
            return development.publications, events
        finally:
            await stream.aclose()

    publications, events = asyncio.run(exercise())

    assert publications == [1, 2]
    assert events[0]["kind"] == "views"
    assert any(
        event["kind"] == "build"
        and event.get("revision") == "presentation-after-catalog-change"
        for event in events
    )
    assert events[-1]["revision"] == "presentation-after-catalog-change"
