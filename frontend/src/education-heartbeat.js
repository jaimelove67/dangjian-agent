// Each course owns its state and persist callback, including any final paused position.
export async function saveHeartbeatWithPending(state, position, persist, force = false) {
  if (state.busy) {
    if (force) state.pendingPosition = position;
    return;
  }
  state.busy = true;
  let nextPosition = position;
  try {
    while (true) {
      state.pendingPosition = null;
      state.at = Date.now();
      const result = await persist(nextPosition);
      const pending = state.pendingPosition;
      if (pending == null || pending === nextPosition) return result;
      nextPosition = pending;
    }
  } finally {
    state.busy = false;
    state.pendingPosition = null;
  }
}
