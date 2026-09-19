# Plan de scraping — Fragrantica.com para Sistema de Recomendación

## 0. Hallazgos del reconocimiento (verificados empíricamente)

Antes de definir la estrategia hice pruebas reales contra el sitio. Esto es lo que se confirmó:

### Escala del sitio (contadores propios del sitio)

| Dimensión | Volumen |
|---|---|
| Perfumes (items) | 137.633 |
| Reviews (interacciones) | 2.611.925 |
| Miembros (usuarios) | 1.988.611 |

### Protección anti-scraping

- El sitio está detrás de **Cloudflare** con *managed challenge*.
- `curl` normal → **403 "Just a moment..."** en toda página interior. `sitemap.xml` → 403.
- **`curl_cffi` con impersonación TLS/JA3 → 200 con contenido real completo.** Verificado con los perfiles `chrome`, `chrome131`, `safari18_0` y `firefox133`; los cuatro pasan.
- No hay CAPTCHA interactivo ni JS challenge bloqueante en el camino feliz: **basta con el fingerprint TLS + headers correctos**. No hace falta navegador para el caso normal.
- Burst test: 12 requests secuenciales sin delay → 12× 200 en 5,8s. No hay rate-limit agresivo inmediato (igual vamos a autolimitar).

### Estructura de datos: el hallazgo clave

**Las reviews vienen renderizadas en el HTML inicial**, no por AJAX. Y cada review trae un blob JSON con los votos estructurados del usuario:

```json
{"rating":4,"winter":1,"spring":1,"summer":1,"autumn":1,"day":1,
 "night":1,"longevity":3,"sillage":2,"gender":null,"relation":"had"}
```

Es decir: **el rating explícito 1–5 por (usuario, item) está disponible directamente en el HTML.** Esto es exactamente la señal que necesita el recomendador.

Datos concretos medidos en la página de `Sauvage` (Dior):
- 210 reviews renderizadas, con 203 usuarios únicos identificados.
- Cada review incluye: `review_id`, username, URL de perfil (`/@usuario`), avatar, timestamp unix, texto y el blob de votos.

**Límite anónimo:** la página trae ~210 reviews. Sauvage tiene 4.2K, o sea que está truncada. El bundle JS confirma el motivo: `"loginPromptMessage":"Sign in to access the full review archive"`. El archivo completo requiere login.

Pero el promedio es 2.6M / 137K ≈ **19 reviews por perfume**, así que para la gran mayoría de items las 210 alcanzan para capturar el listado completo. Solo los populares quedan truncados.

### Páginas de perfil de usuario (`/@usuario`)

Confirmado: devuelven 200 y embeben un array JSON con **todas** las reviews de ese usuario:

```json
{"id":3174654, "parfem_id":30947, "komentar":"<p>mid</p>", "vrijeme":1788028531,
 "naslov":"Ultra Male", "dizajner":"Jean Paul Gaultier",
 "perfume_url":"/perfume/Jean-Paul-Gaultier/Ultra-Male-30947.html",
 "perfume_votes":{"rating":4, ...}}
```

`parfem_id` es el **ID numérico del perfume** → clave de join limpia con el catálogo de items. Además el componente `member-dashboard` expone `:member-id="3158387"` (ID interno del usuario) y `:reviews-total`.

Esto da la vía para **completar la cola de reviews de los perfumes populares** que quedan truncados.

### Identificadores: un hueco detectado y cómo se resuelve

Verificado en el HTML de las reviews de la página de perfume:

- **Sí** hay `review_id` numérico (`id="parent3174649"`, `comment-id="3174649"`).
- **Sí** hay `perfume_id` numérico (`item-id="31861"`, y en la URL).
- **NO** hay `member_id` numérico. Solo el username (`Quilter`) y el slug de perfil (`/@quilter`).

El `member_id` numérico aparece únicamente en la página de perfil (`:member-id="3158387"`).

Probé un atajo: las URLs de avatar tipo `avatari/m.3146574.jpg` sugieren que el número es el `member_id`. **Se confirmó en los casos probados** (`@lanes100` → 3146574 ✓, `@mjoshwil` → 3126834 ✓), **pero no es universal**: los usuarios con avatar custom usan otro almacén (`himg/o.69246.png`, donde 69246 ≠ member_id 3158387).

Conclusión de diseño: el **slug de username es la clave natural durante el crawl** y el `member_id` se resuelve al visitar el perfil. Ver §2 y §3.

### El listado de marca no permite pre-filtrar

Verifiqué si `/designers/Dior.html` expone el conteo de reviews por perfume, para poder descartar items baratos sin descargarlos: **no lo expone** (0 hits de `ratingCount` e `itemprop`). Solo da `perfume_id`, nombre, género y año vía el `title`/`aria-label` (ej. `"Dior Bonne Étoile Baby Dior unisex 2023"`).

Consecuencia: **el conteo real de reviews de un item solo se conoce descargando su página.** Esto condiciona el diseño del filtro por mínimo de reviews (§2b).

### Endpoints AJAX y los "votos sin review"

