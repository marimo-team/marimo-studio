"""Discover installed view providers through one derived-key registry."""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextvars import Context, copy_context
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import PurePosixPath
from threading import Lock, RLock
from typing import cast

from packaging.utils import canonicalize_name

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.provider_operation import (
    find_process_cleanup_error,
    raise_process_cleanup,
)
from marimo_studio.errors import (
    ConfigurationError,
    MarimoStudioError,
    ProviderNotFoundError,
    ViewProjectError,
)
from marimo_studio.view_providers import (
    BuildProfile,
    BuildRequest,
    BuildResult,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    StarterContext,
    ViewProject,
    ViewProvider,
)
from marimo_studio.view_providers._host.conformance import ProviderConformance
from marimo_studio.view_providers._host.identity import starter_id
from marimo_studio.view_providers._host.operations.process import (
    DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
    ProviderOperationCancelled,
    ProviderProcessSpec,
    availability_in_provider_process,
    build_in_provider_process,
    create_in_provider_process,
    describe_in_provider_process,
    inspect_in_provider_process,
    starters_in_provider_process,
)
from marimo_studio.view_providers._host.package_policy import (
    BUNDLED_PROVIDER_DISTRIBUTION,
)
from marimo_studio.view_providers._host.records import ProviderProvenance

ENTRY_POINT_GROUP = "marimo_studio.view_provider"
_ENTRY_POINT_NAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_DISCOVERY_WORKERS = 8
_STARTER_WORKERS = 8


def _validate_provider_methods(provider: ViewProvider) -> None:
    for method in ("availability", "starters", "create", "inspect", "build"):
        operation = getattr(provider, method, None)
        if not callable(operation):
            raise ValueError(f"provider requires {method}()")
        if inspect.iscoroutinefunction(operation):
            raise ValueError(f"provider {method}() must be synchronous")


def provider_key(distribution: str, registration: str) -> str:
    """Derive the durable provider key from package and entry-point identity."""
    package = canonicalize_name(distribution)
    if not package or _ENTRY_POINT_NAME.fullmatch(registration) is None:
        raise ValueError("provider entry-point identity is invalid")
    return f"{package}/{registration}"


@dataclass(frozen=True)
class ProviderCandidate:
    """Identify one installed entry point before its provider is loaded."""

    registration: str
    distribution: str
    version: str
    entry_point: EntryPoint

    @property
    def key(self) -> str:
        return provider_key(self.distribution, self.registration)


@dataclass(frozen=True)
class ProviderDiagnostic:
    """Final diagnostic state for one installed provider registration."""

    registration: str
    distribution: str
    version: str
    provider_key: str | None
    error: str | None
    info: ProviderInfo | None
    availability: ProviderAvailability | None
    starters: tuple[str, ...]

    @property
    def loaded(self) -> bool:
        return self.info is not None and self.error is None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "key": self.provider_key,
            "registration": self.registration,
            "distribution": self.distribution,
            "version": self.version,
            "loaded": self.loaded,
            "error": self.error,
            "availability": (
                self.availability.to_dict() if self.availability is not None else None
            ),
            "starters": list(self.starters),
        }
        if self.info is not None:
            value.update(self.info.to_dict())
        return value


