import uuid

import pytest

from agentrum.auth import security


def test_password_hash_roundtrip():
    hashed = security.hash_password("s3cret-password")
    assert hashed != "s3cret-password"
    assert security.verify_password("s3cret-password", hashed)
    assert not security.verify_password("wrong-password", hashed)


def test_access_token_roundtrip():
    user_id = uuid.uuid4()
    token = security.create_access_token(user_id)
    assert security.decode_access_token(token) == user_id


def test_access_token_invalid():
    with pytest.raises(ValueError):
        security.decode_access_token("not-a-token")


def test_api_token_format_and_hash():
    raw, digest = security.new_api_token()
    assert raw.startswith(security.API_TOKEN_PREFIX)
    assert len(digest) == 64  # sha256 hex
    assert security.hash_api_token(raw) == digest