Descubiertos en el bundle:
- `POST /ajax.php?user_shelves` (body: `action=user_shelves&user_id=<id>`) → wardrobe (have/had/want)
- `GET /ajax.php?view=inventory_items&user_id=<id>`

Ambos responden 200 sin autenticación, **pero el payload viene cifrado con AES** (formato CryptoJS: `{"ct":...,"iv":...,"s":...}`). El passphrase de `window._pd` se deriva del hostname (`www.fragrantica.com`); no está en el HTML.

#### ¿Qué son exactamente los "votos sin review"?

En Fragrantica **puntuar y reseñar son dos acciones separadas**. Podés poner 4/5 estrellas a un perfume con un click, sin escribir nada. Escribir una review es un paso adicional y opcional.

La evidencia numérica en la misma página de `Sauvage`:

| Señal | Valor |
|---|---|
`ratingCount` (microdata) | **33.917 votos** |
Contador de reviews | **~4.200 reviews** |

Es decir: unas **29.700 personas puntuaron Sauvage sin escribir review**. Esas 29.700 puntuaciones individuales alimentan el promedio 3,85 que se muestra, pero **las filas `(usuario, item, rating)` no están en el HTML** — solo su agregado.

Dónde sí están: en el shelf **"My Votes"** de cada usuario, que se sirve por el endpoint `/ajax.php?user_shelves` cifrado.

**Qué implica para el dataset:** sin el ajax, un usuario que reseñó 6 y puntuó 300 aparecería con 6 filas. Con el ajax (decisión del usuario, §10) esas 300 entran como `source=vote` en `interactions`. Los items de wardrobe van a **otra tabla** (`wardrobe.parquet`, have/had/want): no son una calificación y no se mezclan con las reviews.

**La magnitud:** en Sauvage la relación es de ~8 votos por cada review. Si se sostiene, el ajax es el salto de densidad del dataset, no un extra menor.

Las dos razones que pesaban para dejarlo fuera:
1. `robots.txt` prohíbe `/ajax` para `User-agent: *`.
2. Requiere el passphrase de `window._pd`, que no está en el HTML.

**Decisión (usuario): perseguirlo.** Ver §10. El descifrado se porta a Python
(CryptoJS OpenSSL / EvpKDF-MD5); no hay navegador en el camino caliente. El
passphrase se recupera del bundle. Si esa recuperación falla, la fase 3
sigue con las reviews del HTML.

---

## 1. Consideraciones legales y éticas (leer antes de ejecutar)

Esto no es opcional en un contexto académico:

- `robots.txt` declara `Content-Signal: ai-train=no` y `use=reference`. Un sistema de recomendación de filtrado colaborativo **no** es entrenamiento de un modelo de IA generativa, pero conviene dejar constancia del uso académico y no redistribuir el corpus de texto crudo.
- `robots.txt` prohíbe para `*`: `/admin`, `/ajax`, `/goto.php`, `/a.php`, `/social`, `/thumbz`, `/cdn-cgi`, `/board/profile.php`, `/board/userlist.php`, y las páginas de búsqueda. Las rutas que sí usamos (`/perfume/…`, `/designers/…`, `/@usuario`) no están prohibidas. **Excepción explícita:** `POST /ajax.php?user_shelves` para wardrobe y votos sin review (ver §10).
- Ojo: `robots.txt` bloquea explícitamente `User-agent: Scrapy`. Si usamos Scrapy hay que fijar un User-Agent de navegador real (que además es necesario para la coherencia con el fingerprint TLS).
- **PII**: estamos recolectando datos de personas. Desde el minuto cero:
  - Hashear usernames (`sha256(username + salt)`) en la tabla de export; mantener el mapeo en un archivo aparte, fuera de versionado.
  - No recolectar campos sensibles del perfil que no aporten al modelo.
  - No publicar el dataset con texto de reviews atribuible.
- Rate limiting cortés (ver §4). El objetivo es no degradar el servicio.

---

## 2. Modelo de datos objetivo

Tres catálogos, más tablas auxiliares.

### `items` (perfumes)

Clave: `perfume_id` (entero, del URL y de `:perfume-id`).

| Campo | Origen |
|---|---|
`perfume_id`, `url`, `slug` | URL
`name`, `brand` (designer) | JSON-LD / `<title>` / breadcrumb
`gender` (men/women/unisex), `launch_year` | encabezado
`perfumers[]` | sección "Perfumer"
`rating_value`, `rating_count` | microdata `aggregateRating` (ej. 3.85 / 33.917)
`main_accords[]` con intensidad % | widget de accords
`notes_top[]`, `notes_middle[]`, `notes_base[]` | `pyramid-notes-new` / `pyramid-level-new`
`longevity_dist`, `sillage_dist` | `longevity-rating-new`, `sillage-rating-new`
`seasons_dist`, `day_night_dist` | `seasons-rating-new`
`gender_vote_dist`, `price_value_dist` | `gender-widget-new`, `price-value-widget-new`
`likes_dist` (love/like/dislike/hate) | `likes-rating-new`
`similar_perfumes[]` | `similar-perfumes-new`
`pros_cons` | `pros-cons-new`
`country`, `parent_company`, `groups[]`, `image_url` | metadatos laterales
`reviews_total` | contador "Reviews (4.2K)"

