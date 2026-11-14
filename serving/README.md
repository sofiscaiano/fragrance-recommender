# Demo en vivo

La página vive en [`web/`](../web/). La API carga una vez el catálogo y
`recommendation-system/artifacts/serving.joblib`. Cada pedido solo rankea.
Las notas de la sesión quedan en el navegador.

Si el artefacto no existe, o la última evaluación es más nueva que el joblib:

```bash
cd recommendation-system
uv run python main.py export-serving
```

Eso ajusta las fuentes sobre toda la historia y escribe `artifacts/serving.joblib`.
Tarda cerca de dos minutos. El LambdaRank es el de `evaluated_pipeline.joblib`.

## Local

Desde la raíz del repo, un solo worker de la API y la página al lado:

```bash
./scripts/demo.sh
```

En macOS el script deja la máquina despierta (`caffeinate`) mientras corre.
`GET http://127.0.0.1:8000/health` responde `{"ready": true}` cuando el
catálogo y el modelo terminaron de cargar. La página queda en
`http://127.0.0.1:5173`. Ctrl+C apaga las dos.

Sin el script, dos terminales:

```bash
cd serving
uv run fragrantica-serve
```

```bash
cd web
npm install
npm run dev
```

Sin `VITE_API_URL`, el front llama a `http://localhost:8000`.

## Compartir fuera de la red

La página puede vivir en Vercel o en Cloudflare Pages. El modelo no: es un
proceso de Python con el catálogo y `serving.joblib` en memoria, y tiene que
seguir corriendo en esta Mac. Cloudflare Tunnel le da una URL HTTPS pública.
Quien entra a la página llama a esa URL, no a `localhost`.

1. Dejá la API en `http://127.0.0.1:8000`.
2. Publicá la API con un túnel. Sin dominio, un túnel rápido alcanza para la
   demo (la URL cambia si lo reiniciás):

   ```bash
   brew install cloudflared
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

   Con un túnel nombrado y dominio en Cloudflare, la URL queda fija. El token
   va en `serving/.env` y el hostname público apunta a `http://api:8000`:

   ```bash
   caffeinate -dims docker compose -f serving/docker-compose.yml --profile tunnel up --build api cloudflared
   ```

3. Antes de que entre alguien, la API tiene que aceptar el origen de la página:

   ```bash
   CORS_ORIGINS="https://tu-pagina.vercel.app" uv run fragrantica-serve
   ```

4. Publicá `web/` con `VITE_API_URL` igual a la URL HTTPS del túnel, sin barra
   final. En Vercel el directorio raíz es `web`, el comando `npm run build` y
   la salida `dist`. En Cloudflare Pages es lo mismo; `web/public/_redirects`
   deja recargar `/recomendar/...`. `web/vercel.json` hace lo mismo en Vercel.

La Mac tiene que seguir despierta mientras haya gente adentro. Si se duerme,
la página carga y la API no responde.

## Docker

El puerto de la API queda en `127.0.0.1`. El modelo y los parquet se montan
en solo lectura; la imagen no los copia.

```bash
caffeinate -dims docker compose -f serving/docker-compose.yml up --build
```

`serving/.env` (a partir de `serving/.env.example`) puede definir
`CORS_ORIGINS` y `VITE_API_URL`. Con el perfil `tunnel`, Docker publica la
API por Cloudflare. El hostname público del túnel apunta a `http://api:8000`.

```bash
caffeinate -dims docker compose -f serving/docker-compose.yml --profile tunnel up --build
```
