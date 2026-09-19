"""Tests de parsers contra HTML congelado.

El sitio va a cambiar el markup en algun momento. Estos tests fallan en CI en
vez de a mitad de un crawl de 15 horas.
"""

from pathlib import Path

import pytest

from fragrantica.parsers.designer import parse_designer_index, parse_designer_page
from fragrantica.parsers.perfume import parse_perfume
from fragrantica.parsers.profile import member_id_from_avatar, parse_profile

FX = Path(__file__).parent / "fixtures"
SAUVAGE_URL = "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html"


@pytest.fixture(scope="module")
def perfume_parsed():
    return parse_perfume((FX / "perfume_sauvage.html").read_text(), SAUVAGE_URL)


# -- Fase 1 ----------------------------------------------------------------


def test_designer_index_lists_brands():
    slugs = parse_designer_index((FX / "designers_index.html").read_text())
    assert len(slugs) > 50
    assert "Dior" in slugs or "Chanel" in slugs


def test_designer_page_enumerates_perfumes():
    rows = parse_designer_page((FX / "designer_dior.html").read_text(), brand="Dior")
    assert len(rows) > 300
    ids = {r["perfume_id"] for r in rows}
    assert 31861 in ids  # Sauvage
    assert all(r["url"].startswith("https://") for r in rows)


def test_designer_page_excludes_other_brands():
    """Los widgets laterales linkean perfumes ajenos a la marca.

    Sin acotar al contenedor del listado, en Dior se colaban 39 items de otras
    28 marcas sobre 358, corrompiendo la atribucion de marca.
    """
    rows = parse_designer_page((FX / "designer_dior.html").read_text(), brand="Dior")
    brands = {r["designer_in_url"] for r in rows}
    assert brands == {"Dior"}


def test_rows_for_designer_drops_widget_items():
    from fragrantica.parsers.designer import rows_for_designer

    rows = [
        {"perfume_id": 1, "designer_in_url": "Dior", "url": "https://www.fragrantica.com/perfume/Dior/A-1.html"},
        {"perfume_id": 2, "designer_in_url": "Le-Labo", "url": "https://www.fragrantica.com/perfume/Le-Labo/B-2.html"},
    ]
    own = rows_for_designer(rows, "Dior")
    assert [r["perfume_id"] for r in own] == [1]


def test_designer_slug_from_perfume_url():
    from fragrantica.parsers.designer import designer_slug_from_perfume_url

    url = "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html"
    assert designer_slug_from_perfume_url(url) == "Dior"
    assert designer_slug_from_perfume_url("https://example.com/x") is None


def test_designer_page_extracts_cheap_metadata():
    """El listado usa female/male/unisex, no los men/women del resto del sitio."""
    rows = parse_designer_page((FX / "designer_dior.html").read_text(), brand="Dior")
    with_gender = [r for r in rows if r["gender_hint"]]
    assert len(with_gender) > len(rows) * 0.8
    assert {r["gender_hint"] for r in with_gender} <= {"men", "women", "unisex"}


# -- Fase 2: item ----------------------------------------------------------


def test_item_core_fields(perfume_parsed):
    item, _, _ = perfume_parsed
    assert item.perfume_id == 31861
    assert item.name == "Sauvage"
    assert item.brand == "Dior"
    assert item.gender == "men"
    assert item.launch_year == 2015
    assert item.olfactive_family == "Aromatic Fougere"
    assert item.perfumers == ["François Demachy"]


def test_item_ratings(perfume_parsed):
    item, _, _ = perfume_parsed
    assert item.rating_value == pytest.approx(3.85, abs=0.5)
    assert item.rating_count and item.rating_count > 30_000


def test_item_reviews_total_is_flagged_as_approximate(perfume_parsed):
    """El sitio muestra '4.2K', asi que el total es aproximado y hay que decirlo."""
    item, _, _ = perfume_parsed
    assert item.reviews_total_is_approx is True
    assert item.reviews_total and item.reviews_total > 4_000


def test_item_content_features_for_cold_start(perfume_parsed):
    item, _, _ = perfume_parsed
    assert len(item.accords) >= 5
    assert item.accords[0].intensity == pytest.approx(100.0)
    # Las intensidades deben venir ordenadas de mayor a menor.
    intensities = [a.intensity for a in item.accords]
    assert intensities == sorted(intensities, reverse=True)
    assert "Calabrian bergamot" in item.notes_top
    assert item.notes_middle and item.notes_base


def test_item_truncation_is_detected(perfume_parsed):
    """Sauvage tiene ~4.2K reviews pero la pagina anonima trae ~200."""
    item, interactions, _ = perfume_parsed
    assert item.reviews_truncated is True
    assert len(interactions) < item.reviews_total