Los `notes_*` y `main_accords` son el **contenido para el modelo híbrido / cold-start**.

### `users`

Clave primaria: `member_id` (entero, de `:member-id`). Clave natural de crawl: `username_slug`.

| Campo | Origen |
|---|---|
`member_id` | `:member-id` — **solo disponible en la página de perfil**
`username_slug` | `/@lanes100` → `lanes100`; clave de join durante el crawl
`username_display` | `Lanes100` (con mayúsculas originales)
`username_hash` | `sha256(slug + salt)` para el export público
`profile_url`, `avatar_url` | perfil
`reviews_total` | `:reviews-total` (ground truth del sitio)
`n_reviews_scraped`, `first_review_ts`, `last_review_ts` | derivado
`mean_rating`, `rating_std`, `distinct_brands` | derivado (perfilado de usuario)

Uso `member_id` como canónico y no el slug porque el slug **puede cambiar** si el usuario se renombra (el bundle incluso expone un `:admin-rename`), mientras que el ID numérico es estable.

### `interactions`

Clave primaria: `review_id`. Grano: una review = un par (usuario, item).

| Campo | Origen |
|---|---|
`review_id` | `id="parent…"` / `comment-id` / `id` del JSON de perfil
**`perfume_id`** | `item-id="31861"` / `parfem_id` / URL — **siempre presente**
**`member_id`** | resuelto vía perfil (ver §3.4)
`username_slug` | disponible directo en ambas fuentes
`rating` (1–5, nullable) | `perfume_votes.rating` ← **señal explícita principal**
`relation` (have/had/want) | `perfume_votes.relation` ← señal implícita
`longevity`, `sillage`, `gender_vote` | `perfume_votes`
`season_winter/spring/summer/autumn`, `day`, `night` | `perfume_votes` ← contexto
`timestamp` (unix) | `vrijeme` / `unixtime`
`review_text` | `komentar` / `reviewBody`
`source` (`perfume_page` \| `profile_page`) | procedencia, para auditoría

Sobre tu pregunta de los IDs: **sí, quedan guardados los dos**, pero con un matiz que descubrí al revisar el HTML y que el plan original no cubría bien.

`perfume_id` viene siempre, de las dos fuentes. `member_id` **no está en la página de perfume** — ahí solo hay username. Entonces el flujo es:

1. Al parsear una página de perfume escribo la interacción con `username_slug` y `member_id = NULL`.
2. Al crawlear el perfil de ese usuario obtengo su `member_id`.
3. Un paso de resolución hace el backfill de `member_id` en `interactions` por `username_slug`.

Como de todas formas hay que visitar el perfil de todo usuario que se conserve (para sus atributos y su histórico completo), esto no agrega requests: se resuelve solo. La invariante que se valida antes del export es que **ninguna fila de `interactions` tenga `member_id` o `perfume_id` nulos** (§3.6).

---

## 2b. Umbrales de filtrado (según tus directivas)

Tus tres directivas: nada de items sin reviews, nada de items con muy pocas reviews, nada de usuarios sin reviews.

### Principio de diseño: portón permisivo al crawlear, filtro estricto al exportar

Esta separación es importante. Filtrar de más durante el crawl es **irreversible**: si descarto un item con 4 reviews y después decido que el umbral era 3, tengo que volver a crawlear. Filtrar al exportar es gratis y reproducible.

Así que uso dos umbrales distintos:

| Etapa | Parámetro | Valor sugerido | Efecto |
|---|---|---|---|
| Portón de crawl (items) | `CRAWL_MIN_ITEM_REVIEWS` | **1** | Descarta items con 0 reviews. No se puede saber antes de descargar la página, pero sí antes de gastar el parseo completo y las visitas de perfil |
| Portón de crawl (usuarios) | `CRAWL_MIN_USER_REVIEWS` | **1** | Implícito: los usuarios se descubren *desde* reviews, así que un usuario con 0 reviews nunca entra al frontier |
| Filtro de dataset | `MIN_ITEM_INTERACTIONS` | **5** | Umbral real de utilidad para el SR |
| Filtro de dataset | `MIN_USER_INTERACTIONS` | **5** | |

**Sobre "usuarios que no escribieron reviews":** quedan excluidos por construcción, no hace falta un filtro. El frontier de usuarios se puebla exclusivamente con los autores de reviews encontradas. Un miembro con 0 reviews nunca aparece en ningún lado del corpus, así que nunca lo visitamos. De los 2,0M de miembros del sitio, solo una fracción reseñó.

### El filtro tiene que ser iterativo (k-core)

Este es el punto técnico que importa: aplicar los dos umbrales una sola vez **no alcanza**. Si elimino un usuario con 4 reviews, esas 4 reviews desaparecen, y un item que tenía 5 puede caer a 4 y también tener que salir — lo que a su vez puede tumbar a otro usuario. Hay efecto cascada.

