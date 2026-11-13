---
theme: default
layout: none
title: Fragrantica
info: |
  Un recomendador de perfumes.
  Sistemas de recomendación.
colorSchema: light
highlighter: shiki
monaco: false
aspectRatio: 16/9
canvasWidth: 1280
transition: fade
drawings:
  persist: false
fonts:
  provider: none
  sans: "Avenir Next, Segoe UI, sans-serif"
  serif: "Iowan Old Style, Palatino, Palatino Linotype, Georgia, serif"
  mono: "ui-monospace, SFMono-Regular, Menlo, monospace"
---

<div class="frame cover">
  <div class="cover-main">
    <div>
      <p class="kicker">Sistemas de recomendación</p>
      <h1 class="cover-title">Fragrantica</h1>
      <p class="cover-lead">Un recomendador de perfumes</p>
      <div class="glyph-row">
        <span><Scent kind="drop" /> Notas</span>
        <span><Scent kind="leaf" /> Acordes</span>
        <span><Scent kind="bottle" /> Estela</span>
      </div>
      <div class="path">
        <span>Scraping</span>
        <span>Modelo</span>
        <span>App</span>
      </div>
    </div>
    <Scent kind="bottle" spray class="cover-bottle" />
  </div>
</div>

<!--
El recorrido es el del proyecto: cómo se armó el dataset, qué se fue probando en el modelo y cómo queda la app. Para vos ordena con el two-stage. Las otras tres listas siguen por votos, nota y tendencia.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Objetivo</p>
  <h1 class="title sm">Recomendar diez, y medir el orden</h1>
  <div class="points">
    <div class="point">
      <div class="point-k">Qué se recomienda</div>
      <div class="point-num">10</div>
      <div class="slots" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <div class="rank-scale"><span>diez perfumes</span></div>
      <p>Para cada usuario, diez perfumes que todavía no reseñó, de la nota más alta a la más baja.</p>
    </div>
    <div class="point">
      <div class="point-k">Cómo se mide</div>
      <div class="point-num">NDCG@10</div>
      <div class="ranks" aria-hidden="true">
        <i style="height: 100%"></i>
        <i style="height: 63%"></i>
        <i style="height: 50%"></i>
        <i style="height: 43%"></i>
        <i style="height: 39%"></i>
        <i style="height: 36%"></i>
        <i style="height: 33%"></i>
        <i style="height: 32%"></i>
        <i style="height: 30%"></i>
        <i style="height: 29%"></i>
      </div>
      <div class="rank-scale"><span>puesto 1</span><span>puesto 10</span></div>
      <p>Puntúa el puesto de cada perfume dentro del top 10. Es un valor por persona.</p>
    </div>
  </div>
  <div class="split">
    <div class="point-k">Por fecha, dentro de cada usuario · unas 54 reviews en promedio</div>
    <div class="sharebar">
      <div class="sh-train"><b>63%</b><span>Train</span></div>
      <div class="sh-val"><b>18%</b><span>Validación</span></div>
      <div class="sh-hold"><b>18%</b><span>Holdout</span></div>
    </div>
    <div class="shareuse">
      <p>Ajusta el retrieval y LGBMRanker. Dos ventanas de 10 enseñan a predecir el bloque siguiente.</p>
      <p>Las 10 anteriores al holdout. Optuna elige con estas.</p>
      <p>Las últimas 10, el test. No entran al entrenamiento.</p>
    </div>
  </div>
</div>

<!--
El objetivo es un top 10 por usuario. NDCG@10 puntúa el orden de esos puestos. El corte es por fecha y por persona: con unas 54 reviews de promedio, el train es el 63% y ajusta el modelo, la validación es el 18% anterior al holdout y sirve para Optuna, y el holdout es el último 18% y no entra al entrenamiento.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Arquitectura</p>
  <h1 class="title sm">Tres piezas</h1>
  <div class="pieces">
    <div class="piece">
      <div class="piece-n">01</div>
      <h2>Scraper</h2>
      <p>Baja Fragrantica y deja perfumes, usuarios e interacciones en parquet.</p>
    </div>
    <div class="piece">
      <div class="piece-n">02</div>
      <h2>Modelo</h2>
      <p>Dos etapas. El retrieval junta siete fuentes con RRF. LGBMRanker reordena esa lista.</p>
    </div>
    <div class="piece">
      <div class="piece-n">03</div>
      <h2>App</h2>
      <p>Para vos ordena con el two-stage. Las otras listas siguen por votos, nota y tendencia.</p>
    </div>
  </div>
