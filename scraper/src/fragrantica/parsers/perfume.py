"""Fase 2: pagina de perfume -> features del item + interacciones + semillas de usuarios.

Esta es la fase caballito de batalla. De un solo request salen las tres
dimensiones a la vez, porque las reviews vienen renderizadas en el HTML inicial
(no por AJAX) y cada una trae el blob de votos del usuario con su rating 1-5.

Limitacion verificada: el sitio renderiza ~200 reviews para un visitante
anonimo; el resto del archivo queda detras del login. Para la gran mayoria de
items (promedio ~19 reviews) eso captura el listado completo.
"""

from __future__ import annotations

import html as ihtml
import re

import orjson
from selectolax.parser import HTMLParser, Node

from ..config import REVIEW_PAGE_CAP
from ..models import Accord, Gender, Interaction, Item, Note
from .votes import normalise_votes

_PERFUME_ID = re.compile(r"-(\d+)\.html")
_PROFILE_SLUG = re.compile(r"/@([A-Za-z0-9_.\-]+)")
_WIDTH = re.compile(r"width:\s*([\d.]+)%")
_YEAR = re.compile(r"was launched in (\d{4})")
_FAMILY = re.compile(r"\bis an?\s+(.+?)\s+fragrance for\b", re.I)
_GENDER_TEXT = re.compile(r"fragrance for (women and men|men and women|women|men)", re.I)
_REVIEW_TOTAL = re.compile(r"Reviews\s*\(\s*<span[^>]*>([\d.,KMk m]+)</span>", re.I)
_INT_ID = re.compile(r"(\d+)")


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    m = _INT_ID.search(text.replace(",", "").replace(".", ""))
    return int(m.group(1)) if m else None


def _parse_abbrev(text: str) -> tuple[int | None, bool]:
    """Convierte '4.2K' -> (4200, True). El sitio abrevia el total de reviews,
    asi que el valor es aproximado y hay que marcarlo como tal."""
    t = text.strip().replace(",", "")
    m = re.match(r"^([\d.]+)\s*([KMkm]?)$", t)
    if not m:
        return _to_int(t), False
    value = float(m.group(1))
    suffix = m.group(2).upper()
    if suffix == "K":
        return int(value * 1_000), True
    if suffix == "M":
        return int(value * 1_000_000), True
    return int(value), False


def _normalise_gender(raw: str | None) -> Gender:
    if not raw:
        return "unknown"
    r = raw.lower()
    if "women and men" in r or "men and women" in r or "unisex" in r:
        return "unisex"
    if "women" in r:
        return "women"
    if "men" in r:
        return "men"
    return "unknown"


# --------------------------------------------------------------------------
# Item
# --------------------------------------------------------------------------


def _extract_accords(tree: HTMLParser) -> list[Accord]:
    """El widget es una pila de barras; el ancho en % es la intensidad."""
    accords: list[Accord] = []
    for h6 in tree.css("h6"):
        if "main accords" not in (h6.text() or "").strip().lower():
            continue
        container = h6.next
        while container is not None and container.tag != "div":
            container = container.next
        if container is None:
            break
        for bar in container.css("div[style]"):
            label = bar.css_first("span")
            if label is None:
                continue
            name = (label.text() or "").strip()
            if not name:
                continue
            m = _WIDTH.search(bar.attributes.get("style") or "")
            accords.append(Accord(name=name, intensity=float(m.group(1)) if m else 0.0))
        break
    return accords


def _extract_notes(tree: HTMLParser) -> list[Note]:
    notes: list[Note] = []
    for level_node in tree.css("pyramid-level-new"):
        level = (level_node.attributes.get("notes") or "single").lower()
        if level not in ("top", "middle", "base", "single"):
            level = "single"
        for link in level_node.css("a[href]"):
            href = link.attributes.get("href") or ""
            if "/notes/" not in href:
                continue
            label = link.css_first("span")
            img = link.css_first("img")
            name = ""
            if label is not None:
                name = (label.text() or "").strip()
            if not name and img is not None:
                name = (img.attributes.get("alt") or "").strip()
            if not name:
                continue
            nid = re.search(r"-(\d+)\.html", href)
            notes.append(
                Note(name=name, note_id=int(nid.group(1)) if nid else None, level=level)  # type: ignore[arg-type]
            )
    return notes