La solución estándar es el **filtrado k-core iterativo**: repetir "eliminar usuarios con <k, eliminar items con <k" hasta que no cambie nada (punto fijo). Se implementa en unas 15 líneas con DuckDB o Polars.

Recomiendo **k=5**, que es el valor convencional en benchmarks de SR (MovieLens, Amazon Reviews) y hace comparable tu trabajo con la literatura.

### Corolario práctico: reportar la sensibilidad al umbral

Como el umbral es una decisión de modelado y no un hecho, conviene guardar el dataset **sin filtrar** en `staging/` y generar los cortes filtrados como vistas. Así podés reportar en la tesis una tabla de sensibilidad (k=3, 5, 10 → n_users, n_items, sparsity) sin volver a tocar la red. Es un argumento fuerte para una defensa y sale gratis si se diseña así desde el principio.

`rating` puede venir `null` (review sin voto). Hay que decidir: descartarlas para el modelo explícito, o tratarlas como feedback implícito. Recomiendo conservarlas con flag y decidir en el modelado.

Los campos de estación/momento del día habilitan un **recomendador sensible al contexto**, que es un plus interesante para la tesis.

---

## 3. Estrategia y orden de ejecución

El orden importa porque **la Fase 2 produce items e interacciones simultáneamente**. Ese es el atajo central del plan: no hay que crawlear 2M de perfiles para tener las interacciones.

```
Fase 1  Enumerar IDs de items       (barato, define el universo)
Fase 2  Páginas de perfume          → items + ~70% de interacciones + semillas de usuarios
                                      ↳ portón: descartar items con 0 reviews
Fase 3  Perfiles de usuario         → users + member_id + cola de interacciones
Fase 4  Resolución de member_id     → backfill de la FK en interactions
Fase 5  Backfill de items huérfanos
Fase 6  Consolidación, k-core iterativo, export
```

Por qué sigo recomendando **item-first** (páginas de perfume antes que perfiles) incluso con tus directivas de umbral: es la **única fuente del conteo real de reviews por item** (`reviews_total`), que es justo lo que necesita el portón. Si arrancara por usuarios, el conteo de reviews de cada item sería una estimación sesgada de mi muestra: un item con 50 reviews reales podría aparecer con 3 solo porque no crawleé a los otros 47 autores, y lo descartaría por error. Item-first da ground truth.

### Fase 1 — Enumeración del catálogo de items

**Cómo:** `/designers/` lista el índice A–Z de marcas con sus conteos. Cada página de marca (`/designers/Dior.html`) lista todos sus perfumes.

Verificado: `/designers/Dior.html` → 200, 2.65MB, **357 IDs únicos** de perfume extraídos por regex sobre `/perfume/…-(\d+)\.html`.

**Salida:** tabla `item_frontier` con los ~137K `perfume_id` + URL. Costo: unos pocos miles de requests (una por marca). Menos de una hora.

Por qué no el sitemap: devuelve 403 incluso con impersonación (probé `sitemap.xml`, `sitemap_index.xml`, `perfume-sitemap.xml` → 403/404). Las páginas de marca son la ruta confiable.

**Checkpoint:** validar que el total se acerque a 137.633. Si falta mucho, complementar con `/notes/`, `/country/` y `/perfume-map`.

### Fase 2 — Páginas de perfume (el caballito de batalla)

Para cada `perfume_id` de la Fase 1, bajar la página y extraer en **una sola pasada**:

1. Todos los features del item (§2).
2. **Todas las reviews renderizadas** (~hasta 210) con su blob `perfume_votes` → filas de `interactions`.
3. Los usernames y URLs de perfil → semillas para `user_frontier`.

Rendimiento: la página pesa ~1,9MB. **No guardar el HTML crudo** — 137K × 1,9MB ≈ 260GB. Parsear en streaming, escribir Parquet, descartar. Opcionalmente guardar comprimido con zstd solo una muestra del 1% para poder re-parsear si cambia el layout.

Marcar `reviews_truncated = (reviews_total > reviews_scraped)`. Esos items alimentan la Fase 3.

**Portón de items (tu directiva):** si `reviews_total == 0`, el item se marca `status='skipped_no_reviews'` en el frontier, se guarda su fila mínima en `items` (para trazabilidad y para poder revisar la decisión después) y **no genera ninguna semilla de usuario**. Esto es lo que hace que el portón ahorre trabajo de verdad: no ahorra el request del item, pero evita arrastrar cientos de miles de perfiles inútiles a la Fase 3, que es la fase caro.

**Estimación:** 137K requests a ~6 req/s efectivos ≈ **6–7 horas**. Reanudable.

### Fase 3 — Perfiles de usuario

Dos objetivos: construir el catálogo `users` y **recuperar las interacciones truncadas**.

Priorizar la cola de `user_frontier` para maximizar rendimiento por request:
1. Usuarios que aparecen en items con `reviews_truncated = true` (son los que cierran los huecos).
2. Usuarios con más apariciones en el corpus (los más activos aportan más aristas).
3. El resto, por muestreo.

