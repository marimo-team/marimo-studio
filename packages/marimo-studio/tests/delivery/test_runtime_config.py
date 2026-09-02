"""Protect the shared Python and browser runtime configuration contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marimo_studio._delivery.runtime_config import (
    RuntimeConfigInputs,
    encode_runtime_config,
    runtime_projection_revision,
)
from marimo_studio._projections.resolution import projection_policy
from marimo_studio.errors import RuntimeConfigTooLargeError

_FIXTURE = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "protocol"
    / "fixtures"
    / "runtime-config.json"
)

pytestmark = pytest.mark.supported_python


def test_runtime_config_budget_counts_encoded_utf8_bytes() -> None:
    value = {"label": "Zürich"}
    encoded = encode_runtime_config(value, max_bytes=1_024)
    encoded_size = len(encoded)

    assert encode_runtime_config(value, max_bytes=encoded_size) == encoded

    with pytest.raises(RuntimeConfigTooLargeError) as raised:
        encode_runtime_config(value, max_bytes=encoded_size - 1)

    assert raised.value.size == encoded_size
    assert raised.value.limit == encoded_size - 1


def test_runtime_config_matches_the_browser_protocol_fixture() -> None:
    inputs = RuntimeConfigInputs(
        view="dashboard",
        views=("dashboard", "executive"),
        runtime_id="server",
        runtime_instance="server-instance",
        runtime_data={"url": "/proxy/app/"},
        root_url="/proxy/app/",
        public_root_url="/proxy/app/",
        document_root_url="/proxy/app/",
        support_url="/proxy/app/_marimo-studio/views/dashboard",
        projection_revision="a" * 64,
        show_cell_logs=True,
        projection_targets={
            "cells": {
                "result": {
                    "status": "ready",
                    "producer": "cell:v1:result",
                    "dependencyClosure": ["cell:v1:result"],
                }
            },
            "variables": {},
        },
        mounts=(
            {
                "id": "site:result",
                "kind": "cell",
                "source": {
                    "path": "src/index.html",
                    "line": 12,
                    "column": 5,
                },
                "allowedTargets": ["result"],
            },
        ),
        projection_policy=projection_policy(),
        runtime_cell_refs={"cell:v1:result": "runtime-result"},
        diagnostics=(
            {
                "code": "cell-not-found",
                "severity": "error",
                "message": "Cell 'summary' is unavailable.",
                "hint": "Restore the cell or update the view.",
                "view": "dashboard",
                "projection": "cell",
                "target": "summary",
                "source": {
                    "path": "src/index.html",
                    "line": 18,
                    "column": 7,
                },
            },
        ),
        app_config={"width": "medium"},
        user_config={"display": {"theme": "system"}},
        config_overrides={},
        dev=True,
        mode="edit",
    )

    expected = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    assert inputs.to_dict(revision="presentation-revision") == expected


def test_runtime_config_exposes_only_embedded_runtime_settings() -> None:
    inputs = RuntimeConfigInputs(
        view="dashboard",
        views=("dashboard",),
        runtime_id="wasm",
        runtime_instance="runtime-instance",
        runtime_data={},
        root_url="./",
        public_root_url="./",
        document_root_url="./",
        support_url="./_marimo-studio/views/dashboard",
        projection_revision="a" * 64,
        show_cell_logs=False,
        projection_targets={"cells": {}, "variables": {}},
        mounts=(),
        projection_policy=projection_policy(),
        runtime_cell_refs={},
        diagnostics=(),
        app_config={},
        user_config={
            "display": {
                "theme": "dark",
                "cell_output": "above",
                "locale": "de-CH",
                "custom_css": ["leak-user-custom-css"],
            },
            "runtime": {
                "auto_instantiate": True,
                "output_max_bytes": 1024,
                "dotenv": ["leak-user-dotenv"],
                "pythonpath": ["leak-user-pythonpath"],
            },
            "server": {
                "transport": "sse",
                "disable_file_downloads": True,
                "browser": "leak-user-browser-command",
            },
            "completion": {
                "codeium_api_key": "leak-completion-key",
                "api_key": "leak-deprecated-completion-key",
            },
            "ai": {
                "open_ai": {
                    "api_key": "leak-openai-key",
                    "extra_headers": {"Authorization": "leak-ai-header"},
                },
                "bedrock": {
                    "aws_access_key_id": "leak-aws-id",
                    "aws_secret_access_key": "leak-aws-secret",
                },
                "custom_providers": {
                    "private": {"api_key": "leak-custom-provider-key"}
                },
            },
            "mcp": {
                "mcpServers": {
                    "stdio": {"env": {"TOKEN": "leak-mcp-env"}},
                    "http": {"headers": {"Authorization": "leak-mcp-header"}},
                }
            },
            "unknown": {"credential": "leak-unknown-key"},
        },
        config_overrides={
            "display": {"theme": "light"},
            "runtime": {
                "show_tracebacks": True,
                "dotenv": ["leak-override-dotenv"],
            },
            "ai": {"anthropic": {"api_key": "leak-override-ai-key"}},
            "mcp": {
                "mcpServers": {"private": {"headers": {"Token": "leak-override-mcp"}}}
            },
        },
        dev=False,
        mode="run",
    )

    payload = inputs.to_dict(revision="presentation-revision")

    assert payload["userConfig"] == {
        "display": {
            "theme": "dark",
            "cell_output": "above",
            "locale": "de-CH",
        },
        "runtime": {
            "auto_instantiate": True,
            "output_max_bytes": 1024,
        },
        "server": {
            "transport": "sse",
            "disable_file_downloads": True,
        },
    }
    assert payload["configOverrides"] == {
        "display": {"theme": "light"},
        "runtime": {"show_tracebacks": True},
    }


def test_projection_revision_tracks_its_runtime_contract() -> None:
    mounts: tuple[dict[str, object], ...] = (
        {
            "id": "site:result",
            "kind": "cell",
            "source": {"path": "index.html", "line": 1, "column": 1},
            "allowedTargets": ["result"],
        },
    )
    targets = {
        "cells": {
            "result": {
                "status": "ready",
                "producer": "cell:v1:result",
                "dependencyClosure": ["cell:v1:result"],
            }
        },
        "variables": {},
    }
    policy = projection_policy()

    def revision(
        *,
        source_revision: str = "source-a",
        runtime_id: str = "server",
        runtime_instance: str = "runtime-a",
        selected_mounts: tuple[dict[str, object], ...] = mounts,
        runtime_cell_refs: dict[str, str] | None = None,
        diagnostics: tuple[dict[str, object], ...] = (),
    ) -> str:
        return runtime_projection_revision(
            source_revision=source_revision,
            view="dashboard",
            runtime_id=runtime_id,
            runtime_instance=runtime_instance,
            mounts=selected_mounts,
            projection_targets=targets,
            projection_policy=policy,
            runtime_cell_refs=(
                runtime_cell_refs
                if runtime_cell_refs is not None
                else {"cell:v1:result": "runtime-result"}
            ),
            diagnostics=diagnostics,
        )

    baseline = revision()

    assert len(baseline) == 64
    assert revision() == baseline
    assert revision(source_revision="source-b") != baseline
    assert revision(runtime_id="wasm") != baseline
    assert revision(runtime_instance="runtime-b") != baseline
    assert revision(runtime_cell_refs={"cell:v1:result": "runtime-rebound"}) != baseline
    diagnostic: dict[str, object] = {
        "code": "projection-target-missing",
        "severity": "error",
        "message": "The projection target is unavailable.",
        "hint": "Restore the target.",
        "view": "dashboard",
        "projection": "cell",
        "target": "result",
        "source": {"path": "index.html", "line": 1, "column": 1},
    }
    assert revision(diagnostics=(diagnostic,)) != baseline
    assert revision(diagnostics=(diagnostic,)) == revision(
        diagnostics=(
            {
                **diagnostic,
                "source": {"path": "index.html", "line": 12, "column": 8},
            },
        )
    )
    assert (
        revision(
            selected_mounts=(
                {
                    **mounts[0],
                    "source": {"path": "index.html", "line": 8, "column": 5},
                },
            )
        )
        == baseline
    )
    assert (
        revision(
            selected_mounts=(
                {
                    **mounts[0],
                    "allowedTargets": ["summary"],
                },
            )
        )
        != baseline
    )
