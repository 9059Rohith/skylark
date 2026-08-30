export const SESSION_STORAGE_KEY = "skylark.signal.session.v1";
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function getOrCreateSessionId(storage: Pick<Storage, "getItem" | "setItem">): string {
  const existing = storage.getItem(SESSION_STORAGE_KEY)?.toLowerCase();
  if (existing && UUID_V4.test(existing)) return existing;
  const sessionId = crypto.randomUUID();
  storage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}

export function createNewSessionId(storage: Pick<Storage, "setItem">): string {
  const sessionId = crypto.randomUUID();
  storage.setItem(SESSION_STORAGE_KEY, sessionId);
  return sessionId;
}
