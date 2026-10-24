import { useEffect, useState } from "react";
import { useApp } from "../app-context";
import { Tabs } from "../components";
import { LiveMemberBusiness } from "./LiveMemberBusiness";

export function LiveBusinessWorkspace({ children, kind = "development" }) {
  const { routeParams = {} } = useApp();
  const primary = kind === "life" ? "会议与组织生活" : "发展过程与材料";
  const advanced = kind === "life" ? "民主评议办理" : "选优、接转与报送";
  const [tab, setTab] = useState(routeParams.businessTab ? advanced : primary);
  useEffect(() => { if (routeParams.businessTab) setTab(advanced); }, [routeParams.businessTab, advanced]);
  return <><Tabs items={[primary, advanced]} active={tab} onChange={setTab} />
    {tab === primary ? children : <LiveMemberBusiness key={routeParams.businessTab || kind} initialTab={routeParams.businessTab || (kind === "life" ? "民主评议" : "选优结论")} />}</>;
}
