# Recomendador de perfumes

Predice las próximas reviews de cada usuario y las ordena según la nota. El modelo es retrieval, fusión y LambdaRank. La métrica es NDCG@10 sobre las últimas 10 reviews. El contrato está en `SPECS.md`.

## Correr

Desde esta carpeta:

```bash
uv run python eda.py
uv run python main.py evaluate --model popularity --note "popularidad"
uv run python main.py evaluate --note "two_stage"
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
```

`eda.py` escribe `reports/eda.md` con el universo completo, la matriz del corte activo y qué se elimina.

`evaluate` arma el k-core de `ACTIVE_CUT`, reserva las últimas 10 reviews y mide el holdout. `--model` puede ser `two_stage`, `popularity`, `item_cosine`, `als`, `bpr`, `tfidf`, `ease` o `two_tower`. Sin el flag corre `two_stage`. `--tune` busca hiperparámetros con Optuna; sin ese flag, two_stage reutiliza el tuneo guardado en `artifacts/` para la misma config.

Para probar otro corte, cambia `ACTIVE_CUT` en `fragrantica_rec/config.py` a `22_80` o `30_60` y vuelve a correr.