def _extract_perfumers(tree: HTMLParser) -> list[str]:
    names: list[str] = []
    for link in tree.css('a[href*="/noses/"]'):
        href = link.attributes.get("href") or ""
        # El menu de navegacion linkea a /noses/ pelado; los perfumistas del
        # item tienen un slug.
        if href.rstrip("/").endswith("/noses"):
            continue
        span = link.css_first("span")
        name = (span.text() if span is not None else link.text() or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def parse_perfume(html: str, url: str) -> tuple[Item, list[Interaction], list[dict]]:
    """Parsea una pagina de perfume.

    Devuelve (item, interacciones, semillas_de_usuario). Las semillas traen slug
    y display name; el member_id numerico NO esta en esta pagina y se resuelve
    al visitar el perfil (fase 3/4).
    """
    tree = HTMLParser(html)

    m = _PERFUME_ID.search(url)
    if not m:
        raise ValueError(f"no se pudo extraer perfume_id de {url}")
    perfume_id = int(m.group(1))

    h1 = tree.css_first("h1[itemprop=name]")
    raw_title = (h1.text() if h1 is not None else "") or ""
    gender_span = h1.css_first("span") if h1 is not None else None
    gender_raw = (gender_span.text() if gender_span is not None else "") or ""
    title = raw_title.replace(gender_raw, "").strip()

    brand_node = tree.css_first('p[itemprop=brand] span[itemprop=name]')
    brand = (brand_node.text() or "").strip() if brand_node is not None else None

    # El nombre del h1 viene como "<Nombre> <Marca>". Sacando la marca del
    # final queda el nombre limpio.
    name = title
    if brand and title.endswith(brand):
        name = title[: -len(brand)].strip() or title

    desc_node = tree.css_first("div[itemprop=description]")
    description = (desc_node.text() or "").strip() if desc_node is not None else None

    launch_year = None
    olfactive_family = None
    if description:
        if (ym := _YEAR.search(description)) :
            launch_year = int(ym.group(1))
        if (fm := _FAMILY.search(description)) :
            olfactive_family = fm.group(1).strip()

    gender: Gender = _normalise_gender(gender_raw)
    if gender == "unknown" and description:
        if (gm := _GENDER_TEXT.search(description)):
            gender = _normalise_gender(gm.group(1))

    rating_value = None
    rv = tree.css_first("span[itemprop=ratingValue]")
    if rv is not None:
        try:
            rating_value = float((rv.text() or "").strip())
        except ValueError:
            rating_value = None

    rating_count = None
    rc = tree.css_first("span[itemprop=ratingCount]")
    if rc is not None:
        rating_count = _to_int(rc.attributes.get("content") or rc.text())

    reviews_total, is_approx = (None, False)
    if (rt := _REVIEW_TOTAL.search(html)):
        reviews_total, is_approx = _parse_abbrev(rt.group(1))

    image_url = None
    if (img := tree.css_first('picture img[alt^="perfume"]')) is not None:
        image_url = img.attributes.get("src")

    interactions, user_seeds = _extract_reviews(tree, perfume_id)

    # Truncado: o llegamos al tope que renderiza el sitio para anonimos, o el
    # total declarado supera lo que conseguimos.
    truncated = len(interactions) >= REVIEW_PAGE_CAP or (
        reviews_total is not None and reviews_total > len(interactions) * 1.1
    )

    item = Item(
        perfume_id=perfume_id,
        url=url,
        name=name or f"perfume-{perfume_id}",
        brand=brand,
        gender=gender,
        launch_year=launch_year,
        olfactive_family=olfactive_family,
        perfumers=_extract_perfumers(tree),
        rating_value=rating_value,
        rating_count=rating_count,
        reviews_total=reviews_total,
        reviews_total_is_approx=is_approx,
        reviews_scraped=len(interactions),
        reviews_truncated=truncated,
        accords=_extract_accords(tree),
        notes=_extract_notes(tree),
        image_url=image_url,
        description=description,
    )
    return item, interactions, user_seeds


# --------------------------------------------------------------------------
# Reviews
# --------------------------------------------------------------------------


def _review_id_from(card: Node) -> int | None:
    node_id = card.attributes.get("id") or ""
    if (m := re.match(r"parent(\d+)$", node_id)):
        return int(m.group(1))
    vb = card.css_first("vote-buttons-new")
    if vb is not None and (cid := vb.attributes.get("comment-id")):
        return _to_int(cid)
    for inner in card.css("div[id]"):
        if (m := re.match(r"(?:cc|dd|review_)(\d+)$", inner.attributes.get("id") or "")):
            return int(m.group(1))
    return None


def _votes_from(card: Node) -> dict:
    node = card.css_first("user-perfume-votes-new")
    if node is None:
        return {}
    raw = node.attributes.get(":perfume-votes") or node.attributes.get("perfume-votes")
    if not raw:
        return {}
    try:
        return orjson.loads(ihtml.unescape(raw))
    except orjson.JSONDecodeError:
        return {}


def _extract_reviews(tree: HTMLParser, perfume_id: int) -> tuple[list[Interaction], list[dict]]:
    interactions: list[Interaction] = []
    seeds: dict[str, dict] = {}

    for card in tree.css('div[itemprop=review]'):
        review_id = _review_id_from(card)
        if review_id is None:
            continue

        slug = None
        display = None
        avatar = None

        author = card.css_first('div[itemprop=author]') or card
        meta_name = author.css_first("meta[itemprop=name]")
        if meta_name is not None:
            display = (meta_name.attributes.get("content") or "").strip() or None
        if (img := author.css_first("img")) is not None:
            avatar = img.attributes.get("src")

        for node in card.css("[title]"):
            if (sm := _PROFILE_SLUG.search(node.attributes.get("title") or "")):
                slug = sm.group(1).lower()
                break
        if slug is None:
            continue

        timestamp = None
        if (t := card.css_first("fromunixtimenew")) is not None:
            timestamp = _to_int(t.attributes.get("unixtime"))
        if timestamp is None and (dp := card.css_first("[itemprop=datePublished]")) is not None:
            # Fallback: solo fecha, sin hora.
            import datetime as _dt

            raw = dp.attributes.get("content") or ""
            try:
                timestamp = int(_dt.datetime.fromisoformat(raw).timestamp())
            except ValueError:
                timestamp = None

        text = None
        if (body := card.css_first("[itemprop=reviewBody]")) is not None:
            text = (body.text() or "").strip() or None

        v = normalise_votes(_votes_from(card))
        interactions.append(
            Interaction(
                review_id=review_id,
                perfume_id=perfume_id,
                member_id=None,
                username_slug=slug,
                rating=v["rating"],
                relation=v["relation"],
                longevity=v["longevity"],
                sillage=v["sillage"],
                gender_vote=v["gender"],
                season_winter=v["winter"],
                season_spring=v["spring"],
                season_summer=v["summer"],
                season_autumn=v["autumn"],
                day=v["day"],
                night=v["night"],
                timestamp=timestamp,
                review_text=text,
                source="perfume_page",
            )
        )

        if slug not in seeds:
            seeds[slug] = {
                "username_slug": slug,
                "username_display": display,
                "avatar_url": avatar,
            }

    return interactions, list(seeds.values())
