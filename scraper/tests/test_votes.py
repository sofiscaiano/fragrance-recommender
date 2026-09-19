"""Tests de la normalizacion de votos.

El caso critico: el sitio usa 0 para "no voto". Si se colara como valor, un
rating=0 entraria al recomendador como la peor calificacion posible en vez de
como un dato ausente.
"""

from pathlib import Path

from fragrantica.parsers.perfume import parse_perfume
from fragrantica.parsers.votes import cast_no_votes, normalise_votes

FX = Path(__file__).parent / "fixtures"

FULL_VOTE = {
    "rating": 4, "winter": 1, "spring": 1, "summer": 0, "autumn": 1,
    "day": 1, "night": 0, "longevity": 3, "sillage": 2,
    "gender": None, "relation": "had",
}

NO_VOTE = {
    "rating": 0, "winter": 0, "spring": 0, "summer": 0, "autumn": 0,
    "day": 0, "night": 0, "longevity": 0, "sillage": 0,
    "gender": None, "relation": None,
}


def test_zero_rating_becomes_null():
    """El caso que importa: 0 no es una calificacion, es ausencia de voto."""
    assert normalise_votes(NO_VOTE)["rating"] is None


def test_zero_ordinals_become_null():
    v = normalise_votes(NO_VOTE)
    assert v["longevity"] is None
    assert v["sillage"] is None


def test_real_vote_is_preserved():
    v = normalise_votes(FULL_VOTE)
    assert v["rating"] == 4
    assert v["longevity"] == 3
    assert v["sillage"] == 2
    assert v["relation"] == "had"


def test_binary_zero_is_meaningful_when_user_voted():
    """Si el usuario voto, un 0 en 'summer' significa 'no la eligio'."""
    v = normalise_votes(FULL_VOTE)
    assert v["summer"] == 0
    assert v["night"] == 0
    assert v["winter"] == 1


def test_binary_zero_is_null_when_user_did_not_vote():
    """Si no voto nada, esos ceros son ausencia y no 'no la eligio'."""
    v = normalise_votes(NO_VOTE)
    assert all(v[f] is None for f in ("winter", "spring", "summer", "autumn", "day", "night"))


def test_cast_no_votes_detection():
    assert cast_no_votes(NO_VOTE) is True
    assert cast_no_votes(FULL_VOTE) is False
    # Un unico voto binario ya cuenta como haber votado.
    assert cast_no_votes({**NO_VOTE, "winter": 1}) is False


def test_empty_and_none_blobs():
    for blob in (None, {}):
        v = normalise_votes(blob)
        assert v["rating"] is None
        assert v["relation"] == "unknown"


def test_garbage_values_are_rejected():
    v = normalise_votes({"rating": "cinco", "longevity": 999, "sillage": True})
    assert v["rating"] is None
    assert v["longevity"] is None
    assert v["sillage"] is None


def test_relation_normalisation():
    assert normalise_votes({"relation": "have"})["relation"] == "have"
    assert normalise_votes({"relation": "garbage"})["relation"] == "unknown"
    assert normalise_votes({"relation": None})["relation"] == "unknown"


def test_no_zero_ratings_survive_real_parsing():
    """Verificacion end-to-end sobre el fixture real.

    Sauvage tiene 51 reviews sin voto que el sitio reporta como rating=0.
    """
    _, interactions, _ = parse_perfume(
        (FX / "perfume_sauvage.html").read_text(),
        "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html",
    )
    ratings = [i.rating for i in interactions]
    assert 0 not in ratings
    rated = [r for r in ratings if r is not None]
    assert all(1 <= r <= 5 for r in rated)
    # Y las que no votaron quedaron explicitamente como nulas.
    assert ratings.count(None) > 0