</div>

<!--
Son tres programas. El scraper escribe el dataset, el recomendador entrena y mide, y la app sirve ese ranking en Para vos. Más populares, mejor puntuados y tendencia siguen siendo reglas del catálogo.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Scraping</p>
  <h1 class="title sm">De la marca al dataset</h1>
  <div class="step-list">
    <div class="step"><em>01</em><div class="step-n">121</div><div><b>Marcas</b><span>El índice de diseñadores, y de ahí la lista de perfumes.</span></div></div>
    <div class="step"><em>02</em><div class="step-n">20.744</div><div><b>Perfumes</b><span>La ficha, con notas, acordes y las reviews visibles.</span></div></div>
    <div class="step"><em>03</em><div class="step-n">75.077</div><div><b>Perfiles</b><span>Bajados. Quedan 68.010 en la cola.</span></div></div>
    <div class="step"><em>04</em><div class="step-n">93.316</div><div><b>Huérfanos</b><span>Ids citados en una review o en el wardrobe, sin ficha en el export.</span></div></div>
    <div class="step"><em>05</em><div class="step-n">5</div><div><b>k-core</b><span>El corte elegido. Usuario y perfume con al menos cinco, hasta que nadie más cae.</span></div></div>
  </div>
  <div class="tools">
    <div><b>curl_cffi</b><span>El pedido</span></div>
    <div><b>selectolax</b><span>El HTML</span></div>
    <div><b>DuckDB</b><span>Dedup y k-core</span></div>
    <div><b>Parquet</b><span>El export</span></div>
  </div>
</div>

<!--
121 marcas y 20.744 fichas de perfume, todas salidas del listado de marcas. Perfiles: 75.077 bajados y 68.010 todavía pendientes. Los 93.316 salen del export del 11 de octubre: perfume_id distintos que aparecen en una review ya deduplicada o en el wardrobe y no tienen fila en items. No se bajó ninguna de esas fichas. El k-core es 5, elegido al exportar, y se itera hasta punto fijo. El sitio respondía 429 con seis workers cerca de los 150 pedidos, así que el crawl fue un worker con 7–10 segundos, y después un proxy de puertos sticky.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title sm">La matriz que entrena queda en un 5%</h1>
  <div class="funnel">
    <div class="f-row">
      <div class="f-num">5.96M</div>
      <div class="f-track"><div class="f-fill" style="width: 100%"></div></div>
      <div class="f-lbl">Interacciones crudas, todavía con duplicados.</div>
    </div>
    <div class="f-row">
      <div class="f-num">2.29M</div>
      <div class="f-track"><div class="f-fill" style="width: 38%"></div></div>
      <div class="f-lbl">Una por usuario y perfume, ambos con al menos 5.</div>
    </div>
    <div class="f-row">
      <div class="f-num">611k</div>
      <div class="f-track"><div class="f-fill" style="width: 10%"></div></div>
      <div class="f-lbl">Con fecha y nota. Sin fecha no hay holdout temporal.</div>
    </div>
    <div class="f-row">
      <div class="f-num">134k</div>
      <div class="f-track"><div class="f-fill" style="width: 8%"></div></div>
      <div class="f-lbl">Las que sobreviven el corte de actividad y entrenan.</div>
    </div>
  </div>
  <div class="density">
    <div>
      <div class="num">0.10%</div>
      <b>Antes</b>
      <span>Densidad de las reviews con fecha y nota.</span>
    </div>
    <div>
      <div class="num">28 / 60</div>
      <b>El corte</b>
      <span>Mínimo de reviews por usuario y por perfume, repetido hasta que nadie más cae.</span>
    </div>
    <div>
      <div class="num">2.473 × 1.088</div>
      <b>La matriz</b>
      <span>Queda en 4.98%.</span>
    </div>
  </div>
</div>