Cada perfil (~400KB) devuelve el array completo de reviews del usuario en un solo request. Un usuario con 500 reviews aporta 500 interacciones por 1 request — muchísimo más eficiente que paginar páginas de perfume.

**Decisión de alcance:** no crawlear los 2M de miembros. La distribución es long-tail y los usuarios con 1 sola review no aportan casi nada al filtrado colaborativo. Recomiendo apuntar a **~150–250K usuarios activos**, lo que debería cubrir la gran mayoría de las 2.6M reviews. Con eso el grafo queda denso y el dataset manejable.

**Estimación:** ~200K requests ≈ **8–10 horas**.

### Fase 4 — Resolución de `member_id`

Paso puramente local, sin red. Con los perfiles de la Fase 3 se construye el mapa `username_slug → member_id` y se hace `UPDATE interactions SET member_id = … WHERE username_slug = …`.

Casos borde a manejar explícitamente:

- **Usuario renombrado o eliminado** entre la Fase 2 y la 3 → el perfil da 404. La interacción queda con `member_id` nulo. Se descarta en la validación final y se cuenta en el reporte de cobertura.
- **Slug con distinta capitalización** entre fuentes → normalizar a minúsculas siempre (`/@Quilter` y `/@quilter` son el mismo usuario).
- **Atajo del avatar:** para los usuarios cuyo avatar es `avatari/[mt]\.(\d+)\.jpg`, el `member_id` se puede inferir sin visitar el perfil (verificado en §0). Sirve como **chequeo cruzado** de la resolución, no como reemplazo: si el ID inferido no coincide con el del perfil, hay un bug en el parser y quiero saberlo. No lo uso para saltear la visita porque el perfil se necesita igual por el histórico completo.

### Fase 5 — Backfill de items huérfanos

Las reviews de la Fase 3 referencian `parfem_id` que pueden no estar en el catálogo (perfumes descatalogados, o marcas que no capturamos). Diferencia de conjuntos → recrawlear esas páginas de perfume. Garantiza integridad referencial: **toda interacción apunta a un item existente**.

### Fase 6 — Consolidación y export

1. **Dedup** de `interactions` por `review_id` (la misma review llega por ambas fuentes; preferir `profile_page` que trae el texto completo sin truncar).
2. **Integridad referencial**: descartar y contabilizar toda fila con `member_id` o `perfume_id` nulo, o que apunte a un item/usuario ausente. Esta es la validación que cierra el tema de los IDs.
3. **Filtrado k-core iterativo** (§2b) con k=5, hasta punto fijo.
4. **Splits temporales** usando `timestamp` (leave-one-out temporal o corte global por fecha). Evitar splits aleatorios: filtran información del futuro.
5. **Export**: Parquet + un `dataset_card.md` con conteos, sparsity, distribución de ratings, período cubierto, tabla de sensibilidad al umbral y limitaciones conocidas.

Métricas de sanidad a reportar: n_users, n_items, n_interactions, sparsity, media de ratings, distribución de reviews por usuario/item.

---

## 4. Estrategia anti-bloqueo

Basada en lo que **efectivamente funcionó** en las pruebas, en capas de menor a mayor costo:

### Capa 1 — Impersonación TLS (camino principal, ~99% del tráfico)

`curl_cffi` con `impersonate="chrome"`. Verificado funcionando. Es lo que resuelve el problema: Cloudflare acá bloquea por **fingerprint TLS/HTTP2**, no por JS challenge.

- Rotar entre perfiles (`chrome`, `chrome131`, `firefox133`, `safari18_0`) por sesión, no por request.
- **Sesiones persistentes** con cookies (`curl_cffi.Session`), reutilizadas por bloques de N requests.
- Headers coherentes con el perfil: `Accept-Language: en-US,en;q=0.9`, `Referer` plausible (venir de la página de marca al ir al perfume), `Sec-Fetch-*`. `curl_cffi` ya maneja el orden de headers, que es parte del fingerprint.

### Capa 2 — Comportamiento (sí, incluye el sleep aleatorizado)

Respondiendo directo a tu pregunta: **sí, sleep aleatorizado, y no, no se usa navegador en el camino normal.**

El delay concreto que propongo:

```python
BASE_DELAY = 0.8          # segundos
JITTER     = (0.4, 2.0)   # rango uniforme
await asyncio.sleep(random.uniform(*JITTER))
```

Un delay **fijo** sería contraproducente: un patrón de exactamente 1,000s entre requests es en sí mismo una firma de bot, más detectable que ir un poco más rápido de forma irregular. El jitter uniforme entre 0,4 y 2,0s por worker, con 6 workers, da ~5–6 req/s agregados y un patrón temporal que parece tráfico humano concurrente.

Sobre el navegador: **no lo uso en el camino principal, y eso es una decisión deliberada, no una omisión.** Las pruebas mostraron que Cloudflare acá filtra por fingerprint TLS, no con un JS challenge, así que `curl_cffi` alcanza. Un navegador headless sería entre 20 y 50 veces más lento y más pesado en RAM — con 337K requests la diferencia es entre 30 horas y varias semanas. El navegador queda como **fallback** (Capa 4), solo si aparece un challenge real.

