// 发展党员档案卷内目录（38 项材料），口径与后端 app/rules/archive_checklist.py 一致。
// 依据《湖南科技职业学院发展党员综合资料（最终版 20241128）》整理；改一处必须改另一处。
// 这里只放界面需要的字段；某项对应哪种归档材料 / 程序节点由后端判定，前端不重复实现。

export const ARCHIVE_CARRIERS = {
  paste: "粘贴页",
  sign: "签署页",
  placeholder: "占位页",
};

export const ARCHIVE_SECTIONS = [
  { key: "application", label: "一、申请入党" },
  { key: "activist", label: "二、入党积极分子的确定和培养教育" },
  { key: "candidate", label: "三、党员发展对象的确定和考察" },
  { key: "reception", label: "四、预备党员的接收" },
  { key: "probationary", label: "五、预备党员的教育考察和转正" },
];

// [编号, 材料名称, 阶段键, 载体, 是否必备, 手册页码, 备注]
const RAW = [
  ["m01", 1, "入党申请书", "application", "paste", true, 3, "一般要求书写、本人签名；支部复印一份留存"],
  ["m02", 2, "党支部派专人同入党申请人谈话记录", "application", "sign", true, 4, "收到入党申请书后 1 个月内谈话"],
  ["m03", 3, "优秀大学生入党团组织推优（党员推荐）表", "activist", "paste", true, 7, "推优与党员推荐二选一"],
  ["m04", 4, "确定入党积极分子意见", "activist", "sign", true, 8, "确定 1–2 名培养联系人"],
  ["m05", 5, "党支部委员会讨论确定入党积极分子记录", "activist", "sign", true, 9, "无记名投票表决"],
  ["m06", 6, "确定入党积极分子公示", "activist", "sign", true, 11, ""],
  ["m07", 7, "确定入党积极分子基层党委备案意见", "activist", "sign", true, 12, "党总支审议、基层党委备案两级"],
  ["m08", 8, "入党积极分子培养考察登记表", "activist", "sign", true, 13, "4 个季度考察 + 半年考察评价"],
  ["m09", 9, "入党积极分子思想汇报", "activist", "paste", true, 18, ""],
  ["m10", 10, "入党积极分子培训班结业证书", "activist", "paste", true, 19, ""],
  ["m11", 11, "自传", "candidate", "paste", true, 23, ""],
  ["m12", 12, "确定党员发展对象人选意见", "candidate", "sign", true, 24, "须为入党积极分子满 1 年"],
  ["m13", 13, "党内外群众意见座谈会记录", "candidate", "paste", true, 25, ""],
  ["m14", 14, "党支部委员会讨论确定党员发展对象人选记录", "candidate", "sign", true, 26, ""],
  ["m15", 15, "确定为党员发展对象公示情况", "candidate", "sign", true, 28, "不少于 5 个工作日；同步确定 2 名入党介绍人"],
  ["m16", 16, "确定党员发展对象基层党委备案意见", "candidate", "sign", true, 29, ""],
  ["m17", 17, "函调材料", "candidate", "paste", false, 30, "按需形成，不列为必备"],
  ["m18", 18, "政治审查情况报告", "candidate", "paste", true, 31, "未经政审不能发展入党"],
  ["m19", 19, "党员发展对象培训班学员登记表", "candidate", "sign", true, 32, "一式两份"],
  ["m20", 20, "党员发展对象培训班结业证书", "candidate", "paste", true, 33, ""],
  ["m21", 21, "支委会审查意见", "reception", "paste", true, 37, ""],
  ["m22", 22, "基层党委预审意见", "reception", "sign", true, 38, "预审合格后发放《入党志愿书》"],
  ["m23", 23, "接收预备党员公示情况", "reception", "sign", true, 39, "不少于 5 个工作日"],
  ["m24", 24, "《中国共产党入党志愿书》", "reception", "placeholder", true, 40, "正式文件单独印制，另按 19 项核对清单填写"],
  ["m25", 25, "党支部大会讨论接收预备党员会议记录", "reception", "sign", true, 41, "赞成须超应到会有表决权正式党员半数"],
  ["m26", 26, "对预备党员进行备案的报告", "reception", "paste", true, 43, ""],
  ["m27", 27, "基层党委组织部备案意见", "reception", "sign", true, 44, ""],
  ["m28", 28, "预备党员参加入党宣誓情况", "probationary", "sign", true, 48, "可粘贴宣誓照片"],
  ["m29", 29, "预备党员考察表", "probationary", "placeholder", true, 49, "表体须另附"],
  ["m30", 30, "预备党员思想汇报", "probationary", "paste", true, 50, "每半年至少一次"],
  ["m31", 31, "预备党员培训班结业证书", "probationary", "paste", true, 51, ""],
  ["m32", 32, "转正申请书", "probationary", "paste", true, 52, "预备期满前 1–2 周提出"],
  ["m33", 33, "党内外群众意见座谈会记录", "probationary", "paste", true, 53, ""],
  ["m34", 34, "支部委员会审查意见", "probationary", "sign", true, 54, ""],
  ["m35", 35, "拟接收正式党员公示情况", "probationary", "sign", true, 55, "公示一般 7 天"],
  ["m36", 36, "党支部大会讨论转为正式党员会议记录", "probationary", "sign", true, 56, ""],
  ["m37", 37, "对转为中共正式党员进行审批的请示", "probationary", "paste", true, 58, ""],
  ["m38", 38, "学校党委对预备党员转正的审批情况", "probationary", "sign", true, 59, ""],
];

export const ARCHIVE_CHECKLIST = RAW.map(
  ([code, no, name, section, carrier, required, page, note]) => ({
    code,
    no,
    name,
    section,
    carrier,
    carrierLabel: ARCHIVE_CARRIERS[carrier] || "",
    required,
    page,
    note,
  })
);

export function archiveItemsOf(section) {
  return ARCHIVE_CHECKLIST.filter((item) => item.section === section);
}
