// 政治审查四项内容与八类不合格情形，口径与后端 app/rules/political_review.py 一致。
export const POLITICAL_REVIEW_ASPECTS = [
  ["party_line", "对党的路线方针政策的态度"],
  ["political_history", "政治历史和重大政治斗争中的表现"],
  ["law_and_ethics", "遵纪守法和遵守社会公德情况"],
  ["relatives", "直系亲属和主要社会关系的政治情况"],
];

export const POLITICAL_REVIEW_NEGATIVE_CATEGORIES = [
  ["religion", "不信仰马克思主义 / 信仰宗教"],
  ["unsteady", "重大政治斗争中立场不坚定"],
  ["violation", "涉嫌违纪违法"],
  ["mass_line", "群众观念淡薄，不起带头作用"],
  ["morality", "道德品质、生活作风问题"],
  ["dishonesty", "对党不忠诚老实、政审弄虚作假或不配合"],
  ["relatives_risk", "直系亲属和主要社会关系有危害国家安全、民族分裂、暴恐、宗教极端、邪教、严重违法违纪行为而本人不能划清界限"],
  ["other", "其他情形"],
];
