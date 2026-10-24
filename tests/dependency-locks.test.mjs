import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

for (const relative of ["../package-lock.json", "../frontend/package-lock.json"]) {
  test(`${relative} preserves native build packages for clean installs across platforms`, async () => {
    const lock = JSON.parse(await readFile(new URL(relative, import.meta.url), "utf8"));
    assert.ok(lock.packages["node_modules/@rollup/rollup-linux-x64-gnu"],
      "Clean install cannot resolve @rollup/rollup-linux-x64-gnu");
    for (const name of ["rollup", "esbuild"]) {
      const parent = lock.packages[`node_modules/${name}`];
      assert.ok(parent, `${name} must be locked`);
      const native = Object.entries(parent.optionalDependencies).filter(([id]) =>
        id.startsWith("@rollup/") || id.startsWith("@esbuild/"));
      assert.ok(native.some(([id]) => id.includes("linux-x64")), `${name} must declare Linux support`);
      for (const [id, version] of native) {
        const dependency = lock.packages[`node_modules/${id}`];
        assert.ok(dependency, `Clean install cannot resolve ${id}@${version}`);
        assert.equal(dependency.version, version, `${id} must match its native loader`);
        assert.ok(dependency.integrity?.startsWith("sha512-"), `${id} must retain an integrity hash`);
        assert.equal(dependency.optional, true);
      }
    }
  });
}
