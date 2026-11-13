# EDA

Corte `28_60`. Universo: reviews con fecha y rating. Matriz: k-core de ese corte.

## Tamaño

| | universo | matriz | se elimina |
|---|---:|---:|---:|
| reviews | 610974 | 134071 | 476903 (78.1%) |
| usuarios | 42693 | 2473 | 40220 (94.2%) |
| perfumes | 14085 | 1088 | 12997 (92.3%) |
| densidad | 0.10% | 4.98% | |

Salen usuarios con pocas reviews (p50 5) y perfumes con pocas reviews (p50 8).

## Nulos

Porcentaje vacío. En accords, notas y perfumista, vacío incluye lista vacía.
En estación, día y noche no hay nulos: un 0 es «no marcado».

| feature | universo | matriz |
|---|---:|---:|
| rating | 0.0% | 0.0% |
| timestamp | 0.0% | 0.0% |
| longevity | 47.4% | 49.0% |
| sillage | 47.1% | 48.2% |
| gender_vote | 100.0% | 100.0% |
| brand | 0.0% | 0.0% |
| gender | 0.0% | 0.0% |
| olfactive_family | 9.4% | 4.5% |
| launch_year | 6.9% | 1.3% |
| perfumers | 52.3% | 16.6% |
| accords | 0.5% | 0.0% |
| notes | 0.4% | 0.0% |

## Distribución

**Rating.** Universo / matriz: 1 3.7% / 3.0%, 2 11.1% / 11.4%, 3 11.2% / 12.2%, 4 28.8% / 32.0%, 5 45.3% / 41.4%.

**Longevidad**, entre las que tienen valor. Universo / matriz: 1 4.2% / 3.3%, 2 9.4% / 8.1%, 3 37.7% / 37.5%, 4 37.1% / 39.3%, 5 11.6% / 11.9%.

**Estela**, entre las que tienen valor. Universo / matriz: 1 15.2% / 13.9%, 2 51.2% / 51.7%, 3 26.8% / 27.5%, 4 6.8% / 6.9%.

**Estación.** Share de reviews con la estación marcada. Universo / matriz: winter 33.5% / 34.9%, spring 38.6% / 37.5%, summer 30.9% / 28.9%, autumn 39.0% / 40.8%. Sin ninguna: 40.8% universo, 42.2% matriz.

**Día y noche.** Universo / matriz: day 43.3% / 43.1%, night 34.1% / 34.8%. Sin ninguno: 46.3% universo, 46.8% matriz.

**Año de la review.** 2007–2026. Desde 2023: 58.0% universo, 49.6% matriz.

**Género del perfume.** Universo / matriz: men 18.6% / 28.7%, unisex 40.4% / 34.0%, women 41.0% / 37.3%.

**Familia olfativa.** 56 en el universo, 34 en la matriz. Las más frecuentes en la matriz: Oriental Floral (115), Oriental Woody (87), Oriental Vanilla (85), Floral (71), Woody Aromatic (66).

**Marca.** 126 en el universo, 94 en la matriz. Las más frecuentes en la matriz: Dior (56), Chanel (46), Guerlain (45), Tom Ford (41), Amouage (40).

**Año de lanzamiento.** Universo: p50 2019, 1781–2026. Matriz: p50 2015, 1889–2026.

**Perfumista.** Universo: p50 0 por perfume. Top: Alberto Morillas (286), Pierre Montale (214), Dominique Ropion (191), Thierry Wasser (187), Olivier Cresp (179). Matriz: p50 1 por perfume. Top: Alberto Morillas (43), Dominique Ropion (43), François Demachy (40), Quentin Bisch (40), Olivier Cresp (32).

**Accords.** Universo: p50 9 por perfume. Top: woody (9214), sweet (7340), powdery (7340), citrus (6545), aromatic (5963). Matriz: p50 10 por perfume. Top: woody (803), sweet (615), powdery (609), aromatic (548), citrus (513).

**Notas.** Universo: p50 8 por perfume. Top: Musk (4911), Bergamot (4000), Vanilla (3890), Sandalwood (3569), Amber (3565). Matriz: p50 10 por perfume. Top: Musk (405), Bergamot (386), Vanilla (372), Patchouli (357), Sandalwood (334).
