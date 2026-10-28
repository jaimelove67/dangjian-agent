"""团组织推优资格核验。

依据《共青团推优入党工作实施办法（试行）》：推优对象应当是**年满18周岁**的优秀共青团员，
推荐对象应有**1年以上团龄**。系统只按档案中已登记的出生年月、入团时间核算，不推算、不补造
日期；档案缺失时明确提示补录，不默认通过。
"""

from datetime import date

MIN_AGE = 18
MIN_LEAGUE_TENURE_YEARS = 1


def add_years(value: date, years: int) -> date:
    """按周年计算；2月29日在非闰年按2月28日处理。"""
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def age_on(birth_date: date, on: date) -> int:
    """返回 ``on`` 当日的周岁；未到生日按上一周岁计算。"""
    years = max(0, on.year - birth_date.year)
    if on < add_years(birth_date, years):
        years -= 1
    return max(0, years)


def league_eligibility(
    birth_date: date | None,
    league_joined_on: date | None,
    on: date,
) -> tuple[bool | None, str]:
    """核验推优资格。

    返回 ``(结论, 说明)``：``True`` 通过，``False`` 明确不符，``None`` 档案缺项无法判断。
    ``on`` 是推荐日期，资格按推荐当日核算，便于补登历史推优记录。
    """
    missing = []
    if birth_date is None:
        missing.append("出生年月")
    if league_joined_on is None:
        missing.append("入团时间")
    if missing:
        return (
            None,
            f"档案缺少{'、'.join(missing)}，无法核验推优资格；请先在党员档案中补录",
        )
    assert birth_date is not None and league_joined_on is not None

    if birth_date > on:
        return False, "出生年月晚于推荐日期，请核对档案"
    if league_joined_on > on:
        return False, "入团时间晚于推荐日期，请核对档案"

    age = age_on(birth_date, on)
    if age < MIN_AGE:
        return False, (f"推优对象须年满18周岁（推荐日 {on.isoformat()}，档案年龄 {age} 周岁）")

    anniversary = add_years(league_joined_on, MIN_LEAGUE_TENURE_YEARS)
    if anniversary > on:
        return False, (
            "推优对象须入团满1年"
            f"（入团时间 {league_joined_on.isoformat()}，推荐日 {on.isoformat()}）"
        )

    note = f"推荐日已年满18周岁（{age} 周岁），入团已满1年"
    if age > 28:
        note += "；年龄超过28周岁，请组织核对是否仍适用团组织推优"
    return True, note
