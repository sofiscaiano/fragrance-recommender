export type Perfume = {
  perfume_id: number;
  name: string;
  brand: string;
  gender: string;
  olfactive_family: string;
  perfumers: string[];
  launch_year: number | null;
  rating_value: number;
  rating_count: number;
  description: string;
  image_url: string;
  url: string;
  rank: number;
};

export type Preferences = {
  brands: string[];
  genders: string[];
  perfumers: string[];
  families: string[];
};

export type SessionRating = {
  perfume_id: number;
  rating: number;
};

export type SessionResponse = {
  username: string;
  conocido: boolean;
  avatar_url: string | null;
};

export type OptionsResponse = {
  brands: string[];
  genders: string[];
  perfumers: string[];
  families: string[];
};

export type RecommendationResponse = SessionResponse & {
  tab: "populares" | "trending" | "mejor_puntuados" | "para_vos";
  perfumes: Perfume[];
};

export type Tab = RecommendationResponse["tab"];

export function emptyPreferences(): Preferences {
  return { brands: [], genders: [], perfumers: [], families: [] };
}

function apiUrl(): string {
  const configured = import.meta.env.VITE_API_URL;
  return (configured && configured.trim()) || "http://localhost:8000";
}

async function errorFrom(response: Response): Promise<Error> {
  const payload: unknown = await response.json().catch(() => null);
  const detail =
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
      ? payload.detail
      : "No se pudo completar la solicitud";
  return new Error(detail);
}

export async function openSession(username: string): Promise<SessionResponse> {
  const response = await fetch(`${apiUrl()}/sesion`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  if (!response.ok) {
    throw await errorFrom(response);
  }
  return response.json() as Promise<SessionResponse>;
}

export async function fetchOptions(): Promise<OptionsResponse> {
  const response = await fetch(`${apiUrl()}/opciones`);
  if (!response.ok) {
    throw await errorFrom(response);
  }
  return response.json() as Promise<OptionsResponse>;
}

export async function fetchRecommendations(
  username: string,
  tab: Tab,
  valoraciones: SessionRating[],
  preferencias: Preferences,
): Promise<RecommendationResponse> {
  const response = await fetch(`${apiUrl()}/recomendaciones`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, tab, valoraciones, preferencias }),
  });
  if (!response.ok) {
    throw await errorFrom(response);
  }
  return response.json() as Promise<RecommendationResponse>;
}
