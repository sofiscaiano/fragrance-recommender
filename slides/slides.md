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
    <Scent kind="bottle" class="cover-bottle" />
  </div>
</div>

<!--
El recorrido es el del proyecto: cómo se armó el dataset, qué se fue probando en el modelo y cómo queda la app, que hoy ordena el catálogo y va a usar el modelo cuando esté cerrado.
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
      <p>Ajusta las fuentes y LambdaRank. Dos ventanas de 10 enseñan a predecir el bloque siguiente.</p>
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
      <p>Arma un ranking con varias fuentes y lo elige por NDCG en el holdout.</p>
    </div>
    <div class="piece piece-next">
      <div class="piece-n">03</div>
      <h2>App</h2>
      <p>Hoy ordena el catálogo con reglas. Cuando el modelo esté cerrado, las listas salen de ahí.</p>
    </div>
  </div>
</div>

<!--
Son tres programas. El scraper escribe el dataset, el recomendador entrena y mide, y la app todavía ordena por votos, nota y tendencia. El destino de la pantalla es servir el ranking del modelo.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Scraping</p>
  <h1 class="title sm">De la marca al dataset</h1>
  <div class="step-list">
    <div class="step"><em>01</em><b>Marcas</b><span>Recorre los diseñadores y arma la lista de perfumes a bajar.</span></div>
    <div class="step"><em>02</em><b>Perfumes</b><span>De cada ficha saca notas, acordes y las reviews visibles, con un tope que ronda las 200.</span></div>
    <div class="step"><em>03</em><b>Perfiles</b><span>Entra a quien escribió y baja el historial completo, el wardrobe y los votos.</span></div>
    <div class="step"><em>04</em><b>Huérfanos</b><span>Si un perfil nombra un perfume que no estaba en la lista, se baja esa ficha.</span></div>
    <div class="step"><em>05</em><b>k-core</b><span>En local se deduplica y quedan usuario y perfume con al menos 5 interacciones.</span></div>
  </div>
  <p class="facts">El sitio era muy restrictivo: con seis workers devolvía 429 alrededor de los 150 pedidos, así que el crawl quedó en un solo worker con 7–10 segundos entre requests. Después se sumó un proxy de puertos sticky, para seguir por otra salida cuando una IP se quemaba y no tener que frenar en ese bloqueo.</p>
</div>

<!--
El límite se midió: seis workers disparan un 429 cerca de los 150 requests, y por eso la espera de 7 a 10 segundos. El proxy no saca esa espera de un pedido, pero deja continuar por otro puerto cuando la IP se quema. El k-core no vuelve a la red: se aplica al exportar.
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
  <h1 class="title sm">Usuario, perfume e interacción</h1>
  <div class="sides">
    <section>
      <h2>Usuario</h2>
      <div class="side-rows">
        <div class="side-row"><div><b>Su actividad</b><span>Cuántas reviews escribió y cuántas notas tiene en el perfil.</span></div></div>
        <div class="side-row"><div><b>Perfume firma</b><span>El que eligió como propio.</span></div></div>
        <div class="side-row"><div><b>Su wardrobe</b><span>Cuántos perfumes guardó. El número está en el perfil.</span></div></div>
      </div>
    </section>
    <section>
      <h2>Perfume</h2>
      <div class="side-rows">
        <div class="side-row"><div><b>La ficha</b><span>Marca, género del perfume, año y familia olfativa.</span></div></div>
        <div class="side-row"><div><b>Quién lo hizo</b><span>El perfumista.</span></div></div>
        <div class="side-row"><div><b>La composición</b><span>Notas, acordes y la descripción.</span></div></div>
      </div>
    </section>
    <section>
      <h2>Interacción</h2>
      <div class="side-rows">
        <div class="side-row"><div><b>La review</b><span>Nota, fecha y texto de ese perfume.</span></div></div>
        <div class="side-row"><div><b>El voto</b><span>Duración, estela, estación y si es de día o de noche.</span></div></div>
      </div>
    </section>
  </div>
  <p class="side-note">La lista del wardrobe, tiene, quiere o tuvo, es otra tabla. No tiene fecha, así que no entra a entrenar. La app la usa para ocultar lo que la persona ya tiene.</p>
</div>

