"""Outbox dispatcher delivery logic (unit-level, no database)."""

import base64
import hashlib
import hmac

from agentrum.services.notification_dispatcher import _format_text, feishu_sign


def test_feishu_sign_matches_reference_algorithm():
    timestamp = 1700000000
    secret = "my-sign-secret"
    expected = base64.b64encode(
        hmac.new(f"{timestamp}\n{secret}".encode(), digestmod=hashlib.sha256).digest()
    ).decode()
    assert feishu_sign(secret, timestamp) == expected


def test_format_text_contains_identity_and_version():
    text = _format_text(
        {
            "kind": "MCPServer",
            "namespace": "payment",
            "name": "payment-gateway",
            "version": 3,
            "tag": "v1.2.0",
            "subscriber_team": "support",
        }
    )
    assert "MCPServer" in text
    assert "payment/payment-gateway" in text
    assert "v1.2.0" in text
    assert "support" in text
