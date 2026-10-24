import { useEffect, useRef, useState } from "react";
import { IS_LIVE } from "../api";
import { roleApi } from "../role-api";
import { MATERIAL_CATEGORIES } from "../role-data";
import { validateMaterialFile } from "../material-validation";
import {
  adoptMaterialSuggestions,
  clearMaterialSuggestions,
} from "../material-draft";
import "./material-suggestions.css";

export function useMaterialDraft(initial) {
  const [draft, setDraft] = useState(initial);
  const [file, setFile] = useState(null);
  const adopted = useRef({});
  function edit(key, value) {
    delete adopted.current[key];
    setDraft((previous) => ({ ...previous, [key]: value }));
  }
  function selectFile(next) {
    const previousSuggestions = adopted.current;
    setDraft((previous) => clearMaterialSuggestions(previous, previousSuggestions));
    adopted.current = {};
    setFile(next);
  }
  function apply(fields, allowed) {
    const result = adoptMaterialSuggestions(draft, fields, allowed);
    adopted.current = { ...adopted.current, ...result.adopted };
    setDraft(result.draft);
    return Object.keys(result.adopted).length;
  }
  function reset() {
    adopted.current = {};
    setFile(null);
    setDraft(initial);
  }
  return { draft, file, edit, selectFile, apply, reset };
}

const labels = {
  title: "标题",
  category: "个人材料类型",
  material_type: "发展材料类型",
  subject_name: "文档署名",
  doc_date: "文档日期",
  issuer: "出具单位",
  description: "材料说明",
};
export function MaterialSuggestions({
  file,
  profileId,
  maxSize = 10 * 1024 * 1024,
  allowedExtensions,
  onApply,
  disabled,
}) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [retry, setRetry] = useState(0);
  const [adoption, setAdoption] = useState("");
  useEffect(() => {
    let active = true;
    setResult(null);
    setError("");
    setLoading(false);
    setAdoption("");
    if (!file || !IS_LIVE) return;
    try {
      validateMaterialFile(file, maxSize, allowedExtensions);
    } catch (e) {
      setError(e.message);
      return;
    }
    setLoading(true);
    roleApi.previewMaterial(file, profileId)
      .then((value) => {
        if (active) setResult({ file, profileId, value });
      })
      .catch((e) => {
        if (active) setError(e.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => { active = false; };
  }, [file, profileId, maxSize, allowedExtensions, retry]);
  if (!file) return null;
  const value = result?.file === file && result.profileId === profileId ? result.value : null;
  const entries = Object.entries(value?.fields || {}).filter(([key]) =>
    labels[key] && key !== (profileId ? "category" : "material_type"),
  );
  function adopt() {
    const count = onApply(value.fields);
    setAdoption(count
      ? `已填入 ${count} 个空白项，请核对后提交。`
      : "可填写的字段已有内容，已保留原值；其余信息供核对。");
  }
  return (
    <section className="material-suggestions" aria-label="材料填写建议" aria-busy={loading}>
      <div className="material-suggestions-heading">
        <strong>文档填写建议</strong><span>{file.name}</span>
      </div>
      <div aria-live="polite">
        {!IS_LIVE ? (
          <p>材料提取服务暂不可用，请对照原件手动填写；提交前请核对材料信息。</p>
        ) : loading ? (
          <p>正在读取文档，完成后可选择采用建议；也可直接手动填写。</p>
        ) : error ? (
          <p role="alert">
            提取未完成：{error} 可继续手动提交。
            <button type="button" className="text-button link" disabled={disabled} onClick={() => setRetry((n) => n + 1)}>重试提取</button>
          </p>
        ) : value && (
          <>
            {entries.length ? (
              <dl>{entries.map(([key, text]) => (
                <div key={key}>
                  <dt>{labels[key]}</dt>
                  <dd>{key === "category" ? MATERIAL_CATEGORIES[text] : text}
                    <small>原文：{value.evidence[key]}</small>
                  </dd>
                </div>
              ))}</dl>
            ) : <p>未找到可确定的字段，请对照原件手动填写。</p>}
            {value.notes.map((note, index) => <p key={index}>{note}</p>)}
            {entries.length > 0 && (
              <button type="button" className="button secondary" disabled={disabled} onClick={adopt}>采用建议填入空白项</button>
            )}
            {adoption && <p>{adoption}</p>}
            <p>署名、文档日期及出具单位供核对，档案、组织收到日期、核验结论和发展阶段由人工确认。提取在服务器本地完成；确认提交后才保存材料。</p>
          </>
        )}
      </div>
    </section>
  );
}