class _RegisteredProvider:
    """Expose one provider after validation and error isolation."""

    def __init__(
        self,
        provider: ViewProvider | None,
        candidate: ProviderCandidate,
        registry: ProviderRegistry,
        requirement: str,
        process: ProviderProcessSpec | None,
        info: object,
        extension_timeout: float,
    ) -> None:
        self.key = candidate.key
        self.distribution = canonicalize_name(candidate.distribution)
        self.version = candidate.version
        self.registration = candidate.registration
        self.requirement = requirement
        self._provider = provider
        self._registry = registry
        self._process = process
        self._extension_timeout = extension_timeout
        self._starter_lock = Lock()
        self._starters: tuple[ProviderStarter, ...] | None = None
        self._conformance = ProviderConformance(
            self.key,
            info,
            distribution=self.distribution,
            version=self.version,
        )
        self.info = self._conformance.info

    @staticmethod
    def _cancellation() -> ProviderCancellation:
        return current_provider_cancellation() or ProviderCancellation()

    def availability(
        self,
        project: ViewProject | None = None,
    ) -> ProviderAvailability:
        if project is not None:
            project = self._conformance.validate_project(project)
        try:
            availability = self._conformance.validate_availability(
                availability_in_provider_process(
                    self._process,
                    project,
                    self._cancellation(),
                    self._extension_timeout,
                )
                if self._process is not None
                else self._local_provider().availability(project)
            )
            self._registry._clear_error(self.key, "availability")
            return availability
        except Exception as error:
            raise_process_cleanup(error)
            self._registry._record_error(self.key, "availability", error)
            return ProviderAvailability(
                available=False,
                reason=f"{type(error).__name__}: {error}",
                action="Repair or remove the provider registration.",
            )

    def starters(self) -> tuple[ProviderStarter, ...]:
        with self._starter_lock:
            if self._starters is not None:
                return self._starters
            try:
                starters = self._conformance.validate_starters(
                    starters_in_provider_process(
                        self._process,
                        self._cancellation(),
                        self._extension_timeout,
                    )
                    if self._process is not None
                    else self._local_provider().starters()
                )
                self._registry._clear_error(self.key, "starters")
                self._starters = starters
                return starters
            except Exception as error:
                raise_process_cleanup(error)
                self._registry._record_error(self.key, "starters", error)
                return ()

    def create(
        self,
        starter: ProviderStarter,
        context: StarterContext,
    ) -> Mapping[PurePosixPath, bytes]:
        self._conformance.validate_starters((starter,))
        try:
            files = (
                create_in_provider_process(
                    self._process,
                    starter,
                    context,
                    self._cancellation(),
                    self._extension_timeout,
                )
                if self._process is not None
                else self._local_provider().create(starter, context)
            )
        except MarimoStudioError as error:
            raise_process_cleanup(error)
            raise
        except Exception as error:
            raise_process_cleanup(error)
            raise ConfigurationError(
                f"View provider {self.key!r} could not create starter "
                f"{starter.key!r}: {type(error).__name__}: {error}"
            ) from error
        return self._conformance.validate_created_files(starter, files)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        request = self._conformance.validate_inspection_request(request)
        try:
            inspection = (
                self._local_provider().inspect(request)
                if self._process is None
                else inspect_in_provider_process(self._process, request)
            )
        except MarimoStudioError as error:
            raise_process_cleanup(error)
            raise
        except Exception as error:
            raise_process_cleanup(error)
            raise ViewProjectError(
                f"View provider {self.key!r} could not inspect project "
                f"{request.project.name!r}: {type(error).__name__}: {error}",
                source=request.project.manifest,
            ) from error
        return self._conformance.validate_inspection(request.project, inspection)

    def build(self, request: BuildRequest) -> BuildResult:
        request = self._conformance.validate_build_request(request)
        try:
            result = (
                self._local_provider().build(request)
                if self._process is None
                else build_in_provider_process(self._process, request)
            )
        except MarimoStudioError as error:
            raise_process_cleanup(error)
            raise
        except Exception as error:
            raise_process_cleanup(error)
            raise ViewProjectError(
                f"View provider {self.key!r} could not build project "
                f"{request.project.name!r}: {type(error).__name__}: {error}",
                source=request.project.manifest,
            ) from error
        return self._conformance.validate_build_result(request, result)

    def provenance(self, inspection: ProjectInspection) -> ProviderProvenance:
        return self._conformance.provenance(inspection)

    def _local_provider(self) -> ViewProvider:
        if self._provider is None:
            raise RuntimeError("Isolated provider has no in-process implementation")
        return self._provider


