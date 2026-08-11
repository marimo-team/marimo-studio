"""Validate the private Marimo API used by the pinned Studio release."""

from __future__ import annotations

import hashlib
import inspect
import json
import textwrap
from dataclasses import dataclass
from functools import cache
from importlib import import_module
from importlib.metadata import version
from importlib.resources import files
from typing import Any, Literal

from marimo_studio.errors import CompatibilityError

_RELEASE = json.loads(
    files("marimo_studio._compat").joinpath("release.json").read_text(encoding="utf-8")
)
MARIMO_VERSION: str = _RELEASE["version"]
MARIMO_RELEASE_COMMIT: str = _RELEASE["commit"]

ParameterKind = Literal[
    "POSITIONAL_ONLY",
    "POSITIONAL_OR_KEYWORD",
    "VAR_POSITIONAL",
    "KEYWORD_ONLY",
    "VAR_KEYWORD",
]
ParameterContract = tuple[str, ParameterKind, bool]

_PARAMETER_KINDS: dict[object, ParameterKind] = {
    inspect.Parameter.POSITIONAL_ONLY: "POSITIONAL_ONLY",
    inspect.Parameter.POSITIONAL_OR_KEYWORD: "POSITIONAL_OR_KEYWORD",
    inspect.Parameter.VAR_POSITIONAL: "VAR_POSITIONAL",
    inspect.Parameter.KEYWORD_ONLY: "KEYWORD_ONLY",
    inspect.Parameter.VAR_KEYWORD: "VAR_KEYWORD",
}


@dataclass(frozen=True)
class SymbolContract:
    """Expected callable shape and implementation fingerprint."""

    module: str
    qualname: str
    parameters: tuple[ParameterContract, ...] | None
    source_sha256: str

    @property
    def name(self) -> str:
        return f"{self.module}:{self.qualname}"


@dataclass(frozen=True)
class SymbolObservation:
    """Observed callable shape for one installed private symbol."""

    name: str
    parameters: tuple[ParameterContract, ...] | None
    source_sha256: str | None
    error: str | None = None


def _parameters(*items: ParameterContract) -> tuple[ParameterContract, ...]:
    return items


def _source_contract(
    module: str,
    qualname: str,
    source_sha256: str,
) -> SymbolContract:
    return SymbolContract(module, qualname, None, source_sha256)


