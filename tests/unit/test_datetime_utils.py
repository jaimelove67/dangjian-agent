"""日期时间工具函数测试"""
from datetime import date, datetime

import pytest

from app.utils.datetime import to_date


class TestToDate:
    def test_none_returns_none(self):
        assert to_date(None) is None

    def test_date_returns_itself(self):
        d = date(2020, 1, 1)
        assert to_date(d) == d

    def test_datetime_returns_date(self):
        dt = datetime(2020, 1, 1, 12, 30)
        assert to_date(dt) == date(2020, 1, 1)

    def test_iso_string_parsed(self):
        assert to_date("2020-01-01") == date(2020, 1, 1)

    def test_iso_string_with_spaces_parsed(self):
        assert to_date("  2020-01-01  ") == date(2020, 1, 1)

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            to_date("not-a-date")

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError):
            to_date(12345)
