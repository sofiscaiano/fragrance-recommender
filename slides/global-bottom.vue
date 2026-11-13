<script setup>
import { computed } from "vue"
import { useNav } from "@slidev/client"

const { currentPage } = useNav()
const label = computed(() => String(currentPage.value).padStart(2, "0"))
</script>

<template>
  <div class="fr-index">{{ label }}</div>
</template>
