# Scraper de Fragrantica para sistemas de recomendación

Construye un dataset de tres dimensiones (items, usuarios, interacciones) a
partir de [fragrantica.com](https://www.fragrantica.com) para entrenar un
sistema de recomendación.

El plan completo, con el análisis del sitio y las decisiones de diseño, está en
[`PLAN.md`](PLAN.md).

## Instalación

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

El salt de pseudonimización está en `DatasetConfig.username_salt` (`src/fragrantica/config.py`). No se lee del entorno.

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
.venv/bin/fragrantica daemon                     # 1 → 2 → 3, continuo (preferido)
.venv/bin/fragrantica phase 5                    # backfill de items huérfanos
.venv/bin/fragrantica phase 6                    # consolidar y exportar
```

`phase 6` es local y **se puede correr con el daemon en fase 3**. Lee un
snapshot de `staging/` más el mapa `slug → member_id`, aplica k-core y pisa
`data/final/`. No hay que fusionar a mano el parquet viejo de Dior: esas
filas ya están en staging. Reejecutar más tarde incorpora los perfiles
bajados en el medio. Las reviews de perfume cuyo autor todavía no tiene
perfil se descartan (sin `member_id`) hasta el próximo export.

### Proxy

El daemon lee `FRAGRANTICA_PROXY` y `FRAGRANTICA_SHELVES_PROXY` al arrancar,
una sola vez, al importar `CrawlConfig`. Hay que exportarlas en la misma
shell, antes del proceso. Sin ellas, el HTML sale por la IP de la máquina.

```bash
export FRAGRANTICA_PROXY="http://user:pass@host:port"
# opcional: solo el POST de wardrobe. Si falta, el POST usa la misma salida que el GET.
export FRAGRANTICA_SHELVES_PROXY="http://user:pass@residencial:port"
.venv/bin/fragrantica daemon
```

Varias URLs en la misma variable, separadas por coma. Cada una tiene que ser
un puerto sticky (una IP de salida distinta). El proceso se queda en el
primero mientras responda: no salta de IP al renovar la sesión TLS, porque
una IP nueva con el ritmo de crawl dispara el interstitial.

Si ese puerto responde 429 o se cae la conexión, entra en cooldown y el mismo
request sigue por el siguiente. Un interstitial prueba el canario en el mismo
puerto: si pasa, la ficha va a cuarentena y el puerto se conserva; si el
canario también falla, rota. La espera del daemon solo corre cuando no queda
ningún puerto libre. Sin proxy configurado no hay caída a otra salida: la IP
de la máquina sigue como hasta ahora.

Al arrancar, el daemon imprime cuántos proxies cargó; si no hay
`FRAGRANTICA_PROXY`, avisa que el HTML va por la IP hogareña.

`FRAGRANTICA_PROXY` es la salida de las páginas (fases 1–3 y 5).
`FRAGRANTICA_SHELVES_PROXY` es solo el POST a `/ajax.php?user_shelves`. Con
ese proxy aparte, el closet puede ir en paralelo al HTML. El catálogo
completo no entra en una IP hogareña: ahí `FRAGRANTICA_PROXY` tiene que ser
residencial.

### Monitoreo

```bash
.venv/bin/fragrantica daemon          # fase 1 → 2 → 3, no se apaga en el 429
.venv/bin/fragrantica status          # estado del frontier
.venv/bin/fragrantica probe           # un request: ¿ya se levantó el bloqueo?
.venv/bin/fragrantica clear-cooldown  # no heredar espera de interstitial/429 viejos
.venv/bin/fragrantica reset-429       # rehabilitar URLs caídas por 429/403
.venv/bin/fragrantica retry-dead      # devolver dead-letters a la cola
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
- **HTTP 429**: si hay otro puerto en `FRAGRANTICA_PROXY`, ese entra en
  cooldown y el crawl sigue. Si no queda ninguno (o no hay proxy), `phase` se
  detiene (exit 2). El daemon espera, un probe, y reanuda.
- **Interstitial**: canario a Sauvage **en la misma sesión y el mismo puerto**.
  Si el canario pasa, esa URL va a `deferred` (reintento en 12 h) y el puerto
  se queda. Si el canario también falla y hay otro puerto, rota. Si no, se
  corta igual que el 429. Para arrancar sin heredar esa espera:
  `fragrantica clear-cooldown` o borrar `data/daemon_state.json`.
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
| 1 worker, jitter 7–10 s + daemon | default actual (~400 GETs `/perfume/` / IP) |

`daemon` es el modo para terminar el slice. Cómo enrutar HTML y wardrobe
está en [Proxy](#proxy).

## Notas de implementación

Dos detalles que no son obvios y que cuestan un dataset silenciosamente
corrupto si se pasan por alto:

1. **El sitio usa `0` para "no votó"**, no como valor. Un `rating=0` que se
   colara entraría al recomendador como la peor calificación posible en vez de
   como dato ausente. Ver `parsers/votes.py`.
2. **Las páginas de perfume no traen el `member_id` numérico**, solo el
   username. La FK se resuelve al crawlear los perfiles (fase 4).
