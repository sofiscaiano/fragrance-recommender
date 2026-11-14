# Fragrantica

Recomendador de perfumes a partir de reviews de [Fragrantica](https://www.fragrantica.com). Predice, para cada usuario, las próximas reviews y las ordena según la nota.

| Carpeta | Qué es |
|---|---|
| `scraper/` | Baja el sitio y escribe el dataset |
| `recommendation-system/` | Entrena y mide el modelo. Es el experimento |
| `serving/` | API que rankea con el modelo ya entrenado |
| `web/` | Página. En Vercel se publica solo esta carpeta |

La página llama a la API para armar “Para vos”. Sin la API, carga y no recomienda.

Para replicar el modelo: [recommendation-system/README.md](recommendation-system/README.md). El contrato del experimento está en [recommendation-system/SPECS.md](recommendation-system/SPECS.md).

## Datos

No están en el repositorio. Van en `scraper/data/final/`:

- `interactions.parquet`: reviews con fecha y rating
- `items.parquet`: catálogo de perfumes

El resto de `scraper/data/` es el crawl, incluido `PRIVATE_user_mapping.parquet`. No se versiona.

## Demo

Hace falta `recommendation-system/artifacts/serving.joblib` (cómo generarlo está en el README del recomendador). Desde la raíz:

```bash
./scripts/demo.sh
```

La API queda en `http://127.0.0.1:8000` y la página en `http://127.0.0.1:5173`. Vercel, CORS y el túnel están en [serving/README.md](serving/README.md).