# -- Fase 2: interacciones -------------------------------------------------


def test_interactions_extracted(perfume_parsed):
    _, interactions, _ = perfume_parsed
    assert len(interactions) > 150


def test_every_interaction_has_item_id_and_username(perfume_parsed):
    _, interactions, _ = perfume_parsed
    assert all(i.perfume_id == 31861 for i in interactions)
    assert all(i.username_slug for i in interactions)
    assert all(i.review_id > 0 for i in interactions)


def test_review_ids_are_unique(perfume_parsed):
    _, interactions, _ = perfume_parsed
    ids = [i.review_id for i in interactions]
    assert len(ids) == len(set(ids))


def test_perfume_page_has_no_member_id():
    """Hueco conocido: el member_id numerico no esta en la pagina de perfume.

    Si este test empieza a fallar es una buena noticia (el sitio empezo a
    exponerlo) y se puede simplificar la fase 4.
    """
    _, interactions, _ = parse_perfume(
        (FX / "perfume_sauvage.html").read_text(), SAUVAGE_URL
    )
    assert all(i.member_id is None for i in interactions)


def test_explicit_rating_signal_is_present(perfume_parsed):
    """El rating 1-5 es la senal principal del recomendador.

    No todas las reviews traen rating: en este fixture ~24% de los autores
    escribieron texto sin votar (el sitio los reporta como 0 y se normalizan a
    None, ver parsers/votes.py). Esas filas son feedback implicito, no rating.
    """
    _, interactions, _ = perfume_parsed
    rated = [i for i in interactions if i.rating is not None]
    assert len(rated) > len(interactions) * 0.6
    assert all(1 <= i.rating <= 5 for i in rated)
    # Y los ceros del sitio nunca llegan como valores.
    assert all(i.rating != 0 for i in interactions)


def test_context_and_implicit_signals(perfume_parsed):
    _, interactions, _ = perfume_parsed
    assert any(i.relation in ("have", "had", "want") for i in interactions)
    assert any(i.season_winter is not None for i in interactions)
    assert any(i.longevity is not None for i in interactions)


def test_timestamps_present(perfume_parsed):
    _, interactions, _ = perfume_parsed
    with_ts = [i for i in interactions if i.timestamp]
    assert len(with_ts) > len(interactions) * 0.9
    assert all(i.timestamp > 1_000_000_000 for i in with_ts)


def test_user_seeds_deduplicated(perfume_parsed):
    _, interactions, seeds = perfume_parsed
    slugs = [s["username_slug"] for s in seeds]
    assert len(slugs) == len(set(slugs))
    assert set(slugs) == {i.username_slug for i in interactions}


# -- Fase 3: perfil --------------------------------------------------------


def test_profile_yields_member_id():
    user, _ = parse_profile((FX / "profile_quilter.html").read_text(), "quilter")
    assert user.member_id == 3158387
    assert user.username_slug == "quilter"
    assert user.username_display == "Quilter"
    assert user.wardrobe_count == 5
    assert user.notes_count == 0
    # parfem_sig=0 en el sitio significa "no eligió", no el id 0.
    assert user.signature_perfume_id is None


def test_profile_interactions_have_both_ids():
    """El perfil es la fuente que cierra la FK de member_id."""
    _, interactions = parse_profile((FX / "profile_quilter.html").read_text(), "quilter")
    assert interactions
    assert all(i.member_id == 3158387 for i in interactions)
    assert all(i.perfume_id > 0 for i in interactions)
    assert all(i.source == "profile_page" for i in interactions)


def test_profile_review_text_is_stripped_of_html():
    _, interactions = parse_profile((FX / "profile_quilter.html").read_text(), "quilter")
    texts = [i.review_text for i in interactions if i.review_text]
    assert texts
    assert not any("<p>" in t for t in texts)


def test_profile_slug_is_case_normalised():
    user, inter = parse_profile((FX / "profile_quilter.html").read_text(), "QuIlTeR")
    assert user.username_slug == "quilter"
    assert all(i.username_slug == "quilter" for i in inter)


def test_missing_member_id_raises():
    with pytest.raises(ValueError, match="member_id ausente"):
        parse_profile("<html><body>sin datos</body></html>", "ghost")


# -- Atajo del avatar ------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://fimgs.net/mdimg/avatari/t.3146574.jpg", 3146574),
        ("https://fimgs.net/mdimg/avatari/m.3126834.jpg", 3126834),
        ("https://fimgs.net/himg/o.69246.png", None),  # avatar custom: otro almacen
        (None, None),
    ],
)
def test_avatar_member_id_shortcut(url, expected):
    """Verificado contra perfiles reales. Se usa solo como chequeo cruzado."""
    assert member_id_from_avatar(url) == expected
