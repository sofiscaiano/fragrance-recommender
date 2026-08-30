"""Parser de wardrobe / votos a partir del JSON ya descifrado."""

from fragrantica.parsers.shelves import parse_shelves


def test_wardrobe_and_votes_from_named_keys():
    payload = {
        "wardrobe": [
            {"parfem_id": 31861, "relation": "have"},
            {"parfem_id": 109081, "relation": "had"},
        ],
        "myvotes": [
            {
                "parfem_id": 1,
                "perfume_votes": {
                    "rating": 5,
                    "winter": 1,
                    "spring": 0,
                    "summer": 0,
                    "autumn": 1,
                    "day": 0,
                    "night": 1,
                    "longevity": 4,
                    "sillage": 3,
                    "gender": None,
                    "relation": None,
                },
            }
        ],
        "custom": [{"parfem_id": 99, "relation": "have"}],
    }
    parsed = parse_shelves(payload, member_id=3158387, slug="quilter")
    wardrobe_ids = {r.perfume_id for r in parsed.wardrobe}
    vote_ids = {r.perfume_id for r in parsed.votes}
    assert wardrobe_ids == {31861, 109081}
    assert vote_ids == {1}
    # Los estantes custom no son la coleccion ni el voto.
    assert 99 not in wardrobe_ids
    assert all(r.review_id is None for r in parsed.votes)
    assert all(r.member_id == 3158387 for r in parsed.votes)
    assert all(r.member_id == 3158387 for r in parsed.wardrobe)
    have = next(r for r in parsed.wardrobe if r.perfume_id == 31861)
    assert have.relation == "have"
    vote = next(r for r in parsed.votes if r.perfume_id == 1)
    assert vote.rating == 5
    assert vote.season_winter == 1
    assert vote.source == "vote"


def test_list_of_typed_shelves():
    payload = [
        {"type": "wardrobe", "items": [{"perfume_id": 10, "relation": "want"}]},
        {"type": "myvotes", "items": [{"parfem_id": 2, "rating": 4}]},
    ]
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert len(parsed.wardrobe) == 1
    assert parsed.wardrobe[0].perfume_id == 10
    assert parsed.wardrobe[0].relation == "want"
    assert len(parsed.votes) == 1
    assert parsed.votes[0].perfume_id == 2
    assert parsed.votes[0].rating == 4


def test_rating_zero_on_vote_is_absent():
    payload = {"myvotes": [{"parfem_id": 7, "perfume_votes": {"rating": 0, "longevity": 0}}]}
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert parsed.wardrobe == []
    assert len(parsed.votes) == 1
    assert parsed.votes[0].source == "vote"
    assert parsed.votes[0].rating is None


def test_ajax_shelves_use_id_and_shelf_value():
    """Payload vivo: perfumes[].id y have/had/want / rating en el estante."""
    payload = [
        {
            "field": "relation",
            "value": "have",
            "name": "Perfumes I Have",
            "type": "wardrobe",
            "perfumes": [
                {"id": 219, "naslov": "Hypnotic Poison", "dizajner": "Dior",
                 "url": "/perfume/Dior/Hypnotic-Poison-219.html"},
            ],
        },
        {
            "field": "rating",
            "value": 5,
            "name": "love",
            "type": "myvotes",
            "perfumes": [
                {"id": 15452, "naslov": "Alien Essence Absolue", "dizajner": "Mugler",
                 "url": "/perfume/Mugler/Alien-Essence-Absolue-15452.html"},
            ],
        },
        {
            "field": "for_test",
            "value": 1,
            "name": "for test",
            "type": "wardrobe",
            "perfumes": [
                {"id": 99, "naslov": "Skip me", "dizajner": "X",
                 "url": "/perfume/X/Skip-99.html"},
            ],
        },
    ]
    parsed = parse_shelves(payload, member_id=1986300, slug="bansheesmile")
    assert [(w.perfume_id, w.relation) for w in parsed.wardrobe] == [(219, "have")]
    assert len(parsed.votes) == 1
    assert parsed.votes[0].perfume_id == 15452
    assert parsed.votes[0].rating == 5
    assert parsed.votes[0].source == "vote"
    payload = {"myvotes": [{"parfem_id": 7, "perfume_votes": {"rating": 0, "longevity": 0}}]}
    parsed = parse_shelves(payload, member_id=1, slug="u")
    assert parsed.wardrobe == []
    assert len(parsed.votes) == 1
    assert parsed.votes[0].source == "vote"
    assert parsed.votes[0].rating is None
