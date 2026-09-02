"""Render provider diagnostics and the starter catalog."""

from __future__ import annotations

from collections.abc import Mapping

from marimo_studio._cli.print import echo, green, light_blue, yellow
from marimo_studio._views.records import Starter
from marimo_studio.view_providers import ProviderAvailability


def _status(availability: ProviderAvailability) -> str:
    if availability.available:
        version = f" {availability.version}" if availability.version else ""
        return green(f"available{version}")
    return yellow("unavailable")


def _recovery(availability: ProviderAvailability) -> None:
    if availability.available:
        return
    if availability.reason:
        echo(f"  {light_blue('reason')} {availability.reason}")
    if availability.action:
        echo(f"  {light_blue('recover')} {availability.action}", err=True)


def _availability(record: Mapping[str, object]) -> ProviderAvailability | None:
    raw = record.get("availability")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("Provider diagnostic lacks availability")
    return ProviderAvailability(
        available=bool(raw.get("available")),
        version=raw.get("version") or None,
        reason=raw.get("reason") or None,
        action=raw.get("action") or None,
    )


def render_provider(record: Mapping[str, object]) -> None:
    """Write one compact provider diagnostic record."""
    key = str(record.get("key") or record["registration"])
    availability = _availability(record)
    if not record.get("loaded"):
        echo(f"{yellow('unavailable')} {key}")
        _provider_identity(record)
        if error := record.get("error"):
            echo(f"  {light_blue('error')} {error}", err=True)
        if availability is not None:
            _recovery(availability)
        return
    if availability is None:
        raise TypeError("Provider diagnostic lacks availability")
    echo(f"{_status(availability)} {key}")
    _provider_identity(record)
    if summary := record.get("summary"):
        echo(f"  {summary}")
    starters = record.get("starters")
    if isinstance(starters, list) and starters:
        echo(f"  {light_blue('starters')} {', '.join(map(str, starters))}")
    _recovery(availability)


def _provider_identity(record: Mapping[str, object]) -> None:
    echo(f"  {light_blue('distribution')} {record['distribution']}")
    echo(f"  {light_blue('registration')} {record['registration']}")
    echo(f"  {light_blue('installed')} {record['version']}")


def render_starter(starter: Starter) -> None:
    """Write one starter with availability and recovery."""
    echo(f"{_status(starter.availability)} {starter.id}")
    echo(f"  {starter.summary}")
    echo(f"  {light_blue('provider')} {starter.provider}")
    _recovery(starter.availability)