<!--
Cada fila es un filtro distinto. El k-core de 5 es el del export. El 28/60 se itera sobre las reviews fechadas hasta un punto fijo, y por eso la matriz pasa de casi vacía, 0.10%, a 4.98%. En el camino salen el 94% de esas personas y el 92% de esos perfumes.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title sm">El esquema</h1>
  <div class="er">
    <div class="firma"><b>1</b><span>Firma</span><b>0..1</b></div>
    <article class="ent">
      <h2>Usuario</h2>
      <p>Reviews y notas del perfil.</p>
      <p>Cuántos guardó.</p>
    </article>
    <div class="rel">
      <b>1</b>
      <div class="rel-line"><span>reseña</span></div>
      <b>N</b>
    </div>
    <article class="ent train">
      <h2>Interacción</h2>
      <p>Nota, fecha y texto.</p>
      <p>Duración, estela y estación.</p>
      <p>Día o noche.</p>
    </article>
    <div class="rel">
      <b>N</b>
      <div class="rel-line"><span>sobre</span></div>
      <b>1</b>
    </div>
    <article class="ent">
      <h2>Perfume</h2>
      <p>Marca, género, año y familia.</p>
      <p>Perfumista, notas, acordes, descripción.</p>
    </article>
    <div class="er-bridge">
      <span class="stem left">guarda · 1 a N</span>
      <span class="stem right">N–1</span>
    </div>
    <article class="ent ward">
      <h2>Wardrobe</h2>
      <p>Tiene, quiere o tuvo. Sin fecha, así que no entrena. La app oculta lo que ya tiene.</p>
    </article>
  </div>
</div>

<!--
Un usuario reseña N interacciones, y cada una es sobre un perfume. La firma apunta a lo sumo a un perfume. El wardrobe es otra tabla, 1 a N, tiene/quiere/tuvo, sin fecha, y no entra a entrenar. La app la usa para ocultar lo que ya tiene.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Modelo · dos etapas</p>
  <h1 class="title sm">El retrieval trae candidatos. LGBMRanker los ordena.</h1>
  <div class="stages">
    <section class="stage">
      <p class="stage-k">Retrieval</p>
      <div class="src-cards">
        <article><b>Popularidad</b><span>La misma lista para todos, por cuántas veces se reseñó.</span></article>
        <article><b>Coseno</b><span>Cercanos porque los reseñaron las mismas personas.</span></article>
        <article><b>ALS</b><span>Factores latentes de la persona y del perfume.</span></article>
        <article><b>BPR</b><span>Arriba lo reseñado, abajo un perfume que no vio.</span></article>
        <article><b>TF-IDF</b><span>El texto de la ficha contra lo que viene reseñando.</span></article>
        <article><b>Two-tower</b><span>Una red para el historial y otra para la ficha.</span></article>
        <article><b>EASE</b><span>Un peso de cada perfume sobre los demás.</span></article>
      </div>
      <div class="to-rrf" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <div class="rrf-bar">
        <b>RRF</b>
        <span>Las siete listas se funden en un ranking: suma de puestos, con el peso de cada fuente. Quedan 146 candidatos.</span>
      </div>
    </section>
    <div class="stage-arrow">→</div>
    <section class="stage stage-rank">
      <p class="stage-k">Ranker</p>
      <div>
        <b>LGBMRanker</b>
        <span>El ranker de LightGBM. Reordena solo esos 146. Entrena con objetivo lambdarank: cada par pesa según cuánto movería el NDCG.</span>
      </div>
    </section>
  </div>
</div>

