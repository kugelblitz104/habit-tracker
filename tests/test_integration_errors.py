"""Unit tests for legible integration transport-error messages.

A connect/DNS failure is the most common on-prem misconfiguration and httpx
reports it as an opaque ``[Errno -2] Name or service not known``. These lock in
that the message names the host and explains the *backend* must reach it.
"""

import httpx

from habit_tracker.services.integrations.base import transport_error_message


def test_connect_error_names_host_and_explains_backend_reachability():
    exc = httpx.ConnectError("[Errno -2] Name or service not known")
    msg = transport_error_message(
        exc, "Azure DevOps", "https://tfs.prd.costargroup.com"
    )
    assert "Azure DevOps" in msg
    assert "tfs.prd.costargroup.com" in msg
    # The opaque errno is replaced, and the real cause is spelled out.
    assert "Errno" not in msg
    assert "VPN" in msg


def test_connect_timeout_uses_the_connect_branch():
    exc = httpx.ConnectTimeout("timed out establishing connection")
    msg = transport_error_message(exc, "Azure DevOps", "https://example.com")
    assert msg.startswith("Couldn't reach Azure DevOps")


def test_read_timeout_reports_a_slow_host():
    exc = httpx.ReadTimeout("the read timed out")
    msg = transport_error_message(exc, "GitHub")
    assert "GitHub timed out" in msg


def test_other_http_errors_pass_through_verbatim():
    exc = httpx.HTTPError("some other transport failure")
    msg = transport_error_message(exc, "GitHub")
    assert msg == "GitHub request failed: some other transport failure"


def test_message_without_host_omits_the_location_clause():
    exc = httpx.ConnectError("boom")
    msg = transport_error_message(exc, "GitHub")
    assert " at " not in msg
    assert "Couldn't reach GitHub." in msg
