"""Prepare and execute a native Marimo Studio launch."""

from __future__ import annotations

import secrets
import subprocess
import sys
import threading
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode

from marimo_studio._server.routes import studio_url, view_url
from marimo_studio._workspace.environment import environment_command
from marimo_studio._workspace.setup import ensure_view

_DIRECT_LAUNCH_OPTIONS = frozenset(
    {
        "--base-url",
        "--headless",
        "--host",
        "--open",
        "--port",
    }
)
_ENVIRONMENT_OPTIONS = frozenset({"--sandbox", "--no-sandbox"})


class LaunchArgumentError(ValueError):
    """A direct-launch argument conflicts with Studio's Marimo command."""


@dataclass(frozen=True)
class LaunchRequest:
    """Inputs needed to configure and launch one Studio view."""

    notebook: Path
    view_name: str | None
    host: str
    port: int
    open_browser: bool
    base_url: str
    marimo_args: tuple[str, ...]


@dataclass(frozen=True)
class LaunchPlan:
    """Resolved URLs and process arguments for one Studio launch."""

    studio_url: str
    view_url: str
    command: tuple[str, ...]
    working_directory: Path
    open_browser: bool


def validate_base_url(value: str) -> str:
    """Return a valid Marimo base URL path."""
    if value == "/":
        raise LaunchArgumentError(
            "must not be /. This is equivalent to an empty base URL"
        )
    if value and not value.startswith("/"):
        raise LaunchArgumentError("must start with /")
    if value.endswith("/"):
        raise LaunchArgumentError("must not end with /")
    return value


def validate_marimo_args(args: tuple[str, ...]) -> None:
    """Reject pass-through options owned by Studio."""
    for argument in args:
        option = argument.partition("=")[0]
        if (
            option in _DIRECT_LAUNCH_OPTIONS
            or option == "-p"
            or option.startswith("-p")
        ):
            raise LaunchArgumentError(
                f"Pass {option} before `--`. Marimo Studio manages this option."
            )
        if option in _ENVIRONMENT_OPTIONS:
            raise LaunchArgumentError(
                f"Remove {option} from MARIMO_ARGS. "
                "Marimo Studio prepares the notebook environment."
            )
        if option == "--proxy":
            raise LaunchArgumentError(
                "The Marimo Studio direct launcher does not support --proxy."
            )


@dataclass(frozen=True)
class _AuthOptions:
    token_enabled: bool
    token_password: str | None
    token_file: str | None


def _parse_auth_options(marimo_args: tuple[str, ...]) -> _AuthOptions:
    token_enabled = True
    token_password: str | None = None
    token_file: str | None = None
    index = 0
    while index < len(marimo_args):
        argument = marimo_args[index]
        if argument == "--no-token":
            token_enabled = False
        elif argument == "--token":
            token_enabled = True
        elif argument == "--token-password":
            if index + 1 >= len(marimo_args):
                raise LaunchArgumentError("--token-password requires a value")
            index += 1
            token_password = marimo_args[index]
        elif argument.startswith("--token-password="):
            token_password = argument.partition("=")[2]
        elif argument == "--token-password-file":
            if index + 1 >= len(marimo_args):
                raise LaunchArgumentError("--token-password-file requires a path")
            index += 1
            token_file = marimo_args[index]
        elif argument.startswith("--token-password-file="):
            token_file = argument.partition("=")[2]
        index += 1
    if token_password is not None and token_file is not None:
        raise LaunchArgumentError(
            "Only one of --token-password or --token-password-file may be specified."
        )
    return _AuthOptions(
        token_enabled=token_enabled,
        token_password=token_password,
        token_file=token_file,
    )


def _replace_token_file(
    marimo_args: tuple[str, ...],
    token_file: str,
) -> tuple[str, ...]:
    rewritten: list[str] = []
    index = 0
    while index < len(marimo_args):
        argument = marimo_args[index]
        if argument == "--token-password-file":
            rewritten.extend((argument, token_file))
            index += 2
            continue
        if argument.startswith("--token-password-file="):
            rewritten.append(f"--token-password-file={token_file}")
        else:
            rewritten.append(argument)
        index += 1
    return tuple(rewritten)