<!--
Son dos etapas. El retrieval son las siete fuentes: popularidad, coseno, ALS, BPR, TF-IDF, two-tower y EASE. RRF junta puestos, no scores, y se queda con 146. El modelo que reordena ese prefijo es LGBMRanker, de LightGBM. Lambdarank es el objetivo de entrenamiento, no el nombre del modelo. Una review que ninguna fuente trajo baja el NDCG igual.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Optuna · último fold de validación</p>
  <h1 class="title sm">Hiperparámetros seleccionados</h1>
  <div class="tune">
    <article>
      <b>Coseno</b>
      <span><em>812</em> half_life_days</span>
    </article>
    <article>
      <b>ALS</b>
      <span><em>21</em> factors · <em>36</em> iterations</span>
      <span><em>3.53</em> regularization · <em>555</em> half_life_days</span>
    </article>
    <article>
      <b>BPR</b>
      <span><em>63</em> factors · <em>59</em> iterations</span>
      <span><em>0.0135</em> learning_rate · <em>1.91×10⁻⁴</em> regularization</span>
      <span><em>63.7</em> half_life_days</span>
    </article>
    <article>
      <b>TF-IDF</b>
      <span><em>19.931</em> max_features</span>
      <span><em>128</em> half_life_days</span>
    </article>
    <article>
      <b>Two-tower</b>
      <span><em>79</em> embedding_dim · <em>0.00243</em> learning_rate</span>
      <span><em>0.122</em> temperature · <em>16</em> min_item_reads</span>
      <span class="hp-note">Vocabulario: perfumes con al menos 16 interacciones.</span>
    </article>
    <article>
      <b>EASE</b>
      <span><em>1.12×10⁴</em> reg_lambda</span>
      <span><em>24</em> min_interactions</span>
      <span class="hp-note">Matriz ítem-ítem: ítems con al menos 24 interacciones.</span>
    </article>
    <article>
      <b>Popularidad</b>
      <span>Sin búsqueda. El orden es el conteo.</span>
    </article>
    <article>
      <b>Fusión</b>
      <span><em>146</em> rrf_cutoff</span>
      <span>source_weight por fuente</span>
    </article>
  </div>
  <div class="tune-rank">
    <b>LGBMRanker</b>
    <span><em>0.0196</em>learning_rate</span>
    <span><em>23</em>num_leaves</span>
    <span><em>11</em>max_depth</span>
    <span><em>75</em>min_child_samples</span>
    <span><em>0.699</em>subsample</span>
    <span><em>0.628</em>colsample_bytree</span>
  </div>
  <p class="src-foot">Cada fuente se ajustó en su estudio. El two-stage reutiliza esos valores. Optuna selecciona el corte, los pesos y el ranker sobre el último fold. El holdout no interviene.</p>
</div>

<!--
Cada fuente tiene su estudio. Coseno: half_life_days 812. ALS: factors 21, iterations 36, regularization 3.53, half_life_days 555. BPR: factors 63, iterations 59, learning_rate 0.0135, regularization 1.91e-4, half_life_days 63.7. TF-IDF: max_features 19931, half_life_days 128. Two-tower: embedding_dim 79, learning_rate 0.00243, temperature 0.122, min_item_reads 16: solo entran al vocabulario los perfumes con al menos 16 interacciones. EASE: reg_lambda 11154, min_interactions 24: la matriz ítem-ítem descarta los ítems con menos de 24 interacciones. Popularidad no se busca. Optuna del two-stage elige rrf_cutoff 146, un source_weight por fuente y el LGBMRanker: learning_rate 0.0196, num_leaves 23, max_depth 11, min_child_samples 75, subsample 0.699, colsample_bytree 0.628. reg_alpha y reg_lambda quedaron cerca de cero. El objetivo es lambdarank. El holdout no interviene.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Bitácora</p>
  <h1 class="title sm">Qué se fue probando, en orden</h1>
  <div class="log">
    <div class="log-item"><em>01</em><div><b>Popularidad</b><span>Una lista común, con semivida, para tener el piso de lo que se gana al personalizar.</span></div></div>
    <div class="log-item"><em>02</em><div><b>Fuentes solas</b><span>Se barrieron ALS, ítem-kNN, EASE y un two-tower, cada uno con su grilla de hiperparámetros.</span></div></div>
    <div class="log-item"><em>03</em><div><b>Contenido</b><span>El two-tower se probó también solo con ids, para ver si notas y acordes aportaban.</span></div></div>
    <div class="log-item"><em>04</em><div><b>Two-stage</b><span>Esas fuentes se fusionan con RRF y LGBMRanker. Optuna elige sobre el último fold, no sobre el holdout.</span></div></div>
  </div>
</div>

