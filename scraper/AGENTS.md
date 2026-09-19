# AGENTS.md

Guía de onboarding para agentes que trabajen en este repo. Leer completo antes
de tocar código: hay varios hallazgos no obvios sobre el sitio que, si se
ignoran, producen un dataset silenciosamente corrupto.

## Qué es esto

Scraper de [fragrantica.com](https://www.fragrantica.com) que construye un
dataset de tres dimensiones para entrenar un **sistema de recomendación**
(trabajo de maestría).

| Catálogo | Contenido |
|---|---|
| `items` | Perfumes: notas, accords, familia olfativa, rating agregado, perfumistas |
| `users` | Miembros que escribieron al menos una review |
| `interactions` | Reviews y votos (calificación explícita): `(member_id, perfume_id, rating 1-5, texto, timestamp, source)` |
| `wardrobe` | Colección have/had/want. **Tabla aparte**: no es un rating y no entra al k-core |

Escala del sitio, según sus propios contadores: **137.633 perfumes, 2,6M
reviews, 2,0M miembros**.

Documentos hermanos: [`PLAN.md`](PLAN.md) tiene el análisis del sitio y las
decisiones de diseño con su justificación. [`README.md`](README.md) tiene el uso
operativo. **Este archivo no los duplica**; se centra en estado y contexto.

## Estado actual (última actualización: items del slice enumerado done, fase 3 en curso)

Se implementó el pipeline completo, el vertical slice sobre Dior y el crawl
de las marcas enumeradas. El daemon está en **fase 3** (perfiles). La fase 2
de perfume quedó vacía salvo 6 URLs `deferred` (cuarentena 12 h).

### Implementación: completa

- Las 6 fases, el frontier reanudable, el cliente HTTP con impersonación TLS,
  los 3 parsers, la consolidación con k-core, el CLI y el **daemon**.
- `fragrantica phase 6` lee el frontier en solo-lectura y puede correr en
  paralelo al daemon: snapshot de staging, k-core, pisa `data/final/`.
- Tests en verde (incluye consolidación, crypto AES, parser de shelves, watchdog).
- `.gitignore` creado: `data/`, `.venv/`, caches. El mapeo privado no se versiona.

### Datos recolectados hasta ahora

Ver `fragrantica status`. Orden de magnitud reciente: ~18.5k perfumes `done`,
~2k skipped (0 reviews), ~40k perfiles `done` y ~100k pending. El export en
`data/final/` es un snapshot: reejecutar fase 6 suma los perfiles nuevos.

Los pending de perfume que quedaron son 6 `deferred` por interstitial (canario
OK). El daemon no se traba ahí: saltó a fase 3.

### Qué falta

1. Dejar corriendo `fragrantica daemon` hasta vaciar perfiles (y las 6 fichas
   `deferred` cuando venza el backoff).
2. Reejecutar `fragrantica phase 6` de a ratos para agrandar el dataset; fase 5
   (huérfanos) recién cuando no compita con el GET de perfiles.
3. Validar que el dataset entrena un ALS/LightFM.
4. Recién entonces el catálogo completo: **una IP hogareña no alcanza**
   (~2M perfiles). Ahí hace falta `FRAGRANTICA_PROXY` residencial.

## Bloqueador: Cloudflare por IP, no un bug del código

| Configuración | Resultado medido |
|---|---|
| 6 workers, jitter 0.4–2.0s (~5 req/s) | HTTP 429 sostenido tras ~150 requests |
| 1 worker, jitter 5–12 s | interstitial tras un puñado de requests en IP recién rotada |
| 1 worker, jitter 20–40 s + daemon | ~88 páginas OK en 45 min; interstitial en Dioressence |
| 1 worker, jitter 7–10 s + daemon | default actual (~400 GETs `/perfume/` por IP) |

Un burst corto **no** detecta el 429. Siete ráfagas del 5-sep-2026 cortaron
todas en **~397–400 GETs de `/perfume/`** (7–10 s → ~60 min; 10–15 s → ~85 min,
mismo conteo). No es una ventana de 1 h. En el browser el 429 sale en fichas
de perfume, no en perfiles. El daemon **arranca siempre en fase 2**; solo
si un 429 sale en este ciclo **pasa a fase 3**. Un 429 viejo en disco no
desvía: si rotaron la IP, el cupo está limpio. Challenge: espera 30 min y dobla.

```bash
.venv/bin/fragrantica daemon    # el proceso que hay que dejar vivo
.venv/bin/fragrantica status
pgrep -fl fragrantica           # un solo proceso
```

## Monitor: Maple, no Grafana

El dashboard es **[Maple](https://maple.dev/) en local**. Nunca Grafana, Loki
ni Prometheus: un agente que abra `localhost:3000` o el compose de
`observability/` se equivoca de herramienta.

```bash
maple start --offline
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_SERVICE_NAME=fragrantica-scraper
.venv/bin/fragrantica daemon
```

UI: `http://127.0.0.1:4318` (o el link de `local.maple.dev`) → servicio
`fragrantica-scraper` → **Metrics**. Fallos HTTP: `fragrantica.http.failures`
(`status_code`, `via`). Cooldowns: `fragrantica.daemon.cooldowns` (`phase`, `via`).
Logs de consola: pestaña Logs. Detalle operativo en [`README.md`](README.md).

Comandos de higiene del frontier:

```bash
.venv/bin/fragrantica reset-429          # pending+attempts=0 para 429/403/interstitial
.venv/bin/fragrantica retry-dead         # dead-letters genéricos
.venv/bin/fragrantica clear-cooldown     # no heredar espera; borrar daemon_state.json también
.venv/bin/fragrantica enqueue-shelves    # HTML ya done, sin closet → cola de POST
.venv/bin/fragrantica requeue-profiles   # perfiles already-done → pending (2º pase GET)
.venv/bin/fragrantica status
```

## Conocimiento del dominio que hay que tener

Cinco hallazgos verificados empíricamente. Los dos primeros son los que arruinan
el dataset si se ignoran.

### 1. El sitio usa `0` para "no votó", no como valor

Es el más peligroso. El blob de votos de cada review se ve así:

```json
{"rating":4,"winter":1,"longevity":3,"sillage":2,"gender":null,"relation":"had"}
```

Pero en la página de Sauvage, 51 de 210 reviews traen `rating:0` **y además**
`longevity:0`, `sillage:0` y todas las estaciones en 0: son usuarios que
escribieron texto sin votar nada.

Si un `rating=0` se colara al dataset, el recomendador lo leería como la **peor
calificación posible** en vez de como dato ausente, sesgando a la baja todas las
medias de item y de usuario e inventando señal negativa que nunca existió.

La normalización vive en `parsers/votes.py` y la semántica **no es uniforme**:

- `rating`, `longevity`, `sillage` → escalas 1-5, el 0 es ausencia → `None`
- estaciones, `day`, `night` → flags binarios, el 0 **sí** significa "no lo
  eligió"... pero solo si el usuario votó algo; si no votó nada, también `None`

El validador de `models.py` rechaza `rating=0` como red de seguridad.

### 2. Las páginas de perfume no traen el `member_id`

Solo el username y el slug `/@usuario`. El `member_id` numérico aparece
**únicamente** en la página de perfil (`:member-id="3158387"`).

Por eso el flujo es: fase 2 escribe interacciones con `username_slug` y
`member_id = NULL` → fase 3 crawlea perfiles → fase 4 hace el backfill de la FK.
Y por eso la fase 3 es obligatoria y no opcional.

Se usa `member_id` como clave canónica (no el slug) porque el slug cambia si el
usuario se renombra.

Hay un atajo parcial: los avatares tipo `avatari/m.3146574.jpg` codifican el
`member_id` (verificado en 2 perfiles), pero **no es universal** — los avatares
custom usan otro almacén. Se usa solo como chequeo cruzado del parser.

### 3. Cloudflare filtra por fingerprint TLS, no con JS challenge

`curl` normal → 403 "Just a moment" en toda página interior. `curl_cffi` con
`impersonate="chrome"` → 200 con contenido completo. **No hace falta navegador**
en el camino normal, y meterlo sería 20-50× más lento sin aportar nada.

Trampa: el script `challenge-platform` de Cloudflare está embebido en **todas**
las páginas, incluso las buenas. Buscarlo da falsos positivos. La detección
correcta está en `http_client.looks_like_challenge()` y hay un test que la
protege.

### 4. Las reviews vienen server-rendered, pero truncadas a ~200

No se cargan por AJAX: están en el HTML inicial. Excelente, porque un request de
perfume rinde item + ~200 interacciones + ~200 semillas de usuario.

Pero el archivo completo requiere login (el bundle dice `"Sign in to access the
full review archive"`). Con un promedio de ~19 reviews por perfume, para la
mayoría de items las 200 alcanzan; los populares quedan truncados y se marcan
con `reviews_truncated`. La cola se cubre vía fase 3.

### 5. Wardrobe y votos sin review: ajax cifrado, ahora en alcance

En Fragrantica puntuar y reseñar son acciones separadas. Sauvage tiene **33.917
votos** contra **~4.200 reviews**: ~8 votos por review.

Esas puntuaciones individuales y los items del wardrobe viven en
`POST /ajax.php?user_shelves`, que `robots.txt` prohíbe (`Disallow: /ajax`).
**Decisión del usuario: perseguirlos.** El payload viene cifrado CryptoJS
`{ct,iv,s}` (AES-256-CBC, EvpKDF-MD5). El passphrase no está en el HTML
(`toAbby` no abre los blobs). Es `window._pd(hostname)`: se deriva de
`www.fragrantica.com` (el `www.` importa). No hace falta bajar el bundle JS.

La fase 3 hace un POST extra por perfil. Si el descifrado falla, el perfil se
guarda igual con las reviews del HTML. Un 403 en el ajax corta los POST del
resto del proceso para no gastar 13k requests inútiles.

Un **429 en `/ajax.php?user_shelves` no es bloqueo de IP**. El GET del perfil
se confirma `done` y el POST va a `shelves_jobs` (cuaderno durable). Un worker
aparte drena esa cola. Si hay `FRAGRANTICA_SHELVES_PROXY` (residencial, aparte
de `FRAGRANTICA_PROXY`), el closet sale por esa IP y puede ir en paralelo al
HTML hogareño. Sin ese env, GET y POST no se solapan: es la misma IP.

Un 429 de ajax pausa solo el loop de shelves (~45 min). `StopCrawl` queda para
429/interstitial de **página**. Los perfiles ya crawleados sin closet se
encolan al arrancar la fase 3 o con `fragrantica enqueue-shelves`.

Los **votos** entran a `interactions` con `source=vote` y `review_id` nulo
(sí son una calificación). El **wardrobe** va a `staging/wardrobe/` y al
export `wardrobe.parquet`: have/had/want no se mezcla con las reviews ni
pasa por el k-core. El dedup de interacciones es por `(member_id, perfume_id)`
y prefiere review sobre voto. Un PARTITION BY `review_id` colapsaría todos
los votos nulos a una sola fila.

## Arquitectura

```
src/fragrantica/
├── config.py            CrawlConfig (red, cortesía) y DatasetConfig (umbrales)
├── models.py            Item / User / Interaction (Pydantic v2, valida esquema)
├── http_client.py       curl_cffi + rotación de perfiles, jitter, circuit breaker
├── observability.py     OTLP a Maple (métricas, logs, spans); no-op sin endpoint
├── frontier.py          máquina de estados del crawl en SQLite  <-- pieza clave
├── storage.py           writers Parquet atómicos (.tmp + rename)
├── parsers/
│   ├── designer.py      fase 1: enumeración de IDs
│   ├── perfume.py       fase 2: item + interacciones + semillas
│   ├── profile.py       fase 3: usuario + histórico completo + member_id
│   ├── votes.py         normalización del blob de votos  <-- leer el punto 1
│   ├── crypto.py        AES CryptoJS + passphrase = _pd(host)
│   └── shelves.py       votos -> Interaction; wardrobe -> WardrobeItem
├── pipeline/
│   ├── runner.py        motor genérico: concurrencia + estados + orden de commits
│   ├── daemon.py        watchdog: espera + probe + reanuda (fase 2 → 3)
│   ├── phases.py        fases 1, 2, 3, 5 (con red)
│   └── consolidate.py   fases 4 y 6 (locales): dedup, k-core, export
└── cli.py               typer: slice / phase / daemon / status / retry-dead
```

### Reanudabilidad: cómo funciona

Todo el estado vive en `data/frontier.db`, commiteado transaccionalmente.

```
pending --claim--> in_progress --ok--------> done
                        |
                        +--error transitoria--> failed --backoff--> pending
                        |                          |
                        |                    (attempts >= 6)
                        |                          v
                        |                        dead
                        +--404 / sin reviews-----> skipped
                        +--interstitial + canario OK -> deferred
```

Cuatro invariantes que **no hay que romper** al modificar el runner:

1. **El flush de datos ocurre ANTES del `mark_done`.** Si el proceso muere
   entremedio, la URL sigue `in_progress`, el lease vence y se reprocesa. Se
   prefiere trabajo duplicado (que el dedup de la fase 6 absorbe) sobre datos
   perdidos.
2. **Los leases vencen.** `reclaim_stale()` devuelve a `pending` lo que quedó
   `in_progress` hace más de 15 min. Es lo que hace segura la recuperación de un
   `kill -9`.
3. **El 429 de página en fase 2 corta el ciclo** (`requeue` + StopCrawl). En
   fase 3 el GET de perfil hace cooldown de *esa* tarea (espera + probe) y
   reanuda; el loop de shelves no se corta. Un 429 de ajax `/user_shelves`
   tampoco: el job vuelve a `shelves_jobs` y el HTML ya es `done`. Con
   `FRAGRANTICA_SHELVES_PROXY` el POST no comparte IP con el GET. Un
   interstitial hace un canario (Sauvage, misma sesión): si pasa, la URL
   va a `deferred` (12 h) y el lote sigue; si el canario también falla, el
   GET entra en el mismo cooldown (fase 3) o StopCrawl (fase 2).
4. **La condición de salida mira `waiting_count()`, no solo `pending_count()`.**
   `pending_count` solo cuenta lo elegible *ya*; sin `waiting_count` el runner
   abandonaría los items diferidos por backoff. (Este bug existió y está
   cubierto por un test.)

## Cómo correr

```bash
python3 -m venv .venv && .venv/bin/pip install -e .

.venv/bin/python -m pytest tests/ -q        # tests, ~1s, sin red
.venv/bin/fragrantica status
.venv/bin/fragrantica daemon                # fase 1 → 2 → 3, continuo
```

Los tests **no tocan la red**: corren contra HTML congelado en
`tests/fixtures/` (5,2MB, 4 fixtures). Correrlos siempre antes de commitear; son
la defensa contra un cambio de markup del sitio.

Para trabajo iterativo sobre parsers hay un script de salida legible:

```bash
.venv/bin/python tests/check_parsers.py
```

## Issues conocidos

1. **`data/staging/item_frontier/` tiene datos viejos.** Sus 358 filas se
   generaron antes de arreglar la contaminación de marcas (ver abajo) e incluyen
   39 perfumes que no son de Dior. No corrompe el dataset final (los items se
   reparsean de su propia página y el frontier dedupea por URL), pero la
   atribución de marca en esa tabla auxiliar es incorrecta. Para limpiarlo:
   borrar el directorio y recorrer la fase 1.

   El bug era que el listado de marca linkea perfumes ajenos desde widgets
   laterales ("currently wearing", relacionados). Arreglado acotando la
   selección a `a.prefumeHbox`; hay un test que lo cubre.

2. **`.gitignore` ya está.** Cubre `.venv/`, `data/` y caches. No commitear
   `data/final/PRIVATE_user_mapping.parquet` si alguien relaja el ignore.

3. **No subir `concurrency`.** El 429 de perfume es cupo de ~400 GETs por IP,
   no ritmo instantáneo. `delay_min`/`delay_max` (ahora 7–10 s) solo acorta
   la ráfaga. Si vuelve el interstitial, el daemon espera; no compensar con
   más workers.

4. **`reviews_total` es aproximado** en items populares: el sitio lo muestra
   abreviado ("4.2K"). La columna `reviews_total_is_approx` lo marca. No usarlo
   para aritmética exacta.

## Próximos pasos, en orden

1. `fragrantica daemon` hasta vaciar perfume y profile.
2. Fases 5 y 6; revisar el `dataset_card.md` generado.
3. Validar que el dataset entrena un ALS/LightFM sin problemas de integridad.
4. Recién entonces evaluar escalar al catálogo completo, con proxy residencial
   (las estimaciones de `PLAN.md` a ~6 req/s quedaron desactualizadas).

## Convenciones

- **Comentarios, docstrings y documentación en español.** Los identificadores en
  inglés. Mantener esa mezcla, es la convención del repo.
- Los comentarios explican **por qué**, no qué hace el código. Varios documentan
  hallazgos empíricos sobre el sitio; no borrarlos, son la memoria del proyecto.
- Al descubrir algo nuevo sobre el sitio: agregar un test con fixture y
  documentarlo acá o en `PLAN.md`.
- Nunca subir la concurrencia sin medir. El sitio ya demostró que responde 429.
- Los endpoints `/ajax` están en alcance por decisión explícita del usuario
  (`CrawlConfig.fetch_shelves`). No reabrir esa discusión: si hay que
  apagarlos, `fetch_shelves=False`.
- **Observabilidad = Maple.** No proponer Grafana ni abrir paneles de Grafana.
- **Commitear al terminar.** En este repo, cuando se completa el trabajo pedido,
  hay que hacer commit de todos los cambios (tests en verde). No hace falta que
  lo vuelvan a pedir; no dejar el working tree sucio "para después".
