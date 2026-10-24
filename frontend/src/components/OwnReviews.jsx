import { formatBusinessTime } from "../business-time";
import { get, rows } from "../business-api";
import { BusinessTable, ResourceState, useResource } from "./BusinessForms";

export function OwnReviews() {
  const reviews = useResource(() => get("/member/self/reviews"), []);
  return <section className="business-section"><header><h3>本人民主评议结果</h3><button className="button secondary" onClick={reviews.reload}>刷新结果</button></header><p>仅显示本人经另一位组织人员审核后生效的结果。</p><ResourceState resource={reviews} /><BusinessTable items={rows(reviews.value)} empty="暂无已生效的本人民主评议结果" columns={[["年度", r => r.year], ["评定等次", r => r.grade_label], ["评定依据", r => r.basis], ["支部意见", r => r.branch_opinion], ["整改要求", r => r.rectification || "—"], ["审核时间", r => r.reviewed_at ? formatBusinessTime(r.reviewed_at) : "未登记"]]} /></section>;
}
