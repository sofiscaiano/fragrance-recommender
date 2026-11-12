# Recomendador de perfumes

Predice las próximas reviews de cada usuario y las ordena según la nota. La métrica es NDCG@10 sobre validación. El test queda escrito y no se mide.

El corte, el modelo y los hiperparámetros de partida están en `config.py`. El contrato del experimento está en `SPECS.md`.

## Correr

Desde esta carpeta:

```bash
uv run python eda.py
uv run python run.py
uv run python tune.py
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
```

`eda.py` escribe `reports/eda.md` con el universo completo, la matriz del corte activo y qué se elimina. `run.py` arma el split, entrena los modelos de `config.MODELS` y loguea la validación en MLflow. Las métricas quedan como `ndcg_at_10`, `recall_at_10` y `coverage_at_10`. Al final compara cada modelo contra `config.BASELINE`; si ese modelo no está en `MODELS`, lo entrena igual para el reporte.

`tune.py` elige por NDCG@10 de validación y escribe el corte activo en `chosen.json`. La siguiente corrida de `run.py` usa esos valores. Si el corte no está en el archivo, siguen los de `config.py`.

Para probar otro corte, cambia `ACTIVE_CUT` en `config.py` a `22_80` o `30_60` y vuelve a correr.
