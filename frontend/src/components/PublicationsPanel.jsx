import { useEffect, useState } from "react";
import { ArrowRight, CaretRight, FileText, Megaphone, DownloadSimple, ArrowClockwise } from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { useStore } from "../store";
import { IS_LIVE, request } from "../api";
import { get, key, rows } from "../business-api";
import { hasPermission } from "../roles";
import { getDemoFile } from "../demo-files";
import { Badge, Empty, ErrorBox, Loading, Modal, SearchInput, Tabs, Pagination, downloadBlob } from "../components";
import { PUBLICATION_TABS, canDownloadDemoPublicationFile, demoPublications, documentIsPublished, filterPublications, normalizeDocument, normalizeNotice, noticeIsPublished, publicationToday } from "../publications";
import "../publications.css";

function PublicationRows({ items, open }) {
  return <div className="publication-list">{items.map((item) => {
    const publicity = item.category === "publicity", document = item.category === "document";
    const Icon = publicity ? Megaphone : FileText;
    return <button className="publication-row" key={item.id} onClick={() => open(item)}>
      <span className={`publication-kind ${publicity ? "publicity" : document ? "document" : "notice"}`}><Icon size={22} /><span>{publicity ? "公示中" : document ? "制度" : "通知"}</span></span>
      <span className="publication-summary"><span className="publication-title">{item.title}{item.pinned && <Badge tone="red">置顶</Badge>}</span><span className="publication-meta">{item.issuer}<span>· {item.scope}</span>{publicity ? <span>公示期：{item.startsOn}—{item.expiresOn}</span> : item.publishedOn && <time>{item.publishedOn}</time>}</span></span>
      {item.attachments.length > 0 && <span className="publication-attachment"><FileText size={15} />附件{item.attachments.length}份</span>}
      <CaretRight size={17} className="publication-chevron" />
    </button>;
  })}</div>;
}

function PublicationDetail({ item, close, identity }) {
  const { session } = useApp();
  const [resource, setResource] = useState({ identity, busy: IS_LIVE, value: IS_LIVE ? null : item, error: null });
  const [retry, setRetry] = useState(0), [downloadError, setDownloadError] = useState(null), [downloading, setDownloading] = useState(null);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setResource({ identity, busy: true, value: null, error: null });
    const path = item.source === "notice" ? `/school/business/records/${key(item.recordId)}` : `/knowledge-docs/${key(item.recordId)}`;
    request(path).then((value) => {
      if (!active) return;
      if (item.source === "notice" ? !noticeIsPublished(value) : !documentIsPublished(value)) throw new Error("该信息当前未发布或已不在展示期限内，请刷新公示列表。");
      setResource({ identity, busy: false, value: item.source === "notice" ? normalizeNotice(value) : normalizeDocument(value), error: null });
    }).catch((error) => { if (active) setResource({ identity, busy: false, value: null, error }); });
    return () => { active = false; };
  }, [item.id, identity, retry]);
  const d = resource.identity === identity ? resource.value : null;
  async function download(evidence) {
    setDownloadError(null); setDownloading(evidence.doc_id);
    try {
      if (!IS_LIVE) {
        if (!canDownloadDemoPublicationFile(session.user, d.raw, evidence)) throw new Error("原件尚未上传或不在当前授权范围内，请联系发布组织查阅。");
        const blob = await getDemoFile(evidence.local_file_id, evidence.local_owner_id);
        downloadBlob(blob, evidence.file_name || evidence.title || "文件原件");
        return;
      }
      if (evidence.has_file === false) throw new Error("原件尚未上传，请联系发布组织查阅。");
      const document = await request(`/knowledge-docs/${key(evidence.doc_id)}`);
      if (!documentIsPublished(document)) throw new Error("附件当前未发布或已失效，请联系发布组织核对。");
      const blob = await request(`/knowledge-docs/${key(evidence.doc_id)}/file?revision=${key(evidence.revision || 1)}`, { download: true });
      downloadBlob(blob, evidence.file_name || document.file_name || evidence.title || "文件原件");
    } catch (error) { setDownloadError(error); }
    finally { setDownloading(null); }
  }
  return <Modal title="公示与文件详情" onClose={close} wide flat className="publication-detail">
    {resource.busy && <Loading />}{resource.error && <ErrorBox error={resource.error} retry={() => setRetry((n) => n + 1)} />}
    {d && <><div className="publication-detail-heading"><Badge tone={d.category === "publicity" ? "red" : "blue"}>{PUBLICATION_TABS.find((t) => t.id === d.category)?.label}</Badge><h2>{d.title}</h2><p>{d.issuer} · {d.scope}{d.publishedOn && ` · ${d.publishedOn}`}</p></div>
      {d.category === "publicity" && <p className="publication-period">公示期：{d.startsOn} 至 {d.expiresOn}</p>}
      {d.source === "document" && <dl className="detail-list"><dt>发文字号</dt><dd>{d.raw.doc_number || "未登记"}</dd><dt>文件版本</dt><dd>{d.raw.content_revision || 1}</dd><dt>文件效力</dt><dd>现行有效</dd></dl>}
      <div className="publication-content">{d.content || "未填写正文或摘要，请查阅授权原件，或联系发布组织。"}</div>
      {downloadError && <ErrorBox error={downloadError} />}
      {d.attachments.length > 0 ? <section className="publication-files"><h3>附件与原件</h3>{d.attachments.map((e, i) => <div key={`${e.doc_id}-${e.revision}-${i}`}><FileText size={20} /><span>{e.file_name || e.title || "文件原件"}<small>版本 {e.revision || 1}</small></span><button className="button secondary" disabled={downloading === e.doc_id} onClick={() => download(e)}><DownloadSimple size={16} />{downloading === e.doc_id ? "正在下载" : "下载原件"}</button></div>)}</section> : <p className="publication-file-note">{IS_LIVE ? "该条信息未附原件。" : "原件尚未上传，请联系发布组织查阅。"}</p>}
    </>}
  </Modal>;
}

