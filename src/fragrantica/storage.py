"""Escritura de datos con garantias de idempotencia.

Reanudar solo es seguro si reprocesar una pagina no duplica datos. Tres
medidas, en orden de actuacion:

1. Escritura atomica: cada batch va a un .tmp y se renombra al final. Un rename
   en el mismo filesystem es atomico, asi que nunca queda un Parquet a medias.
2. El commit del frontier ocurre DESPUES del flush de datos. Si el proceso muere
   entremedio, la URL sigue in_progress -> lease vencido -> se reprocesa. Se
   prefiere trabajo duplicado sobre datos perdidos.
3. Dedup por clave primaria en la consolidacion, que absorbe los duplicados que
   genera el punto 2.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel

log = logging.getLogger(__name__)


class ParquetWriter:
    """Acumula filas y las descarga a Parquet en batches atomicos."""

    def __init__(self, out_dir: Path, name: str, flush_every: int = 500) -> None:
        self.out_dir = out_dir / name
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.flush_every = flush_every
        self._buffer: list[dict[str, Any]] = []
        self.total_written = 0
        self._cleanup_orphan_tmp()

    def _cleanup_orphan_tmp(self) -> None:
        """Borra .tmp de una corrida anterior que murio antes del rename."""
        for orphan in self.out_dir.glob("*.tmp"):
            log.warning("borrando parquet huerfano %s", orphan.name)
            orphan.unlink(missing_ok=True)

    def add(self, record: BaseModel | dict[str, Any]) -> None:
        row = record.model_dump(mode="json") if isinstance(record, BaseModel) else record
        self._buffer.append(_flatten(row))
        if len(self._buffer) >= self.flush_every:
            self.flush()

    def add_many(self, records: list[BaseModel | dict[str, Any]]) -> None:
        for r in records:
            self.add(r)

    def flush(self) -> None:
        if not self._buffer:
            return
        table = pa.Table.from_pylist(self._buffer)
        final = self.out_dir / f"part-{uuid.uuid4().hex}.parquet"
        tmp = final.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp, compression="zstd")
        os.replace(tmp, final)  # atomico
        self.total_written += len(self._buffer)
        log.debug("%s: escritas %d filas en %s", self.name, len(self._buffer), final.name)
        self._buffer.clear()

    def __enter__(self) -> ParquetWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.flush()


def existing_ids(directory: Path, column: str) -> set[str]:
    """IDs ya escritos en un directorio de parts. Para no re-pedir la pagina."""
    files = list(directory.glob("*.parquet"))
    if not files:
        return set()
    ids: set[str] = set()
    for path in files:
        table = pq.read_table(path, columns=[column])
        ids.update(str(v) for v in table[column].to_pylist() if v is not None)
    return ids


def existing_int_ids(directory: Path, column: str) -> set[int]:
    """Igual que existing_ids pero para enteros (member_id del wardrobe)."""
    files = list(directory.glob("*.parquet"))
    if not files:
        return set()
    ids: set[int] = set()
    for path in files:
        table = pq.read_table(path, columns=[column])
        for v in table[column].to_pylist():
            if v is None:
                continue
            ids.add(int(v))
    return ids


def _flatten(row: dict[str, Any]) -> dict[str, Any]:
    """Serializa estructuras anidadas para que Parquet infiera un esquema estable.

    Las listas de objetos (accords, notes) se guardan como JSON string: son
    metadata de contenido que se consume entera, no se filtra por campo, asi
    que no vale la pena el costo de un esquema anidado.
    """
    import orjson

    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (list, dict)):
            if value and isinstance(value, list) and isinstance(value[0], (str, int, float)):
                out[key] = orjson.dumps(value).decode()
            elif value:
                out[key] = orjson.dumps(value).decode()
            else:
                out[key] = None
        else:
            out[key] = value
    return out