<!--
El perfil del usuario trae conteos de reviews y de notas, el perfume firma y el tamaño del wardrobe. El perfume trae ficha, perfumista y composición. La interacción es la review y el voto. La lista del wardrobe es otra tabla, sin fecha, y no entra a entrenar.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Modelo</p>
  <h1 class="title sm">Siete rankings se funden en uno</h1>
  <div class="sources">
    <div><b>Popularidad</b><span>Lo que todos reseñan</span></div>
    <div><b>Coseno</b><span>Parecido a lo ya puntuado</span></div>
    <div><b>ALS</b><span>Factores latentes</span></div>
    <div><b>BPR</b><span>Visto contra no visto</span></div>
    <div><b>TF-IDF</b><span>Texto de notas y acordes</span></div>
    <div><b>Two-tower</b><span>Próximas interacciones</span></div>
    <div><b>EASE</b><span>Pesos ítem a ítem</span></div>
  </div>
  <div class="merge">
    <div class="merge-box">
      <b>RRF</b>
      <span>Cada fuente aporta su puesto, no su score, y la suma deja un prefijo de candidatos.</span>
    </div>
    <div class="arrow">→</div>
    <div class="merge-box main">
      <b>LambdaRank</b>
      <span>Es el LGBMRanker de LightGBM. LambdaRank pondera cada par por cuánto cambiaría el NDCG si se invirtieran.</span>
    </div>
  </div>
  <p class="origin">Una review futura que ninguna fuente trajo igual baja el NDCG.</p>
</div>

<!--
RRF mira el puesto para que una escala no pise a las otras. LambdaRank es LightGBM en modo ranking: el gradiente de cada par depende de cuánto subiría o bajaría el NDCG al invertirlos, y solo reordena el prefijo. Un positivo que el retrieval no trajo penaliza igual.
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
    <div class="log-item"><em>04</em><div><b>Two-stage</b><span>Esas fuentes se fusionan con RRF y LightGBM LambdaRank. Optuna elige sobre el último fold, no sobre el holdout.</span></div></div>
  </div>
</div>

<!--
Primero el piso de popularidad, después cada fuente por separado, después la torre sin el texto del perfume, y al final la fusión. El tuneo no mira el holdout: ese queda para la medición final.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">NDCG@10 · 2.473 usuarios · 13 nov · pesos del RRF a las 13:01</p>
  <h1 class="title sm">Cada fuente sola, y el peso que quedó</h1>
  <div class="src-board">
    <div class="src-head"><span></span><span>Sola</span><span>Peso en el RRF</span></div>
    <div class="src-row">
      <b>EASE</b>
      <div class="src-bar"><i style="width: 100%"></i></div>
      <em>0.082</em>
      <div class="src-bar w"><i style="width: 30%"></i></div>
      <em>0.101</em>
    </div>
    <div class="src-row">
      <b>ALS</b>
      <div class="src-bar"><i style="width: 96%"></i></div>
      <em>0.079</em>
      <div class="src-bar w"><i style="width: 36%"></i></div>
      <em>0.121</em>
    </div>
    <div class="src-row">
      <b>Coseno</b>
      <div class="src-bar"><i style="width: 88%"></i></div>
      <em>0.072</em>
      <div class="src-bar w"><i style="width: 18%"></i></div>
      <em>0.059</em>
    </div>
    <div class="src-row">
      <b>BPR</b>
      <div class="src-bar"><i style="width: 70%"></i></div>
      <em>0.057</em>
      <div class="src-bar w"><i style="width: 12%"></i></div>
      <em>0.039</em>
    </div>
    <div class="src-row">
      <b>TF-IDF</b>
      <div class="src-bar"><i style="width: 62%"></i></div>
      <em>0.051</em>
      <div class="src-bar w"><i style="width: 97%"></i></div>
      <em>0.324</em>
    </div>
    <div class="src-row">
      <b>Popularidad</b>
      <div class="src-bar"><i style="width: 33%"></i></div>
      <em>0.027</em>
      <div class="src-bar w"><i style="width: 100%"></i></div>
      <em>0.334</em>
    </div>
    <div class="src-row">
      <b>Two-tower</b>
      <div class="src-bar"></div>
      <em class="missing">—</em>
      <div class="src-bar w"><i style="width: 6%"></i></div>
      <em>0.021</em>
    </div>
  </div>
  <p class="src-foot">Los pesos suman 1 y salen del tuneo de las 13:01. Juntas y reordenadas, el two-stage llega a 0.104. El two-tower no se midió solo ese día.</p>
