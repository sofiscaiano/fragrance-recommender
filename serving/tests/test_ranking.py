from fragrantica_serving.ranking import (
    Item,
    Preferences,
    counts_for_floor,
    percentile_75,
    rank_items,
)


def perfume(
    perfume_id: int,
    *,
    name: str | None = None,
    brand: str = "Chanel",
    gender: str = "women",
    family: str = "Floral",
    perfumers: tuple[str, ...] = ("Alberto Morillas",),
    rating_value: float = 4.0,
    rating_count: int = 1000,
) -> Item:
    return Item(
        perfume_id=perfume_id,
        name=name or f"Perfume {perfume_id}",
        brand=brand,
        gender=gender,
        olfactive_family=family,
        perfumers=perfumers,
        launch_year=2020,
        rating_value=rating_value,
        rating_count=rating_count,
        description="Una descripción",
        image_url="https://example.test/foto.jpg",
        url="https://example.test/perfume",
    )


def test_percentile_75_interpola() -> None:
    assert percentile_75([]) == 0
    assert percentile_75([7]) == 7
    assert percentile_75([10, 20, 30, 40]) == 32.5


def test_el_piso_ignora_ratings_por_debajo_de_ok() -> None:
    items = [
        perfume(1, rating_value=2.9, rating_count=10_000),
        perfume(2, rating_value=3.0, rating_count=10),
        perfume(3, rating_value=4.0, rating_count=40),
    ]
    assert counts_for_floor(items) == [10, 40]
    assert percentile_75(counts_for_floor(items)) == 32.5


def test_populares_ordena_por_votos_y_deja_afuera_menos_de_ok() -> None:
    items = [
        perfume(1, rating_value=2.99, rating_count=9000),
        perfume(2, rating_value=3.0, rating_count=100),
        perfume(3, rating_value=4.2, rating_count=100),
        perfume(4, rating_value=3.5, rating_count=50),
    ]
    # perfume 2 y 3 empatan en votos: gana el de mejor rating, después el id menor.
    ranked = rank_items(
        items,
        "populares",
        exclude=set(),
        preferences=Preferences(),
        vote_floor=999,
    )
    assert [item.perfume_id for item in ranked] == [3, 2, 4]


def test_mejor_puntuados_usa_el_piso_del_catalogo_y_desempata_por_votos() -> None:
    items = [
        perfume(1, rating_value=4.8, rating_count=30),
        perfume(2, rating_value=4.6, rating_count=100),
        perfume(3, rating_value=4.6, rating_count=80),
        perfume(4, rating_value=4.9, rating_count=32),
    ]
    ranked = rank_items(
        items,
        "mejor_puntuados",
        exclude=set(),
        preferences=Preferences(),
        vote_floor=32.5,
    )
    # 30 queda afuera aunque sea el mejor del subconjunto. 32.0 también.
    # 4.6 con 100 votos gana al 4.6 con 80.
    assert [item.perfume_id for item in ranked] == [2, 3]


def test_filtros_son_o_adentro_y_y_entre_preguntas() -> None:
    items = [
        perfume(1, brand="Chanel", gender="women", family="Floral", perfumers=("A", "B")),
        perfume(2, brand="Dior", gender="women", family="Woody", perfumers=("B",)),
        perfume(3, brand="Chanel", gender="men", family="Floral", perfumers=("C",)),
        perfume(4, brand="Chanel", gender="unisex", family="Floral", perfumers=("A",)),
    ]
    prefs = Preferences(
        brands=frozenset({"Chanel", "Dior"}),
        genders=frozenset({"women", "unisex"}),
        perfumers=frozenset({"B", "Z"}),
        families=frozenset({"Floral"}),
    )
    ranked = rank_items(
        items,
        "populares",
        exclude=set(),
        preferences=prefs,
        vote_floor=0,
    )
    # Dior no es Floral. Chanel men no está en el género. Chanel unisex no tiene B.
    assert [item.perfume_id for item in ranked] == [1]


def test_preferencias_vacias_no_filtran() -> None:
    items = [perfume(1, brand="Chanel"), perfume(2, brand="Dior", gender="men")]
    ranked = rank_items(
        items,
        "populares",
        exclude=set(),
        preferences=Preferences(),
        vote_floor=0,
    )
    assert {item.perfume_id for item in ranked} == {1, 2}


def test_trending_ordena_por_interacciones_recientes() -> None:
    items = [
        perfume(1, rating_value=4.0, rating_count=9000),
        perfume(2, rating_value=3.2, rating_count=10),
        perfume(3, rating_value=2.5, rating_count=50),
        perfume(4, rating_value=4.5, rating_count=20),
        perfume(5, rating_value=4.9, rating_count=8000),
    ]
    ranked = rank_items(
        items,
        "trending",
        exclude={2},
        preferences=Preferences(),
        vote_floor=0,
        recent_counts={1: 5, 2: 80, 3: 100, 4: 5},
    )
    # 3 está bajo ok. 2 está excluido. 5 no tuvo interacciones en el año.
    # 1 y 4 empatan en 5: gana el de mejor rating.
    assert [item.perfume_id for item in ranked] == [4, 1]


def test_exclusiones_y_lista_corta() -> None:
    items = [perfume(i, rating_count=1000 - i) for i in range(1, 6)]
    ranked = rank_items(
        items,
        "populares",
        exclude={1, 2},
        preferences=Preferences(),
        vote_floor=0,
        limit=10,
    )
    assert [item.perfume_id for item in ranked] == [3, 4, 5]

    short = rank_items(
        items,
        "populares",
        exclude=set(),
        preferences=Preferences(),
        vote_floor=0,
        limit=2,
    )
    assert [item.perfume_id for item in short] == [1, 2]
