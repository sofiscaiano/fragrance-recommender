"""Esquemas de las tres dimensiones del dataset.

La validacion Pydantic actua como canario: si el sitio cambia el markup, el
parser empieza a devolver campos nulos y estos modelos fallan temprano en vez
de escribir silenciosamente un dataset degradado.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Gender = Literal["men", "women", "unisex", "unknown"]
Relation = Literal["have", "had", "want", "unknown"]


class Accord(BaseModel):
    name: str
    intensity: float  # 0-100, del ancho de la barra en el widget


class Note(BaseModel):
    name: str
    note_id: int | None = None
    level: Literal["top", "middle", "base", "single"]


class Item(BaseModel):
    """Un perfume."""

    perfume_id: int
    url: str
    name: str
    brand: str | None = None
    gender: Gender = "unknown"
    launch_year: int | None = None
    olfactive_family: str | None = None

    perfumers: list[str] = Field(default_factory=list)

    rating_value: float | None = None
    rating_count: int | None = None

    # El sitio muestra el total de reviews abreviado ("4.2K"), asi que este
    # valor es aproximado. Ver reviews_total_is_approx.
    reviews_total: int | None = None
    reviews_total_is_approx: bool = False
    reviews_scraped: int = 0
    reviews_truncated: bool = False

    accords: list[Accord] = Field(default_factory=list)
    notes: list[Note] = Field(default_factory=list)

    similar_perfume_ids: list[int] = Field(default_factory=list)
    image_url: str | None = None
    description: str | None = None

    @field_validator("perfume_id")
    @classmethod
    def _positive_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("perfume_id debe ser positivo")
        return v

    @property
    def notes_top(self) -> list[str]:
        return [n.name for n in self.notes if n.level == "top"]

    @property
    def notes_middle(self) -> list[str]:
        return [n.name for n in self.notes if n.level == "middle"]

    @property
    def notes_base(self) -> list[str]:
        return [n.name for n in self.notes if n.level == "base"]


class User(BaseModel):
    """Un miembro que escribio al menos una review.

    Los usuarios con cero reviews quedan excluidos por construccion: el frontier
    de perfiles se puebla solo con autores de reviews encontradas, asi que un
    miembro sin reviews nunca entra al corpus.
    """

    member_id: int
    username_slug: str
    username_display: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None

    reviews_total: int | None = None
    n_reviews_scraped: int = 0

    # Conteos y preferencia explícita que vienen en el HTML del perfil
    # (blobs :header / :punbbdata / member-tabs). No son métricas derivadas.
    wardrobe_count: int | None = None
    notes_count: int | None = None
    signature_perfume_id: int | None = None

    @field_validator("username_slug")
    @classmethod
    def _normalise_slug(cls, v: str) -> str:
        # /@Quilter y /@quilter son el mismo usuario.
        return v.strip().lower()


class WardrobeItem(BaseModel):
    """Un perfume en la coleccion del miembro (have / had / want).

    No es una interaccion de rating: el usuario no califico ni reseño, solo
    lo guardo. Vive en su propia tabla para no contaminar la matriz con la
    que se entrena el recomendador. `relation=unknown` se admite porque el
    JSON del ajax no esta congelado y a veces el estante no trae el status.
    """

    member_id: int
    username_slug: str
    perfume_id: int
    relation: Relation = "unknown"
    timestamp: int | None = None

    @field_validator("username_slug")
    @classmethod
    def _normalise_slug(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("perfume_id")
    @classmethod
    def _positive_id(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("perfume_id debe ser positivo")
        return v


class Interaction(BaseModel):
    """Un par (usuario, item) con senal explicita: review o voto sin texto.

    El wardrobe NO entra aca (ver WardrobeItem). perfume_id viene siempre.
    member_id NO esta en la pagina de perfume (solo el username), asi que se
    resuelve en la fase 4 por username_slug. El dedup final es por
    (member_id, perfume_id) y prefiere review sobre voto.
    """

    # None en votos sin review: esas filas no tienen review_id.
    review_id: int | None = None
    perfume_id: int
    member_id: int | None = None
    username_slug: str

    rating: int | None = None
    relation: Relation = "unknown"
    longevity: int | None = None
    sillage: int | None = None
    gender_vote: int | None = None

    season_winter: int | None = None
    season_spring: int | None = None
    season_summer: int | None = None
    season_autumn: int | None = None
    day: int | None = None
    night: int | None = None

    timestamp: int | None = None
    review_text: str | None = None

    source: Literal["perfume_page", "profile_page", "vote"] = "perfume_page"

    @field_validator("username_slug")
    @classmethod
    def _normalise_slug(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("rating")
    @classmethod
    def _rating_range(cls, v: int | None) -> int | None:
        # El 0 del sitio significa "no voto" y se normaliza a None antes de
        # llegar aca (ver parsers/votes.py). Un 0 en este punto seria un bug.
        if v is not None and not (1 <= v <= 5):
            raise ValueError(f"rating fuera de rango 1-5: {v}")
        return v
