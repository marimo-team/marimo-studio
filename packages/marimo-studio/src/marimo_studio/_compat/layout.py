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

from marimo_studio.errors._internal import CompatibilityError

_RELEASE = json.loads(
    files("marimo_studio._compat").joinpath("release.json").read_text(encoding="utf-8")
)
MARIMO_VERSION: str = _RELEASE["version"]
MARIMO_RELEASE_COMMIT: str = _RELEASE["commit"]
MARIMO_FRONTEND_PATCH_SHA256: str = _RELEASE["frontendPatchSha256"]

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
    closure_indices: tuple[int, ...] = ()

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
    "usage-process-sampling": (
        SymbolContract(
            "marimo._server.api.endpoints.health",
            "usage",
            _parameters(("request", "POSITIONAL_OR_KEYWORD", False)),
            "6fa17048382f0bb92cb51a646926c54f2c3db12b9ead226b41f9f97717c02cd6",
        ),
    ),
    "server-context": (
        _source_contract(
            "marimo._server.session_manager",
            "SessionManager.__init__",
            "31b1b282bf11f160460da26768b06fc4237faa778ae5734516308e726cf42bec",
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
            "993c2270c70d67b7527e82e1064793e13e36caa894617ebcc46df7ad1778dd45",
        ),
        SymbolContract(
            "marimo._server.session_manager",
            "SessionManager.close_session",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("session_id", "POSITIONAL_OR_KEYWORD", False),
            ),
            "d888a14630aa9e6762221d5f57e7abdcdf57e403c9600b72bfc7846d2074ac10",
        ),
    ),
    "programmatic-main-module": (
        SymbolContract(
            "marimo._runtime.patches",
            "patch_sys_module",
            _parameters(("module", "POSITIONAL_OR_KEYWORD", False)),
            "494ba13930024d0711ae04ff917d72107b695969c40e1778b177df6787d33be4",
        ),
    ),
    "session-query-metadata": (
        _source_contract(
            "marimo._session.managers.kernel",
            "KernelManagerImpl.__init__",
            "cab5c5e1db540f13bd6efa5475812786515223648944a724cccc4e0c76ddcbb6",
        ),
        _source_contract(
            "marimo._session.managers.ipc",
            "IPCKernelManagerImpl.__init__",
            "406097cedbf70cbff9091e9fb0dea0bcc83d23c25d7dc273975a3846ca908c5b",
        ),
        _source_contract(
            "marimo._session.managers.app_host",
            "AppHostKernelManager.__init__",
            "014556ace181b9a55450149a7e303ac7d83e1cc6ea6dc08698137a08d21fcf43",
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
            "SessionConnector.connect",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "11d7816287c90e455c383c44d825a66f59b29306a3bfd89dc157326e9f9e2d68",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector._connect",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "898a4def2b274ff61ac880983e33d5575c33d8a1dde6d284a39dbfdb6305d5cc",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector._connect_kiosk",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "fb918e0fca6ebdc0d0ef0770a5aa5b4bf0a9f96aeab43713770d042d3f54f962",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws.ws_session_connector",
            "SessionConnector._create_new_session",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "f226aecbc9b1f4505dab482fe3a90385d7e1449aea21928acc8427651d86c3ba",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws_endpoint",
            "WebSocketHandler.start",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "ec2c3c51e63f1d892cde29065e382342c51aba848aea30a3a2174a98405e3200",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws_endpoint",
            "WebSocketHandler._safe_close",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("code", "POSITIONAL_OR_KEYWORD", False),
                ("reason", "POSITIONAL_OR_KEYWORD", False),
            ),
            "b24dff35c179d5e027c513b3ba76e622ee8560abf842ed3d6a00cd832982e95b",
        ),
        SymbolContract(
            "marimo._server.api.endpoints.ws.session_handler",
            "SessionHandler._on_disconnect",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "cc7de12f46c884da4582d1b5072e94042a641dc7ddd7a8dd65130458ddb04a03",
        ),
    ),
    "session-replay": (
        _source_contract(
            "marimo._server.api.endpoints.ws.session_handler",
            "SessionHandler._reconnect_session",
            "6f29d58798f375ed92654a81a8e4c9af50d2709a9f0a2ce7f2e1384758cb47ea",
        ),
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
    "session-cache-publication": (
        SymbolContract(
            "marimo._session.state.serialize",
            "SessionCacheWriter.run",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "91479c6f2ba69ff586e60605196263bf9350c5b7c5d78d01100d22818ab4114f",
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
            "178c04d53ba6bc80e034080a14c8ae4183286c211e9e65d1a4e0b7d6c7822698",
        ),
        SymbolContract(
            "marimo._environments.script_metadata",
            "notebook_file_lock",
            _parameters(("path", "POSITIONAL_OR_KEYWORD", False)),
            "e782d586d9f6098dd1e4a3a23dec79ab83ae697165a6aab4a00c411bce0fd2b9",
        ),
    ),
    "document-transaction-evidence": (
        SymbolContract(
            "marimo._server.api.endpoints.document",
            "document_transaction",
            _parameters(("request", "POSITIONAL_OR_KEYWORD", False)),
            "54cc42d08406f4baac07dc8777c563609345264769454a9472141c34d46c807e",
            (0,),
        ),
        SymbolContract(
            "marimo._messaging.notebook.document",
            "NotebookDocument.apply",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("tx", "POSITIONAL_OR_KEYWORD", False),
            ),
            "4a442fd6a6657614d6f3ec21ccd3b7c89d8a646e5c708cff6b68e76deae59f04",
        ),
        SymbolContract(
            "marimo._server.api.deps",
            "AppState.get_current_session",
            _parameters(("self", "POSITIONAL_OR_KEYWORD", False)),
            "d93367ee269d025636b5eae05785c7634a5892017634172fe321e18cf770ddc1",
        ),
        _source_contract(
            "marimo._session.session",
            "SessionImpl.document.fget",
            "1872e92c1205e410d33e220852f7522d04dba78e2c5037cd5b45aa524614e3cb",
        ),
        _source_contract(
            "marimo._messaging.notebook.document",
            "NotebookDocument.cells.fget",
            "34fe5025eec035e8370bf13e308ae47d9e09bae26ca0538d26c96f829b006ade",
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
            "6473a9377a00158029d74303b69bf5217f75d94c62d3b798f04dab181b6d5ac7",
        ),
    ),
    "lens-mount-policy": (
        SymbolContract(
            "marimo._runtime.runner.hooks_lens",
            "mount_lens",
            _parameters(
                ("cell", "POSITIONAL_OR_KEYWORD", False),
                ("ctx", "POSITIONAL_OR_KEYWORD", False),
                ("result", "POSITIONAL_OR_KEYWORD", False),
            ),
            "7dfc24c0a1c4ff767c3888e33ce59448da9b2e11b9e763af987aca053d0bf5b9",
        ),
        _source_contract(
            "marimo._runtime.runner.hooks",
            "_HookList.add",
            "f512376cc0d128c6529b9a2f6db6d884fdfda5347cf3a6871020eb975ba4bb84",
        ),
        _source_contract(
            "marimo._runtime.runner.hooks",
            "_HookList.sorted_hooks.fget",
            "9714abce2444ff496860c1f8a4b275dee2f02d2bff8d2704c1ed64bd4a07440b",
        ),
        _source_contract(
            "marimo._runtime.runner.hooks",
            "NotebookCellHooks.copy",
            "7a21d82d77b4a7f6ad0d4d5637b40c3c105477f8f4d54b7da448f43a9ff1e446",
        ),
    ),
    "sandbox-studio-runtime": (
        SymbolContract(
            "marimo._environments.overlay",
            "runtime_overlay",
            _parameters(
                ("extras", "POSITIONAL_OR_KEYWORD", True),
                ("command", "POSITIONAL_OR_KEYWORD", True),
            ),
            "3b61b0052b33b3f66b65e6bc3ec263c6a9cdaa03687dce5fc90276de67c303cd",
        ),
        _source_contract(
            "marimo._environments.overlay",
            "RuntimeOverlay",
            "060b46852f7c25c22b65e96e139623d891e1f8b875f6c4e044fada0779fdeca0",
        ),
        _source_contract(
            "marimo._environments.environment",
            "_with_args",
            "6480ab176df2e68a96de15fe87aab4ea86b2a4ef3a76c939a8a1876f33e6dcdb",
        ),
        _source_contract(
            "marimo._session.managers.ipc",
            "IPCKernelManagerImpl.start_kernel",
            "090a5be3b647330a2d67093c6f5520e905765544adb3655d9b1c05097ee32c83",
        ),
        _source_contract(
            "marimo._session.app_host.pool",
            "AppHostPool._sandbox_plan",
            "40e8899556119579c6401b1df39549046c4fca9e863da3fb2ba5c3a8ec4c6d7e",
        ),
    ),
    "zero-python-state-ledger": (
        SymbolContract(
            "marimo._runtime.runner.hooks",
            "NotebookCellHooks.add_on_finish",
            _parameters(
                ("self", "POSITIONAL_OR_KEYWORD", False),
                ("hook", "POSITIONAL_OR_KEYWORD", False),
                ("priority", "POSITIONAL_OR_KEYWORD", True),
            ),
            "5037f538d99c5a5bb280900fbc6bc817fd85c43d313639f08f730e3ca9cf4635",
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
            "3b32697185bf7c654232db4f3c570be8f74792ace851f3076ab38e4e168d40a9",
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
    for index in contract.closure_indices:
        closure = value.__closure__
        if closure is None:
            raise AttributeError(f"{contract.name} has no closure")
        value = closure[index].cell_contents
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


if __name__ == "__main__":
    print(json.dumps(_contract_snapshot(), indent=2))
