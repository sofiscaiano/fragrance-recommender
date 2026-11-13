<script setup>
import { ref } from "vue"
import { onSlideEnter } from "@slidev/client"

const on = ref(false)

onSlideEnter(() => {
  on.value = false
  requestAnimationFrame(() => {
    on.value = true
  })
})

const max = 0.1
const rows = [
  { name: "Two-stage", value: 0.1, text: "0.100", highlight: true },
  { name: "ALS", value: 0.0783, text: "0.078" },
  { name: "Item-kNN", value: 0.0779, text: "0.078" },
  { name: "Two-tower", value: 0.0767, text: "0.077" },
  { name: "EASE", value: 0.0689, text: "0.069" },
  { name: "Popularidad", value: 0.0296, text: "0.030" },
]
</script>

<template>
  <div class="bars" :class="{ on }">
    <div
      v-for="row in rows"
      :key="row.name"
      class="bar-row"
      :class="{ hl: row.highlight }"
    >
      <div class="bar-name">{{ row.name }}</div>
      <div class="bar-track">
        <div class="bar-fill" :style="{ '--w': String(row.value / max) }" />
      </div>
      <div class="bar-value">{{ row.text }}</div>
    </div>
  </div>
</template>
