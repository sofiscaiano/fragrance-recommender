# Demo

La página está en [`web/`](../web/). La API carga una vez el catálogo y `recommendation-system/artifacts/serving.joblib`, y cada pedido solo rankea. Las notas de la sesión quedan en el navegador.

Si falta el artefacto, o la última evaluación es más nueva:

```bash
cd recommendation-system
uv run python main.py export-serving
```

Ajusta las fuentes sobre toda la historia y escribe `artifacts/serving.joblib`. Tarda cerca de dos minutos. El LambdaRank sale de `evaluated_pipeline.joblib`.

## Local

Desde la raíz, la API y la página juntas:

```bash
./scripts/demo.sh
```

En macOS el script deja la máquina despierta. `GET http://127.0.0.1:8000/health` responde `{"ready": true}` cuando terminó de cargar. La página queda en `http://127.0.0.1:5173`. Ctrl+C apaga las dos.

Sin el script:

```bash
cd serving && uv run fragrantica-serve
cd web && npm install && npm run dev
```

Sin `VITE_API_URL`, la página llama a `http://localhost:8000`.

## Publicar la página

La página puede ir a Vercel. El modelo no: es un proceso de Python con el catálogo en memoria, y tiene que seguir corriendo en la máquina que lo sirve. Quien entra a la página llama a una URL HTTPS de esa API, no a `localhost`.

1. Dejá la API en `http://127.0.0.1:8000`.
2. Abrí un túnel. La URL rápida cambia si lo reiniciás:

   ```bash
   brew install cloudflared
   cloudflared tunnel --url http://127.0.0.1:8000
   ```

   Con dominio fijo, el token va en `serving/.env` (copiado de `.env.example`) y el hostname público apunta a `http://api:8000`:

   ```bash
   docker compose -f serving/docker-compose.yml --profile tunnel up --build api cloudflared
   ```

3. La API tiene que aceptar el origen de la página:

   ```bash
   CORS_ORIGINS="https://tu-pagina.vercel.app" uv run fragrantica-serve
   ```

4. En Vercel, el directorio raíz es `web`, el comando `npm run build` y la salida `dist`. `VITE_API_URL` es la URL HTTPS del túnel, sin barra final. `web/vercel.json` permite recargar `/recomendar/...`.

Si la máquina se duerme, la página carga y la API no responde.

La API sola, en Docker, con el modelo y los parquet montados en solo lectura:

```bash
docker compose -f serving/docker-compose.yml up --build
```
