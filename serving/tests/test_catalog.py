from pathlib import Path

import duckdb
from fastapi.testclient import TestClient

from fragrantica_serving.app import create_app
from fragrantica_serving.catalog import Catalog, Profile, load_catalog
from fragrantica_serving.ranking import Item, LikedPerfume, Preferences


def perfume(
    perfume_id: int,
    *,
    brand: str = "Chanel",
    gender: str = "women",
    family: str = "Floral",
    perfumers: tuple[str, ...] = ("A",),
    rating_value: float = 4.0,
    rating_count: int = 1000,
) -> Item:
    return Item(
        perfume_id=perfume_id,
        name=f"Perfume {perfume_id}",
        brand=brand,
        gender=gender,
        olfactive_family=family,
        perfumers=perfumers,
        launch_year=2020,
        rating_value=rating_value,
        rating_count=rating_count,
        description="desc",
        image_url="https://example.test/foto.jpg",
        url="https://example.test/perfume",
    )


def catalog() -> Catalog:
    items = [
        perfume(1, brand="Chanel", rating_count=500, rating_value=4.2),
        perfume(2, brand="Dior", gender="men", family="Woody", rating_count=400, rating_value=4.8),
        perfume(3, brand="Chanel", rating_value=2.5, rating_count=9000),
    ]
    profiles = {"ada": Profile(member_id=7, username="ada", avatar_url="https://example.test/a.jpg")}
    return Catalog(items, profiles, {7: {1}})


def test_las_familias_sueltas_no_entran_en_la_encuesta() -> None:
    items = [
        perfume(1, family="Floral"),
        perfume(2, family="Floral"),
        perfume(3, family="fragrance for women. texto largo que no es una familia"),
    ]
    loaded = Catalog(items, {}, {})
    assert loaded.options.families == ("Floral",)


def test_conocido_ignora_la_encuesta_y_saca_lo_visto() -> None:
    result = catalog().recommend(
        "Ada",
        "populares",
        ratings=[],
        preferences=Preferences(brands=frozenset({"Chanel"})),
    )
    assert result.conocido is True
    assert result.avatar_url == "https://example.test/a.jpg"
    assert result.username == "ada"
    # Chanel 1 ya lo vio. El filtro de Chanel no aplica. Queda Dior.
    # El de rating 2.5 no entra.
    assert [item.perfume_id for item in result.perfumes] == [2]


def test_trending_usa_el_anio_y_sigue_sacando_lo_visto() -> None:
    loaded = Catalog(
        catalog().items,
        catalog().profiles,
        {7: {1}},
        recent_counts={1: 30, 2: 4, 3: 100},
    )
    result = loaded.recommend("ada", "trending", ratings=[], preferences=Preferences())
    # 1 ya lo vio, aunque sea el más reciente. 3 está bajo ok.
    assert [item.perfume_id for item in result.perfumes] == [2]


def test_para_vos_sin_modelo_responde_503() -> None:
    with TestClient(create_app(catalog())) as client:
        response = client.post(
            "/recomendaciones",
            json={
                "username": "ada",
                "tab": "para_vos",
                "valoraciones": [{"perfume_id": 2, "rating": 5}],
                "preferencias": {},
            },
        )
        assert response.status_code == 503


def test_para_vos_usa_la_nota_y_no_aplica_el_piso_ni_la_encuesta() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.member_id: int | None = None
            self.ratings: list[tuple[int, int]] = []
            self.exclude: set[int] = set()

        def rank(
            self,
            member_id: int | None,
            ratings: list[tuple[int, int]],
            exclude: set[int],
        ) -> list[int]:
            self.member_id = member_id
            self.ratings = list(ratings)
            self.exclude = set(exclude)
            return [2, 1, 3]

    loaded = catalog()
    recorder = Recorder()
    loaded.personal = recorder
    result = loaded.recommend(
        "Ada",
        "para_vos",
        [2],
        Preferences(brands=frozenset({"Chanel"})),
        {2: 4},
    )
    assert recorder.member_id == 7
    assert recorder.ratings == [(2, 4)]
    assert recorder.exclude == {1, 2}
    # 1 ya lo vio, 2 lo puntuó. 3 queda aunque esté bajo ok y no sea Chanel.
    assert [item.perfume_id for item in result.perfumes] == [3]
    assert result.tab == "para_vos"


def test_nuevo_arma_para_vos_con_los_cinco_y_el_wardrobe_con_la_relacion() -> None:
    class Recorder:
        def __init__(self) -> None:
            self.ratings: list[tuple[int, int]] = []
            self.exclude: set[int] = set()

        def rank(
            self,
            member_id: int | None,
            ratings: list[tuple[int, int]],
            exclude: set[int],
        ) -> list[int]:
            self.ratings = list(ratings)
            self.exclude = set(exclude)
            return [2, 1, 3]

    loaded = catalog()
    recorder = Recorder()
    loaded.personal = recorder
    liked = (
        LikedPerfume(1, "have"),
        LikedPerfume(3, "want"),
    )
    preferences = Preferences(liked=liked)
    ranked = loaded.recommend("nadie", "para_vos", [1], preferences, {1: 4})
    assert recorder.ratings == [(1, 4), (3, 5)]
    assert recorder.exclude == {1, 3}
    assert [item.perfume_id for item in ranked.perfumes] == [2]

    wardrobe = loaded.recommend("nadie", "wardrobe", [], preferences)
    assert [(item.perfume_id, wardrobe.relations[item.perfume_id]) for item in wardrobe.perfumes] == [
        (1, "have"),
        (3, "want"),
    ]


