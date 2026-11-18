<script setup>
import { RouterView } from 'vue-router'
import AppLayout from '@/components/AppLayout.vue'
</script>

<template>
  <AppLayout>
    <RouterView v-slot="{ Component }">
      <keep-alive :include="['HomeView']">
        <component :is="Component" />
      </keep-alive>
    </RouterView>
  </AppLayout>
</template>
