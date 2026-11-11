import assert from "node:assert/strict";
import test from "node:test";

import { normalizeAnswerMarkdown, withCitationLinks } from "../src/answer-markdown.js";

test("inline bullets after a colon become a real markdown list", () => {
  assert.equal(
    normalizeAnswerMarkdown("依据如下： * 第一条\n* 第二条"),
    "依据如下：\n\n* 第一条\n* 第二条",
  );
});

test("inline ordered items after a colon become a real markdown list", () => {
  assert.equal(
    normalizeAnswerMarkdown("要求如下： 1. 第一条\n2. 第二条"),
    "要求如下：\n\n1. 第一条\n2. 第二条",
  );
});

test("normalization keeps code, italics and decimal numbers intact", () => {
  assert.equal(
    normalizeAnswerMarkdown("代码 `依据： * 第一条`；注意： *斜体*；时间： 1.5 小时"),
    "代码 `依据： * 第一条`；注意： *斜体*；时间： 1.5 小时",
  );
});

test("numeric citations that exist become internal citation links", () => {
  assert.equal(
    withCitationLinks("结论 [1]，另有依据 [2]。", [1, 2]),
    "结论 [1](citation:1)，另有依据 [2](citation:2)。",
  );
});

test("unknown citation numbers and non-numeric brackets stay unchanged", () => {
  assert.equal(
    withCitationLinks("结论 [9]，范围 [当前账号角色与权限范围]。", [1]),
    "结论 [9]，范围 [当前账号角色与权限范围]。",
  );
});

test("fenced code and inline code keep literal citation numbers", () => {
  const source = "正文 [1]\n```\n[1]\n```\n行内 `[1]` 也保留";
  assert.equal(
    withCitationLinks(source, [1]),
    "正文 [1](citation:1)\n```\n[1]\n```\n行内 `[1]` 也保留",
  );
});

test("existing markdown links and reference definitions are not rewritten", () => {
  assert.equal(
    withCitationLinks("[1](https://example.com) 和 [1]: https://example.com", [1]),
    "[1](https://example.com) 和 [1]: https://example.com",
  );
});

test("empty content and empty citation list are safe", () => {
  assert.equal(withCitationLinks("", [1]), "");
  assert.equal(withCitationLinks("结论 [1]", []), "结论 [1]");
});
