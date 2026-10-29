import { useState } from "react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { hasPermission } from "../roles";
import { request } from "../api";
import { PageHeader, SearchInput, Select, Modal, Pagination, downloadBlob } from "../components";
import { get, send, key, rows } from "../business-api";
import { BusinessForm, BusinessTable, BusinessToolbar, RecordTrace, ResourceState, Status, useResource } from "../components/BusinessForms";

export function LiveKnowledge() {
  const { session } = useApp(), { notify } = useStore();
  const can = p => hasPermission(session, p);
  const [q, setQ] = useState(""), [filter, setFilter] = useState(""), [page, setPage] = useState(1), [form, setForm] = useState(null), [selected, setSelected] = useState(null);
  const documents = useResource(() => get("/knowledge-docs", { q, page, page_size: 20, review_status: filter }), [q, filter, page]);
  const detail = useResource(() => selected ? get(`/knowledge-docs/${key(selected)}`) : Promise.resolve(null), [selected]);
  const chunks = useResource(() => selected ? get(`/knowledge-docs/${key(selected)}/chunks`, { page: 1, page_size: 100 }) : Promise.resolve(null), [selected]);
  const processing = useResource(() => selected ? get(`/knowledge-docs/${key(selected)}/processing-status`) : Promise.resolve(null), [selected]);
  const d = detail.value;
  function open(title, fields, submit, initial = {}, description, suggest) { setForm({ title, fields, submit, initial, description, suggest }); }
  function reload() { documents.reload(); detail.reload(); chunks.reload(); processing.reload(); }
  async function save(path, body, method = "POST") { const result = await send(path, body, method); reload(); notify("知识库记录已保存"); return result; }
  function upload() {
    open("上传制度文件并解析入库", [
      { name: "file", label: "原始文件（10MB以内）", type: "file", accept: ".pdf,.docx,.txt,.md" },
      { name: "doc_id", label: "稳定文件编号", value: `DOC-${crypto.randomUUID().slice(0, 12)}`, maxLength: 100 },
      { name: "title", label: "文件标题" }, { name: "issuer", label: "发文机关" },
      { name: "level", label: "制度层级", options: [["central", "中央"], ["provincial", "省级"], ["school", "校级"], ["department", "院系级"]], value: "school" },
      { name: "visibility", label: "可见范围", options: [["public", "公开"], ["school", "本校"], ["department", "本院系"], ["branch", "本支部"]], value: "school" },
      { name: "security_level", label: "数据级别", options: [["public", "公开资料"], ["internal", "内部资料"], ["sensitive", "敏感资料（仅本地模型）"], ["classified", "涉密材料（仅人工归档）"]], value: "public" },
      { name: "authority", label: "权威来源", options: [["party_constitution", "党章"], ["party_regulation", "党内法规"], ["superior_document", "上级文件"], ["school_policy", "学校制度"], ["reference", "参考资料"]], value: "school_policy" },
      { name: "effective_date", label: "生效日期", type: "date" }, { name: "expiration_date", label: "失效日期（长期有效可留空）", type: "date", required: false },
      { name: "doc_number", label: "发文字号", required: false }, { name: "tags", label: "主题标签（逗号分隔）" },
      { name: "summary", label: "摘要", type: "textarea", required: false },
    ], async values => {
      if (values.file.size > 10 * 1024 * 1024) throw new Error("文件不能超过10MB");
      const body = new FormData();
      for (const [name, value] of Object.entries(values)) if (value !== "" && value != null) body.append(name, value);
      body.append("file_name", values.file.name);
      const result = await request("/knowledge-docs", { method: "POST", body });
      reload(); setSelected(result.document.doc_id); notify(`入库成功，解析为${result.chunk_count}个片段；向量化及发布状态请单独核对`);
    }, {}, "选择文件后系统会读取正文，自动识别标题、发文字号、发文机关等信息并预填空白项，识别不到的请人工填写。上传后保存加密原件并解析正文。公开库内容经审核后发布；向量化需要已配置的模型，处理失败会显示实际原因。", {
      fileField: "file",
      run: file => {
        const body = new FormData();
        body.append("file", file);
        return request("/knowledge-docs/suggest-meta", { method: "POST", body, timeout: 120000 });
      },
      apply: s => ({
        title: s.title, issuer: s.issuer, level: s.level, doc_number: s.doc_number,
        effective_date: s.effective_date, expiration_date: s.expiration_date,
        tags: Array.isArray(s.tags) ? s.tags.join(",") : "", summary: s.summary,
      }),
    });
  }
  function replace() {
    open("上传新的原件版本", [{ name: "file", label: "新原件", type: "file", accept: ".pdf,.docx,.txt,.md" }, { name: "reason", label: "更换原件原因", type: "textarea" }], async values => {
      const body = new FormData(); body.append("file", values.file); body.append("reason", values.reason); body.append("expected_revision", String(d.content_revision));
      await request(`/knowledge-docs/${key(d.doc_id)}/content`, { method: "PUT", body }); reload(); notify("原件版本已更新，相关引用和审核需复核");
    });
  }
  function review() { open("审核知识发布", [{ name: "decision", label: "发布决定", options: [["approve", "批准发布"], ["reject", "退回补充"]] }, { name: "note", label: "审核意见", type: "textarea", max: 500 }], values => save(`/knowledge-docs/${key(d.doc_id)}/review`, values)); }
  function metadata() {
    open("修正文件信息", [
      { name: "title", label: "文件标题" }, { name: "issuer", label: "发文机关" },
      { name: "doc_number", label: "发文字号", required: false },
      { name: "effective_date", label: "生效日期", type: "date" },
      { name: "expiration_date", label: "失效日期", type: "date", required: false },
      { name: "tags", label: "主题标签（逗号分隔）" },
      { name: "summary", label: "摘要", type: "textarea", required: false },
      { name: "reason", label: "修正依据", type: "textarea" },
    ], values => save(`/knowledge-docs/${key(d.doc_id)}/metadata`, { ...values, expiration_date: values.expiration_date || null }, "PATCH"), { ...d, tags: d.tags.join(",") });
  }
  function maintenance() { open("确认制度供给复核", [{ name: "note", label: "复核依据与说明", type: "textarea", max: 500 }], values => save(`/knowledge-docs/${key(d.doc_id)}/maintenance`, values)); }
  function changeStatus() { open("变更文件效力状态", [{ name: "status", label: "文件状态", options: [["effective", "有效"], ["expired", "已失效"], ["abolished", "已废止"]] }, { name: "reason", label: "变更依据", type: "textarea", max: 500 }], values => save(`/knowledge-docs/${key(d.doc_id)}/status`, values, "PATCH")); }
  function embed() { open("为当前版本建立检索向量", [{ name: "confirm", label: "确认按资料级别调用已配置的模型", type: "checkbox" }], async values => {
    if (!values.confirm) throw new Error("请先确认资料级别与模型用途");
    const result = await save("/embeddings/embed", { doc_id: d.doc_id }); notify(`已向量化${result.embedded_count}个片段`);
  }); }
  return <section className="panel workspace-panel"><PageHeader title="党建工作库" subtitle="制度原件、解析片段、人工复核及检索处理状态" action={can("knowledge.manage") && <button className="button primary" onClick={upload}>上传制度文件</button>} />
    <BusinessToolbar actions={<button className="button secondary" onClick={reload}>刷新</button>}><SearchInput value={q} placeholder="搜索文件标题、机关或编号" onChange={e => { setQ(e.target.value); setPage(1); }} />{can("knowledge.manage") && <Select label="发布状态" value={filter} onChange={e => { setFilter(e.target.value); setPage(1); }}><option value="">全部发布状态</option><option value="pending">待审核</option><option value="published">已发布</option><option value="rejected">已退回</option></Select>}</BusinessToolbar>
    <ResourceState resource={documents} /><BusinessTable items={rows(documents.value)} columns={[["制度文件", r => <strong>{r.title}</strong>], ["发文机关 / 生效日", r => `${r.issuer} · ${r.effective_date || "待确认"}`], ["范围 / 级别", r => `${({ public: "公开", school: "本校", department: "院系", branch: "支部" })[r.visibility]} · ${r.security_level}`], ["发布状态", r => <Status value={r.review_status} />], ["原件版本", r => r.content_revision], ["操作", r => <button className="text-button link" onClick={() => setSelected(r.doc_id)}>原件与处理</button>]]} />
    <Pagination page={page} total={documents.value?.total || 0} pages={Math.max(1, Math.ceil((documents.value?.total || 0) / 20))} onChange={setPage} />
    {selected && <Modal title="制度原件与入库处理" wide flat onClose={() => setSelected(null)}><ResourceState resource={detail} />{d && <><h3>{d.title}</h3><p>{d.doc_number} · {d.issuer}</p><Status value={d.review_status} /><RecordTrace record={d} /><p className="business-content">{d.summary || "未填写摘要"}</p><p>原件版本：{d.content_revision}；效力：{d.status !== "effective" ? ({ expired: "已失效", abolished: "已废止" })[d.status] || d.status : ({ effective: "现行有效", pending: "待生效", superseded: "已被替代", repealed: "已废止" })[d.validity] || d.validity}</p>
      <div className="business-actions"><button className="button secondary" onClick={() => open("下载授权原件", [{ name: "confirm", label: "按授权用途使用原件", type: "checkbox" }], async values => { if (!values.confirm) throw new Error("请先确认用途"); downloadBlob(await request(`/knowledge-docs/${key(d.doc_id)}/file`, { download: true }), d.file_name); })}>下载原件</button>{can("knowledge.manage") && <><button className="button secondary" onClick={metadata}>修正文件信息</button><button className="button secondary" onClick={replace}>更新原件版本</button><button className="button secondary" onClick={maintenance}>供给复核</button><button className="button secondary" onClick={changeStatus}>变更效力状态</button><button className="button secondary" onClick={embed}>建立 / 重试检索向量</button></>}{can("knowledge.review") && d.review_status !== "published" && <button className="button primary" onClick={review}>审核发布</button>}</div>
      <ResourceState resource={processing} />{processing.value && <p className="inline-note">检索处理：{processing.value.status || processing.value.embedding_status || "已读取处理状态"}；已入库片段：{processing.value.chunk_count ?? processing.value.total_chunks ?? rows(chunks.value).length}。未建立向量时不能据此认定语义检索已就绪。</p>}
      {processing.value?.error && <p className="inline-note" role="alert">检索处理未完成：{typeof processing.value.error === "string" ? processing.value.error : processing.value.error.message || "请按请求记录核查处理原因"}</p>}
      <h4>已解析的正文片段</h4><ResourceState resource={chunks} /><div className="business-list">{rows(chunks.value).map((chunk, index) => <article key={chunk.id || index}><strong>{chunk.section || chunk.chapter || `片段${index + 1}`}</strong><p className="business-content">{chunk.content || chunk.text}</p><small>页码：{chunk.page_number || chunk.page || "文本资料无页码"}</small></article>)}</div>
    </>}</Modal>}
    {form && <BusinessForm key={form.title} {...form} onSubmit={form.submit} onClose={() => setForm(null)} />}
  </section>;
}
