import assert from "node:assert/strict";
import test from "node:test";
import { resolveApiBase } from "../src/api-config.js";

test("API base keeps the current same-origin contract by default", () => {
  for (const value of [undefined, "", "  ", "/api/v1/"]) {
    assert.equal(resolveApiBase(value), "/api/v1");
  }
});

test("API base accepts a separate backend origin and keeps its version prefix", () => {
  assert.equal(resolveApiBase(" https://api.example.edu/api/v1/// "), "https://api.example.edu/api/v1");
  assert.equal(resolveApiBase("http://127.0.0.1:18001/api/v1"), "http://127.0.0.1:18001/api/v1");
});

test("invalid API bases fail before authentication can use them", () => {
  for (const value of ["api/v1", "//example.edu/api/v1", "http:example.edu", "javascript:alert(1)", "https://user:pass@example.edu/api/v1", "/api/v1?token=secret", "https://example.edu/api/v1#fragment", "/api\\v1"]) {
    assert.throws(() => resolveApiBase(value), /VITE_API_BASE_URL/);
  }
});
