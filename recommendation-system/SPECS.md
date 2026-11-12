# Contrato del experimento

El sistema predice, para cada usuario, las próximas reviews y el orden según la nota que les va a poner.

## Datos

Entran solo las reviews con fecha y rating de `scraper/data/final/interactions.parquet`. Los votos no tienen fecha y no entran. El wardrobe no se usa.

## Matriz

Primero se arma la matriz. El corte activo está en `config.py` (`ACTIVE_CUT`). Los tres cortes disponibles son 28/60, 22/80 y 30/60: mínimo de reviews por usuario y por perfume, iterando hasta que nadie más cae del piso.

Ese piso se calcula con todas las reviews de la matriz, también las que después se esconden. La popularidad, los embeddings y cualquier agregado de una review se calculan solo con train.

## Split

Sobre la matriz ya filtrada, por usuario y por fecha:

- las últimas 10 reviews son test
- las 10 anteriores son validación
- el resto es train

El test se escribe en `splits/test.parquet` y no se lee. No hay script que lo mida.

## Métrica

La selección es NDCG@10. La relevancia es la nota. La ganancia es `2^nota - 1`, descontada por `log2(posición + 1)`. Se promedia un valor por usuario, contra el catálogo completo menos lo que ya reseñó en train.

Acompañan Recall@10 y la cobertura del catálogo en el top 10. Esas tres se calculan solo en validación.

## Modelos

Los cuatro baselines corren siempre: popularidad con decaimiento temporal, EASE, item-kNN y ALS implícito. El two-tower es un solo modelo: el score es el producto interno y con eso se ordena el catálogo. La loss es implícita y el peso de cada positivo es la misma ganancia, `2^nota - 1`. `two_tower` usa el contenido del perfume. `two_tower_id` usa solo el id.

Un modelo nuevo entra por `run.py`, con el mismo train, la misma validación y las mismas métricas. Se queda el de mejor NDCG@10 de validación. Cada corrida queda en MLflow, sin métricas de test.

Los hiperparámetros de partida están en `config.py`. `tune.py` elige por NDCG@10 de validación y escribe el corte activo en `chosen.json`. La corrida siguiente usa esos valores.

`config.BASELINE` es el piso del reporte. `run.py` lo entrena si no está en `MODELS` y muestra la diferencia de cada modelo contra sus métricas de validación. La decisión del ranker usa solo los baselines que corrieron dentro de `MODELS`.
