import { request } from "./api.js";
export const key = encodeURIComponent;
export const query = (values = {}) => "?" + new URLSearchParams(Object.entries(values).filter(([, v]) => v !== "" && v != null));
export const get = (path, values) => request(path + (values ? query(values) : ""));
export const send = (path, body = {}, method = "POST") => request(path, { method, body: JSON.stringify(body) });
export const rows = (value) => Array.isArray(value) ? value : value?.items || [];