<!--
Primero el piso de popularidad, después cada fuente por separado, después la torre sin el texto del perfume, y al final la fusión. El tuneo no mira el holdout: ese queda para la medición final.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">NDCG@10 · 2.473 usuarios</p>
  <h1 class="title sm">Cada fuente sola, y las siete juntas</h1>
  <div class="src-board">
    <div class="src-row">
      <b>EASE</b>
      <div class="src-bar"><i style="width: 79%"></i></div>
      <em>0.082</em>
    </div>
    <div class="src-row">
      <b>ALS</b>
      <div class="src-bar"><i style="width: 76%"></i></div>
      <em>0.079</em>
    </div>
    <div class="src-row">
      <b>Coseno</b>
      <div class="src-bar"><i style="width: 69%"></i></div>
      <em>0.072</em>
    </div>
    <div class="src-row">
      <b>BPR</b>
      <div class="src-bar"><i style="width: 55%"></i></div>
      <em>0.057</em>
    </div>
    <div class="src-row">
      <b>TF-IDF</b>
      <div class="src-bar"><i style="width: 49%"></i></div>
      <em>0.051</em>
    </div>
    <div class="src-row">
      <b>Popularidad</b>
      <div class="src-bar"><i style="width: 26%"></i></div>
      <em>0.027</em>
    </div>
    <div class="src-row">
      <b>Two-tower</b>
      <div class="src-bar"></div>
      <em class="missing">—</em>
    </div>
    <div class="src-row best">
      <b>Two-stage</b>
      <div class="src-bar"><i style="width: 100%"></i></div>
      <em>0.104</em>
    </div>
  </div>
</div>

<!--
Mismas 2.473 personas. Solas: EASE 0.082, ALS 0.079, coseno 0.072, BPR 0.057, TF-IDF 0.051, popularidad 0.027. El two-tower no tiene NDCG solo. Las siete juntas, two-stage, llegan a 0.104.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">RRF · los pesos suman 1</p>
  <h1 class="title sm">Cuánto empuja cada fuente</h1>
  <div class="src-board weights">
    <div class="src-row">
      <b>Popularidad</b>
      <div class="src-bar"><i style="width: 100%"></i></div>
      <em>0.334</em>
    </div>
    <div class="src-row">
      <b>TF-IDF</b>
      <div class="src-bar"><i style="width: 97%"></i></div>
      <em>0.324</em>
    </div>
    <div class="src-row">
      <b>ALS</b>
      <div class="src-bar"><i style="width: 36%"></i></div>
      <em>0.121</em>
    </div>
    <div class="src-row">
      <b>EASE</b>
      <div class="src-bar"><i style="width: 30%"></i></div>
      <em>0.101</em>
    </div>
    <div class="src-row">
      <b>Coseno</b>
      <div class="src-bar"><i style="width: 18%"></i></div>
      <em>0.059</em>
    </div>
    <div class="src-row">
      <b>BPR</b>
      <div class="src-bar"><i style="width: 12%"></i></div>
      <em>0.039</em>
    </div>
    <div class="src-row">
      <b>Two-tower</b>
      <div class="src-bar"><i style="width: 6%"></i></div>
      <em>0.021</em>
    </div>
  </div>
</div>

