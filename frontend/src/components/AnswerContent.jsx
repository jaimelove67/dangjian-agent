import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { normalizeAnswerMarkdown, withCitationLinks } from "../answer-markdown";

function citationLabel(children) {
  const text = Array.isArray(children)
    ? children.map((item) => (typeof item === "string" ? item : "")).join("")
    : String(children ?? "");
  return text.startsWith("[") ? text : `[${text}]`;
}

/**
 * 智能体回答渲染：安全 Markdown + 行内引用角标。
 *
 * 原始 HTML 不参与渲染；图片不加载外部地址，只显示替代文字。
 */
export default function AnswerContent({ content, citations = [], onCitation }) {
  const source = withCitationLinks(
    normalizeAnswerMarkdown(content),
    citations.map((item) => item.index),
  );
  const components = {
    a({ href, children }) {
      if (typeof href === "string" && href.startsWith("citation:")) {
        const index = Number(href.slice("citation:".length));
        const citation = citations.find((item) => Number(item.index) === index);
        if (citation && onCitation) {
          return (
            <button
              type="button"
              className="inline-citation"
              title={citation.title ? `查看引用：${citation.title}` : "查看引用"}
              onClick={() => onCitation(citation)}
            >
              {citationLabel(children)}
            </button>
          );
        }
        return <span>{children}</span>;
      }
      if (typeof href === "string" && /^https?:\/\//i.test(href)) {
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        );
      }
      return <span>{children}</span>;
    },
    table({ children }) {
      return (
        <div className="answer-table-wrap">
          <table>{children}</table>
        </div>
      );
    },
    img({ alt }) {
      return (
        <span className="answer-image-alt">
          [图片{alt ? `：${alt}` : ""}]
        </span>
      );
    },
  };

  return (
    <div className="answer-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) =>
          url.startsWith("citation:") ? url : defaultUrlTransform(url)
        }
        components={components}
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
