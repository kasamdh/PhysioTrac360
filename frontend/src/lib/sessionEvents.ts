// Notifies the app (and every other open tab) that the current session has
// ended — new login elsewhere, idle/absolute timeout, password changed, or
// an admin action (deactivate/suspend/delete/unlock-all). Carries only a
// human-readable message, never a token or PHI, so it's safe to broadcast.
type Listener = (message: string) => void;

const listeners = new Set<Listener>();
const channel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("physiotrac360-session") : null;

export function onSessionEnded(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function notifySessionEnded(message: string, options: { broadcast?: boolean } = {}) {
  listeners.forEach((listener) => listener(message));
  if (options.broadcast !== false) {
    channel?.postMessage({ type: "session-ended", message });
  }
}

if (channel) {
  channel.onmessage = (event: MessageEvent) => {
    if (event.data?.type === "session-ended" && typeof event.data.message === "string") {
      notifySessionEnded(event.data.message, { broadcast: false });
    }
  };
}
