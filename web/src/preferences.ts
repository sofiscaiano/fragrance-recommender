import type { LikedPerfume, Preferences, WardrobeRelation } from "./api";

function storageKey(username: string): string {
  return `fragrantica:survey:${username}`;
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}

function likedList(value: unknown): LikedPerfume[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const liked: LikedPerfume[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") {
      continue;
    }
    const perfumeId = "perfume_id" in item ? item.perfume_id : undefined;
    const relation = "relation" in item ? item.relation : undefined;
    const name = "name" in item ? item.name : undefined;
    const brand = "brand" in item ? item.brand : undefined;
    if (typeof perfumeId !== "number" || !isRelation(relation) || typeof name !== "string") {
      continue;
    }
    liked.push({
      perfume_id: perfumeId,
      relation,
      name,
      brand: typeof brand === "string" ? brand : "",
    });
    if (liked.length === 5) {
      break;
    }
  }
  return liked;
}

function isRelation(value: unknown): value is WardrobeRelation {
  return value === "have" || value === "want" || value === "had";
}

export function loadSurvey(username: string): Preferences | null {
  const raw = sessionStorage.getItem(storageKey(username));
  if (!raw) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || !("liked" in parsed)) {
      return null;
    }
    return {
      brands: stringList("brands" in parsed ? parsed.brands : undefined),
      genders: stringList("genders" in parsed ? parsed.genders : undefined),
      perfumers: [],
      families: [],
      liked: likedList("liked" in parsed ? parsed.liked : undefined),
    };
  } catch {
    return null;
  }
}

export function saveSurvey(username: string, preferences: Preferences): void {
  sessionStorage.setItem(storageKey(username), JSON.stringify(preferences));
}
