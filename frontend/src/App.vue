<template>
  <div id="app">
    <a-layout style="min-height: 100vh">
      <a-layout-header style="background: #001529; padding: 0 50px">
        <div style="color: white; font-size: 24px; font-weight: bold">
          🌍 智能旅行助手
        </div>
      </a-layout-header>
      <a-layout-content style="padding: 24px">
        <router-view />
      </a-layout-content>
      <a-layout-footer style="text-align: center">
        智能旅行助手 ©2026
      </a-layout-footer>
    </a-layout>

    <!-- 全局 AI 悬浮助手，放在a-layout外面 -->
    <ChatWidget :plan="tripPlan" />
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import ChatWidget from '@/components/ChatWidget.vue'
import type { TripPlan } from '@/types'


const route = useRoute()

// 新增调试打印，看真实path
watch(()=>route.path,(val)=>{
  console.log("====当前route.path====", val)
},{immediate:true})

// 从 sessionStorage 读取行程，解析失败时返回 null
const loadTripPlan = (): TripPlan | null => {
  try {
    const data = sessionStorage.getItem('tripPlan')
    return data ? JSON.parse(data) : null
  } catch (e) {
    console.error('解析 tripPlan 失败:', e)
    return null
  }
}

const tripPlan = ref<TripPlan | null>(loadTripPlan())

// 路由切换的时候，重新读取本地存储
watch(() => route.path, () => {
  tripPlan.value = loadTripPlan()
})
</script>

<style>
#app {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif;
}
</style>