import type { SessionRating } from "./api";

function storageKey(username: string): string {
  return `fragrantica:ratings:${username}`;
}

export function loadRatings(username: string): SessionRating[] {
  const raw = localStorage.getItem(storageKey(username));
  if (!raw) {
    return [];
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.flatMap((item) => {
      if (!item || typeof item !== "object") {
        return [];
      }
      const perfumeId = "perfume_id" in item ? item.perfume_id : undefined;
      const rating = "rating" in item ? item.rating : undefined;
      if (typeof perfumeId !== "number" || typeof rating !== "number") {
        return [];
      }
      if (rating < 1 || rating > 5) {
        return [];
      }
      return [{ perfume_id: perfumeId, rating }];
    });
  } catch {
    return [];
  }
}

export function saveRatings(username: string, ratings: SessionRating[]): void {
  localStorage.setItem(storageKey(username), JSON.stringify(ratings));
}

export function mergeRatings(
  current: SessionRating[],
  drafts: Record<string, string>,
): SessionRating[] {
  const next = new Map(current.map((item) => [item.perfume_id, item.rating]));
  for (const [perfumeId, value] of Object.entries(drafts)) {
    const rating = Number(value);
    const id = Number(perfumeId);
    if (Number.isInteger(id) && rating >= 1 && rating <= 5) {
      next.set(id, rating);
    }
  }
  return [...next.entries()].map(([perfume_id, rating]) => ({ perfume_id, rating }));
}
