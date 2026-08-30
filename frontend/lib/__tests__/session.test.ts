import { getOrCreateSessionId, SESSION_STORAGE_KEY } from "@/lib/session";

describe("session continuity", () => {
  beforeEach(() => window.localStorage.clear());

  it("creates and reuses only a canonical UUIDv4", () => {
    const first = getOrCreateSessionId(window.localStorage);
    const second = getOrCreateSessionId(window.localStorage);

    expect(first).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    expect(second).toBe(first);
    expect(window.localStorage).toHaveLength(1);
    expect(window.localStorage.getItem(SESSION_STORAGE_KEY)).toBe(first);
  });

  it("replaces invalid persisted identifiers", () => {
    window.localStorage.setItem(SESSION_STORAGE_KEY, "board-data-should-never-persist");
    expect(getOrCreateSessionId(window.localStorage)).not.toContain("board-data");
  });
});
