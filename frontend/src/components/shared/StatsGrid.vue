<script setup lang="ts">
import { NCard, NGrid, NGi, NStatistic } from 'naive-ui'

interface StatItem {
  label: string
  value: string | number
}

defineProps<{
  items: StatItem[]
  cols?: number
}>()
</script>

<template>
  <n-grid v-if="items.length" :cols="cols || items.length" :x-gap="12" style="margin-bottom: 20px">
    <n-gi v-for="(item, idx) in items" :key="idx">
      <n-card size="small" :bordered="true" style="text-align: center">
        <n-statistic :label="item.label" :value="item.value" />
      </n-card>
    </n-gi>
  </n-grid>
</template>