class ProviderRegistry:
    """Load installed entry points and isolate each registration's failures."""

    def __init__(
        self,
        candidates: tuple[ProviderCandidate, ...],
        requirements: Mapping[str, str] | None = None,
        *,
        isolate_operations: bool = False,
        extension_timeout: float = DEFAULT_PROVIDER_EXTENSION_TIMEOUT,
    ) -> None:
        if (
            isinstance(extension_timeout, bool)
            or not isinstance(extension_timeout, (int, float))
            or not math.isfinite(extension_timeout)
            or extension_timeout <= 0
        ):
            raise ValueError("Provider extension timeout must be finite and positive")
        self._lock = RLock()
        self._scan_lock = Lock()
        self._candidates = candidates
        self._requirements = dict(requirements or {})
        self._isolate_operations = isolate_operations
        self._extension_timeout = float(extension_timeout)
        self._providers: dict[str, _RegisteredProvider] | None = None
        self._diagnostics: tuple[ProviderDiagnostic, ...] | None = None
        self._conflicts: dict[str, tuple[ProviderCandidate, ...]] = {}
        self._runtime_errors: dict[str, dict[str, str]] = {}

    @classmethod
    def discover(
        cls,
        requirements: Mapping[str, str] | None = None,
    ) -> ProviderRegistry:
        candidates = []
        for point in entry_points(group=ENTRY_POINT_GROUP):
            distribution = point.dist
            candidates.append(
                ProviderCandidate(
                    registration=point.name,
                    distribution=(
                        distribution.name if distribution is not None else "unknown"
                    ),
                    version=(
                        distribution.version if distribution is not None else "unknown"
                    ),
                    entry_point=point,
                )
            )
        return cls(tuple(candidates), requirements, isolate_operations=True)

    def _scan(self) -> None:
        with self._lock:
            if self._providers is not None:
                return
        with self._scan_lock:
            with self._lock:
                if self._providers is not None:
                    return
            discovery_control = (
                current_provider_cancellation() or ProviderCancellation()
            )
            providers: dict[str, _RegisteredProvider] = {}
            diagnostics: list[ProviderDiagnostic | None] = [None] * len(
                self._candidates
            )
            grouped: dict[str, list[tuple[int, ProviderCandidate]]] = {}
            for index, candidate in enumerate(self._candidates):
                try:
                    grouped.setdefault(candidate.key, []).append((index, candidate))
                except ValueError as error:
                    diagnostics[index] = ProviderDiagnostic(
                        registration=candidate.registration,
                        distribution=candidate.distribution,
                        version=candidate.version,
                        provider_key=None,
                        error=str(error),
                        info=None,
                        availability=None,
                        starters=(),
                    )
            conflicts = {
                key: tuple(candidate for _, candidate in items)
                for key, items in grouped.items()
                if len(items) > 1
            }
            descriptions: dict[
                int,
                tuple[ViewProvider | None, ProviderProcessSpec | None, object],
            ] = {}
            description_errors: dict[int, Exception] = {}
            external: list[tuple[int, ProviderProcessSpec]] = []
            for key, items in grouped.items():
                if len(items) > 1:
                    owners = ", ".join(
                        f"{item.distribution} {item.version}" for _, item in items
                    )
                    for index, item in items:
                        diagnostics[index] = ProviderDiagnostic(
                            registration=item.registration,
                            distribution=item.distribution,
                            version=item.version,
                            provider_key=key,
                            error=(
                                f"provider key {key!r} has multiple registrations: "
                                f"{owners}"
                            ),
                            info=None,
                            availability=None,
                            starters=(),
                        )
                    continue
                index, candidate = items[0]
                isolated = (
                    self._isolate_operations
                    and canonicalize_name(candidate.distribution)
                    != BUNDLED_PROVIDER_DISTRIBUTION
                )
                if isolated:
                    external.append(
                        (
                            index,
                            ProviderProcessSpec(
                                key,
                                candidate.registration,
                                candidate.distribution,
                                candidate.version,
                                candidate.entry_point.value,
                            ),
                        )
                    )
                    continue
                try:
                    implementation = cast(
                        ViewProvider,
                        candidate.entry_point.load(),
                    )
                    _validate_provider_methods(implementation)
                    descriptions[index] = (
                        implementation,
                        None,
                        getattr(implementation, "info", None),
                    )
                except Exception as error:
                    raise_process_cleanup(error)
                    if discovery_control.cancelled:
                        raise ProviderOperationCancelled(
                            "Provider discovery was cancelled"
                        ) from error
                    description_errors[index] = error

            if external:
                executor = ThreadPoolExecutor(
                    max_workers=min(_DISCOVERY_WORKERS, len(external)),
                    thread_name_prefix="marimo-studio-provider-discovery",
                )
                futures: dict[
                    Future[ProviderInfo],
                    tuple[int, ProviderProcessSpec],
                ] = {}
                cleanup_error = None
                cancellation_error: ProviderOperationCancelled | None = None
                try:
                    for index, process in external:
                        context = copy_context()

                        def describe(
                            selected: ProviderProcessSpec = process,
                            selected_context: Context = context,
                        ) -> ProviderInfo:
                            return selected_context.run(
                                describe_in_provider_process,
                                selected,
                                discovery_control,
                                self._extension_timeout,
                            )

                        futures[executor.submit(describe)] = (index, process)
                    for future in as_completed(futures):
                        index, process = futures[future]
                        try:
                            info = future.result()
                        except Exception as error:
                            cleanup = find_process_cleanup_error(error)
                            if cleanup is not None:
                                cleanup_error = cleanup_error or cleanup
                                discovery_control.cancel()
                            elif isinstance(error, ProviderOperationCancelled):
                                cancellation_error = cancellation_error or error
                            else:
                                description_errors[index] = error
                        else:
                            descriptions[index] = (None, process, info)
                finally:
                    executor.shutdown(
                        wait=True,
                        cancel_futures=(
                            cleanup_error is not None
                            or cancellation_error is not None
                            or discovery_control.cancelled
                        ),
                    )
                if cleanup_error is not None:
                    raise cleanup_error
                if cancellation_error is not None or discovery_control.cancelled:
                    raise ProviderOperationCancelled(
                        "Provider discovery was cancelled"
                    ) from cancellation_error

            for key, items in grouped.items():
                if len(items) > 1:
                    continue
                index, candidate = items[0]
                error = description_errors.get(index)
                if error is not None:
                    diagnostics[index] = ProviderDiagnostic(
                        registration=candidate.registration,
                        distribution=candidate.distribution,
                        version=candidate.version,
                        provider_key=key,
                        error=f"{type(error).__name__}: {error}",
                        info=None,
                        availability=None,
                        starters=(),
                    )
                    continue
                implementation, process, info = descriptions[index]
                try:
                    registered = _RegisteredProvider(
                        implementation,
                        candidate,
                        self,
                        self._requirements.get(
                            key,
                            f"{canonicalize_name(candidate.distribution)}"
                            f"=={candidate.version}",
                        ),
                        process,
                        info,
                        self._extension_timeout,
                    )
                except Exception as error:
                    raise_process_cleanup(error)
                    if discovery_control.cancelled:
                        raise ProviderOperationCancelled(
                            "Provider discovery was cancelled"
                        ) from error
                    diagnostics[index] = ProviderDiagnostic(
                        registration=candidate.registration,
                        distribution=candidate.distribution,
                        version=candidate.version,
                        provider_key=key,
                        error=f"{type(error).__name__}: {error}",
                        info=None,
                        availability=None,
                        starters=(),
                    )
                else:
                    providers[key] = registered
                    diagnostics[index] = ProviderDiagnostic(
                        registration=candidate.registration,
                        distribution=candidate.distribution,
                        version=candidate.version,
                        provider_key=key,
                        error=None,
                        info=registered.info,
                        availability=None,
                        starters=(),
                    )
            if any(diagnostic is None for diagnostic in diagnostics):
                raise RuntimeError(
                    "Provider discovery did not classify every candidate"
                )
            with self._lock:
                if discovery_control.cancelled:
                    raise ProviderOperationCancelled("Provider discovery was cancelled")
                self._providers = providers
                self._conflicts = conflicts
                self._diagnostics = tuple(
                    cast(ProviderDiagnostic, diagnostic) for diagnostic in diagnostics
                )

    def _record_error(self, key: str, operation: str, error: Exception) -> None:
        with self._lock:
            message = f"{operation}: {type(error).__name__}: {error}"
            self._runtime_errors.setdefault(key, {})[operation] = message

    def _clear_error(self, key: str, operation: str) -> None:
        with self._lock:
            bucket = self._runtime_errors.get(key)
            if bucket is None:
                return
            bucket.pop(operation, None)
            if not bucket:
                self._runtime_errors.pop(key, None)

    @property
    def ids(self) -> tuple[str, ...]:
        self._scan()
        with self._lock:
            assert self._providers is not None
            return tuple(sorted(self._providers))

    def get(self, key: str) -> _RegisteredProvider:
        self._scan()
        with self._lock:
            assert self._providers is not None
            provider = self._providers.get(key)
            conflict = self._conflicts.get(key)
            available = tuple(sorted(self._providers))
        if provider is not None:
            return provider
        if conflict:
            owners = ", ".join(
                f"{item.distribution} {item.version}" for item in conflict
            )
            raise ConfigurationError(
                f"View provider {key!r} has multiple registrations: {owners}"
            )
        raise ProviderNotFoundError(key, available=available)

    def diagnostics(self) -> tuple[ProviderDiagnostic, ...]:
        """Return finalized load, availability, and starter diagnostics."""
        self._scan()
        accepted = self.starter_records()
        starter_keys: dict[str, list[str]] = {}
        for provider, starter in accepted:
            starter_keys.setdefault(provider.key, []).append(
                starter_id(provider.key, starter.key)
            )
        availability = {key: self.get(key).availability() for key in self.ids}
        with self._lock:
            assert self._diagnostics is not None
            assert self._providers is not None
            diagnostics = self._diagnostics
            providers = dict(self._providers)
            runtime_errors = {
                key: dict(errors) for key, errors in self._runtime_errors.items()
            }
        records = []
        for diagnostic in diagnostics:
            key = diagnostic.provider_key
            errors = runtime_errors.get(key or "", {})
            installed = providers.get(key) if key else None
            records.append(
                ProviderDiagnostic(
                    registration=diagnostic.registration,
                    distribution=diagnostic.distribution,
                    version=diagnostic.version,
                    provider_key=key,
                    error=("; ".join(errors.values()) if errors else diagnostic.error),
                    info=installed.info if installed is not None else diagnostic.info,
                    availability=availability.get(key or ""),
                    starters=tuple(starter_keys.get(key or "", ())),
                )
            )
        return tuple(records)

    def validate_project(self, project: ViewProject) -> ViewProject:
        return self.get(project.provider)._conformance.validate_project(project)

    def validate_profile(self, key: str, profile: object) -> BuildProfile:
        return self.get(key)._conformance.validate_profile(profile)

    def starter_records(
        self,
    ) -> tuple[tuple[_RegisteredProvider, ProviderStarter], ...]:
        """Return provider-local starters from healthy installed providers."""
        self._scan()
        with self._lock:
            assert self._providers is not None
            providers = tuple(self._providers[key] for key in sorted(self._providers))
        if not providers:
            return ()
        with ThreadPoolExecutor(
            max_workers=min(_STARTER_WORKERS, len(providers)),
            thread_name_prefix="marimo-studio-provider-starters",
        ) as executor:
            futures: list[
                tuple[_RegisteredProvider, Future[tuple[ProviderStarter, ...]]]
            ] = []
            for provider in providers:
                context = copy_context()

                def starters(
                    selected: _RegisteredProvider = provider,
                    selected_context: Context = context,
                ) -> tuple[ProviderStarter, ...]:
                    return selected_context.run(selected.starters)

                futures.append((provider, executor.submit(starters)))
            return tuple(
                (provider, starter)
                for provider, future in futures
                for starter in future.result()
            )
