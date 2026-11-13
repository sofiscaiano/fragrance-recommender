<script setup>
defineProps({
  kind: { type: String, default: "bottle" },
  spray: { type: Boolean, default: false },
})
</script>

<template>
  <svg
    :viewBox="kind === 'bottle' ? (spray ? '0 0 160 168' : '90 12 64 146') : '0 0 80 140'"
    fill="none"
    aria-hidden="true"
  >
    <template v-if="kind === 'bottle'">
      <g v-if="spray" class="mist">
        <path pathLength="1" d="M108 31c-14-12-30-12-46-2" class="cone" />
        <path pathLength="1" d="M108 32c-18-1-34 6-48 14" class="cone" />
        <path pathLength="1" d="M108 30c-12-16-24-22-40-18" class="cone" />
        <circle class="puff" cx="96" cy="27" r="2.2" style="--dx: -24px; --dy: -16px; --delay: 0.05s" />
        <circle class="puff" cx="90" cy="33" r="1.7" style="--dx: -34px; --dy: -2px; --delay: 0.28s" />
        <circle class="puff" cx="100" cy="23" r="1.4" style="--dx: -12px; --dy: -24px; --delay: 0.5s" />
        <circle class="puff" cx="84" cy="29" r="2.5" style="--dx: -46px; --dy: -10px; --delay: 0.72s" />
        <circle class="puff" cx="92" cy="37" r="1.3" style="--dx: -28px; --dy: 8px; --delay: 0.94s" />
        <circle class="puff" cx="78" cy="24" r="1.5" style="--dx: -18px; --dy: -18px; --delay: 1.16s" />
        <circle class="puff" cx="86" cy="31" r="1.1" style="--dx: -22px; --dy: -8px; --delay: 1.38s" />
      </g>
      <rect class="ink" x="116" y="14" width="14" height="8" rx="2" stroke="currentColor" stroke-width="2" />
      <rect class="collar" x="109" y="22" width="28" height="8" rx="1" />
      <path class="nozzle" d="M109 26H82" />
      <circle class="nozzle-tip" cx="80" cy="26" r="2.2" />
      <path class="ink" d="M117 30h12v20h-12z" stroke="currentColor" stroke-width="2" />
      <path
        class="ink"
        d="M117 50h12c11 7 18 20 18 36v32c0 18-11 28-24 28s-24-10-24-28V86c0-16 7-29 18-36z"
        stroke="currentColor"
        stroke-width="2.2"
      />
      <path class="liquid" d="M103 108h40v12c0 14-8 22-20 22s-20-8-20-22z" />
      <path class="glass" d="M112 70v48" stroke-width="1.5" stroke-linecap="round" />
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
