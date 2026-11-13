# Cómo modificar este repo

El modelo es el paquete `fragrantica_rec`. La web y `serving/` no se tocan desde acá.

- Un cambio de algoritmo entra en la etapa que le corresponde: una fuente en `two_stage/retrieval.py`, una columna del ranker en `two_stage/columns.py`, el corte en `splits.py`.
- Los parámetros van en `fragrantica_rec/config.py`. No dejes un número que se pueda querer cambiar dentro de una función.
- La marca es la etiqueta de una sola casa y la familia olfativa es la del género. No agregues una tercera familia de transiciones para perfumistas.
- La nota es 1–5. La confianza de las fuentes que la normalizan usa `RATING_MAX`.
- El holdout y el horizonte rolling salen de `SplitConfig`. La métrica del holdout es NDCG@10.
- Cada corrida se loguea en MLflow. Los artefactos van a `artifacts/`.
- `SPECS.md` es el contrato del experimento. Si el código y ese archivo se contradicen, manda `SPECS.md`.