export function PublicationsPanel({ limit = 5, className = "" }) {
  const { session, navigate } = useApp(), { data } = useStore();
  const identity = `${session.user.tenant_id}:${session.user.id}:${session.user.role}:${session.user.org_unit_id}`;
  const mayReadDocuments = hasPermission(session, "knowledge.query"), mayManageDocuments = hasPermission(session, "knowledge.manage");
  const [remote, setRemote] = useState({ identity, items: [], errors: [], busy: IS_LIVE, documentTotal: 0 });
  const [extraDocuments, setExtraDocuments] = useState({ identity, items: [], busy: false, error: null });
  const [tick, setTick] = useState(0), [category, setCategory] = useState("all"), [query, setQuery] = useState(""), [all, setAll] = useState(false), [detail, setDetail] = useState(null), [page, setPage] = useState(1);
  useEffect(() => { setDetail(null); setAll(false); setCategory("all"); setQuery(""); setPage(1); }, [identity]);
  useEffect(() => {
    if (!IS_LIVE) return;
    let active = true;
    setRemote({ identity, items: [], errors: [], busy: true, documentTotal: 0 });
    setExtraDocuments({ identity, items: [], busy: false, error: null });
    const sources = [get("/school/business/records", { kind: "notice" }), mayReadDocuments ? get("/knowledge-docs", { page_size: 100, ...(mayManageDocuments ? { review_status: "published" } : {}) }) : Promise.resolve({ items: [] })];
    Promise.allSettled(sources).then((results) => {
      if (!active) return;
      const today = publicationToday(), items = [], errors = [];
      results.forEach((result, i) => {
        if (result.status === "rejected") errors.push({ name: i === 0 ? "公示公告" : "制度文件", error: result.reason });
        else items.push(...rows(result.value).filter((r) => i === 0 ? noticeIsPublished(r, today) : documentIsPublished(r, today)).map(i === 0 ? normalizeNotice : normalizeDocument));
      });
      const documentTotal = results[1].status === "fulfilled" ? Number(results[1].value?.total || 0) : 0;
      setRemote({ identity, items: filterPublications(items), errors, busy: false, documentTotal });
    });
    return () => { active = false; };
  }, [identity, tick, mayReadDocuments, mayManageDocuments]);
  const current = remote.identity === identity ? remote : { items: [], errors: [], busy: IS_LIVE, documentTotal: 0 };
  useEffect(() => {
    if (!IS_LIVE || !all || !mayReadDocuments || current.documentTotal <= 100) return;
    let active = true;
    const collected = [];
    setExtraDocuments({ identity, items: [], busy: true, error: null });
    async function loadRemaining() {
      try {
        for (let nextPage = 2; nextPage <= Math.ceil(current.documentTotal / 100); nextPage++) {
          const result = await get("/knowledge-docs", { page: nextPage, page_size: 100, ...(mayManageDocuments ? { review_status: "published" } : {}) });
          if (!active) return;
          collected.push(...rows(result).filter((r) => documentIsPublished(r)).map(normalizeDocument));
          setExtraDocuments({ identity, items: [...collected], busy: nextPage < Math.ceil(current.documentTotal / 100), error: null });
        }
      } catch (error) { if (active) setExtraDocuments({ identity, items: [...collected], busy: false, error }); }
    }
    loadRemaining();
    return () => { active = false; };
  }, [all, identity, current.documentTotal, tick, mayReadDocuments, mayManageDocuments]);
  const extra = extraDocuments.identity === identity ? extraDocuments : { items: [], busy: false, error: null };
  const items = IS_LIVE ? [...new Map([...current.items, ...extra.items].map((item) => [item.id, item])).values()] : demoPublications(data, session);
  const filtered = filterPublications(items, { category, query });
  const openDetail = (item) => setDetail({ item, identity });
  const setTab = (value) => { setCategory(value); setPage(1); };
  const setSearch = (e) => { setQuery(e.target.value); setPage(1); };
  const renderControls = (expanded = false) => <div className="publication-toolbar"><Tabs items={PUBLICATION_TABS} active={category} onChange={setTab} compact />{expanded ? <div className="publication-toolbar-actions"><SearchInput placeholder="搜索标题、发布单位" value={query} onChange={setSearch} /><button className="button secondary publication-refresh" onClick={() => setTick((n) => n + 1)}><ArrowClockwise size={16} />刷新信息</button></div> : <SearchInput placeholder="搜索标题、发布单位" value={query} onChange={setSearch} />}</div>;
  const messages = <>{current.errors.map(({ name, error }) => <ErrorBox key={name} error={{ ...error, message: `${name}暂未加载：${error.message || "请求失败，请重试。"}` }} retry={() => setTick((n) => n + 1)} />)}{current.busy && <Loading />}</>;
  return <section className={`panel publications-panel ${className}`} aria-label="公示公告">
    <div className="publication-panel-heading"><div><h2><i />公示公告</h2><p>本校及所属组织发布的信息</p></div><div className="publication-panel-actions"><button className="text-button link" onClick={() => { setAll(true); setPage(1); }}>查看全部<ArrowRight size={14} /></button>{session.user.role === "school_admin" && <button className="button secondary" onClick={() => navigate("school-notices")}>发布管理</button>}</div></div>
    {renderControls()}{messages}
    {!current.busy && <><PublicationRows items={filtered.slice(0, limit)} open={openDetail} />{!filtered.length && <Empty title={current.errors.length ? "当前未取得可展示信息" : "暂无符合条件的公示或文件"} description="仅展示已发布且在展示期限内、当前账号有权查阅的信息。" />}</>}
    {all && !detail && <Modal title="公示公告与制度文件" onClose={() => setAll(false)} wide flat className="publication-all">{renderControls(true)}{messages}{extra.busy && <p className="publication-file-note" role="status">正在读取更多制度文件…</p>}{extra.error && <ErrorBox error={extra.error} retry={() => setTick((n) => n + 1)} />}<PublicationRows items={filtered.slice((page - 1) * 10, page * 10)} open={openDetail} />{!filtered.length && !current.busy && !extra.busy && <Empty title="暂无符合条件的信息" />}<Pagination page={page} pages={Math.max(1, Math.ceil(filtered.length / 10))} total={filtered.length} onChange={setPage} /></Modal>}
    {detail?.identity === identity && <PublicationDetail key={`${identity}:${detail.item.id}`} item={detail.item} identity={identity} close={() => setDetail(null)} />}
  </section>;
}
