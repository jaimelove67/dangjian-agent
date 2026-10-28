// 团组织推优资格：与后端 app/rules/member_league.py 同一口径。
// 中央《共青团推优入党工作实施办法（试行）》：推优对象须年满18周岁、入团满1年。
// 只按档案中已登记的日期核算；缺项时显示“待补录”，不默认通过。

export const LEAGUE_MIN_AGE = 18;
export const LEAGUE_MIN_TENURE_YEARS = 1;

function parts(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

function pad(value) {
  return String(value).padStart(2, "0");
}

function iso({ year, month, day }) {
  return `${year}-${pad(month)}-${pad(day)}`;
}

function addYears(value, years) {
  const year = value.year + years;
  if (value.month === 2 && value.day === 29) {
    const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
    return { year, month: 2, day: leap ? 29 : 28 };
  }
  return { year, month: value.month, day: value.day };
}

function compare(left, right) {
  return iso(left).localeCompare(iso(right));
}

function ageOn(birth, on) {
  let years = Math.max(0, on.year - birth.year);
  if (compare(on, addYears(birth, years)) < 0) years -= 1;
  return Math.max(0, years);
}

export function leagueEligibility(birthDate, leagueJoinedOn, on = new Date()) {
  const birth = parts(birthDate);
  const joined = parts(leagueJoinedOn);
  const today = {
    year: on.getFullYear(),
    month: on.getMonth() + 1,
    day: on.getDate(),
  };
  const missing = [];
  if (!birth) missing.push("出生年月");
  if (!joined) missing.push("入团时间");
  if (missing.length) {
    return {
      eligible: null,
      note: `档案缺少${missing.join("、")}，无法核验推优资格；请先补录`,
    };
  }
  if (compare(birth, today) > 0) {
    return { eligible: false, note: "出生年月晚于今天，请核对档案" };
  }
  if (compare(joined, today) > 0) {
    return { eligible: false, note: "入团时间晚于今天，请核对档案" };
  }
  const age = ageOn(birth, today);
  if (age < LEAGUE_MIN_AGE) {
    return {
      eligible: false,
      note: `推优对象须年满18周岁（档案年龄 ${age} 周岁）`,
    };
  }
  if (compare(today, addYears(joined, LEAGUE_MIN_TENURE_YEARS)) < 0) {
    return {
      eligible: false,
      note: `推优对象须入团满1年（入团时间 ${iso(joined)}）`,
    };
  }
  let note = `已年满18周岁（${age} 周岁），入团已满1年`;
  if (age > 28) note += "；年龄超过28周岁，请组织核对是否仍适用团组织推优";
  return { eligible: true, note };
}

export function todayIso() {
  return iso({
    year: new Date().getFullYear(),
    month: new Date().getMonth() + 1,
    day: new Date().getDate(),
  });
}
