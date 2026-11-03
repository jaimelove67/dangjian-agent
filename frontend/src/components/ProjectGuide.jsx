import { useMemo, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  CheckCircle,
  MagnifyingGlass,
  Question,
} from "@phosphor-icons/react";
import { useApp } from "../app-context";
import { Modal, Badge } from "../components";
import { roleLabel } from "../roles";
import {
  GUIDE_FAQS,
  PAGE_GUIDES,
  ROLE_GUIDES,
} from "../project-guide";

function guideKey(user) {
  return `dangjian.project-guide.v1.${user?.tenant_id || "tenant"}.${user?.id || "user"}.${user?.role || "role"}`;
}

function readDismissed(user) {
  try {
    return localStorage.getItem(guideKey(user)) === "1";
  } catch {
    return false;
  }
}

export function RoleOnboarding({ onOpenGuide }) {
  const { session, navigate } = useApp();
  const [dismissed, setDismissed] = useState(() => readDismissed(session.user));
  const guide = ROLE_GUIDES[session.user.role];
  if (dismissed || !guide) return null;

  function dismiss() {
    setDismissed(true);
    try {
      localStorage.setItem(guideKey(session.user), "1");
    } catch {
      /* 浏览器存储不可用时不阻断使用 */
    }
  }

  return (
    <section className="role-onboarding">
      <div className="role-onboarding-head">
        <div>
          <span className="role-onboarding-kicker">首次使用建议</span>
          <h2>{roleLabel(session.user)}，先从这几件事开始</h2>
          <p>{guide.intro}</p>
        </div>
        <button type="button" className="text-button" onClick={dismiss}>
          暂时收起
        </button>
      </div>
      <div className="role-onboarding-grid">
        {guide.items.map(([route, label, description], index) => (
          <button
            type="button"
            className="role-onboarding-item"
            key={route}
            onClick={() => navigate(route)}
          >
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{label}</strong>
            <small>{description}</small>
            <ArrowRight size={14} />
          </button>
        ))}
      </div>
      <button type="button" className="text-button role-onboarding-more" onClick={onOpenGuide}>
        <Question size={14} />
        查看完整使用指南
      </button>
    </section>
  );
}

export function HelpCenter({ route, onClose }) {
  const { session, navigate } = useApp();
  const [query, setQuery] = useState("");
  const pageGuide = PAGE_GUIDES[route];
  const roleGuide = ROLE_GUIDES[session.user.role];
  const keyword = query.trim();

  const results = useMemo(() => {
    if (!keyword) return [];
    const text = keyword.toLowerCase();
    const matches = [];
    for (const [id, guide] of Object.entries(PAGE_GUIDES)) {
      if (
        guide.title.toLowerCase().includes(text) ||
        guide.purpose.toLowerCase().includes(text) ||
        guide.steps.some((step) => step.toLowerCase().includes(text))
      ) {
        matches.push({ kind: "页面", title: guide.title, detail: guide.purpose, route: id });
      }
    }
    for (const [id, label, detail] of roleGuide?.items || []) {
      if (label.toLowerCase().includes(text) || detail.toLowerCase().includes(text)) {
        matches.push({ kind: "本角色", title: label, detail, route: id });
      }
    }
    for (const item of GUIDE_FAQS) {
      if (item.q.toLowerCase().includes(text) || item.a.toLowerCase().includes(text)) {
        matches.push({ kind: "常见问题", title: item.q, detail: item.a, route: "" });
      }
    }
    return matches.slice(0, 20);
  }, [keyword, roleGuide]);

  function openRoute(id) {
    if (!id) return;
    navigate(id);
    onClose();
  }

  return (
    <Modal title="使用指南" wide flat onClose={onClose}>
      <div className="project-guide">
        <div className="project-guide-search">
          <MagnifyingGlass size={16} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索页面、角色操作或常见问题…"
            aria-label="搜索使用指南"
          />
        </div>

        {keyword ? (
          <section className="project-guide-section">
            <h3>搜索结果</h3>
            {results.length ? (
              <div className="project-guide-list">
                {results.map((item, index) => (
                  <button
                    type="button"
                    key={`${item.kind}-${item.title}-${index}`}
                    onClick={() => openRoute(item.route)}
                    disabled={!item.route}
                  >
                    <Badge tone="blue">{item.kind}</Badge>
                    <span>
                      <strong>{item.title}</strong>
                      <small>{item.detail}</small>
                    </span>
                    {item.route && <ArrowRight size={14} />}
                  </button>
                ))}
              </div>
            ) : (
              <p className="project-guide-empty">没有找到匹配说明，可以换一个关键词，或联系学校管理员。</p>
            )}
          </section>
        ) : (
          <>
            {pageGuide && (
              <section className="project-guide-section project-guide-current">
                <div className="project-guide-section-head">
                  <Badge tone="green">当前页面</Badge>
                  <h3>{pageGuide.title}</h3>
                </div>
                <p>{pageGuide.purpose}</p>
                <ol>
                  {pageGuide.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </section>
            )}

            <section className="project-guide-section">
              <div className="project-guide-section-head">
                <Badge tone="blue">本角色</Badge>
                <h3>{roleLabel(session.user)}上手清单</h3>
              </div>
              {roleGuide ? (
                <>
                  <p>{roleGuide.intro}</p>
                  <div className="project-guide-list">
                    {roleGuide.items.map(([id, label, detail]) => (
                      <button type="button" key={id} onClick={() => openRoute(id)}>
                        <CheckCircle size={17} />
                        <span>
                          <strong>{label}</strong>
                          <small>{detail}</small>
                        </span>
                        <ArrowRight size={14} />
                      </button>
                    ))}
                  </div>
                </>
              ) : (
                <p className="project-guide-empty">当前角色暂无单独清单，请从左侧导航进入业务页面。</p>
              )}
            </section>

            <section className="project-guide-section">
              <div className="project-guide-section-head">
                <Badge tone="orange">常见问题</Badge>
                <h3>遇到问题先看这里</h3>
              </div>
              <div className="project-guide-faqs">
                {GUIDE_FAQS.map((item) => (
                  <details key={item.q}>
                    <summary>{item.q}</summary>
                    <p>{item.a}</p>
                  </details>
                ))}
              </div>
            </section>

            <div className="inline-note project-guide-note">
              <BookOpen size={15} />
              系统只提供操作说明和事实依据；政策口径以正式文件和组织意见为准，找不到入口时请联系有权限的管理员。
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}
