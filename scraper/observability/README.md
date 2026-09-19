# Observabilidad

**El monitor en uso es Maple**, no este directorio.

```bash
maple start --offline
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318
export OTEL_SERVICE_NAME=fragrantica-scraper
```

Dashboard: `http://127.0.0.1:4318` (flag `--offline`) o el link de `local.maple.dev`.
Servicio `fragrantica-scraper`. Ver [`README.md`](../README.md) (sección Maple).

El `docker-compose.yml` de acá (collector + Prometheus + Loki + Grafana) es un
stack opcional que **no se usa**. No apuntar a un agente hacia Grafana.
