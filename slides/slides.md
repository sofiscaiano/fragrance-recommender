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
  <p class="kicker">Sistemas de recomendación</p>
  <h1 class="cover-title">Fragrantica</h1>
  <p class="cover-lead">Un recomendador de perfumes</p>
  <div class="path">
    <span>Scraping</span>
    <span>Modelo</span>
    <span>App</span>
  </div>
</div>

<!--
El recorrido es el del proyecto: cómo se armó el dataset, qué modelo se probó —primero en libros, después en perfumes— y qué hace la app. Quince minutos. Los números salen de los commits de los dos repos y de MLflow.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">La tarea</p>
  <h1 class="title">Las próximas reviews,<br>ordenadas por la nota</h1>
  <div class="metrics">
    <div class="metric">
      <div class="num">NDCG@10</div>
      <div class="lbl">métrica</div>
    </div>
    <div class="metric">
      <div class="num">2<sup>nota</sup> − 1</div>
      <div class="lbl">ganancia</div>
    </div>
    <div class="metric">
      <div class="num">10</div>
      <div class="lbl">últimas reviews</div>
    </div>
  </div>
</div>

<!--
No es predecir la nota con el menor error. Para cada usuario, cuáles van a ser las próximas reviews y en qué orden, con más peso en las notas altas. Un 5 pesa mucho más que un 3. El holdout son las últimas 10 reviews, por fecha. No hay un test sellado aparte: esas diez se miden.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Arquitectura</p>
  <h1 class="title">Tres piezas</h1>
  <div class="pieces">
    <div class="piece">
      <div class="piece-n">01</div>
      <h2>Scraper</h2>
      <p>Fragrantica → parquet</p>
    </div>
    <div class="piece">
      <div class="piece-n">02</div>
      <h2>Modelo</h2>
      <p>Retrieval, fusión, LambdaRank → NDCG</p>
    </div>
    <div class="piece piece-off">
      <div class="piece-n">03</div>
      <h2>App</h2>
      <p>Ordena el catálogo. No usa el modelo.</p>
    </div>
  </div>
</div>

<!--
Son tres programas. El scraper escribe parquet. El recomendador entrena y mide NDCG. La app lee el mismo parquet y ordena con reglas: votos, nota, tendencia. El modelo entrenado no entra a la app. Lo digo ahora para que el final no sorprenda.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Scraping</p>
  <h1 class="title">Seis fases, un worker</h1>
  <div class="phases">
    <div class="phase"><b>01</b><span>Marcas</span></div>
    <div class="phase"><b>02</b><span>Perfumes</span></div>
    <div class="phase"><b>03</b><span>Perfiles</span></div>
    <div class="phase"><b>04</b><span>member_id</span></div>
    <div class="phase"><b>05</b><span>Huérfanos</span></div>
    <div class="phase"><b>06</b><span>k-core</span></div>
  </div>
  <div class="facts">
    <div>
      <strong>7–10 s</strong>
      <span>Un worker. El crawl se retoma.</span>
    </div>
    <div>
      <strong>429 a los ~150</strong>
      <span>Seis workers quedaron afuera.</span>
    </div>
    <div>
      <strong>Proxy + Maple</strong>
      <span>Puertos sticky. Fallos y cooldowns.</span>
    </div>
  </div>
</div>

<!--
El crawl tiene seis fases y se puede cortar y seguir. El sitio bloquea: con seis workers apareció un 429 alrededor de los 150 requests. Quedó un solo worker, entre 7 y 10 segundos, y un proxy con puertos sticky: si uno se quema, sigue el siguiente. Maple mira los fallos HTTP y los cooldowns. El k-core de 5 se aplica al exportar, no durante el crawl.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title">Casi todo se va</h1>
  <div class="funnel">
    <div class="f-row">
      <div class="f-num">5.96M</div>
      <div class="f-track"><div class="f-fill" style="width: 100%"></div></div>
      <div class="f-lbl">crudas</div>
    </div>
    <div class="f-row">
      <div class="f-num">2.29M</div>
      <div class="f-track"><div class="f-fill" style="width: 38%"></div></div>
      <div class="f-lbl">k-core · 46k × 15k</div>
    </div>
    <div class="f-row">
      <div class="f-num">611k</div>
      <div class="f-track"><div class="f-fill" style="width: 10%"></div></div>
      <div class="f-lbl">con fecha y nota</div>
    </div>
    <div class="f-row">
      <div class="f-num">134k</div>
      <div class="f-track"><div class="f-fill" style="width: 8%"></div></div>
      <div class="f-lbl">matriz 28/60</div>
    </div>
  </div>
  <div class="punch">
    <div class="num">2.473 × 1.088</div>
    <div class="lbl">−94% de los usuarios con fecha<br>−92% de los perfumes</div>
  </div>
</div>

