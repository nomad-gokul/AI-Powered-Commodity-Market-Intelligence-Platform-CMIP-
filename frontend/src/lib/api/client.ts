/**
 * Single switch-point for the whole frontend's data layer.
 *
 * Every page reads data through a TanStack Query hook in lib/api/*, never
 * straight from lib/mock-data/*. Today USE_MOCKS is always true (no
 * backend call is made anywhere in this prototype, per spec) — flipping
 * it to false and filling in the fetch bodies below is meant to be the
 * only change needed to point this UI at the real Phase 1-5 FastAPI
 * backend later.
 */
export const USE_MOCKS = true;

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

export async function simulateLatency(ms = 350): Promise<void> {
  if (!USE_MOCKS) return;
  const jitter = ms * 0.4;
  const delay = ms - jitter / 2 + Math.random() * jitter;
  await new Promise((resolve) => setTimeout(resolve, delay));
}