_SYMBOLS = {
    "server-context": (
        _source_contract(
            "marimo._server.session_manager",
            "SessionManager.__init__",
            "74a8c4356a36ef5916f1167be7f556bdd3585934b9c789bf40280ead31870d2b",
        ),
        SymbolContract(
            "marimo._server.session_manager",
            "SessionManager.get_session",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("session_id", "POSITIONAL_OR_KEYWORD", False),
            ),
            "fb746e34acd9c7f4be84dfbaed31f4e9fcfa0c4949d0aa89739d1f3901f7e386",
        ),
        SymbolContract(
            "marimo._server.session_manager",
            "SessionManager.get_session_by_file_key",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("file_key", "POSITIONAL_OR_KEYWORD", False),
            ),
            "bb705d24adf284fc0be75a332743a31ba05bd9d1f710341ca5b44270ae80c401",
        ),
    ),
    "existing-session-attachment": (
        _source_contract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector.__init__",
            "4a135b10ed87f0f2b1b715c61db6137f590618bd47ac5fce0219fe98e6853983",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector._connect_kiosk",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "fb918e0fca6ebdc0d0ef0770a5aa5b4bf0a9f96aeab43713770d042d3f54f962",
        ),
    ),
    "session-replay": (
        SymbolContract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector._reconnect_session",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("session", "POSITIONAL_OR_KEYWORD", False),
            ),
            "fa5709fd94b1a953e97c29a3acc620452c270025c6a3047efaa279487f193203",
        ),
    ),
    "notebook-save-transform": (
        _source_contract(
            "marimo._session.notebook.file_manager",
            "AppFileManager.__init__",
            "924f6026135619b264467e9c33619b254e6060c1dd0bc93694f077db311cac67",
        ),
        SymbolContract(
            "marimo._session.notebook.file_manager",
            "AppFileManager._save_file",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("path", "POSITIONAL_OR_KEYWORD", False),
                ("notebook", "KEYWORD_ONLY", False),
                ("persist", "KEYWORD_ONLY", False),
                ("previous_path", "KEYWORD_ONLY", True),
            ),
            "5de4d099725d669ccef2a111501a7160922179a9337b60d02486a67c4daa649b",
        ),
    ),
    "session-extension-state": (
        _source_contract(
            "marimo._session.extensions.types",
            "EventAwareExtension.__init__",
            "17153be72840f87f24bff810dd8077c72a7415526050c5cae010e40af97fdf72",
        ),
        _source_contract(
            "marimo._session.extensions.types",
            "EventAwareExtension.on_attach",
            "899ffb4d65c0b3a14b422168aaf95279bd8c12f52d790da207df38a7ba932453",
        ),
        _source_contract(
            "marimo._session.extensions.types",
            "EventAwareExtension.on_detach",
            "3f5b96883a66e8b7d28d91b49b022250b21ccbb52c8c5dccc29d1c0f80e72eb0",
        ),
        _source_contract(
            "marimo._session.room",
            "Room.__init__",
            "a2b8538aee8e7b7b1fcafbfebba03ef3aafe0b0b3c6f3ad04605b9fd7ff789d7",
        ),
        _source_contract(
            "marimo._session.session",
            "SessionImpl.__init__",
            "a7a8e3ce7df349424cd2fb8ee67d0d8bc5cddb0c9dbc2777dd3b0f8e299fcf86",
        ),
    ),
    "cached-cell-repair": (
        SymbolContract(
            "marimo._runtime.executor.lifecycles.cached",
            "CachedLifecycle._restored_ui_defs",
            _parameters(
                ("attempt", "POSITIONAL_OR_KEYWORD", False),
                ("glbls", "POSITIONAL_OR_KEYWORD", False),
            ),
            "9b5f7e2c2a95464bb7506baf152b4163dc9d954b0bbbdd9c487e68f49d123a71",
        ),
        SymbolContract(
            "marimo._save.encode",
            "_contiguous_tensor_bytes",
            _parameters(("data", "POSITIONAL_OR_KEYWORD", False)),
            "b5af49d65687b2ee6b1469ebe46299cb0f975d2f3135962108cbe1b7255f4642",
        ),
    ),
    "kernel-projection-host": (
        SymbolContract(
            "marimo._runtime.context.kernel_context",
            "KernelRuntimeContext.with_cell_id",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("cell_id", "POSITIONAL_OR_KEYWORD", False),
            ),
            "be03ba0422d42362bd72e115ee915f2ab3032e3c072683eb2dda28015baffe53",
        ),
        SymbolContract(
            "marimo._runtime.context.kernel_context",
            "KernelRuntimeContext.provide_ui_ids",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("prefix", "POSITIONAL_OR_KEYWORD", False),
            ),
            "3ef72e074d6f822b8a97a9b3ed6719c93af3c6008d635efc9a817824526c8c95",
        ),
        SymbolContract(
            "marimo._plugins.ui._core.registry",
            "UIElementRegistry.delete",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("object_id", "POSITIONAL_OR_KEYWORD", False),
                ("python_id", "POSITIONAL_OR_KEYWORD", False),
            ),
            "ba17876fbb18aabd724ad38eaea860c73dfe89d95109d1f0e0e8e5f839b2aa6e",
        ),
        SymbolContract(
            "marimo._runtime.cell_lifecycle_registry",
            "CellLifecycleRegistry.dispose",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("cell_id", "POSITIONAL_OR_KEYWORD", False),
                ("deletion", "POSITIONAL_OR_KEYWORD", False),
            ),
            "1d2a693c4a3011704fdf51806fa479fcd488408b3f640de4daf977039b52aa3d",
        ),
    ),
    "peer-state-relay": (
        SymbolContract(
            "marimo._session.events",
            "SessionEventBus.subscribe",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("listener", "POSITIONAL_OR_KEYWORD", False),
            ),
            "b08f9028e7bca92a785a3dd9bb7ac02ef96099a03c444257e85c676db1ee015a",
        ),
        SymbolContract(
            "marimo._session.events",
            "SessionEventBus.unsubscribe",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("listener", "POSITIONAL_OR_KEYWORD", False),
            ),
            "c1c5d7bc0ef5577c1d5e3c1d8935420eee64e54be17b9556272172e0f8a3da33",
        ),
        SymbolContract(
            "marimo._session.extensions.types",
            "ExtensionRegistry.add",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("extensions", "VAR_POSITIONAL", False),
            ),
            "99bbe772305055d1ea66d466d93f497c00598dec2fd1cbd1320980e0d9810471",
        ),
        SymbolContract(
            "marimo._session.room",
            "Room.broadcast",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("notification", "POSITIONAL_OR_KEYWORD", False),
                ("except_consumer", "KEYWORD_ONLY", False),
            ),
            "16ff49bf6f3f3675cbcf57721df2c669f9dfa012c785458a7233c3b33655c672",
        ),
    ),
    "live-notebook-runner": (
        SymbolContract(
            "marimo._server.session_manager",
            "SessionManager.create_session",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("session_id", "POSITIONAL_OR_KEYWORD", False),
                ("session_consumer", "POSITIONAL_OR_KEYWORD", False),
                ("query_params", "POSITIONAL_OR_KEYWORD", False),
                ("file_key", "POSITIONAL_OR_KEYWORD", False),
                ("auto_instantiate", "POSITIONAL_OR_KEYWORD", False),
            ),
            "b71d489d5b086b560ff1de533bab394ccc110461b32725b7ac5a21e3dfe5d73f",
        ),
        SymbolContract(
            "marimo._session.session",
            "SessionImpl.instantiate",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("request", "POSITIONAL_OR_KEYWORD", False),
                ("http_request", "KEYWORD_ONLY", False),
            ),
            "7b61d1f599151ef5d96b3ac5d6319f6324c6711b35f3d8ef392a81d7f371697d",
        ),
    ),
}


