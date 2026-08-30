import "@testing-library/jest-dom/vitest";

Object.assign(navigator, {
  clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
});

Element.prototype.scrollIntoView = vi.fn();

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});