Resto de las medidas de comportamiento:

- Concurrencia **4–8 workers**, no más.
- Backoff exponencial con jitter ante 403/429/503 (`tenacity`).
- **Detección de challenge**: chequear `"Just a moment"` / `"challenge-platform"` en el body junto con ausencia de marcadores de contenido real (ojo: el script de Cloudflare está embebido en *todas* las páginas, incluso las buenas — validar por presencia de contenido esperado, no por presencia del script; me pasó de tener un falso positivo con eso).
- Circuit breaker: si la tasa de challenges supera el 5%, pausar y bajar la concurrencia automáticamente.
- Correr de noche en el huso horario del sitio.

### Capa 3 — Rotación de IP (si aparecen bloqueos)

Pool de **proxies residenciales rotativos** (Bright Data / Oxylabs / IPRoyal / Decodo) con sesiones sticky por worker. En las pruebas no fue necesario, pero a escala de 137K + 200K requests desde una sola IP es probable que haga falta. Diseñar el cliente con la abstracción de proxy desde el principio.

### Capa 4 — Navegador stealth (fallback y casos raros)

Solo si Cloudflare escala a challenge real. **Camoufox** (Firefox parcheado, el estado del arte en evasión) o **patchright** (fork indetectable de Playwright) para resolver el challenge, extraer la cookie `cf_clearance` e **inyectarla de vuelta en la sesión de `curl_cffi`**. Así se paga el costo del navegador una vez cada muchos requests.

Este mismo canal serviría para extraer `cf_clearance` si Cloudflare escala a
challenge real. El descifrado AES de `/ajax` ya no depende del navegador: el
passphrase se recupera del bundle y CryptoJS se porta a Python.

**No usar:** `cloudscraper` (no funciona contra Cloudflare moderno), `undetected-chromedriver` (sin mantenimiento), `playwright-stealth` / `selenium-stealth` (detectables hoy).

---

## 4b. Reanudabilidad y tolerancia a fallos

Sí está contemplado, pero en el plan original estaba en una línea suelta y merece su propia sección: con crawls de 15+ horas, **no es un extra, es un requisito**.

### El frontier como máquina de estados en SQLite

Todo el estado del crawl vive en una tabla, no en memoria:

```sql
CREATE TABLE frontier (
  url            TEXT PRIMARY KEY,
  kind           TEXT NOT NULL,   -- 'designer' | 'perfume' | 'profile'
  entity_id      TEXT NOT NULL,   -- perfume_id | username_slug
  status         TEXT NOT NULL,   -- ver máquina de estados
  attempts       INTEGER DEFAULT 0,
  last_error     TEXT,
  next_retry_at  INTEGER,         -- unix ts; NULL = elegible ya
  claimed_at     INTEGER,         -- para detectar leases vencidos
  updated_at     INTEGER
);
CREATE INDEX idx_claimable ON frontier(kind, status, next_retry_at);
```

Máquina de estados:

```
pending ──claim──> in_progress ──ok──────> done
                        │
                        ├──error transitoria──> failed ──backoff──> pending
                        │                          │
                        │                     (attempts >= MAX)
                        │                          ↓
                        │                        dead   (dead-letter queue)
                        └──404 / sin reviews───> skipped
```

Esto responde directamente a tu pregunta de "si tiene que saltear un item y seguir con otro, que después lo vuelva a buscar": un item que falla **no se pierde ni bloquea la cola**. Pasa a `failed`, se le calcula `next_retry_at = now + backoff(attempts)`, y el worker sigue con el siguiente. Cuando vence el backoff vuelve a ser elegible automáticamente. Solo después de `MAX_ATTEMPTS` (sugiero 5) cae a `dead`, y los `dead` se reportan al final para revisión manual o un reintento dirigido.

Distingo `skipped` de `dead` a propósito: `skipped` es una decisión deliberada (404 real, o item sin reviews por tu directiva) y no hay que reintentarlo; `dead` es un fracaso que quizá quiera reintentar mañana con otra IP.

### Recuperación de una caída dura

El caso que importa: matás el proceso con Ctrl-C o se corta la luz mientras hay 8 requests en vuelo. Esas 8 filas quedan en `in_progress` para siempre y se perderían.

Solución: **leases con vencimiento**. Al arrancar, el pipeline ejecuta primero

```sql
UPDATE frontier SET status='pending', claimed_at=NULL
WHERE status='in_progress' AND claimed_at < (unixepoch() - 900);
```

Cualquier trabajo reclamado hace más de 15 minutos se considera abandonado y vuelve a la cola. Con eso `python -m pipeline.phase2 --resume` retoma exactamente donde quedó, sin trabajo duplicado ni perdido.

### Escrituras idempotentes

Reanudar solo es seguro si reprocesar una página **no duplica datos**. Tres medidas:

