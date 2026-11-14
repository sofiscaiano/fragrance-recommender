# Fragrantica

Recomendador de perfumes a partir de reviews de [Fragrantica](https://www.fragrantica.com). Predice, para cada usuario, las próximas reviews y las ordena según la nota.

| Carpeta | Qué es |
|---|---|
| `scraper/` | Baja el sitio y escribe el dataset |
| `recommendation-system/` | Entrena y mide el modelo. Es el experimento |
| `serving/` | API que rankea con el modelo ya entrenado |
| `web/` | Página que muestra el catálogo y las recomendaciones |

Para replicar el modelo: [recommendation-system/README.md](recommendation-system/README.md). El contrato del experimento está en [recommendation-system/SPECS.md](recommendation-system/SPECS.md).

## Datos

No están en el repositorio. Van en `scraper/data/final/`:

- `interactions.parquet`: reviews con fecha y rating
- `items.parquet`: catálogo de perfumes

El resto de `scraper/data/` es el crawl. No se versiona.
