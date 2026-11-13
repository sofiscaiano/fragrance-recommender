const GENDER_LABEL: Record<string, string> = {
  women: "Mujer",
  men: "Hombre",
  unisex: "Unisex",
};

export function genderLabel(value: string): string {
  return GENDER_LABEL[value] ?? value;
}

export function formatCommunityRating(value: number, count: number): string {
  const score = value.toLocaleString("es-AR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  const votes = count.toLocaleString("es-AR");
  return `${score} · ${votes} votos`;
}
