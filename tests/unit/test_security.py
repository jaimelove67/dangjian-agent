"""安全模块单元测试：密码哈希与 JWT 令牌"""
import pytest

from app.core.security import (
    TokenError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import UserRole


class TestPasswordHashing:
    """密码哈希与校验"""

    def test_hash_then_verify_succeeds(self):
        hashed = hash_password("Secret@123", rounds=4)
        assert hashed != "Secret@123"
        assert verify_password("Secret@123", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("Secret@123", rounds=4)
        assert verify_password("wrong", hashed) is False

    def test_empty_inputs_fail_safely(self):
        assert verify_password("", "somehash") is False
        assert verify_password("somepass", "") is False

    def test_empty_password_rejected_on_hash(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_long_password_is_truncated_safely(self):
        # 超过 72 字节不应抛错
        long_password = "a" * 200
        hashed = hash_password(long_password, rounds=4)
        assert verify_password(long_password, hashed) is True


class TestJWT:
    """JWT 签发与校验"""

    def test_access_token_roundtrip(self):
        token = create_access_token("u1", tenant_id="t1", role=UserRole.MEMBER)
        payload = decode_token(token, expected_type=TokenType.ACCESS)
        assert payload["sub"] == "u1"
        assert payload["tenant_id"] == "t1"
        assert payload["role"] == "member"
        assert payload["type"] == "access"

    def test_refresh_token_type_mismatch_rejected(self):
        token = create_refresh_token("u1", tenant_id="t1", role=UserRole.MEMBER)
        with pytest.raises(TokenError):
            decode_token(token, expected_type=TokenType.ACCESS)

    def test_invalid_token_rejected(self):
        with pytest.raises(TokenError):
            decode_token("not-a-jwt")

    def test_missing_token_rejected(self):
        with pytest.raises(TokenError):
            decode_token("")

    def test_expired_token_rejected(self):
        token = create_access_token("u1", tenant_id="t1", expires_minutes=-1)
        with pytest.raises(TokenError):
            decode_token(token)
