---
theme: default
layout: none
title: Fragrantica
info: |
  Un recomendador de fragancias.
  Sistemas de recomendación - FCEN UBA
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
      <p class="kicker">Sistemas de recomendación - FCEN UBA</p>
      <h1 class="cover-title">Fragrantica</h1>
      <p class="cover-lead">Un recomendador de fragancias</p>
      <div class="path">
        <span>Scraping</span>
        <span>Recomendador</span>
        <span>App</span>
      </div>
    </div>
    <Scent kind="bottle" spray class="cover-bottle" />
  </div>
</div>

<!--
El recorrido es el del proyecto: cómo se armó el dataset, qué se fue probando en el modelo y cómo queda la app. For you ordena con el two-stage. Las otras tres listas siguen por votos, nota y tendencia.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Objetivo</p>
  <h1 class="title sm">Recomendar fragancias</h1>
  <div class="points">
    <div class="point">
      <div class="point-k">Qué se recomienda</div>
      <div class="point-num">10 items</div>
      <div class="slots" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <div class="rank-scale"><span>diez fragancias</span></div>
      <p>Para cada usuario, diez fragancias que todavía no reseñó, de la nota estimada más alta a la más baja.</p>
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
      <p>Puntúa el puesto de cada item dentro del top 10.</p>
    </div>
  </div>
  <div class="split">
    <div class="point-k">Split del dataset</div>
    <div class="sharebar">
      <div class="sh-train"><b>63%</b><span>Train</span></div>
      <div class="sh-val"><b>18%</b><span>Validación</span></div>
      <div class="sh-hold"><b>18%</b><span>Holdout</span></div>
    </div>
    <div class="shareuse">
      <p>Ajusta el retrieval y el LGBMRanker. Dos folds de 10 interacciones enseñan a predecir el bloque siguiente.</p>
      <p>Las 10 interacciones anteriores al holdout. </p>
      <p>Las últimas 10 interacciones.</p>
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
  <h1 class="title sm">Tres etapas</h1>
  <div class="pieces">
    <div class="piece">
      <div class="piece-n">01</div>
      <h2>Scraper</h2>
      <p>Sobre el sitio de Fragrantica y guarda los items, usuarios e interacciones en parquet.</p>
    </div>
    <div class="piece">
      <div class="piece-n">02</div>
      <h2>Modelo</h2>
      <p>Dos etapas: El retrieval junta siete fuentes con RRF y luego LGBMRanker reordena esa lista.</p>
    </div>
    <div class="piece">
      <div class="piece-n">03</div>
      <h2>App</h2>
      <p>La seccion For You recomienda items con los modelos entrenados. Además se ofrecen otras listas según popularidad y tendencia.</p>
    </div>
  </div>
</div>

<!--
Son tres programas. El scraper escribe el dataset, el recomendador entrena y mide, y la app sirve ese ranking en For you. Más populares, mejor puntuados y tendencia siguen siendo reglas del catálogo.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Scraping</p>
  <h1 class="title sm">De la marca al dataset</h1>
  <div class="step-list">
    <div class="step"><em>01</em><div class="step-n">121</div><div><b>Marcas</b><span>A partir del índice de diseñadores se obtiene la lista de fragancias.</span></div></div>
    <div class="step"><em>02</em><div class="step-n">20.744</div><div><b>Fragancias</b><span>Se obtiene la ficha con notas, acordes y las reviews visibles (hasta 200).</span></div></div>
    <div class="step"><em>03</em><div class="step-n">75.077</div><div><b>Usuarios</b><span>Se obtienen las reviews de cada perfil. Quedaron 68.010 en la cola.</span></div></div>
    <div class="step"><em>04</em><div class="step-n">93.316</div><div><b>Huérfanos</b><span>Items citados en una review o en el wardrobe, sin ficha descargada.</span></div></div>
    <div class="step"><em>05</em><div class="step-n">5</div><div><b>k-core</b><span>El corte elegido es de al menos cinco reviews.</span></div></div>
  </div>
</div>