def _resolve(contract: SymbolContract) -> Any:
    value: Any = import_module(contract.module)
    for part in contract.qualname.split("."):
        value = getattr(value, part)
    return value


def _parameter_contract(value: Any) -> tuple[ParameterContract, ...]:
    signature = inspect.signature(value)
    return tuple(
        (
            parameter.name,
            _PARAMETER_KINDS[parameter.kind],
            parameter.default is not inspect.Parameter.empty,
        )
        for parameter in signature.parameters.values()
    )


def _source_sha256(value: Any) -> str:
    source = textwrap.dedent(inspect.getsource(value))
    return hashlib.sha256(source.encode()).hexdigest()


def _observe_symbol(contract: SymbolContract) -> SymbolObservation:
    """Return the installed shape of one private symbol."""
    try:
        value = _resolve(contract)
        return SymbolObservation(
            name=contract.name,
            parameters=_parameter_contract(value),
            source_sha256=_source_sha256(value),
        )
    except Exception as error:
        return SymbolObservation(
            name=contract.name,
            parameters=None,
            source_sha256=None,
            error=f"{type(error).__name__}: {error}",
        )


@cache
def assert_pinned_release() -> str:
    """Return the pinned version or raise before private adapter use."""
    installed = version("marimo")
    failures: list[str] = []
    if installed != MARIMO_VERSION:
        failures.append(f"installed version {installed!r}, expected {MARIMO_VERSION!r}")
    for capability, contracts in _SYMBOLS.items():
        for contract in contracts:
            observed = _observe_symbol(contract)
            if observed.error is not None:
                failures.append(f"{capability}: {contract.name}: {observed.error}")
                continue
            if (
                contract.parameters is not None
                and observed.parameters != contract.parameters
            ):
                failures.append(
                    f"{capability}: {contract.name}: parameters "
                    f"{observed.parameters!r}, expected {contract.parameters!r}"
                )
            if observed.source_sha256 != contract.source_sha256:
                failures.append(
                    f"{capability}: {contract.name}: fingerprint "
                    f"{observed.source_sha256}, expected {contract.source_sha256}"
                )
    if failures:
        detail = "\n".join(f"- {failure}" for failure in failures)
        raise CompatibilityError(
            "The installed Marimo source does not match Studio's pinned release. "
            f"Required release: {MARIMO_VERSION}.\n{detail}"
        )
    return MARIMO_VERSION


def clear_release_cache() -> None:
    """Clear cached validation after a test replaces a private symbol."""
    assert_pinned_release.cache_clear()


def _contract_snapshot() -> dict[str, object]:
    contracts: list[dict[str, object]] = []
    for capability, expected_contracts in _SYMBOLS.items():
        for expected in expected_contracts:
            observed = _observe_symbol(expected)
            contracts.append(
                {
                    "capability": capability,
                    "module": expected.module,
                    "qualname": expected.qualname,
                    "parameters": observed.parameters,
                    "source_sha256": observed.source_sha256,
                    "error": observed.error,
                }
            )
    return {
        "configuredVersion": MARIMO_VERSION,
        "installedVersion": version("marimo"),
        "contracts": contracts,
    }


__all__ = [
    "MARIMO_RELEASE_COMMIT",
    "MARIMO_VERSION",
    "assert_pinned_release",
    "clear_release_cache",
]


if __name__ == "__main__":
    print(json.dumps(_contract_snapshot(), indent=2))
