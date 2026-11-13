"""API de un proceso: el catálogo se carga al arrancar y cada request solo rankea."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from fragrantica_serving.catalog import Catalog, Recommendation, load_catalog
from fragrantica_serving.ranking import Item, Preferences, Tab

LOGGER = logging.getLogger("uvicorn.error")


class RatingIn(BaseModel):
    perfume_id: int = Field(gt=0)
    rating: int = Field(ge=1, le=5)


class PreferencesIn(BaseModel):
    brands: list[str] = Field(default_factory=list)
    genders: list[str] = Field(default_factory=list)
    perfumers: list[str] = Field(default_factory=list)
    families: list[str] = Field(default_factory=list)

    def to_domain(self) -> Preferences:
        return Preferences(
            brands=_choices(self.brands),
            genders=_choices(self.genders),
            perfumers=_choices(self.perfumers),
            families=_choices(self.families),
        )


class SessionIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)

    @field_validator("username")
    @classmethod
    def strip_user(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("Nombre de perfil requerido")
        return text


class RecommendIn(SessionIn):
    tab: Tab = "populares"
    valoraciones: list[RatingIn] = Field(default_factory=list)
    preferencias: PreferencesIn = Field(default_factory=PreferencesIn)


class SessionOut(BaseModel):
    username: str
    conocido: bool
    avatar_url: str | None


class OptionsOut(BaseModel):
    brands: list[str]
    genders: list[str]
    perfumers: list[str]
    families: list[str]


class PerfumeOut(BaseModel):
    perfume_id: int
    name: str
    brand: str
    gender: str
    olfactive_family: str
    perfumers: list[str]
    launch_year: int | None
    rating_value: float
    rating_count: int
    description: str
    image_url: str
    url: str
    rank: int


class RecommendOut(BaseModel):
    username: str
    conocido: bool
    avatar_url: str | None
    tab: Tab
    perfumes: list[PerfumeOut]


def _choices(values: Iterable[str]) -> frozenset[str]:
    return frozenset(value.strip() for value in values if value and value.strip())


def _origins() -> list[str]:
    raw = os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def _catalog(request: Request) -> Catalog:
    catalog = getattr(request.app.state, "catalog", None)
    if catalog is None:
        raise HTTPException(status_code=503, detail="El catálogo todavía no está cargado")
    return catalog


def _perfume_out(item: Item, rank: int) -> PerfumeOut:
    return PerfumeOut(
        perfume_id=item.perfume_id,
        name=item.name,
        brand=item.brand,
        gender=item.gender,
        olfactive_family=item.olfactive_family,
        perfumers=list(item.perfumers),
        launch_year=item.launch_year,
        rating_value=item.rating_value,
        rating_count=item.rating_count,
        description=item.description,
        image_url=item.image_url,
        url=item.url,
        rank=rank,
    )


def _recommend_out(result: Recommendation) -> RecommendOut:
    return RecommendOut(
        username=result.username,
        conocido=result.conocido,
        avatar_url=result.avatar_url,
        tab=result.tab,
        perfumes=[_perfume_out(item, index) for index, item in enumerate(result.perfumes, start=1)],
    )


def create_app(catalog: Catalog | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if catalog is None:
            LOGGER.info("Cargando catálogo")
            started = time.perf_counter()
            app.state.catalog = load_catalog()
            LOGGER.info("Catálogo listo en %.1f s", time.perf_counter() - started)
        else:
            app.state.catalog = catalog
        yield
        app.state.catalog = None

    app = FastAPI(title="Fragrantica", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins(),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health(request: Request) -> dict[str, bool]:
        return {"ready": getattr(request.app.state, "catalog", None) is not None}

    @app.get("/opciones", response_model=OptionsOut)
    def opciones(request: Request) -> OptionsOut:
        options = _catalog(request).options
        return OptionsOut(
            brands=list(options.brands),
            genders=list(options.genders),
            perfumers=list(options.perfumers),
            families=list(options.families),
        )

    @app.post("/sesion", response_model=SessionOut)
    def sesion(body: SessionIn, request: Request) -> SessionOut:
        found = _catalog(request).session(body.username)
        return SessionOut(
            username=found.username,
            conocido=found.conocido,
            avatar_url=found.avatar_url,
        )

    @app.post("/recomendaciones", response_model=RecommendOut)
    def recomendaciones(body: RecommendIn, request: Request) -> RecommendOut:
        started = time.perf_counter()
        result = _catalog(request).recommend(
            body.username,
            body.tab,
            (rating.perfume_id for rating in body.valoraciones),
            body.preferencias.to_domain(),
        )
        LOGGER.info(
            "Recomendación de %s (%s) en %.3f s",
            result.username,
            body.tab,
            time.perf_counter() - started,
        )
        return _recommend_out(result)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