<!--
121 marcas y 20.744 fichas de fragancia, todas salidas del listado de marcas. Perfiles: 75.077 bajados y 68.010 todavía pendientes. Los 93.316 salen del export del 11 de octubre: fragancia_id distintos que aparecen en una review ya deduplicada o en el wardrobe y no tienen fila en items. No se bajó ninguna de esas fichas. El k-core es 5, elegido al exportar, y se itera hasta punto fijo. El sitio respondía 429 con seis workers cerca de los 150 pedidos, así que el crawl fue un worker con 7–10 segundos, y después un proxy de puertos sticky.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title sm">Limpieza y filtros de registros</h1>
  <div class="fall">
    <div class="fall-head">
      <div><b>5.96M</b><em></em><span>Interacciones descargadas.</span></div>
      <div><b>2.29M</b><em></em><span>Una por usuario y fragancia.</span></div>
      <div><b>611k</b><em>0.10%</em><span>Reviews con fecha y nota.</span></div>
      <div class="is-final"><b>134k</b><em>4.98%</em><span>Matriz final. 2.473 × 1.088.</span></div>
    </div>
    <div class="fall-plot">
      <div class="fall-col"><i class="keep" style="height: 100%"></i></div>
      <div class="fall-col">
        <i class="drop" style="height: 61.6%; bottom: 38.4%"></i>
        <i class="keep" style="height: 38.4%"></i>
      </div>
      <div class="fall-col">
        <i class="drop" style="height: 28.2%; bottom: 10.3%"></i>
        <i class="keep" style="height: 10.3%"></i>
      </div>
      <div class="fall-col is-final">
        <i class="drop" style="height: 8%; bottom: 2.2%"></i>
        <i class="keep" style="height: 2.2%"></i>
      </div>
      <span class="fall-bridge b1"></span>
      <span class="fall-bridge b2"></span>
      <span class="fall-bridge b3"></span>
      <span class="fall-delta d1">−3.67M</span>
      <span class="fall-delta d2">−1.68M</span>
      <span class="fall-delta d3">−477k</span>
    </div>
  </div>
</div>

<!--
Las crudas son 5.96 millones. Queda una interacción por usuario y fragancia, 2.29 millones. De ahí, 611 mil tienen fecha y nota: esa matriz está al 0.10%. El corte de 28 reviews por usuario y 60 por fragancia se itera hasta un punto fijo y deja 134 mil reviews, 2.473 por 1.088, con densidad 4.98%.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title sm">El esquema de datos</h1>
  <div class="er">
    <article class="ent user">
      <h2>Usuario</h2>
      <p>Del perfil: reviews, notas y cuántos guardó.</p>
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
    <div class="rel next">
      <b>N</b>
      <div class="rel-line"><span>sobre</span></div>
      <b>1</b>
    </div>
    <article class="ent fragancia">
      <h2>Fragancia</h2>
      <p>Marca, género, año y familia.</p>
      <p>Perfumista, notas, acordes, descripción.</p>
    </article>
    <div class="stem-user">1 a N</div>
    <article class="ent ward">
      <h2>Wardrobe</h2>
      <p>Tiene, quiere o tuvo. Sin fecha, así que no entrena.</p>
    </article>
  </div>
</div>

<!--
Del perfil se bajaron cuántas reviews, cuántas notas y cuántos fragancias guardó. Un usuario reseña N interacciones, y cada una es sobre un fragancia. El wardrobe sale del mismo perfil: tiene, quiere o tuvo, sin fecha, y no entra a entrenar.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Bitácora</p>
  <h1 class="title sm">Experimentos realizados</h1>
  <div class="log">
    <div class="log-item"><em>01</em><div><b>Popularidad</b><span>Una lista común para todos los usuarios, con recencia, para tener de baseline.</span></div></div>
    <div class="log-item"><em>02</em><div><b>Fuentes individuales</b><span>Se experimento con ALS, ítem-kNN, EASE y un two-tower, cada uno con su grilla de hiperparámetros.</span></div></div>
    <div class="log-item"><em>03</em><div><b>Contenido</b><span>El two-tower se probó también solo con ids de items, para ver si las notas y acordes de los items aportaban.</span></div></div>
    <div class="log-item"><em>04</em><div><b>Two-stage</b><span>Las distintas fuentes se fusionan con RRF y LGBMRanker.</span></div></div>
  </div>
