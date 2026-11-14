<template>
  <div class="flow-svg" aria-label="Diagrama del recorrido en la web.">
    <svg viewBox="0 0 1080 480" width="1080" height="480">
      <rect x="370" y="0" width="340" height="42" rx="8" fill="#fffcf8" stroke="#7c2f38" stroke-width="1.5" />
      <text class="wf-name" x="478" y="27" text-anchor="end">Perfil</text>
      <text class="wf-note" x="494" y="27" text-anchor="start">Entra con su nombre.</text>

      <rect x="16" y="64" width="460" height="58" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-name" x="246" y="88" text-anchor="middle">Conocido</text>
      <text class="wf-note" x="246" y="108" text-anchor="middle">Two-stage. No repite reviews ni wardrobe.</text>

      <rect x="536" y="64" width="528" height="58" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-name" x="800" y="88" text-anchor="middle">Nuevo</text>
      <text class="wf-note" x="800" y="108" text-anchor="middle">Encuesta opcional.</text>

      <rect x="536" y="150" width="250" height="70" rx="8" fill="#fffcf8" stroke="#a6844a" stroke-width="1.5" />
      <text class="wf-name" x="661" y="178" text-anchor="middle">¿Fragancias?</text>
      <text class="wf-note" x="661" y="202" text-anchor="middle">Sí: two-stage. No: popularidad.</text>

      <rect x="806" y="150" width="258" height="70" rx="8" fill="#fffcf8" stroke="#a6844a" stroke-width="1.5" />
      <text class="wf-name" x="935" y="178" text-anchor="middle">¿Marcas o para quién?</text>
      <text class="wf-note" x="935" y="202" text-anchor="middle">Filtra. Si no elige, catálogo entero.</text>

      <rect x="16" y="286" width="248" height="62" rx="8" fill="#f6e4e2" stroke="#7c2f38" stroke-width="1.5" />
      <text class="wf-name" x="140" y="310" text-anchor="middle">For you</text>
      <text class="wf-note" x="140" y="330" text-anchor="middle">Inferencia con el modelo</text>

      <rect x="280" y="286" width="248" height="62" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-name" x="404" y="322" text-anchor="middle">Más populares</text>

      <rect x="544" y="286" width="248" height="62" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-name" x="668" y="322" text-anchor="middle">Tendencia</text>

      <rect x="808" y="286" width="256" height="62" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-name" x="936" y="322" text-anchor="middle">Mejor puntuados</text>

      <rect x="230" y="372" width="620" height="44" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-step" x="270" y="400">01</text>
      <text class="wf-name" x="308" y="400">Puntúa</text>
      <text class="wf-note" x="392" y="400">La nota entra al historial y esa tarjeta sale.</text>

      <rect x="230" y="432" width="620" height="40" rx="8" fill="#fffcf8" stroke="#d9d0c6" stroke-width="1.5" />
      <text class="wf-step" x="270" y="458">02</text>
      <text class="wf-name" x="308" y="458">Otra vez</text>
      <text class="wf-note" x="420" y="458">For you se arma de nuevo, sin reentrenar.</text>

      <path d="M540 42 V54 H246 V64" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M540 54 H800 V64" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="246,64 238,52 254,52" fill="#a6844a" />
      <polygon points="800,64 792,52 808,52" fill="#a6844a" />

      <path d="M800 122 V136 H661 V150" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M800 136 H935 V150" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="661,150 653,138 669,138" fill="#a6844a" />
      <polygon points="935,150 927,138 943,138" fill="#a6844a" />

      <path d="M140 122 V274" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="140,286 132,274 148,274" fill="#a6844a" />

      <path d="M661 220 V244 H210 V274" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="210,286 202,274 218,274" fill="#a6844a" />

      <path d="M470 122 V136 H796 V262" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M404 262 H936" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M935 220 V262" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M404 262 V274" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M668 262 V274" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M936 262 V274" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="404,286 396,274 412,274" fill="#a6844a" />
      <polygon points="668,286 660,274 676,274" fill="#a6844a" />
      <polygon points="936,286 928,274 944,274" fill="#a6844a" />

      <path d="M140 348 V360 H936" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M404 348 V360" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M668 348 V360" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M936 348 V360" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <path d="M540 360 V372" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="540,372 532,360 548,360" fill="#a6844a" />
      <path d="M540 416 V432" fill="none" stroke="#a6844a" stroke-width="1.75" />
      <polygon points="540,432 532,420 548,420" fill="#a6844a" />
    </svg>
  </div>
</template>

<style>
.flow-svg svg {
  container-type: inline-size;
  display: block;
  width: 100%;
  height: auto;
  max-height: 100%;
  aspect-ratio: 1080 / 480;
}

.flow-svg text {
  font-family: "Avenir Next", "Segoe UI", sans-serif;
}

.flow-svg .wf-name,
.flow-svg .wf-step {
  font-family: "Iowan Old Style", Palatino, Georgia, serif;
  fill: #1a1814;
}

.flow-svg .wf-name { font-size: 1.48cqw; }
.flow-svg .wf-note { font-size: 1.2cqw; fill: #6f675f; }
.flow-svg .wf-step { font-size: 1.3cqw; fill: #a6844a; }
</style>
