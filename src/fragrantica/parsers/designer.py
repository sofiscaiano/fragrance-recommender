"""Fase 1: enumeracion de items desde los listados de marca.

El listado de marca es la ruta confiable para enumerar el catalogo: los
sitemaps devuelven 403 incluso con impersonacion TLS.

Limitacion verificada: el listado NO expone el conteo de reviews por perfume
(0 hits de ratingCount/itemprop). Por eso el porton de "minimo de reviews" no
se puede aplicar aca y hay que descargar la pagina del item.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser

# Los links de perfume incluyen el id al final del slug.
PERFUME_HREF = re.compile(
    r"^(?:https://www\.fragrantica\.com)?/perfume/([^/]+)/[^\"']*?-(\d+)\.html$"
)

# Los cards del listado propiamente dicho. Sin esto se cuelan perfumes de otras
# marcas desde los widgets laterales ("currently wearing", relacionados): en el
# listado de Dior aparecian 39 items ajenos sobre 358.
LISTING_SELECTORS = ("a.prefumeHbox", "a.tw-gridlist-card-base")

DESIGNER_HREF = re.compile(r"^(?:https://www\.fragrantica\.com)?/designers/([^/\"']+)\.html$")

# El title del listado trae "<Marca> <Nombre> <genero> <anio>", que da nombre,
# genero y anio gratis sin descargar la pagina del item.
# El listado usa female/male/unisex, no los men/women del resto del sitio.
TITLE_TAIL = re.compile(r"\s+(female|male|unisex|men|women)\s+(\d{4})\s*$", re.I)

_GENDER_MAP = {
    "female": "women",
    "women": "women",
    "male": "men",
    "men": "men",
    "unisex": "unisex",
}


def parse_designer_index(html: str) -> list[str]:
    """Extrae los slugs de marca del indice /designers/."""
    tree = HTMLParser(html)
    slugs: dict[str, None] = {}
    for node in tree.css("a[href]"):
        m = DESIGNER_HREF.match(node.attributes.get("href") or "")
        if m:
            slugs[m.group(1)] = None
    return list(slugs)


def parse_designer_page(html: str, brand: str | None = None) -> list[dict]:
    """Extrae los perfumes listados en la pagina de una marca.

    Devuelve dicts con perfume_id, url y los metadatos baratos del title.
    Los *_hint son provisorios: la fuente autoritativa es la pagina del item.
    """
    tree = HTMLParser(html)
    seen: dict[int, dict] = {}

    nodes = []
    for selector in LISTING_SELECTORS:
        nodes = tree.css(selector)
        if nodes:
            break
    if not nodes:
        # Fallback si el sitio renombra las clases: se acepta el ruido de los
        # widgets antes que perder la enumeracion entera.
        nodes = tree.css("a[href]")

    for node in nodes:
        href = node.attributes.get("href") or ""
        m = PERFUME_HREF.match(href)
        if not m:
            continue
        designer_in_url = m.group(1)
        perfume_id = int(m.group(2))
        if perfume_id in seen:
            continue

        title = (node.attributes.get("title") or "").strip()
        gender = None
        year = None
        name_hint = title or None
        tail = TITLE_TAIL.search(title)
        if tail:
            gender = _GENDER_MAP.get(tail.group(1).lower())
            year = int(tail.group(2))
            name_hint = title[: tail.start()].strip() or None
        if name_hint and brand and name_hint.startswith(brand):
            name_hint = name_hint[len(brand) :].strip() or name_hint

        seen[perfume_id] = {
            "perfume_id": perfume_id,
            "url": href if href.startswith("http") else f"https://www.fragrantica.com{href}",
            "name_hint": name_hint,
            "gender_hint": gender,
            "year_hint": year,
            "designer_in_url": designer_in_url,
        }

    return list(seen.values())


def designer_slug_from_perfume_url(url: str) -> str | None:
    """Marca embebida en /perfume/<Designer>/.... None si la URL no es de item."""
    m = PERFUME_HREF.match(url) or PERFUME_HREF.search(url)
    return m.group(1) if m else None


def rows_for_designer(rows: list[dict], designer_slug: str) -> list[dict]:
    """Descarta widgets laterales cuya URL es de otra marca.

    El selector `a.prefumeHbox` ya evita la mayoria; esto es la red de
    seguridad para no encolar (ni pedir) un Lattafa porque aparecio en
    el listado de Dior.
    """
    return [r for r in rows if r.get("designer_in_url") == designer_slug]
