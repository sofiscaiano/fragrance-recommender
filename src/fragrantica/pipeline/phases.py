"""Las fases de crawl (1, 2, 3, 5). Las fases 4 y 6 son locales, sin red."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console

from ..config import CRAWL, DATASET, DatasetConfig
from ..frontier import Frontier
from ..http_client import ChallengeDetected, Client, FetchError, NotFound, RateLimited, absolute
from ..models import User
from ..parsers.crypto import DecryptError, unwrap_ajax_body
from ..parsers.designer import (
    designer_slug_from_perfume_url,
    parse_designer_index,
    parse_designer_page,
    rows_for_designer,
)
from ..parsers.perfume import parse_perfume
from ..parsers.profile import member_id_from_avatar, parse_profile
from ..parsers.shelves import ParsedShelves, parse_shelves
from ..storage import ParquetWriter, existing_ids
from .runner import AlreadyHave, SkipItem, run_phase

log = logging.getLogger(__name__)
console = Console()


# --------------------------------------------------------------------------
# Fase 1: enumeracion del catalogo de items
# --------------------------------------------------------------------------


async def phase1_enumerate(
    frontier: Frontier,
    client: Client,
    staging: Path,
    designers: list[str] | None = None,
) -> None:
    """Puebla el frontier de perfumes desde los listados de marca.

    Si `designers` es None, primero enumera el indice A-Z. Para el vertical
    slice se pasa una sola marca.
    """
    if designers is None:
        console.print("[bold]Fase 1a[/bold]: indice de marcas")
        result = await client.fetch(absolute("/designers/"))
        designers = parse_designer_index(result.body)
        console.print(f"  {len(designers)} marcas encontradas")

    rows = [
        (absolute(f"/designers/{slug}.html"), "designer", slug, 10) for slug in designers
    ]
    added = frontier.add_many(rows)
    console.print(f"[bold]Fase 1b[/bold]: {added} listados de marca encolados")

    writer = ParquetWriter(staging, "item_frontier")

    def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        brand = entity_id.replace("-", " ")
        found = parse_designer_page(body, brand=brand)
        own = rows_for_designer(found, entity_id)
        dropped = len(found) - len(own)
        if dropped:
            log.info("fase 1: %d perfumes ajenos a %s no se encolan", dropped, entity_id)
        if not own:
            raise SkipItem("el listado de marca no tiene perfumes propios")
        frontier.add_many(
            [(row["url"], "perfume", str(row["perfume_id"]), 50) for row in own]
        )
        return {"item_frontier": [{**row, "designer_slug": entity_id} for row in own]}

    with writer:
        await run_phase(
            name="Fase 1: listados de marca",
            kind="designer",
            frontier=frontier,
            client=client,
            writers={"item_frontier": writer},
            handler=handle,
        )


# --------------------------------------------------------------------------
# Fase 2: paginas de perfume -> items + interacciones + semillas de usuarios
# --------------------------------------------------------------------------


async def phase2_perfumes(
    frontier: Frontier,
    client: Client,
    staging: Path,
    dataset: DatasetConfig = DATASET,
    limit: int | None = None,
) -> None:
    items = ParquetWriter(staging, "items")
    inter = ParquetWriter(staging, "interactions_from_perfume")
    already = existing_ids(staging / "items", "perfume_id")
    allowed = frontier.listed_designer_slugs()

    def precheck(url: str, entity_id: str) -> None:
        if entity_id in already or frontier.entity_is_done("perfume", entity_id):
            raise AlreadyHave()
        slug = designer_slug_from_perfume_url(url)
        if slug and allowed and slug not in allowed:
            raise SkipItem(f"marca {slug} fuera de las marcas listadas")

    def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        item, interactions, seeds = parse_perfume(body, url)

        # Porton de items: descartar los que no llegan al minimo de reviews.
        # Lo importante no es ahorrar este request (ya se gasto), sino evitar
        # arrastrar cientos de miles de perfiles inutiles a la fase 3.
        n = len(interactions)
        if n < dataset.crawl_min_item_reviews:
            # Se guarda igual la fila del item, para trazabilidad y para poder
            # revisar la decision despues sin volver a la red.
            items.add(item)
            already.add(str(item.perfume_id))
            raise SkipItem(f"solo {n} reviews (< {dataset.crawl_min_item_reviews})")

        # Solo los items que pasan el porton generan semillas de usuario.
        frontier.add_many(
            [
                (absolute(f"/@{s['username_slug']}"), "profile", s["username_slug"],
                 20 if item.reviews_truncated else 60)
                for s in seeds
            ]
        )
        already.add(str(item.perfume_id))
        return {"items": [item], "interactions_from_perfume": interactions}

    with items, inter:
        await run_phase(
            name="Fase 2: paginas de perfume",
            kind="perfume",
            frontier=frontier,
            client=client,
            writers={"items": items, "interactions_from_perfume": inter},
            handler=handle,
            limit=limit,
            precheck=precheck,
        )


# --------------------------------------------------------------------------
# Fase 3: perfiles de usuario -> users + member_id + historico completo
# --------------------------------------------------------------------------


async def phase3_profiles(
    frontier: Frontier,
    client: Client,
    staging: Path,
    limit: int | None = None,
) -> None:
    users = ParquetWriter(staging, "users")
    inter = ParquetWriter(staging, "interactions_from_profile")
    wardrobe = ParquetWriter(staging, "wardrobe")

    mismatches = 0

    async def handle(url: str, entity_id: str, body: str) -> dict[str, list]:
        nonlocal mismatches
        user, interactions = parse_profile(body, entity_id)

        # Chequeo cruzado del atajo del avatar. No se usa para saltear la
        # visita (el perfil se necesita igual por el historico), sino como
        # canario: si no coincide, hay un bug en el parser y quiero saberlo.
        inferred = member_id_from_avatar(user.avatar_url)
        if inferred is not None and inferred != user.member_id:
            mismatches += 1
            log.warning(
                "member_id del avatar (%s) != del perfil (%s) en @%s",
                inferred, user.member_id, entity_id,
            )

        shelves = await _shelves_for_profile(client, body, user, url)
        frontier.record_member_id(user.username_slug, user.member_id)
        return {
            "users": [user],
            "interactions_from_profile": interactions + shelves.votes,
            "wardrobe": shelves.wardrobe,
        }

    with users, inter, wardrobe:
        await run_phase(
            name="Fase 3: perfiles de usuario",
            kind="profile",
            frontier=frontier,
            client=client,
            writers={
                "users": users,
                "interactions_from_profile": inter,
                "wardrobe": wardrobe,
            },
            handler=handle,
            limit=limit,
        )

    if mismatches:
        console.print(f"[yellow]  {mismatches} discrepancias de member_id via avatar[/yellow]")


async def _shelves_for_profile(
    client: Client,
    html: str,
    user: User,
    profile_url: str,
) -> ParsedShelves:
    """Un POST extra por perfil. RateLimited/challenge se propagan al runner.

    Un fallo de descifrado o de forma del JSON no tumba el perfil: las reviews
    del HTML ya estan parseadas. El passphrase es `_pd(host)`, no el bundle.

    Los votos vuelven como Interaction; el wardrobe como WardrobeItem. No se
    mezclan: have/had/want no es una calificacion.
    """
    empty = ParsedShelves()
    if not client.cfg.fetch_shelves or client._shelves_disabled:
        return empty
    pw = await client.ensure_passphrase(html)
    if not pw:
        return empty
    try:
        result = await client.post(
            absolute("/ajax.php?user_shelves"),
            data={"action": "user_shelves", "user_id": str(user.member_id)},
            referer=profile_url,
        )
        payload = unwrap_ajax_body(result.body, pw)
    except RateLimited:
        raise
    except ChallengeDetected as exc:
        client.disable_shelves(str(exc))
        return empty
    except (DecryptError, FetchError, NotFound, ValueError) as exc:
        log.warning("shelves de @%s: %s", user.username_slug, exc)
        if isinstance(exc, DecryptError):
            client._shelves_decrypt_fails += 1
            if client._shelves_decrypt_fails >= 3:
                client.disable_shelves("descifrado ajax fallo 3 veces seguidas")
        return empty
    client._shelves_decrypt_fails = 0
    return parse_shelves(payload, member_id=user.member_id, slug=user.username_slug)


# --------------------------------------------------------------------------
# Fase 5: backfill de items huerfanos
# --------------------------------------------------------------------------


async def phase5_orphans(
    frontier: Frontier,
    client: Client,
    staging: Path,
    orphan_ids: list[int],
    url_by_id: dict[int, str],
) -> int:
    """Crawlea los items referenciados por interacciones pero ausentes del catalogo.

    Garantiza integridad referencial: toda interaccion apunta a un item que
    existe en la tabla de items.
    """
    rows = []
    for pid in orphan_ids:
        url = url_by_id.get(pid)
        if url:
            rows.append((url, "perfume", str(pid), 30))
    if not rows:
        return 0
    added = frontier.add_many(rows)
    console.print(f"[bold]Fase 5[/bold]: {added} items huerfanos encolados")
    if added:
        await phase2_perfumes(frontier, client, staging)
    return added


def prune_slice(
    frontier: Frontier,
    staging: Path,
    designer_slug: str,
) -> dict[str, int]:
    """Limpia el frontier de un vertical slice: nada ajeno a `designer_slug`.

    Los perfume ya `done` de otras marcas se dejan: borrarles el done haria
    que una fase 1 posterior de esa marca los volviera a pedir.
    Los perfiles pending que no reseñaron ningun item de la marca salen de
    la cola para no gastar 13k GETs de ruido.
    """
    n_perfumes = frontier.drop_perfumes_not_from(designer_slug, keep_done=True)
    ids = _perfume_ids_for_designer(staging, frontier, designer_slug)
    slugs = _reviewer_slugs(staging, ids)
    # Sin slugs no borramos: un staging vacio vaciaria 13k perfiles por error.
    n_profiles = frontier.drop_profiles_except(slugs) if slugs else 0
    return {
        "perfumes_pending_dropped": n_perfumes,
        "profiles_dropped": n_profiles,
        "profiles_kept": len(slugs),
        "items_of_designer": len(ids),
    }


def _perfume_ids_for_designer(
    staging: Path, frontier: Frontier, designer_slug: str
) -> set[int]:
    ids: set[int] = set()
    items_dir = staging / "items"
    if items_dir.exists():
        import pyarrow.parquet as pq

        for path in items_dir.glob("*.parquet"):
            table = pq.read_table(path, columns=["perfume_id", "brand", "url"])
            for row in table.to_pylist():
                url = row.get("url") or ""
                brand = row.get("brand") or ""
                if (
                    f"/perfume/{designer_slug}/" in url
                    or brand.replace(" ", "-") == designer_slug
                    or brand == designer_slug
                ):
                    ids.add(int(row["perfume_id"]))
    like = f"%/perfume/{designer_slug}/%"
    for r in frontier.conn.execute(
        "SELECT entity_id FROM frontier WHERE kind='perfume' AND url LIKE ?",
        (like,),
    ):
        try:
            ids.add(int(r["entity_id"]))
        except (TypeError, ValueError):
            continue
    return ids


def _reviewer_slugs(staging: Path, perfume_ids: set[int]) -> set[str]:
    if not perfume_ids:
        return set()
    slugs: set[str] = set()
    inter_dir = staging / "interactions_from_perfume"
    if not inter_dir.exists():
        return slugs
    import pyarrow.parquet as pq

    want = {int(p) for p in perfume_ids}
    for path in inter_dir.glob("*.parquet"):
        table = pq.read_table(path, columns=["perfume_id", "username_slug"])
        for row in table.to_pylist():
            if row["perfume_id"] in want and row["username_slug"]:
                slugs.add(str(row["username_slug"]).lower())
    return slugs
