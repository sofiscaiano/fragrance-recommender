# Recomendador de perfumes

Predice las próximas reviews de cada usuario y las ordena según la nota. La métrica es NDCG@10 sobre las últimas 10 reviews. El modelo busca candidatos con siete fuentes, los fusiona con Reciprocal Rank Fusion y los reordena con LambdaRank. Corte, split y columnas están en `SPECS.md`.

## Correr

Hace falta [uv](https://docs.astral.sh/uv/) y estos dos archivos, que no están en el repositorio:

- `../scraper/data/final/interactions.parquet`
- `../scraper/data/final/items.parquet`

Entran solo las reviews con fecha y rating.

```bash
uv sync
uv run python eda.py
uv run python main.py evaluate --note "two_stage"
```

`eda.py` escribe `reports/eda.md`: cuántas reviews, usuarios y perfumes quedan en la matriz y qué se elimina. El corte activo es `ACTIVE_CUT` en `fragrantica_rec/config.py` (`28_60`; también están `22_80` y `30_60`).

`evaluate` reserva las últimas 10 reviews de cada usuario y mide ese holdout. `--note` es obligatoria.

Sin `--tune`, reutiliza un tuneo de la misma config en `artifacts/tuning_history.json`. Esa carpeta es local y no se sube. Si no hay un tuneo compatible, el comando pide `--tune`.

```bash
uv run python main.py evaluate --tune --note "busqueda two_stage"
```

`--tune` hace 30 trials de Optuna sobre el corte de la fusión, el peso de cada fuente y LambdaRank. Cada trial entrena las fuentes, incluido el two-tower.

Otras opciones: `--seed` (default 42), `--label-gain linear|exponential` (default exponencial; cambiarla pide otro `--tune`), `--two-tower-source` / `--no-two-tower-source`, `--ease-source` / `--no-ease-source`, `--data` y `--artifacts`.

## Resultados

Quedan en `artifacts/`. `evaluation.json` tiene el NDCG@10 del modelo y el de la popularidad. La misma corrida se registra en `mlflow.db`:

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db
```
