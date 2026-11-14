<script setup>
defineProps({
  kind: { type: String, default: "bottle" },
  spray: { type: Boolean, default: false },
})
</script>

<template>
  <svg
    :viewBox="kind === 'bottle' ? (spray ? '0 -8 200 260' : '90 70 80 180') : '0 0 80 140'"
    fill="none"
    aria-hidden="true"
  >
    <template v-if="kind === 'bottle'">
      <defs>
        <clipPath id="cover-glass"><rect x="96" y="74" width="64" height="158" rx="32" /></clipPath>
      </defs>
      <ellipse class="shadow" cx="128" cy="238" rx="34" ry="3.5" />
      <g clip-path="url(#cover-glass)">
        <rect class="glass" x="96" y="74" width="64" height="158" rx="32" />
        <rect class="liquid" x="96" y="178" width="64" height="54" />
        <rect class="shine" x="108" y="108" width="5" height="46" rx="2.5" />
      </g>
      <rect class="edge" x="96" y="74" width="64" height="158" rx="32" />
      <g v-if="spray" class="mist" transform="translate(39 36)">
        <circle class="puff" cx="-8" cy="-2" r="4.2" style="--dx: -22px; --dy: -16px; --delay: 0s" />
        <circle class="puff" cx="-14" cy="1" r="3.4" style="--dx: -36px; --dy: -6px; --delay: 0.08s" />
        <circle class="puff" cx="-6" cy="-6" r="3" style="--dx: -14px; --dy: -22px; --delay: 0.16s" />
        <circle class="puff" cx="-18" cy="4" r="3.8" style="--dx: -40px; --dy: 4px; --delay: 0.06s" />
        <circle class="puff" cx="-12" cy="-4" r="4.8" style="--dx: -26px; --dy: -12px; --delay: 0.22s" />
        <circle class="puff" cx="-22" cy="0" r="3.2" style="--dx: -34px; --dy: -8px; --delay: 0.12s" />
        <circle class="puff" cx="-10" cy="5" r="2.8" style="--dx: -24px; --dy: 8px; --delay: 0.18s" />
      </g>
      <path class="neck" d="M119 98V55h18v43z" />
      <path class="edge" d="M119 92V55h18v37" />
      <rect class="collar" x="108" y="46" width="40" height="8" rx="1" />
      <rect class="metal" x="106" y="28" width="44" height="18" rx="2" />
      <rect class="lip" x="108" y="42" width="40" height="4" />
      <rect class="metal" x="42" y="32" width="66" height="8" rx="4" />
      <circle class="metal-dark" cx="42" cy="36" r="3.6" />
      <circle class="hole" cx="39" cy="36" r="1.2" />
      <g class="pump">
        <rect class="stem" x="122" y="18" width="12" height="14" />
        <rect class="cap" x="108" y="0" width="40" height="18" rx="3" />
        <rect class="cap-mark" x="116" y="6" width="24" height="2.4" rx="1" />
      </g>
    </template>
    <template v-else-if="kind === 'drop'">
      <path
        d="M40 18c12 16 22 30 22 46a22 22 0 1 1-44 0c0-16 10-30 22-46z"
        stroke="currentColor"
        stroke-width="2.2"
      />
      <path d="M32 78c4 6 8 8 14 6" class="scent-brass" stroke-width="1.8" stroke-linecap="round" />
    </template>
    <template v-else>
      <path
        d="M40 118c0-28 8-44 28-62-8 28-6 40-28 62z"
        stroke="currentColor"
        stroke-width="2.2"
        stroke-linejoin="round"
      />
      <path
        d="M40 118C40 78 28 52 12 36c6 30 10 46 28 82z"
        stroke="currentColor"
        stroke-width="2.2"
        stroke-linejoin="round"
      />
      <path d="M40 118V28" class="scent-brass" stroke-width="1.8" stroke-linecap="round" />
    </template>
  </svg>
</template>