def _remove_token_file(marimo_args: tuple[str, ...]) -> tuple[str, ...]:
    filtered: list[str] = []
    index = 0
    while index < len(marimo_args):
        argument = marimo_args[index]
        if argument == "--token-password-file":
            index += 2
            continue
        if not argument.startswith("--token-password-file="):
            filtered.append(argument)
        index += 1
    return tuple(filtered)


def _read_token_file(token_file: str) -> tuple[str, str]:
    path = Path(token_file).expanduser().resolve()
    try:
        token_password = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        raise LaunchArgumentError(
            f"Token password file not found: {token_file}"
        ) from None
    except PermissionError:
        raise LaunchArgumentError(
            f"Permission denied reading token password file: {token_file}"
        ) from None
    except UnicodeError as error:
        raise LaunchArgumentError(
            f"Token password file is not valid UTF-8: {token_file}"
        ) from error
    except OSError as error:
        raise LaunchArgumentError(
            f"Error reading token password file {token_file!r}: {error}"
        ) from error
    if not token_password:
        raise LaunchArgumentError(f"No token password found in file: {token_file}")
    return str(path), token_password


def browser_auth(
    marimo_args: tuple[str, ...],
    *,
    open_browser: bool,
    token_factory: Callable[[int], str] | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Resolve Marimo token options and the browser access token."""
    options = _parse_auth_options(marimo_args)
    token_password = options.token_password
    if options.token_file:
        if options.token_file == "-":
            if not open_browser:
                return marimo_args, None
            raise LaunchArgumentError(
                "Use --headless when --token-password-file reads from stdin"
            )
        token_file, token_password = _read_token_file(options.token_file)
        marimo_args = _replace_token_file(marimo_args, token_file)
    elif options.token_file == "" and open_browser and options.token_enabled:
        marimo_args = _remove_token_file(marimo_args)

    if token_password:
        return marimo_args, token_password
    if not open_browser or not options.token_enabled:
        return marimo_args, None

    factory = token_factory or secrets.token_urlsafe
    token_password = factory(24)
    return (*marimo_args, "--token-password", token_password), token_password


def prepare_launch(
    request: LaunchRequest,
    *,
    token_factory: Callable[[int], str] | None = None,
) -> LaunchPlan:
    """Configure the view and return its native Marimo launch plan."""
    validate_base_url(request.base_url)
    validate_marimo_args(request.marimo_args)
    marimo_args, access_token = browser_auth(
        request.marimo_args,
        open_browser=request.open_browser,
        token_factory=token_factory,
    )
    setup = ensure_view(request.notebook, request.view_name)
    studio = setup.studio
    if studio is None:
        raise RuntimeError("View setup did not return a Studio configuration")

    query = {"access_token": access_token} if access_token is not None else {}
    suffix = f"?{urlencode(query)}" if query else ""
    public_host = "127.0.0.1" if request.host in {"0.0.0.0", "::"} else request.host
    url_host = f"[{public_host}]" if ":" in public_host else public_host
    origin = f"http://{url_host}:{request.port}"
    selected = setup.name
    command = environment_command(
        studio,
        [
            "marimo",
            "edit",
            str(studio.notebook),
            "--host",
            request.host,
            "--port",
            str(request.port),
            "--base-url",
            request.base_url,
            "--headless",
            "--no-sandbox",
            *marimo_args,
        ],
    )
    working_directory = (
        studio.notebook.parent if studio.uses_notebook_config else studio.root
    )
    return LaunchPlan(
        studio_url=(f"{origin}{studio_url(request.base_url, selected)}{suffix}"),
        view_url=f"{origin}{view_url(request.base_url, selected)}{suffix}",
        command=tuple(command),
        working_directory=working_directory,
        open_browser=request.open_browser,
    )


def _open_later(url: str) -> None:
    timer = threading.Timer(1.2, webbrowser.open, args=(url,))
    timer.daemon = True
    timer.start()


def execute_launch(
    plan: LaunchPlan,
    *,
    open_url: Callable[[str], None] | None = None,
    run_process: Callable[..., subprocess.CompletedProcess[object]] | None = None,
) -> int:
    """Open the selected Studio URL and run the planned Marimo process."""
    if plan.open_browser:
        (open_url or _open_later)(plan.studio_url)
    runner = run_process or subprocess.run
    return runner(
        list(plan.command),
        cwd=plan.working_directory,
        check=False,
        stdout=sys.stderr,
        stderr=sys.stderr,
    ).returncode