</div>

<!--
Primero el piso de popularidad, después cada fuente por separado, después la torre sin el texto del fragancia, y al final la fusión. El tuneo no mira el holdout: ese queda para la medición final.
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
        <article>
          <b>Popularidad</b>
          <span>Lista única ordenada por cantidad de reseñas.</span>
          <div class="src-tags"><em>global</em></div>
        </article>
        <article>
          <b>Coseno</b>
          <span>Coseno ítem&#8288;–&#8288;ítem: items que los reseñaron las mismas personas incluyendo nota y recencia.</span>
          <div class="src-tags"><em>colaborativo</em><em class="side">ítem–ítem</em></div>
        </article>
        <article>
          <b>ALS</b>
          <span>Factores latentes de usuario e ítem; el ranking es su producto, con confianza de nota y recencia.</span>
          <div class="src-tags"><em>colaborativo</em><em class="side">usuario–ítem</em><em class="rep">factores</em></div>
        </article>
        <article>
          <b>BPR</b>
          <span>Factores latentes de usuario e ítem entrenados por pares para poner lo reseñado arriba de lo no observado.</span>
          <div class="src-tags"><em>colaborativo</em><em class="side">usuario–ítem</em><em class="rep">factores</em></div>
        </article>
        <article>
          <b>TF-IDF</b>
          <span>Coseno entre el texto del historial y el item candidato: notas, acordes, marca y descripción.</span>
          <div class="src-tags"><em>contenido</em></div>
        </article>
        <article>
          <b>Two-tower</b>
          <span>Producto de dos redes: el historial promediado, y el ítem con id, marca y familia olfativa.</span>
          <div class="src-tags"><em>colaborativo</em><em class="side">usuario–ítem</em><em class="rep">embeddings</em></div>
        </article>
        <article>
          <b>EASE</b>
          <span>Peso lineal de cada fragancia sobre las demás, ajustado por mínimos cuadrados sobre la nota.</span>
          <div class="src-tags"><em>colaborativo</em><em class="side">ítem–ítem</em></div>
        </article>
      </div>
      <div class="to-rrf" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <div class="rrf-bar">
        <b>RRF (Reciprocal Rank Fusion)</b>
        <span>Las siete listas se mergean en un unico ranking: suma de puestos, con el peso de cada fuente. Se seleccionan 255 candidatos.</span>
      </div>
    </section>
    <div class="stage-arrow">→</div>
    <section class="stage stage-rank">
      <p class="stage-k">Ranker</p>
      <div>
        <b>LGBMRanker</b>
        <span>El ranker de LightGBM reordena los candidatos. Entrena con objetivo lambdarank: cada par pesa según cuánto movería el NDCG.</span>
      </div>
    </section>
  </div>
</div>

<!--
Son dos etapas. El retrieval son las siete fuentes: popularidad, coseno, ALS, BPR, TF-IDF, two-tower y EASE. RRF junta puestos, no scores, y se queda con 255. El modelo que reordena ese prefijo es LGBMRanker, de LightGBM. Lambdarank es el objetivo de entrenamiento, no el nombre del modelo. Una review que ninguna fuente trajo baja el NDCG igual.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Optuna · Fold de validación</p>
  <h1 class="title sm">Hiperparámetros ajustados</h1>
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
    </article>
    <article>
      <b>EASE</b>
      <span><em>1.12×10⁴</em> reg_lambda</span>
      <span><em>24</em> min_interactions</span>
    </article>
    <article>
      <b>Popularidad</b>
      <span>Sin hiperparametros.</span>
    </article>
    <article>
      <b>RRF</b>
      <span><em>255</em> rrf_cutoff</span>
      <span>source_weight por fuente</span>
    </article>
  </div>
  <div class="tune-rank">
    <b>LGBMRanker</b>
    <span><em>0.0172</em>learning_rate</span>
    <span><em>21</em>num_leaves</span>
    <span><em>10</em>max_depth</span>
    <span><em>58</em>min_child_samples</span>
    <span><em>0.769</em>subsample</span>
    <span><em>0.756</em>colsample_bytree</span>
  </div>
  <p class="src-foot">Cada source se ajustó en un study individual. Optuna selecciona el corte del RRF, los pesos de cada source y el ranker sobre el último fold.</p>
