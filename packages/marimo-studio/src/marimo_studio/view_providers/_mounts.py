"""Expose the provider mount attribute without loading document parsers."""

from marimo_studio.view_providers._validation import validate_projection_site_id

MOUNT_ATTRIBUTE = "data-marimo-studio-site"


def mount_attribute(site_id: str) -> tuple[str, str]:
    """Return the canonical runtime mount attribute for one projection site."""
    return MOUNT_ATTRIBUTE, validate_projection_site_id(
        site_id,
        field="projection site id",
    )
