import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.jsx";
import "./styles.css";
import "./pages.css";
import "./responsive.css";
import "./roles.css";
import "./school.css";

// crypto.randomUUID 仅在安全上下文（HTTPS / localhost）存在。
// 私有化部署常以明文 http://IP 访问，此时调用会抛 TypeError 导致整页白屏。
// 这里统一垫底：非安全上下文用 crypto.getRandomValues 实现 UUID v4。
if (typeof crypto.randomUUID !== "function") {
  crypto.randomUUID = function () {
    const bytes = new Uint8Array(16);
    crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  };
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
