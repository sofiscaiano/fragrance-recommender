"""Chequeo manual de los parsers contra los fixtures. Salida legible."""

import json
from pathlib import Path

from fragrantica.parsers.designer import parse_designer_index, parse_designer_page
from fragrantica.parsers.perfume import parse_perfume
from fragrantica.parsers.profile import member_id_from_avatar, parse_profile

FX = Path(__file__).parent / "fixtures"

print("=" * 72)
print("FASE 1: indice de marcas")
idx = parse_designer_index((FX / "designers_index.html").read_text())
print(f"  marcas: {len(idx)}  ejemplo: {idx[:6]}")

print("\nFASE 1: listado de Dior")
rows = parse_designer_page((FX / "designer_dior.html").read_text())
print(f"  perfumes: {len(rows)}")
for r in rows[:4]:
    print("   ", r)
with_year = sum(1 for r in rows if r["year_hint"])
with_gender = sum(1 for r in rows if r["gender_hint"])
print(f"  con year_hint: {with_year}/{len(rows)}   con gender_hint: {with_gender}/{len(rows)}")

print("\n" + "=" * 72)
print("FASE 2: pagina de perfume (Sauvage)")
item, inter, seeds = parse_perfume(
    (FX / "perfume_sauvage.html").read_text(),
    "https://www.fragrantica.com/perfume/Dior/Sauvage-31861.html",
)
d = item.model_dump()
for k in [
    "perfume_id", "name", "brand", "gender", "launch_year", "olfactive_family",
    "perfumers", "rating_value", "rating_count", "reviews_total",
    "reviews_total_is_approx", "reviews_scraped", "reviews_truncated",
]:
    print(f"  {k:26} = {d[k]!r}")
print(f"  accords ({len(item.accords)}):")
for a in item.accords[:6]:
    print(f"      {a.name:20} {a.intensity:6.2f}%")
print(f"  notes top    = {item.notes_top}")
print(f"  notes middle = {item.notes_middle}")
print(f"  notes base   = {item.notes_base}")
print(f"  image_url    = {item.image_url}")

print(f"\n  interacciones: {len(inter)}   semillas de usuario: {len(seeds)}")
print("  ejemplo de interaccion:")
print("   ", json.dumps(inter[0].model_dump(), ensure_ascii=False)[:400])
rated = [i for i in inter if i.rating is not None]
print(f"  con rating no nulo: {len(rated)}/{len(inter)}")
print(f"  con timestamp:      {sum(1 for i in inter if i.timestamp)}/{len(inter)}")
print(f"  con texto:          {sum(1 for i in inter if i.review_text)}/{len(inter)}")
print(f"  member_id nulo:     {sum(1 for i in inter if i.member_id is None)}/{len(inter)} (esperado: todos)")
print(f"  relations: {dict((r, sum(1 for i in inter if i.relation == r)) for r in ['have','had','want','unknown'])}")

print("\n" + "=" * 72)
print("FASE 3: perfil de usuario (@quilter)")
user, uinter = parse_profile((FX / "profile_quilter.html").read_text(), "quilter")
print(f"  {user.model_dump()}")
print(f"  interacciones del perfil: {len(uinter)}")
if uinter:
    print("   ", json.dumps(uinter[0].model_dump(), ensure_ascii=False)[:400])
print(f"  member_id nulo: {sum(1 for i in uinter if i.member_id is None)}/{len(uinter)} (esperado: 0)")

print("\n  chequeo cruzado del atajo del avatar:")
for av, expected in [
    ("https://fimgs.net/mdimg/avatari/t.3146574.jpg", 3146574),
    ("https://fimgs.net/himg/o.69246.png", None),
]:
    got = member_id_from_avatar(av)
    print(f"    {av[-28:]:30} -> {got!r}  (esperado {expected!r})  {'OK' if got == expected else 'FALLA'}")
