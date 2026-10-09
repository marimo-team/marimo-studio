"""Build and cache the installed-provider registry.

The registry derives each durable key from distribution and entry-point
identity, rejects conflicts, and scans independent candidates concurrently.
Import, metadata, availability, and starter failures remain attached to their
registration so healthy providers stay available and provider diagnostics can
explain how to recover.

Built-in providers run in process. Third-party calls use owned worker processes.
Both return through the same conformance checks. Discovery, provider identity,
installed version, and starters are cached, while availability is checked when
an operation needs it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager, suppress
from contextvars import Context, copy_context
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from pathlib import Path
from threading import Lock, RLock
from typing import cast

from packaging.utils import canonicalize_name

from marimo_studio._processes.cancellation import current_provider_cancellation
from marimo_studio._processes.operation import ProviderCommandError
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
    DocumentProvider,
    InspectionRequest,
    ProjectInspection,
    ProviderAvailability,
    ProviderCancellation,
    ProviderInfo,
    ProviderStarter,
    RenderRequest,
    StarterContext,
    StarterPlan,
    ViewProject,
    ViewProvider,
)
from marimo_studio.view_providers._host.conformance import (
    ProviderConformance,
    provider_methods,
)
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
    render_in_provider_process,
    starters_in_provider_process,
)
from marimo_studio.view_providers._host.package_policy import (
    BUILTIN_PROVIDER_DISTRIBUTION,
)
from marimo_studio.view_providers._host.records import ProviderProvenance
from marimo_studio.view_providers._host.starters import (
    validate_starter_context,
    validate_starter_plan,
    validate_starters,
)

ENTRY_POINT_GROUP = "marimo_studio.view_provider"
_ENTRY_POINT_NAME = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?")
_DISCOVERY_WORKERS = 8
_STARTER_WORKERS = 8


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
        *,
        renders: bool,
    ) -> None:
        self.key = candidate.key
        self.renders = renders
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
        self._availability: ProviderAvailability | None = None
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

    @contextmanager
    def _guard(self, action: str, source: Path | None = None) -> Iterator[None]:
        """Report an unexpected provider failure as a Studio error for ``action``."""
        try:
            yield
        except MarimoStudioError as failure:
            raise_process_cleanup(failure)
            raise
        except Exception as failure:
            raise_process_cleanup(failure)
            # A command budget or limit explains itself. Other failures are
            # provider bugs, so their type helps the provider's author.
            detail = (
                str(failure)
                if isinstance(failure, ProviderCommandError)
                else f"{type(failure).__name__}: {failure}"
            )
            raise ViewProjectError(
                f"View provider {self.key!r} could not {action}: {detail}",
                source=source,
            ) from failure

    def availability(self) -> ProviderAvailability:
        try:
            availability = self._conformance.validate_availability(
                availability_in_provider_process(
                    self._process,
                    self._cancellation(),
                    self._extension_timeout,
                )
                if self._process is not None
                else self._local_provider().availability()
            )
            self._registry._clear_error(self.key, "availability")
        except Exception as error:
            raise_process_cleanup(error)
            self._registry._record_error(self.key, "availability", error)
            availability = ProviderAvailability(
                available=False,
                reason=f"{type(error).__name__}: {error}",
                action="Repair or remove the provider registration.",
            )
        self._availability = availability
        return availability

    def starters(self) -> tuple[ProviderStarter, ...]:
        with self._starter_lock:
            if self._starters is not None:
                return self._starters
            try:
                starters = validate_starters(
                    self.key,
                    starters_in_provider_process(
                        self._process,
                        self._cancellation(),
                        self._extension_timeout,
                    )
                    if self._process is not None
                    else self._local_provider().starters(),
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
    ) -> StarterPlan:
        validate_starters(self.key, (starter,))
        context = validate_starter_context(self.key, context)
        with self._guard(f"create starter {starter.key!r}"):
            plan = (
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
        return validate_starter_plan(self.key, starter, context, plan)

    def inspect(self, request: InspectionRequest) -> ProjectInspection:
        request = self._conformance.validate_inspection_request(request)
        with self._guard(
            f"inspect view {request.project.name!r}",
            request.project.manifest,
        ):
            if self._process is not None:
                return self._conformance.validate_inspection(
                    request.project,
                    inspect_in_provider_process(self._process, request),
                )
            return self._conformance.inspect(self._local_provider(), request)

    def build(self, request: BuildRequest) -> BuildResult:
        request = self._conformance.validate_build_request(request)
        with self._guard(
            f"build view {request.project.name!r}",
            request.project.manifest,
        ):
            if self._process is not None:
                result = build_in_provider_process(self._process, request)
                return self._conformance.validate_build_result(request, result)
            return self._conformance.build(self._local_provider(), request)

    def render(self, request: RenderRequest) -> BuildResult:
        if not self.renders:
            raise ConfigurationError(f"View provider {self.key!r} has no render()")
        request = self._conformance.validate_render_request(request)
        with self._guard(f"render {request.document.as_posix()!r}"):
            if self._process is not None:
                result = render_in_provider_process(self._process, request)
                return self._conformance.validate_render_result(request, result)
            return self._conformance.render(
                cast(DocumentProvider, self._local_provider()),
                request,
            )

    def provenance(self) -> ProviderProvenance:
        """Identify the provider and tool versions that build this provider's views.

        The tool version comes from the latest availability check. Builds check
        availability first, so a tool upgrade reaches the next build.
        """
        return self._conformance.provenance(
            (self._availability or self.availability()).version
        )

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
                tuple[ViewProvider | None, ProviderProcessSpec | None, object, bool],
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
                    != BUILTIN_PROVIDER_DISTRIBUTION
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
                    descriptions[index] = (
                        implementation,
                        None,
                        getattr(implementation, "info", None),
                        provider_methods(implementation),
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
                    Future[tuple[ProviderInfo, bool]],
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
                        ) -> tuple[ProviderInfo, bool]:
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
                            info, renders = future.result()
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
                            descriptions[index] = (None, process, info, renders)
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
                implementation, process, info, renders = descriptions[index]
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
                        renders=renders,
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

    def entry_module(self, key: str) -> str | None:
        """Return the module that registers ``key``, without loading it."""
        for candidate in self._candidates:
            with suppress(ValueError):
                if candidate.key == key:
                    return candidate.entry_point.module
        return None

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
