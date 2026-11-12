# Cómo modificar este repo

El código es minimalista y simple. Sin sobreingeniería.

- Un archivo hace una cosa. Una función hace una cosa. Si un cambio necesita una capa, una clase base o un registro de plugins, no hace falta.
- Los parámetros van en `config.py`. No dejes un número que se pueda querer cambiar dentro de una función.
- Un modelo nuevo es una función que entrena con train y devuelve una matriz de scores del catálogo. Usa `metrics.py`. No traigas otro split ni otra métrica.
- Cada corrida se loguea en MLflow con métricas de validación. No se leen ni se loguean métricas de test.
- El diff se mantiene chico. No agregues un framework que el archivo no necesite.
- `SPECS.md` es el contrato del experimento. Si el código y ese archivo se contradicen, manda `SPECS.md`.
