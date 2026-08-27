from __future__ import annotations

import asyncio
import shutil
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import tomlkit

from marimo_studio._server.development import source_changes
from marimo_studio._server.development.coordinator import DevelopmentCoordinator
from marimo_studio._workspace import load_studio
from marimo_studio.errors._internal import ViewDeletionInProgress
from marimo_studio.view_providers._host import provider_registry

from ..app_helpers import created_one_view
from ..source_change_test_support import next_source


@pytest.mark.parametrize("active", (True, False), ids=("active", "idle"))
def test_committed_deletion_evicts_monitor_before_provider_recreation(
    notebook_path: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active: bool,
) -> None:
    studio = created_one_view(notebook_path)
    project = studio.views["dashboard"]
    manifest = tomlkit.parse(project.manifest.read_text(encoding="utf-8"))
    manifest["provider"] = "third-party/old"
    project.manifest.write_text(tomlkit.dumps(manifest), encoding="utf-8")
    old_studio = load_studio(studio.notebook)
    old_project = old_studio.views["dashboard"]
    replacement = tmp_path / "replacement-dashboard"
    shutil.copytree(old_project.root, replacement)

    builtin = provider_registry().get("marimo-studio/vanilla")

    class Provider:
        def __init__(self) -> None:
            self.inspections = 0
            self.inspected = threading.Event()

        def inspect(self, selected: Any) -> Any:
            self.inspections += 1
            self.inspected.set()
            return builtin.inspect(
                replace(
                    selected,
                    project=replace(
                        selected.project,
                        provider="marimo-studio/vanilla",
                    ),
                )
            )

        def provenance(self, inspection: Any) -> Any:
            return builtin.provenance(inspection)

    old_provider = Provider()
    new_provider = Provider()
    registry = SimpleNamespace(
        get=lambda provider_id: (
            old_provider if provider_id == "third-party/old" else new_provider
        ),
        validate_project=lambda project: project,
    )
    monkeypatch.setattr(source_changes, "provider_registry", lambda: registry)

    async def exercise() -> None:
        coordinator = DevelopmentCoordinator(interval=60)
        subscription = await coordinator.subscribe(old_studio, "dashboard")
        try:
            assert await asyncio.to_thread(old_provider.inspected.wait, 1)
            if not active:
                await subscription.close()
            old_inspections = old_provider.inspections

            async with coordinator.deleting_view("dashboard") as deletion:
                shutil.rmtree(old_project.root)
                shutil.copytree(replacement, old_project.root)
                recreated_manifest = tomlkit.parse(
                    old_project.manifest.read_text(encoding="utf-8")
                )
                recreated_manifest["provider"] = "third-party/new"
                old_project.manifest.write_text(
                    tomlkit.dumps(recreated_manifest),
                    encoding="utf-8",
                )
                deletion.commit()

            current = load_studio(studio.notebook)
            catalog = await coordinator.project_catalog(current, "dashboard")
            assert catalog.project.provider == "third-party/new"
            assert old_provider.inspections == old_inspections
            assert new_provider.inspections >= 1

            if active:
                replacement_subscription = await coordinator.subscribe(
                    current,
                    "dashboard",
                )
                await subscription.close()
                recreated = current.views["dashboard"].root / "index.html"
                recreated.write_text(
                    recreated.read_text(encoding="utf-8") + "\n",
                    encoding="utf-8",
                )
                change = await asyncio.wait_for(
                    next_source(replacement_subscription),
                    timeout=2,
                )
                assert change.change.kind == "project"
                await replacement_subscription.close()
        finally:
            await subscription.close()
            await coordinator.close()

    asyncio.run(exercise())


def test_completed_source_constructor_is_superseded_by_deletion(
    notebook_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    studio = created_one_view(notebook_path)

    async def exercise() -> ViewDeletionInProgress:
        coordinator = DevelopmentCoordinator(interval=60)
        claim = coordinator._claim_source_creation
        claim_started = asyncio.Event()
        release_claim = asyncio.Event()
        deletion_started = asyncio.Event()
        release_deletion = asyncio.Event()

        async def blocked_claim(view_name: Any, creation: Any, producer: Any) -> Any:
            claim_started.set()
            await release_claim.wait()
            return await claim(view_name, creation, producer)

        monkeypatch.setattr(coordinator, "_claim_source_creation", blocked_claim)
        pending = asyncio.create_task(coordinator.subscribe(studio, "dashboard"))
        await asyncio.wait_for(claim_started.wait(), timeout=2)

        async def remove() -> None:
            async with coordinator.deleting_view("dashboard"):
                deletion_started.set()
                await release_deletion.wait()

        deletion = asyncio.create_task(remove())
        await asyncio.wait_for(deletion_started.wait(), timeout=2)
        release_claim.set()
        try:
            with pytest.raises(ViewDeletionInProgress) as captured:
                await pending
            return captured.value
        finally:
            release_deletion.set()
            await deletion
            await coordinator.close()

    error = asyncio.run(exercise())

    assert error.code == "view-deletion-in-progress"
    assert error.status_code == 409
    assert error.transient
    assert error.diagnostic_details() == {"view": "dashboard"}