</div>

<!--
Cada fuente tiene su estudio. Coseno: half_life_days 812. ALS: factors 21, iterations 36, regularization 3.53, half_life_days 555. BPR: factors 63, iterations 59, learning_rate 0.0135, regularization 1.91e-4, half_life_days 63.7. TF-IDF: max_features 19931, half_life_days 128. Two-tower: embedding_dim 79, learning_rate 0.00243, temperature 0.122, min_item_reads 16: solo entran al vocabulario los fragancias con al menos 16 interacciones. EASE: reg_lambda 11154, min_interactions 24: la matriz ítem-ítem descarta los ítems con menos de 24 interacciones. Popularidad no se busca. Optuna del two-stage elige rrf_cutoff 255, un source_weight por fuente y el LGBMRanker: learning_rate 0.0172, num_leaves 21, max_depth 10, min_child_samples 58, subsample 0.769, colsample_bytree 0.756. reg_alpha y reg_lambda quedaron cerca de cero. El objetivo es lambdarank. El holdout no interviene.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">NDCG@10</p>
  <h1 class="title sm">Cada fuente sola y las siete juntas</h1>
  <div class="src-board">
    <div class="src-row">
      <b>EASE</b>
      <div class="src-bar"><i style="width: 80%"></i></div>
      <em>0.082</em>
    </div>
    <div class="src-row">
      <b>ALS</b>
      <div class="src-bar"><i style="width: 77%"></i></div>
      <em>0.079</em>
    </div>
    <div class="src-row">
      <b>Two-tower</b>
      <div class="src-bar"><i style="width: 76%"></i></div>
      <em>0.078</em>
    </div>
    <div class="src-row">
      <b>Coseno</b>
      <div class="src-bar"><i style="width: 71%"></i></div>
      <em>0.072</em>
    </div>
    <div class="src-row">
      <b>BPR</b>
      <div class="src-bar"><i style="width: 56%"></i></div>
      <em>0.057</em>
    </div>
    <div class="src-row">
      <b>TF-IDF</b>
      <div class="src-bar"><i style="width: 50%"></i></div>
      <em>0.051</em>
    </div>
    <div class="src-row">
      <b>Popularidad</b>
      <div class="src-bar"><i style="width: 26%"></i></div>
      <em>0.027</em>
    </div>
    <div class="src-row best">
      <b>Two-stage</b>
      <div class="src-bar"><i style="width: 100%"></i></div>
      <em>0.102</em>
    </div>
  </div>
</div>

<!--
Mismas 2.473 personas. Solas: EASE 0.082, ALS 0.079, two-tower 0.078, coseno 0.072, BPR 0.057, TF-IDF 0.051, popularidad 0.027. Las siete juntas, two-stage, llegan a 0.102.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">RRF</p>
  <h1 class="title sm">Peso de cada fuente</h1>
  <div class="src-board weights">
    <div class="src-row">
      <b>TF-IDF</b>
      <div class="src-bar"><i style="width: 100%"></i></div>
      <em>0.256</em>
    </div>
    <div class="src-row">
      <b>Coseno</b>
      <div class="src-bar"><i style="width: 91%"></i></div>
      <em>0.232</em>
    </div>
    <div class="src-row">
      <b>Popularidad</b>
      <div class="src-bar"><i style="width: 84%"></i></div>
      <em>0.215</em>
    </div>
    <div class="src-row">
      <b>ALS</b>
      <div class="src-bar"><i style="width: 53%"></i></div>
      <em>0.136</em>
    </div>
    <div class="src-row">
      <b>EASE</b>
      <div class="src-bar"><i style="width: 36%"></i></div>
      <em>0.092</em>
    </div>
    <div class="src-row">
      <b>BPR</b>
      <div class="src-bar"><i style="width: 14%"></i></div>
      <em>0.037</em>
    </div>
    <div class="src-row">
      <b>Two-tower</b>
      <div class="src-bar"><i style="width: 13%"></i></div>
      <em>0.032</em>
    </div>
  </div>