def test_conocido_muestra_su_wardrobe_y_no_usa_la_encuesta() -> None:
    loaded = Catalog(
        catalog().items,
        catalog().profiles,
        {7: {1}},
        wardrobe={7: [(3, "had"), (2, "have")]},
    )
    result = loaded.recommend(
        "ada",
        "wardrobe",
        [],
        Preferences(liked=(LikedPerfume(1, "want"),)),
    )
    assert [(item.perfume_id, result.relations[item.perfume_id]) for item in result.perfumes] == [
        (2, "have"),
        (3, "had"),
    ]


def test_buscar_perfumes_por_nombre_o_marca() -> None:
    hits = catalog().search_perfumes("dio")
    assert [item.perfume_id for item in hits] == [2]


def test_desconocido_aplica_la_encuesta() -> None:
    result = catalog().recommend(
        "Nadie",
        "populares",
        ratings=[2],
        preferences=Preferences(brands=frozenset({"Chanel"})),
    )
    assert result.conocido is False
    assert result.avatar_url is None
    # Dior no es Chanel. El 2 está puntuado en la sesión. El 3 está bajo ok.
    # Chanel 1 sigue disponible.
    assert [item.perfume_id for item in result.perfumes] == [1]


def test_api_sesion_opciones_y_recomendaciones() -> None:
    with TestClient(create_app(catalog())) as client:
        ready = client.get("/health")
        assert ready.json() == {"ready": True}

        options = client.get("/opciones")
        assert options.status_code == 200
        assert options.json()["brands"] == ["Chanel", "Dior"]
        assert options.json()["genders"] == ["women", "men"]

        unknown = client.post("/sesion", json={"username": "  Nadie "})
        assert unknown.json()["conocido"] is False
        assert unknown.json()["username"] == "nadie"

        known = client.post("/sesion", json={"username": "ADA"})
        assert known.json() == {
            "username": "ada",
            "conocido": True,
            "avatar_url": "https://example.test/a.jpg",
        }

        recs = client.post(
            "/recomendaciones",
            json={
                "username": "ada",
                "tab": "mejor_puntuados",
                "valoraciones": [{"perfume_id": 2, "rating": 5}],
                "preferencias": {"brands": ["Chanel"]},
            },
        )
        assert recs.status_code == 200
        body = recs.json()
        # 1 visto, 2 puntuado en la sesión, 3 bajo el piso de rating.
        assert body["perfumes"] == []
        assert body["conocido"] is True

        empty = client.post("/sesion", json={"username": "   "})
        assert empty.status_code == 422


def _copy(con: duckdb.DuckDBPyConnection, sql: str, path: Path) -> None:
    con.execute(f"COPY ({sql}) TO '{path}' (FORMAT PARQUET)")


def test_load_catalog_lee_parquet_sin_el_hash(tmp_path: Path) -> None:
    con = duckdb.connect()
    _copy(
        con,
        """
        SELECT * FROM (VALUES
          (1, 'http://a', 'Alpha', 'Chanel', 'women', 2020, 'Floral', '["Alberto Morillas"]',
           4.5, 100, 'http://img/1', 'texto',
           '[{"name":"Bergamot","level":"top"},{"name":"Rose","level":"middle"},{"name":"Musk","level":"base"}]'),
          (2, 'http://b', 'Beta', 'Dior', 'men', 2019, 'Woody', '["Otro"]',
           4.2, 50, 'http://img/2', 'texto', '[]'),
          (3, 'http://c', 'Bajo', 'Chanel', 'women', 2018, 'Floral', '["Alberto Morillas"]',
           2.0, 9999, 'http://img/3', 'texto', NULL)
        ) t(perfume_id, url, name, brand, gender, launch_year, olfactive_family, perfumers,
             rating_value, rating_count, image_url, description, notes)
        """,
        tmp_path / "items.parquet",
    )
    _copy(
        con,
        """
        SELECT * FROM (VALUES
          (7, 'http://avatar', 'hash-secreto')
        ) t(member_id, avatar_url, user_hash)
        """,
        tmp_path / "users.parquet",
    )
    _copy(
        con,
        """
        SELECT * FROM (VALUES
          (7, 'Ada', 'hash-secreto')
        ) t(member_id, username_slug, user_hash)
        """,
        tmp_path / "PRIVATE_user_mapping.parquet",
    )
    _copy(
        con,
        "SELECT * FROM (VALUES (7, 1, 1700000000)) t(member_id, perfume_id, timestamp)",
        tmp_path / "interactions.parquet",
    )
    _copy(
        con,
        """
        SELECT * FROM (VALUES
          (7, 2, 'want'),
          (7, 2, 'have'),
          (7, 1, 'had')
        ) t(member_id, perfume_id, relation)
        """,
        tmp_path / "wardrobe.parquet",
    )

    loaded = load_catalog(tmp_path)
    result = loaded.recommend("ada", "populares", ratings=[], preferences=Preferences())
    assert result.conocido is True
    assert result.avatar_url == "http://avatar"
    assert result.perfumes == []
    assert "hash-secreto" not in repr(loaded.profiles)
    assert loaded.options.perfumers == ("Alberto Morillas", "Otro")
    alpha = next(item for item in loaded.items if item.perfume_id == 1)
    assert [(note.name, note.level) for note in alpha.notes] == [
        ("Bergamot", "top"),
        ("Rose", "middle"),
        ("Musk", "base"),
    ]
    wardrobe = loaded.recommend("ada", "wardrobe", ratings=[], preferences=Preferences())
    assert [(item.perfume_id, wardrobe.relations[item.perfume_id]) for item in wardrobe.perfumes] == [
        (2, "have"),
        (1, "had"),
    ]