<!--
Estos cortes no se mezclan. Lo crudo son casi 6 millones de filas. El k-core deja 2.3 millones, 46 mil usuarios y 15 mil perfumes. La mayoría no tiene fecha: son votos. Con fecha y nota quedan 611 mil. El corte del modelo, mínimo 28 reviews por usuario y 60 por perfume, deja 134 mil reviews. 2.473 usuarios y 1.088 perfumes. Se va el 94% de los usuarios que ya tenían fecha.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Datos</p>
  <h1 class="title">Lo que quedó afuera</h1>
  <div class="grid-2">
    <div class="cell">
      <div class="num">1.4M</div>
      <div class="lbl">Votos sin fecha</div>
      <div class="sub">No entran al split</div>
    </div>
    <div class="cell">
      <div class="num">Wardrobe</div>
      <div class="lbl">Have, want, had</div>
      <div class="sub">No se entrena</div>
    </div>
    <div class="cell">
      <div class="num">Vacío</div>
      <div class="lbl">Sin género ni edad</div>
      <div class="sub">Esas columnas quedan vacías</div>
    </div>
    <div class="cell">
      <div class="num">19k / 138k</div>
      <div class="lbl">Perfumes del sitio</div>
      <div class="sub">Perfiles a medias</div>
    </div>
  </div>
</div>

<!--
Los votos son 1.4 millones y no tienen fecha, así que no entran al holdout. El wardrobe —lo que tiene, tuvo o quiere— no se entrena; la app solo lo usa para ocultar. No hay género ni edad del usuario. Y el crawl no es el sitio entero: unos 19 mil perfumes de 138 mil, con los perfiles a medias. Es una muestra sesgada hacia quien escribe reviews.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Modelo</p>
  <h1 class="title">Retrieval, fusión, orden</h1>
  <div class="flow">
    <div class="pills">
      <span>Popularidad</span>
      <span>Coseno</span>
      <span>ALS</span>
      <span>BPR</span>
      <span>TF-IDF</span>
      <span>Two-tower</span>
      <span>EASE</span>
    </div>
    <div class="stages">
      <div class="stage">
        <b>RRF</b>
        <span>Fusión de las siete fuentes</span>
      </div>
      <div class="arrow">→</div>
      <div class="stage main">
        <b>LambdaRank</b>
        <span>Ordena el prefijo</span>
      </div>
    </div>
  </div>
  <p class="origin">Armado en Qué Libro Leo. Portado a perfumes.</p>
</div>

<!--
Siete fuentes proponen candidatos. Reciprocal Rank Fusion las junta. LambdaRank ordena ese prefijo. Un positivo que el retrieval no trajo igual penaliza el NDCG. Esto no nació en perfumes: se construyó para Qué Libro Leo, se midió ahí durante dos meses, y en noviembre se portó.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Bitácora</p>
  <h1 class="title">De agosto a noviembre</h1>
  <div class="tl">
    <div class="tl-col">
      <div class="tl-when">Ago</div>
      <div class="tl-dot"></div>
      <ul>
        <li>Scraper y wardrobe</li>
        <li>Primer ranker de libros</li>
        <li class="em">0.17</li>
      </ul>
    </div>
    <div class="tl-col">
      <div class="tl-when">Sep</div>
      <div class="tl-dot"></div>
      <ul>
        <li>Daemon y Maple</li>
        <li>Two-stage</li>
        <li>MLflow y Optuna</li>
      </ul>
    </div>
    <div class="tl-col">
      <div class="tl-when">Oct</div>
      <div class="tl-dot"></div>
      <ul>
        <li>Proxies</li>
        <li>Salen SVD y el coseno ajustado</li>
        <li>Two-tower de próximas lecturas</li>
        <li class="em">0.17 → 0.19</li>
      </ul>
    </div>
    <div class="tl-col">
      <div class="tl-when">Nov</div>
      <div class="tl-dot"></div>
      <ul>
        <li>EASE como fuente</li>
        <li>Libros 0.211</li>
        <li>Perfumes 0.100</li>
        <li>App sin el modelo</li>
      </ul>
    </div>
  </div>
</div>

<!--
Junta los dos repos: 15 commits acá, 91 en libros. Agosto arranca el scraper y, en libros, un ranker en 0.17 de NDCG@20. Septiembre es el daemon, Maple, y el two-stage con MLflow y Optuna. Octubre se poda: salen SVD y el coseno ajustado, el two-tower deja de predecir la nota y pasa a las próximas lecturas, aparece la UI de libros, y el pipeline sube a 0.19. Noviembre suma EASE. En libros llega a 0.211. En perfumes, hoy, a 0.100. La app ordena el catálogo sin ese modelo.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Libros · NDCG@20</p>
  <h1 class="title">Lo que sí</h1>
  <div class="stats">
    <div class="stat hero">
      <div class="num">0.211</div>
      <div class="lbl">two-stage</div>
    </div>
    <div class="stat">
      <div class="num">0.072</div>
      <div class="lbl">popularidad</div>
    </div>
    <div class="stat">
      <div class="num">0.55</div>
      <div class="lbl">recall</div>
    </div>
    <div class="stat">
      <div class="num">0.136</div>
      <div class="lbl">entrega</div>
    </div>
  </div>
  <p class="aside">Últimas 20 lecturas y autores: la torre pasa de ~0.14 a ~0.15.</p>
</div>

