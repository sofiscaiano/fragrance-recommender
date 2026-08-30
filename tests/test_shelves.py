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
    rows = parse_shelves(payload, member_id=3158387, slug="quilter")
    sources = {(r.source, r.perfume_id) for r in rows}
    assert ("wardrobe", 31861) in sources
    assert ("wardrobe", 109081) in sources
    assert ("vote", 1) in sources
    # Los estantes custom no son la coleccion ni el voto.
    assert ("wardrobe", 99) not in sources
    assert all(r.review_id is None for r in rows)
    assert all(r.member_id == 3158387 for r in rows)
    have = next(r for r in rows if r.perfume_id == 31861)
    assert have.relation == "have"
    assert have.rating is None
    vote = next(r for r in rows if r.perfume_id == 1)
    assert vote.rating == 5
    assert vote.season_winter == 1


def test_list_of_typed_shelves():
    payload = [
        {"type": "wardrobe", "items": [{"perfume_id": 10, "relation": "want"}]},
        {"type": "myvotes", "items": [{"parfem_id": 2, "rating": 4}]},
    ]
    rows = parse_shelves(payload, member_id=1, slug="u")
    by_src = {r.source: r for r in rows}
    assert by_src["wardrobe"].perfume_id == 10
    assert by_src["wardrobe"].relation == "want"
    assert by_src["vote"].perfume_id == 2
    assert by_src["vote"].rating == 4


def test_rating_zero_on_vote_is_absent():
    payload = {"myvotes": [{"parfem_id": 7, "perfume_votes": {"rating": 0, "longevity": 0}}]}
    rows = parse_shelves(payload, member_id=1, slug="u")
    assert len(rows) == 1
    assert rows[0].source == "vote"
    assert rows[0].rating is None
