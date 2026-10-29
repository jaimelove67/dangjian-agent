import { test } from "node:test";
import assert from "node:assert/strict";
import { saveHeartbeatWithPending } from "../src/education-heartbeat.js";

const stateFor = () => ({ busy: false, at: 0, pendingPosition: null });
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

test("forced pauses during a request queue only the latest position without blocking", async () => {
  const state = stateFor(), first = deferred(), second = deferred(), secondStarted = deferred(), positions = [];
  const persist = position => {
    positions.push(position);
    if (positions.length === 1) return first.promise;
    secondStarted.resolve();
    return second.promise;
  };
  const saving = saveHeartbeatWithPending(state, 10, persist);
  assert.equal(state.busy, true);
  assert.ok(state.at > 0);
  await saveHeartbeatWithPending(state, 15, persist, true);
  await saveHeartbeatWithPending(state, 20, persist, true);
  await saveHeartbeatWithPending(state, 25, persist, true);
  assert.deepEqual(positions, [10]);
  assert.equal(state.pendingPosition, 25);
  first.resolve("first saved");
  await secondStarted.promise;
  assert.deepEqual(positions, [10, 25]);
  assert.equal(state.busy, true);
  second.resolve("latest saved");
  assert.equal(await saving, "latest saved");
  assert.equal(state.busy, false);
  assert.equal(state.pendingPosition, null);
});

test("the same paused position does not cause a duplicate heartbeat", async () => {
  const state = stateFor(), first = deferred(), positions = [];
  const persist = position => { positions.push(position); return first.promise; };
  const saving = saveHeartbeatWithPending(state, 10, persist);
  await saveHeartbeatWithPending(state, 15, persist, true);
  await saveHeartbeatWithPending(state, 10, persist, true);
  first.resolve();
  await saving;
  assert.deepEqual(positions, [10]);
  assert.equal(state.busy, false);
  assert.equal(state.pendingPosition, null);
});

test("ordinary time updates during a busy request do not queue another request", async () => {
  const state = stateFor(), first = deferred(), positions = [];
  const persist = position => { positions.push(position); return first.promise; };
  const saving = saveHeartbeatWithPending(state, 10, persist);
  await saveHeartbeatWithPending(state, 20, persist);
  assert.equal(state.pendingPosition, null);
  first.resolve();
  await saving;
  assert.deepEqual(positions, [10]);
});

test("a failed heartbeat releases its lock and clears pending state for a real retry", async () => {
  const state = stateFor(), first = deferred(), positions = [], failure = new Error("request failed");
  const persist = position => { positions.push(position); return first.promise; };
  const saving = saveHeartbeatWithPending(state, 10, persist);
  const rejected = assert.rejects(saving, error => error === failure);
  await saveHeartbeatWithPending(state, 20, persist, true);
  first.reject(failure);
  await rejected;
  assert.equal(state.busy, false);
  assert.equal(state.pendingPosition, null);
  await saveHeartbeatWithPending(state, 20, async position => { positions.push(position); });
  assert.deepEqual(positions, [10, 20]);
  assert.equal(state.busy, false);
});

test("switching course state keeps queued positions with the original course callback", async () => {
  const oldState = stateFor(), newState = stateFor(), first = deferred(), final = deferred(), newRequest = deferred(), finalStarted = deferred(), saved = [];
  const persistOld = position => {
    saved.push(["old course", position]);
    if (position === 10) return first.promise;
    finalStarted.resolve();
    return final.promise;
  };
  const oldSaving = saveHeartbeatWithPending(oldState, 10, persistOld);
  await saveHeartbeatWithPending(oldState, 25, () => assert.fail("queued calls must not replace the original callback"), true);
  const newSaving = saveHeartbeatWithPending(newState, 3, position => { saved.push(["new course", position]); return newRequest.promise; });
  first.resolve();
  await finalStarted.promise;
  final.resolve();
  await oldSaving;
  assert.deepEqual(saved, [["old course", 10], ["new course", 3], ["old course", 25]]);
  assert.equal(oldState.busy, false);
  assert.equal(oldState.pendingPosition, null);
  assert.equal(newState.busy, true);
  newRequest.resolve();
  await newSaving;
  assert.equal(newState.busy, false);
});

test("forced positions arriving during a queued save are flushed before unlocking", async () => {
  const state = stateFor(), first = deferred(), second = deferred(), secondStarted = deferred(), positions = [];
  const persist = position => {
    positions.push(position);
    if (position === 10) return first.promise;
    if (position === 20) { secondStarted.resolve(); return second.promise; }
    return Promise.resolve();
  };
  const saving = saveHeartbeatWithPending(state, 10, persist);
  await saveHeartbeatWithPending(state, 20, persist, true);
  first.resolve();
  await secondStarted.promise;
  await saveHeartbeatWithPending(state, 25, persist, true);
  await saveHeartbeatWithPending(state, 30, persist, true);
  second.resolve();
  await saving;
  assert.deepEqual(positions, [10, 20, 30]);
  assert.equal(state.busy, false);
  assert.equal(state.pendingPosition, null);
});
