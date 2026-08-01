"""Build Studio URLs beneath Marimo's public base path."""

STUDIO_PATH = "/studio"
SUPPORT_PATH = "/_marimo-studio"


def public_url(base_url: str, path: str = "") -> str:
    """Join a root-relative path to Marimo's public base URL."""
    base_path = base_url.rstrip("/")
    suffix = path if path.startswith("/") or not path else f"/{path}"
    return f"{base_path}{suffix}" or "/"


def studio_url(base_url: str, view_name: str | None = None) -> str:
    """Return the public Studio workspace URL."""
    suffix = f"{STUDIO_PATH}/{view_name}/" if view_name else f"{STUDIO_PATH}/"
    return public_url(base_url, suffix)


def view_url(base_url: str, view_name: str) -> str:
    """Return the public standalone URL for a named view."""
    return public_url(base_url, f"/{view_name}/")
