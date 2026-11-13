# Contrato del experimento

El sistema predice, para cada usuario, las próximas reviews y el orden según la nota que les va a poner. El modelo es el prototipo de dos etapas: retrieval, fusión por Reciprocal Rank Fusion y LambdaRank.

## Datos

Entran solo las reviews con fecha y rating de `scraper/data/final/interactions.parquet`, y el catálogo de `items.parquet`. Los votos no tienen fecha y no entran. El wardrobe no se usa. No hay género ni año de nacimiento del usuario: esas columnas del ranker quedan vacías.

## Matriz

Primero se arma la matriz. El corte activo está en `fragrantica_rec/config.py` (`ACTIVE_CUT`). Los tres cortes disponibles son 28/60, 22/80 y 30/60: mínimo de reviews por usuario y por perfume, iterando hasta que nadie más cae del piso.

Ese piso se calcula con todas las reviews de la matriz, también las que después se esconden. Cada fuente y el ranker se ajustan solo con el historial anterior a su corte.

## Split

Sobre la matriz ya filtrada, por usuario y por fecha:

- las últimas 10 reviews son el holdout, y son la evaluación
- dentro de lo anterior, tres folds rolling de horizonte 10 y mínimo de historia 5 entrenan el ranker
- el último fold es la validación del early stopping y de Optuna

No hay un test sellado aparte. Esas 10 interacciones se miden.

## Métrica

La selección es NDCG@10. La relevancia es la nota, de 1 a 5. La ganancia es `2^nota - 1`. Un positivo que el retrieval no trajo penaliza el NDCG. Se promedia un valor por usuario.

## Modelo

Las fuentes de candidatos, en este orden, son popularidad, coseno ítem-ítem, ALS, BPR, TF-IDF, two-tower y EASE. La fusión es Reciprocal Rank Fusion y se queda con un prefijo. LambdaRank ordena ese prefijo.

La marca ocupa el lugar del autor y la familia olfativa el del género: son una sola etiqueta por perfume. Perfumistas, accords, notas, género del perfume, nombre y descripción entran solo al texto del TF-IDF. La confianza de ALS, BPR, coseno y TF-IDF es `1 + rating / 5`.

`main.py evaluate` corre el holdout. `--tune` busca con Optuna y escribe `artifacts/`. Sin `--tune`, two_stage reutiliza un tuneo de la misma config. No hay lista de entrega: Optuna puntúa a todos los usuarios del último fold.
