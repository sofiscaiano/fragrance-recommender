<script setup>
defineProps({
  kind: { type: String, default: "bottle" },
})
</script>

<template>
  <svg viewBox="0 0 80 140" fill="none" aria-hidden="true">
    <template v-if="kind === 'bottle'">
      <rect x="32" y="4" width="16" height="16" rx="2" stroke="currentColor" stroke-width="2.2" />
      <path d="M36 20h8v14h-8z" stroke="currentColor" stroke-width="2.2" />
      <path
        d="M36 34c-12 10-18 20-18 34v42c0 12 11 18 22 18s22-6 22-18V68c0-14-6-24-18-34z"
        stroke="currentColor"
        stroke-width="2.2"
      />
      <path d="M22 86h36" stroke="currentColor" stroke-width="1.6" opacity="0.45" />
      <path d="M40 96c8 6 10 12 6 20" class="scent-brass" stroke-width="1.8" stroke-linecap="round" />
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
