import type { Preferences } from "./api";

function storageKey(username: string): string {
  return `fragrantica:survey:${username}`;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

export function loadSurvey(username: string): Preferences | null {
  const raw = sessionStorage.getItem(storageKey(username));
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    return {
      brands: stringList("brands" in parsed ? parsed.brands : undefined),
      genders: stringList("genders" in parsed ? parsed.genders : undefined),
      perfumers: stringList("perfumers" in parsed ? parsed.perfumers : undefined),
      families: stringList("families" in parsed ? parsed.families : undefined),
    };
  } catch {
    return null;
  }
}

export function saveSurvey(username: string, preferences: Preferences): void {
  sessionStorage.setItem(storageKey(username), JSON.stringify(preferences));
}
