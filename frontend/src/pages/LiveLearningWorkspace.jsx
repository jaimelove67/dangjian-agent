import { useEffect, useState } from "react";
import { useApp } from "../app-context";
import { hasPermission } from "../roles";
import { Tabs } from "../components";
import { LiveLearning } from "./LiveLearning";
import { LiveEducation } from "./LiveEducation";
import { LiveSchoolBusiness } from "./LiveSchoolBusiness";

export function LiveLearningWorkspace() {
  const { session } = useApp();
  const items = hasPermission(session, "study.query") ? ["年度中心组计划", "学习任务", "课程与活动"] : ["课程与活动", "学习任务"];
  const [tab, setTab] = useState(items[0]);
  return <><Tabs items={items} active={tab} onChange={setTab} />{tab === "年度中心组计划" ? <LiveLearning /> : tab === "学习任务" ? <LiveSchoolBusiness mode="tasks" category="learning" /> : <LiveEducation />}</>;
}

export function LivePersonalWorkspace({ children }) {
  const { routeParams } = useApp();
  const [tab, setTab] = useState(routeParams.workspace === "tasks" ? "通知与任务" : "个人工作台");
  useEffect(() => { setTab(routeParams.workspace === "tasks" ? "通知与任务" : "个人工作台"); }, [routeParams.workspace, routeParams.recordId]);
  return <><Tabs items={["个人工作台", "学习与主题活动", "通知与任务"]} active={tab} onChange={setTab} />{tab === "个人工作台" ? children : tab === "学习与主题活动" ? <LiveEducation /> : <LiveSchoolBusiness mode="personal" />}</>;
}