</div>

<!--
Holdout del 13 de noviembre, mismas 2.473 personas. Solas: EASE 0.082, ALS 0.079, coseno 0.072, BPR 0.057, TF-IDF 0.051, popularidad 0.027. El two-tower no tiene medición sola de ese día. Los pesos del RRF, normalizados, son popularidad 0.334, TF-IDF 0.324, ALS 0.121, EASE 0.101, coseno 0.059, BPR 0.039 y two-tower 0.021. El two-stage llega a 0.104.
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
  <p class="kicker">Dónde se corta</p>
  <h1 class="title sm">La lista es más corta, y el orden sigue corto.</h1>
  <div class="gap">
    <div>
      <div class="gap-num">0.46</div>
      <b>Recall del retrieval</b>
      <span>Mira 146 de 1.088 perfumes y trae esa fracción de las próximas reviews.</span>
    </div>
    <div>
      <div class="gap-num">0.104</div>
      <b>NDCG@10 real</b>
      <span>El top 10 del two-stage. Traer la review no la deja primera.</span>
    </div>
    <div class="win">
      <div class="gap-num">0.59</div>
      <b>Si el orden fuera perfecto</b>
      <span>El NDCG de esas mismas reviews si LambdaRank las hubiera puesto arriba.</span>
    </div>
  </div>
  <div class="dead">
    <div><b>0.068</b><span>Two-tower solo con ids. Cubre el 32%. Con el contenido del perfume llega a 0.077 y cubre el 56%.</span></div>
    <div><b>0.030</b><span>Two-tower con learning rate 0.0001. Cae al nivel de la popularidad.</span></div>
  </div>
</div>

<!--
En la corrida de las 13:01 el retrieval mira 146 de 1.088 perfumes y el recall queda en 0.46. Si el ranker pusiera primeras las que sí trajo, el NDCG sería 0.59 y queda en 0.104. La torre sin contenido, de una corrida anterior, baja a 0.068, y un learning rate de 0.0001 la deja en 0.030.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">App</p>
  <h1 class="title sm">Hoy son reglas. Después, el modelo.</h1>
  <div class="grid-2">
    <div class="cell">
      <div class="cell-k">Conocido</div>
      <div class="lbl">Oculta lo que ya tiene</div>
      <div class="sub">Si el usuario está en el dataset, se esconden sus reviews y su wardrobe. La encuesta no se usa.</div>
    </div>
    <div class="cell">
      <div class="cell-k">Nuevo</div>
      <div class="lbl">Encuesta</div>
      <div class="sub">Si no está, filtra por marca, género del perfume, perfumista y familia olfativa.</div>
    </div>
  </div>
  <div class="lists">
    <div class="list-card"><b>Más populares</b><span>Más votos de la comunidad</span></div>
    <div class="list-card"><b>Mejor puntuados</b><span>Nota alta, entre los que tienen bastantes votos</span></div>
    <div class="list-card"><b>Tendencia</b><span>Más interacciones fechadas en 365 días</span></div>
  </div>
  <p class="app-note">De a 20, solo con nota media de al menos 3. Puntuar una card la saca de la sesión y no reentrena. Estas tres listas van a salir del modelo cuando esté cerrado.</p>
</div>

<!--
Usuario conocido: se oculta lo que ya tiene. Usuario nuevo: se filtra por lo que eligió. Las tres pestañas son reglas sobre el catálogo. Cuando el two-stage esté cerrado, la misma pantalla ordena con ese ranking.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Cierre</p>
  <h1 class="title sm">El ranking sube.<br>El top 10, todavía no.</h1>
  <div class="close close-2">
    <div>
      <div class="num hero">0.104</div>
      <div class="lbl">NDCG@10, desde 0.027 de popularidad y arriba de 0.082 de la mejor fuente sola.</div>
    </div>
    <div>
      <div class="num close-open">Sigue</div>
      <div class="lbl">Cerrar el modelo y servirlo en la app.</div>
    </div>
  </div>
</div>

<!--
Se pasó de 0.027 a 0.104, por encima de EASE. El retrieval de esta corrida mira 146 perfumes y el orden del top 10 sigue siendo el hueco. Lo que sigue es conectar ese ranking a la app.
-->