1. **Escritura atómica**: cada batch se escribe a `staging/part-<uuid>.parquet.tmp` y se hace `os.rename` al final. Un `rename` en el mismo filesystem es atómico, así que nunca queda un Parquet a medio escribir. Un `.tmp` huérfano se borra al arrancar.
2. **Commit del frontier después del flush de datos**, nunca antes. Si el proceso muere entre ambos, la URL sigue `in_progress` → lease vencido → se reprocesa. Se prefiere trabajo duplicado sobre datos perdidos.
3. **Dedup por clave primaria en la consolidación** (`review_id`, `perfume_id`, `member_id`). Absorbe cualquier duplicado del punto 2. Por eso el dedup de la Fase 6 no es cosmético: es lo que hace correcta la estrategia de reintentos.

### Checkpoints y observabilidad

- Flush a Parquet cada N=500 registros o 60s, lo que ocurra primero. Acota la pérdida ante caída a menos de un minuto de trabajo.
- Progreso derivado del frontier con SQL, no de un contador en memoria: `SELECT kind, status, count(*) FROM frontier GROUP BY 1,2`. Sobrevive a los reinicios y da un dashboard honesto.
- Log de la tasa de challenges por ventana de 5 min, para poder correlacionar un pico de fallos con un endurecimiento de Cloudflare.

### Nota sobre Scrapy y esto

El `JOBDIR` de Scrapy persiste la cola y el dupefilter, pero **solo en un shutdown ordenado** (un `SIGTERM`). Un `kill -9` o un corte de energía pierde el estado de la cola. Si la reanudabilidad robusta es prioridad —y por lo que preguntás, lo es— la **Opción B (asyncio + frontier propio en SQLite)** es la más sólida, porque el estado está commiteado en disco de forma transaccional en todo momento. Es la que recomiendo.

---

## 5. Librerías

### Núcleo

| Librería | Rol | Por qué |
|---|---|---|
| **`curl_cffi`** | Cliente HTTP con impersonación TLS/JA3 | **Validado contra el sitio.** Es la pieza que resuelve Cloudflare. `AsyncSession` para concurrencia |
| **`selectolax`** | Parseo HTML (motor Lexbor) | Órdenes de magnitud más rápido que BeautifulSoup — crítico con páginas de 1,9MB × 137K |
| **`orjson`** | Parseo de los blobs JSON embebidos | El más rápido; los blobs vienen HTML-escapeados (`html.unescape` primero) |
| **`pydantic`** v2 | Validación de esquema | Falla temprano si el layout del sitio cambia a mitad del crawl |
| **`tenacity`** | Retries con backoff exponencial | |
| **`aiolimiter`** | Rate limiting (token bucket) | |

### Orquestación

- **Opción B — recomendada: `asyncio` + `curl_cffi.AsyncSession` + `aiolimiter`**, con el frontier en SQLite (§4b). Unas 200 líneas, control total, y **el estado del crawl queda commiteado transaccionalmente en disco en todo momento** — que es la propiedad que hace la reanudación realmente confiable.
- **Opción A — `scrapy` + `scrapy-impersonate`.** El download handler usa `curl_cffi` por debajo, así que conserva el bypass, y trae gratis scheduling, dedup, `AutoThrottle` y reintentos. La descarté como primera opción por el límite del `JOBDIR` descrito en §4b (no sobrevive a un `kill -9`). Si se usa: fijar el User-Agent, porque `robots.txt` bloquea explícitamente `User-agent: Scrapy`.

### Almacenamiento

| Librería | Rol |
|---|---|
| **`duckdb`** | Staging + consultas analíticas sobre Parquet. Ideal para armar el dataset y calcular sparsity/k-core en SQL |
| **`pyarrow`** | Escritura Parquet particionada, incremental |
| **`polars`** | Transformaciones del dataset final (dedup, k-core, splits) |
| **`sqlite3`** (stdlib) | Frontier + estado del crawl + dedup de IDs visitados |

### Fallback anti-bot

| Librería | Rol |
|---|---|
| **`camoufox`** | Navegador stealth (Firefox) para minar `cf_clearance` |
| **`patchright`** | Alternativa: fork indetectable de Playwright |
| **`rnet`** / **`primp`** | Clientes HTTP alternativos (Rust) con otros fingerprints, para diversificar el pool |

### Observabilidad

`rich` (dashboard de progreso), `structlog` (logs JSON), `prometheus-client` opcional para métricas de tasa de challenge.

### Downstream (el SR, ya fuera del scraping)

- **`implicit`** — ALS / BPR sobre feedback implícito (`relation`: have/had/want).
- **`LightFM`** — híbrido; aprovecha `notes_*` y `main_accords` como features de item → resuelve cold-start.
- **`RecBole`** — benchmarking de decenas de modelos con splits estandarizados. Muy conveniente para la parte comparativa de una tesis.
- **`surprise`** — baselines clásicos de rating explícito (SVD, KNN).
- **`sentence-transformers`** — embeddings del texto de reviews como features adicionales.

---

## 6. Estructura de proyecto propuesta