<!--
Pesos del RRF ya normalizados: popularidad 0.334, TF-IDF 0.324, ALS 0.121, EASE 0.101, coseno 0.059, BPR 0.039, two-tower 0.021.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Ranker · importancia en la corrida de las 13:01</p>
  <h1 class="title sm">Qué variables se armaron, y cuáles pesaron</h1>
  <div class="funnel">
    <div class="f-row">
      <div class="f-num">49%</div>
      <div class="f-track"><div class="f-fill" style="width: 100%"></div></div>
      <div class="f-lbl">Fuentes. Score, puesto y recíproco de cada modelo, más el RRF.</div>
    </div>
    <div class="f-row">
      <div class="f-num">19%</div>
      <div class="f-track"><div class="f-fill" style="width: 39%"></div></div>
      <div class="f-lbl">Año. Lanzamiento, edad del perfume y distancia al año que esa persona suele reseñar.</div>
    </div>
    <div class="f-row">
      <div class="f-num">12%</div>
      <div class="f-track"><div class="f-fill" style="width: 25%"></div></div>
      <div class="f-lbl">Secuencia. Transición de marca, familia y perfume en las últimas cinco.</div>
    </div>
    <div class="f-row">
      <div class="f-num">9%</div>
      <div class="f-track"><div class="f-fill" style="width: 18%"></div></div>
      <div class="f-lbl">Marca. Afinidad, repetición y días desde la última de esa marca.</div>
    </div>
    <div class="f-row">
      <div class="f-num">5%</div>
      <div class="f-track"><div class="f-fill" style="width: 10%"></div></div>
      <div class="f-lbl">Usuario. Media y dispersión de su nota, y el ritmo entre reviews.</div>
    </div>
    <div class="f-row">
      <div class="f-num">4%</div>
      <div class="f-track"><div class="f-fill" style="width: 8%"></div></div>
      <div class="f-lbl">Perfume. Cuántos lo reseñaron, la nota media y la popularidad frente a ese usuario.</div>
    </div>
    <div class="f-row">
      <div class="f-num">2%</div>
      <div class="f-track"><div class="f-fill" style="width: 5%"></div></div>
      <div class="f-lbl">Familia. Afinidad a la familia olfativa, en todo el historial y en lo reciente.</div>
    </div>
  </div>
</div>

<!--
La importancia es la ganancia de LightGBM en la corrida 20261113-130113. Casi la mitad cae en las fuentes. Después el año del perfume, las transiciones y la marca. Usuario, estadísticas del perfume y familia pesan menos. Género y edad del usuario quedan en cero porque el perfil no los trae.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Two-stage · holdout · 2.473 usuarios · 13 nov</p>
  <h1 class="title sm">Métricas</h1>
  <div class="gap hold">
    <div>
      <div class="gap-num">0.104</div>
      <b>NDCG@10</b>
    </div>
    <div>
      <div class="gap-num">0.027</div>
      <b>NDCG@10 de popularidad</b>
    </div>
    <div>
      <div class="gap-num">0.46</div>
      <b>Recall</b>
    </div>
    <div>
      <div class="gap-num">0.59</div>
      <b>Oracle NDCG@10</b>
    </div>
  </div>
</div>

<!--
Corrida 20261113-130113. NDCG@10 0.104, baseline de popularidad 0.027, recall del retrieval 0.46, oracle NDCG@10 0.59. Lista de 146 candidatos.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">App · Para vos</p>
  <h1 class="title sm">Cada pedido recorre el modelo</h1>
  <div class="circuit">
    <div class="circuit-in">
      <article>
        <b>Conocido</b>
        <span>Historial del dataset. Se ocultan sus reviews y su wardrobe.</span>
      </article>
      <article>
        <b>Nuevo</b>
        <span>Encuesta de marca, género del perfume, perfumista y familia. Con eso se filtran las tres listas del catálogo. Para vos, sin historial, arranca por popularidad.</span>
      </article>
    </div>
    <div class="circuit-arrow">→</div>
    <article class="circuit-model">
      <b>Two-stage</b>
      <span>Siete fuentes, RRF y LGBMRanker. Sobre el historial de ese pedido.</span>
    </article>
    <div class="circuit-arrow">→</div>
    <article class="circuit-out">
      <b>20</b>
      <span>Para vos</span>
    </article>
  </div>
  <div class="circuit-loop">
    <b>Puntúa</b>
    <span>La nota entra al historial, esa card sale, y el mismo circuito se arma de nuevo. No reentrena.</span>
  </div>
  <div class="circuit-side">
    <b>Al lado</b>
    <span>Más populares, mejor puntuados y tendencia, con nota media de al menos 3, acotadas por la encuesta.</span>
  </div>
</div>

<!--
Para vos corre el two-stage en cada pedido. Si la persona está en el dataset, el historial son sus reviews y se ocultan reviews y wardrobe. Si es nueva, primero responde la encuesta de marca, género del perfume, perfumista y familia. Esa encuesta deja, en las tres listas del catálogo, solo los perfumes que coinciden con lo que eligió. Para vos no tiene historial, así que esa lista arranca por popularidad del modelo. Un puntaje de la sesión se suma a ese historial y se vuelve a pedir el ranking, sin reentrenar.
-->