<!--
En libros la popularidad queda en 0.072. El two-stage llega a 0.211, con un recall de retrieval de 0.55. En la entrega, los lectores de ejemplo.csv, baja a 0.136: el holdout completo se ve mejor que el corte que se entrega. Meter las últimas 20 lecturas y los autores en la torre sube el two-tower solo de alrededor de 0.14 a 0.15, y como fuente empuja al pipeline.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Perfumes · NDCG@10 · corte 28/60</p>
  <h1 class="title">Lo que sí</h1>
  <Bars />
  <div class="caption">
    <span>Fuentes sueltas, 11 nov. Two-stage, holdout de hoy.</span>
    <span>EASE cubre 86%. Popularidad, 4%.</span>
  </div>
</div>

<!--
Misma métrica, mismo corte, 2.473 usuarios. Las fuentes sueltas son el bake-off del 11 de noviembre. ALS queda apenas arriba de item-kNN, 0.0783 contra 0.0779, y el two-tower en 0.077. EASE rankea peor, 0.069, y cubre el 86% del catálogo. Popularidad queda en 0.030 y cubre el 4%. El two-stage, medido hoy, sube a 0.100. Gana, y el top 10 sigue sin traer las próximas reviews.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Experimentos</p>
  <h1 class="title">Lo que no</h1>
  <div class="miss">
    <div>
      <h2>Se cayó</h2>
      <div class="miss-row"><b>0.002</b><span>rating_mlp. Optimizaba la nota.</span></div>
      <div class="miss-row"><b>0.068</b><span>Torre solo con ids. Cubre 32%.</span></div>
      <div class="miss-row"><b>0.030</b><span>Two-tower con lr 0.0001.</span></div>
    </div>
    <div>
      <h2>Quedó abierto</h2>
      <div class="miss-row"><b>0.96</b><span>Recall. 801 de 1.088 perfumes.</span></div>
      <div class="miss-row"><b>0.10</b><span>NDCG del top 10.</span></div>
      <div class="miss-row"><b>0.98</b><span>Si el orden fuera perfecto.</span></div>
    </div>
  </div>
  <p class="foot">BPR y TF-IDF no tienen score propio. La app no sirve este modelo.</p>
</div>

<!--
En libros, una red que minimizaba el error de la nota sacó 0.002: el objetivo estaba mal. La torre solo con ids pierde contra la que ve el contenido y cubre un tercio del catálogo. Con learning rate 0.0001 el two-tower cae a 0.030, al nivel de la popularidad. BPR y TF-IDF entran como fuentes y no tienen un número de modelo único. El hueco de perfumes está en el orden: el retrieval trae el 96%, con 801 candidatos de 1.088, y si esas reviews quedaran primeras el NDCG sería 0.98. El top 10 queda en 0.10. La app no llama a este modelo.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">App</p>
  <h1 class="title">Tres listas, sin reentrenar</h1>
  <div class="grid-2">
    <div class="cell">
      <div class="num">Conocido</div>
      <div class="lbl">Oculta lo que ya tiene</div>
      <div class="sub">Reviews o wardrobe. La encuesta no se usa.</div>
    </div>
    <div class="cell">
      <div class="num">Nuevo</div>
      <div class="lbl">Encuesta</div>
      <div class="sub">Marca, género, perfumista, familia.</div>
    </div>
  </div>
  <div class="lists">
    <div class="list-card"><b>Más populares</b><span>Más votos de la comunidad</span></div>
    <div class="list-card"><b>Mejor puntuados</b><span>Nota alta, con bastantes votos</span></div>
    <div class="list-card"><b>Tendencia</b><span>Últimos 365 días</span></div>
  </div>
  <p class="app-note">De a 20. Nota media ≥ 3. Puntuar una card solo la saca de la sesión.</p>
</div>

<!--
Si el usuario existe, se esconde lo que ya está en sus reviews o en el wardrobe, y la encuesta no aplica. Si no existe, se filtra por marca, género, perfumista y familia. Después hay tres listas de 20, solo con nota media de al menos 3: los más votados, los mejor puntuados entre los que tienen bastantes votos, y los más reseñados en el último año. Puntuar una card la saca de la sesión. No se reentrena nada.
-->

---
layout: none
---

<div class="frame">
  <p class="kicker">Cierre</p>
  <h1 class="title">El método viajó.<br>El ranking, a medias.</h1>
  <div class="close">
    <div>
      <div class="num">0.211</div>
      <div class="lbl">Libros, desde 0.072</div>
    </div>
    <div>
      <div class="num hero">0.100</div>
      <div class="lbl">Perfumes, desde 0.027</div>
    </div>
    <div>
      <div class="num close-open">Abierto</div>
      <div class="lbl">Servir el modelo.<br>Terminar el crawl.</div>
    </div>
  </div>
</div>

<!--
En libros el mismo esquema pasó de 0.072 a 0.211. En perfumes, de 0.027 a 0.100, por encima de cualquier fuente sola, sobre una matriz que dejó afuera al 94% de los usuarios. Lo que no quedó es un top 10 que anticipe la próxima review, ni una app que sirva ese ranking. Queda conectar el modelo y seguir el crawl.
-->
