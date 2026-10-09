"""数据脱敏工具单元测试"""
from app.core.desensitization import (
    mask_dict,
    mask_email,
    mask_id_card,
    mask_name,
    mask_number,
    mask_phone,
)


class TestMaskFunctions:
    def test_id_card(self):
        assert mask_id_card("110101199001011234") == "110101********1234"

    def test_id_card_too_short(self):
        assert mask_id_card("123") == "***"
        assert mask_id_card("12345") == "***"
        assert mask_id_card("1234567890") == "123456********7890"

    def test_phone(self):
        assert mask_phone("13812345678") == "138****5678"

    def test_phone_too_short(self):
        assert mask_phone("12345") == "***"

    def test_email(self):
        assert mask_email("alice@example.com") == "a***@example.com"

    def test_email_invalid(self):
        assert mask_email("not-an-email") == "***"
        assert mask_email("@example.com") == "***"

    def test_name(self):
        assert mask_name("张三丰") == "张**"
        assert mask_name("李") == "李"

    def test_number(self):
        assert mask_number("6222021234567890", head=4, tail=4) == "6222********7890"
        assert mask_number("123", head=4, tail=4) == "***"

    def test_none_is_passthrough(self):
        assert mask_id_card(None) is None
        assert mask_phone(None) is None
        assert mask_email(None) is None


class TestMaskDict:
    def test_nested_dict_masked_and_original_untouched(self):
        data = {
            "user": {"phone": "13812345678", "id_card": "110101199001011234"},
            "items": [{"email": "a@b.com"}],
            "count": 1,
        }
        masked = mask_dict(data)

        assert masked["user"]["phone"] == "138****5678"
        assert masked["user"]["id_card"] == "110101********1234"
        assert masked["items"][0]["email"] == "a***@b.com"
        assert masked["count"] == 1
        # 原对象不被修改
        assert data["user"]["phone"] == "13812345678"

    def test_custom_fields(self):
        data = {"name": "张三", "phone": "13812345678"}
        masked = mask_dict(data, sensitive_fields={"name"})
        assert masked["name"] == "张*"
        assert masked["phone"] == "13812345678"