</div>

<!--
Pesos del RRF ya normalizados: TF-IDF 0.256, coseno 0.232, popularidad 0.215, ALS 0.136, EASE 0.092, BPR 0.037, two-tower 0.032.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Ranker LightGBM</p>
  <h1 class="title sm">Feature Importance</h1>
  <div class="funnel">
    <div class="f-row">
      <div class="f-num">58%</div>
      <div class="f-track"><div class="f-fill" style="width: 100%"></div></div>
      <div class="f-lbl">Fuentes. Score y posicion de cada modelo y del RRF.</div>
    </div>
    <div class="f-row">
      <div class="f-num">21%</div>
      <div class="f-track"><div class="f-fill" style="width: 36%"></div></div>
      <div class="f-lbl">Año. Lanzamiento, antiguedad de la fragancia y distancia respecto al año que esa persona suele reseñar.</div>
    </div>
    <div class="f-row">
      <div class="f-num">7%</div>
      <div class="f-track"><div class="f-fill" style="width: 12%"></div></div>
      <div class="f-lbl">Secuencia. Transición de marca, familia y fragancia en las últimas cinco interacciones.</div>
    </div>
    <div class="f-row">
      <div class="f-num">6%</div>
      <div class="f-track"><div class="f-fill" style="width: 10%"></div></div>
      <div class="f-lbl">Marca. Afinidad, repetición y días desde la última interaccion con esa marca.</div>
    </div>
    <div class="f-row">
      <div class="f-num">3%</div>
      <div class="f-track"><div class="f-fill" style="width: 5%"></div></div>
      <div class="f-lbl">Usuario. Media y dispersión de su nota, y el ritmo entre reviews.</div>
    </div>
    <div class="f-row">
      <div class="f-num">3%</div>
      <div class="f-track"><div class="f-fill" style="width: 5%"></div></div>
      <div class="f-lbl">Fragancia. Cuántos la reseñaron, la nota media y la popularidad frente a ese usuario.</div>
    </div>
    <div class="f-row">
      <div class="f-num">2%</div>
      <div class="f-track"><div class="f-fill" style="width: 3%"></div></div>
      <div class="f-lbl">Familia. Afinidad a la familia olfativa, en todo el historial y en lo reciente.</div>
    </div>
  </div>
</div>

<!--
La importancia es la ganancia de LightGBM en la corrida 20261113-153541. El 58% cae en las fuentes. Después el año del fragancia, las transiciones y la marca. Usuario, estadísticas del fragancia y familia pesan menos. Género y edad del usuario quedan en cero porque el perfil no los trae.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Two-stage · holdout</p>
  <h1 class="title sm">Métricas</h1>
  <div class="gap hold">
    <div>
      <div class="gap-num">0.102</div>
      <b>NDCG@10 Two Stage</b>
    </div>
    <div>
      <div class="gap-num">0.027</div>
      <b>NDCG@10 de popularidad</b>
    </div>
    <div>
      <div class="gap-num">0.67</div>
      <b>Recall</b>
    </div>
    <div>
      <div class="gap-num">0.77</div>
      <b>Oracle NDCG@10</b>
    </div>
  </div>
</div>

<!--
Corrida 20261113-153541. NDCG@10 0.102, baseline de popularidad 0.027, recall del retrieval 0.67, oracle NDCG@10 0.77. Lista de 255 candidatos.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">App</p>
  <h1 class="title tight">El recorrido en la web</h1>
  <WebFlow />
</div>

<!--
Entra con el nombre. Conocido: For you corre two-stage con sus reviews, y esas fragancias y las del wardrobe no se vuelven a listar. Las otras tres pestañas son el catálogo, sin la encuesta. Nuevo: la encuesta es opcional. Si marca fragancias, entran como nota 5 y For you usa two-stage. Si no marca ninguna, For you se arma con popularidad. En los dos casos es inferencia con el modelo. Si elige marcas o para quién, Más populares, Tendencia y Mejor puntuados muestran solo ese recorte. Si no elige, el catálogo entero. Después una nota de la sesión entra al historial, esa tarjeta sale y For you se pide de nuevo, sin reentrenar.
-->
