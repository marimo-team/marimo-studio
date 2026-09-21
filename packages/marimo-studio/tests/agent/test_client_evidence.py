from __future__ import annotations

import pytest

import marimo_studio._browser_client.transport as browser_transport


def test_http_errors_preserve_structured_details() -> None:
    with pytest.raises(browser_transport.AgentRequestError) as raised:
        browser_transport._raise_response_error(
            404,
            b'{"error":"view-not-found","message":"missing",'
            b'"view":"missing","available_views":["dashboard"],'
            b'"hint":"Select an available view.","transient":true}',
        )

    assert raised.value.public_hint == "Select an available view."
    assert raised.value.transient is True
    assert raised.value.diagnostic_details() == {
        "view": "missing",
        "available_views": ["dashboard"],
    }
