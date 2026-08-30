# Scraper de Fragrantica para sistemas de recomendación

Construye un dataset de tres dimensiones (items, usuarios, interacciones) a
partir de [fragrantica.com](https://www.fragrantica.com) para entrenar un
sistema de recomendación.

El plan completo, con el análisis del sitio y las decisiones de diseño, está en
[`PLAN.md`](PLAN.md).

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Configurar el salt de pseudonimización antes de correr en serio:

```bash
export FRAGRANTICA_SALT="algo-secreto-y-estable"
```

## Uso

### Vertical slice (empezar por acá)

Corre las 6 fases de punta a punta sobre una sola marca. Sirve para validar el
esquema y calibrar la tasa de bloqueos con un ciclo de feedback de minutos en
vez de horas.

```bash
.venv/bin/fragrantica slice --designer Dior
```

### Fases individuales

Todas son reanudables: reejecutar el mismo comando retoma donde quedó.

```bash
.venv/bin/fragrantica phase 1                    # enumerar todas las marcas
.venv/bin/fragrantica phase 1 --designer Chanel  # una sola marca
.venv/bin/fragrantica phase 2                    # páginas de perfume
.venv/bin/fragrantica phase 2 --limit 50         # acotado, para calibrar
.venv/bin/fragrantica phase 3                    # perfiles de usuario
.venv/bin/fragrantica daemon                     # 2 y 3, continuo (preferido)
.venv/bin/fragrantica phase 5                    # backfill de items huérfanos
.venv/bin/fragrantica phase 6                    # consolidar y exportar
```

### Monitoreo

```bash
.venv/bin/fragrantica daemon      # fase 2 → 3, no se apaga en el 429
.venv/bin/fragrantica status      # estado del frontier
.venv/bin/fragrantica probe       # un request: ¿ya se levantó el bloqueo?
.venv/bin/fragrantica reset-429   # rehabilitar URLs caídas por 429/403
.venv/bin/fragrantica retry-dead  # devolver dead-letters a la cola
```

`status` lee del frontier en SQLite, así que refleja el estado real y sobrevive
a los reinicios.

## Interrupciones y reanudación

El estado del crawl vive en `data/frontier.db`, commiteado transaccionalmente.

- **Ctrl-C o `kill`**: volvés a correr el mismo comando y sigue. Las URLs que
  quedaron `in_progress` con requests en vuelo se recuperan por vencimiento de
  lease (15 min por defecto).
- **Un item falla**: no bloquea la cola. Pasa a `failed` con backoff exponencial
  y vuelve a ser elegible solo. Después de 6 intentos cae a `dead` y se reporta.
- **HTTP 429**: `phase` se detiene (exit 2). El daemon espera, un probe, y reanuda.
- **Interstitial**: canario a Sauvage **en la misma sesión**. Si el canario
  pasa, esa URL va a `deferred` (reintento en 12 h) y el lote sigue. Si el
  canario también falla, se corta igual que el 429.
- **`kill -9` o corte de luz**: igual que Ctrl-C. Nunca hay estado crítico solo
  en memoria, y las escrituras a Parquet son atómicas (`.tmp` + rename).

## Estructura de salida

```
data/
├── frontier.db                    # estado del crawl (reanudación)
├── staging/                       # datos crudos SIN filtrar, por fase
│   ├── item_frontier/
│   ├── items/
│   ├── interactions_from_perfume/
│   ├── interactions_from_profile/
│   └── users/
└── final/
    ├── items.parquet
    ├── users.parquet
    ├── interactions.parquet
    ├── dataset_card.md            # conteos, sparsity, limitaciones
    ├── report.json
    └── PRIVATE_user_mapping.parquet   # NO publicar ni versionar
```

El staging se guarda **sin filtrar** a propósito: permite regenerar el dataset
con otro umbral `k` sin volver a tocar la red, y reportar la tabla de
sensibilidad al umbral.

## Umbrales

Configurables en `src/fragrantica/config.py`.

| Parámetro | Default | Qué hace |
|---|---|---|
| `crawl_min_item_reviews` | 1 | Portón de crawl: descarta items sin reviews |
| `k_core` | 5 | Filtro de dataset: k-core iterativo hasta punto fijo |

La separación es deliberada. Filtrar de más durante el crawl es irreversible
(habría que volver a la red); filtrar al exportar es gratis y reproducible.

Los usuarios sin reviews quedan excluidos por construcción: el frontier de
perfiles se puebla solo con autores de reviews encontradas.

## Cortesía y cumplimiento

- Se respetan las rutas prohibidas por `robots.txt` **salvo** `/ajax`: la
  fase 3 pide `POST /ajax.php?user_shelves` para wardrobe y votos sin review
  (decisión explícita; apagable con `CrawlConfig.fetch_shelves=False`). El
  resto de `Disallow` se sigue respetando.
- Rate limiting con jitter aleatorio, calibrado empíricamente (ver más abajo).
- Los usernames se pseudonimizan con SHA-256 más salt en el export.
- Uso académico. No redistribuir el texto de las reviews atribuible a personas.

### Calibración medida

El vertical slice descubrió que **el sitio devuelve HTTP 429 bajo carga
sostenida**, algo que un burst corto de prueba no detecta:

| Configuración | Resultado |
|---|---|
| 6 workers, jitter 0.4–2.0s (~5 req/s) | 429 sostenido tras ~150 requests |
| 1 worker, jitter 20–40 s + daemon | ~88 páginas OK; no duplicar workers |
| 1 worker, jitter 10–20 s + daemon | default actual |

`daemon` es el modo para terminar el slice: un worker, 10–20 s entre
requests. El catálogo completo (137k items, ~2M perfiles) no entra en una IP
hogareña; ahí `FRAGRANTICA_PROXY` tiene que ser residencial.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q   # 78 tests, ~1s, sin red
```

Los parsers se testean contra HTML congelado en `tests/fixtures/`. Son
importantes: el sitio va a cambiar el markup en algún momento, y conviene que
los parsers fallen en CI y no a mitad de un crawl de 15 horas.

## Notas de implementación

Dos detalles que no son obvios y que cuestan un dataset silenciosamente
corrupto si se pasan por alto:

1. **El sitio usa `0` para "no votó"**, no como valor. Un `rating=0` que se
   colara entraría al recomendador como la peor calificación posible en vez de
   como dato ausente. Ver `parsers/votes.py`.
2. **Las páginas de perfume no traen el `member_id` numérico**, solo el
   username. La FK se resuelve al crawlear los perfiles (fase 4).
