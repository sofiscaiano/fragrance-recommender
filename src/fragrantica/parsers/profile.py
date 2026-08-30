"""Fase 3: perfil de usuario -> atributos + historico COMPLETO de reviews.

El perfil embebe un array JSON con todas las reviews del usuario, cada una con
parfem_id (el id numerico del perfume) y el mismo blob de votos. Un usuario con
500 reviews aporta 500 interacciones en un solo request, muchisimo mas eficiente
que paginar paginas de perfume.

Esta fase tambien es la unica fuente del member_id numerico, que no aparece en
las paginas de perfume.
"""

from __future__ import annotations

import html as ihtml
import re

import orjson
from selectolax.parser import HTMLParser

from ..models import Interaction, User
from .votes import normalise_votes

_MEMBER_ID = re.compile(r':member-id="(\d+)"')
_REVIEWS_TOTAL = re.compile(r':reviews-total="(\d+)"')
_OWNER_AVATAR = re.compile(r'owner-avatar="([^"]+)"')
_ALL_REVIEWS = re.compile(r':all-reviews="((?:&quot;|[^"])*)"')
_HTML_TAGS = re.compile(r"<[^>]+>")
_PUNBBDATA = re.compile(r":punbbdata='([^']*)'")
_HEADER = re.compile(r":header='([^']*)'")
_WARDROBE_COUNT = re.compile(r':wardrobe-count="(\d+)"')
_NOTES_COUNT = re.compile(r':notes-count="(\d+)"')

# Atajo verificado: para los avatares del tipo avatari/[mt].<N>.jpg el numero
# ES el member_id (@lanes100 -> 3146574, @mjoshwil -> 3126834). No es universal
# (los avatares custom usan otro almacen), asi que se usa solo como chequeo
# cruzado del parser, nunca como reemplazo de la visita al perfil.
_AVATAR_ID = re.compile(r"/avatari/[mts]\.(\d+)\.")


def member_id_from_avatar(avatar_url: str | None) -> int | None:
    if not avatar_url:
        return None
    m = _AVATAR_ID.search(avatar_url)
    return int(m.group(1)) if m else None


def parse_profile(html: str, slug: str) -> tuple[User, list[Interaction]]:
    """Parsea un perfil. Lanza ValueError si no encuentra el member_id."""
    m = _MEMBER_ID.search(html)
    if not m:
        raise ValueError(f"member_id ausente en el perfil de @{slug}")
    member_id = int(m.group(1))

    reviews_total = None
    if (rt := _REVIEWS_TOTAL.search(html)):
        reviews_total = int(rt.group(1))

    avatar_url = None
    if (av := _OWNER_AVATAR.search(html)):
        avatar_url = av.group(1)

    display = None
    tree = HTMLParser(html)
    if (title := tree.css_first("title")) is not None:
        raw = (title.text() or "").strip().split("|")[0].strip()
        # El title del perfil es "<Usuario> My Fragrantica".
        raw = re.sub(r"\s*My Fragrantica\s*$", "", raw).strip()
        display = raw or None

    punbb = _parse_json_attr(html, _PUNBBDATA)
    header = _parse_json_attr(html, _HEADER)

    wardrobe_count = _first_int(
        (header or {}).get("perfumes_num"),
        _int_attr(html, _WARDROBE_COUNT),
    )
    notes_count = _int_attr(html, _NOTES_COUNT)
    sig = (punbb or {}).get("profile", {}).get("parfem_sig") if punbb else None
    # 0 en el sitio significa "no eligió perfume firma", no el id 0.
    signature_perfume_id = int(sig) if isinstance(sig, int) and sig > 0 else None

    if not display and punbb and punbb.get("username"):
        display = str(punbb["username"])

    interactions = _extract_profile_reviews(html, member_id, slug)

    user = User(
        member_id=member_id,
        username_slug=slug,
        username_display=display,
        profile_url=f"https://www.fragrantica.com/@{slug}",
        avatar_url=avatar_url,
        reviews_total=reviews_total,
        n_reviews_scraped=len(interactions),
        wardrobe_count=wardrobe_count,
        notes_count=notes_count,
        signature_perfume_id=signature_perfume_id,
    )
    return user, interactions


def _parse_json_attr(html: str, pattern: re.Pattern[str]) -> dict | None:
    m = pattern.search(html)
    if not m:
        return None
    try:
        data = orjson.loads(ihtml.unescape(m.group(1)))
    except orjson.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _int_attr(html: str, pattern: re.Pattern[str]) -> int | None:
    m = pattern.search(html)
    return int(m.group(1)) if m else None


def _first_int(*values: object) -> int | None:
    for v in values:
        if isinstance(v, int):
            return v
        if isinstance(v, str) and v.isdigit():
            return int(v)
    return None


def _extract_profile_reviews(html: str, member_id: int, slug: str) -> list[Interaction]:
    m = _ALL_REVIEWS.search(html)
    if not m:
        return []
    try:
        rows = orjson.loads(ihtml.unescape(m.group(1)))
    except orjson.JSONDecodeError:
        return []

    out: list[Interaction] = []
    for row in rows:
        review_id = row.get("id")
        perfume_id = row.get("parfem_id")
        if not review_id or not perfume_id:
            continue

        votes = normalise_votes(row.get("perfume_votes"))
        text = row.get("komentar")
        if text:
            text = _HTML_TAGS.sub(" ", ihtml.unescape(text))
            text = re.sub(r"\s+", " ", text).strip() or None

        out.append(
            Interaction(
                review_id=int(review_id),
                perfume_id=int(perfume_id),
                member_id=member_id,
                username_slug=slug,
                rating=votes["rating"],
                relation=votes["relation"],
                longevity=votes["longevity"],
                sillage=votes["sillage"],
                gender_vote=votes["gender"],
                season_winter=votes["winter"],
                season_spring=votes["spring"],
                season_summer=votes["summer"],
                season_autumn=votes["autumn"],
                day=votes["day"],
                night=votes["night"],
                timestamp=row.get("vrijeme"),
                review_text=text,
                source="profile_page",
            )
        )
    return out