```
scraper/
├── pyproject.toml              # uv / poetry
├── README.md
├── PLAN.md
├── config/
│   └── settings.toml           # concurrencia, delays, proxies, perfiles impersonate
├── src/fragrantica/
│   ├── http/
│   │   ├── client.py           # wrapper curl_cffi: rotación de perfiles, proxies, retries
│   │   └── challenge.py        # detección de challenge + escalado a Camoufox
│   ├── parsers/
│   │   ├── designer.py         # Fase 1: enumeración de IDs
│   │   ├── perfume.py          # Fase 2: item features + reviews + semillas de usuarios
│   │   └── profile.py          # Fase 3: atributos de usuario + histórico completo
│   ├── models.py               # esquemas Pydantic de Item / User / Interaction
│   ├── storage.py              # writers Parquet + frontier SQLite
│   └── pipeline/
│       ├── phase1_items.py  … phase5_export.py
├── data/
│   ├── raw/                    # muestra comprimida (1%) para re-parseo
│   ├── staging/                # Parquet por fase
│   └── final/                  # items.parquet, users.parquet, interactions.parquet
└── tests/
    └── fixtures/               # HTML congelado → tests de parser sin red
```

Los **tests con fixtures de HTML congelado** son importantes: el sitio va a cambiar el markup en algún momento, y querés que los parsers fallen en CI y no a mitad de un crawl de 15 horas.

---

## 7. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| Cloudflare endurece la protección a mitad del crawl | Diseño en capas (§4); Camoufox listo como fallback; checkpoints frecuentes para reanudar |
| Volumen de HTML (260GB si se guarda crudo) | Parsear en streaming y descartar; guardar solo muestra del 1% con zstd |
| Cambio de markup rompe parsers silenciosamente | Validación Pydantic + tests con fixtures + alertas por tasa de campos nulos |
| Truncado a 210 reviews en items populares | Fase 3 (perfiles) cierra el hueco; `reviews_truncated` marca la deuda explícitamente |
| Interacciones sin `member_id` (perfil 404, usuario renombrado) | Fase 4 resuelve la FK; la validación de integridad descarta y **contabiliza** los residuos |
| Umbral de reviews mal elegido, irreversible | Portón de crawl permisivo (=1) + filtro estricto al exportar; staging sin filtrar permite recortar de nuevo sin red |
| Corte de ejecución / caída dura | Frontier en SQLite con leases vencibles + escrituras atómicas + dedup (§4b) |
| Votos sin review inaccesibles (AJAX cifrado) | Documentar como limitación; el dataset de 2.6M reviews es suficiente |
| Sesgo de muestreo al no crawlear los 2M de usuarios | Priorización explícita + documentar el criterio en el dataset card; el k-core los eliminaría igual |
| Bloqueo de IP | Proxies residenciales con sticky sessions desde el diseño |
| PII / cumplimiento | Hashear usernames, no redistribuir texto crudo, uso académico documentado |

---

## 8. Cronograma estimado

| Fase | Requests | Tiempo | Notas |
|---|---|---|---|
| 0. Harness + parsers + tests | — | 2–3 días | Desarrollo |
| 1. Enumeración de items | ~3K | < 1 h | |
| 2. Páginas de perfume | ~137K | 6–8 h | Reanudable; produce items + interacciones + semillas |
| 3. Perfiles de usuario | ~200K | 8–10 h | Reanudable |
| 4. Backfill de huérfanos | ~5–15K | 1 h | |
| 5. Consolidación y export | — | 2–4 h | Sobre todo cómputo local |

**Total de red: ~24–30 horas**, ejecutables en 2–3 noches. El desarrollo del harness es el que domina el esfuerzo real.

---

## 9. Siguiente paso sugerido

Antes de escalar, construir un **vertical slice** de punta a punta sobre una sola marca (Dior, 357 perfumes):

1. Fases 1→5 completas, alcance reducido.
2. Validar que el dataset resultante entrena un ALS o LightFM sin problemas de integridad.
3. Medir la tasa real de challenges y calibrar concurrencia y delays con datos.

Recién entonces largar el crawl completo. Así se descubren los problemas de esquema y de bloqueo con un ciclo de feedback de minutos en lugar de horas.

---

## 10. Decisión: perseguir wardrobe y votos sin review

Decisión del usuario: incluirlos, aceptando ignorar `Disallow: /ajax`.

Implementación, sin navegador:

- Un `POST /ajax.php?user_shelves` extra por perfil (mismo jitter/circuit breaker).
- Payload CryptoJS `{ct,iv,s}` → AES-256-CBC, EvpKDF-MD5. El `iv` del JSON es redundante.
- El passphrase **no** está en el HTML (`toAbby` no abre los blobs). Es `window._pd("www.fragrantica.com")` (el `www.` importa); no se baja el bundle.
- Los **votos** son interacciones (`source=vote`, `review_id` nulo). El **wardrobe** (have/had/want) es una tabla aparte (`wardrobe.parquet`): no entra al k-core ni se colapsa con la review del mismo par (usuario, item). Dedup de interacciones: review > voto.
- Si el descifrado ajax falla, la fase 3 no se cae: guarda reviews y deja los shelves (o `fetch_shelves=False`).

La señal `relation` (have/had/want) de las reviews del HTML sigue en la fila de la review (el formulario de voto). El wardrobe es la colección completa, en `wardrobe.parquet`.
