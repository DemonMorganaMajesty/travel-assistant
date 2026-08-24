<template>
  <div v-if="visible" class="chat-panel">
    <div class="chat-header">
      <span class="chat-title">伴游助手</span>
      <span class="close-btn" @click="visible = false">✕</span>
    </div>
    <div class="chat-messages" ref="msgBox">
      <div v-if="messages.length === 0" class="empty-hint">向伴游助手提问，基于行程回答你的问题</div>
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">{{ m.content }}</div>
      <div v-if="streaming" class="msg assistant">{{ streamingText }}<span class="cursor">|</span></div>
    </div>
    <div class="input-row">
      <a-input v-model:value="inputText" placeholder="输入问题..." @pressEnter.prevent="send" :disabled="sending" />
      <a-button type="primary" size="small" @click="send" :loading="sending" :disabled="!inputText.trim()">发送</a-button>
    </div>
  </div>

  <div
    v-show="!visible"
    class="fab"
    ref="fab"
    @mousedown="onDown"
    @touchstart.prevent="onDown"
  >💬</div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { chatWithCompanionSSE } from '@/services/api'

const props = defineProps<{ plan: any }>()
let abortController: AbortController | null = null

const visible = ref(false)
const inputText = ref('')
const messages = ref<{ role: 'user' | 'assistant'; content: string }[]>([])
const streamingText = ref('')
const streaming = ref(false)
const sending = ref(false)
const msgBox = ref<HTMLElement | null>(null)
const fab = ref<HTMLElement | null>(null)

// 拖拽状态
let dragging = false, moved = false
let startMouseX = 0, startMouseY = 0, startLeft = 0, startTop = 0

function applyFabPos(x: number, y: number) {
  const el = fab.value; if (!el) return
  el.style.bottom = 'auto'; el.style.right = 'auto'
  el.style.left = x + 'px'; el.style.top = y + 'px'
}

function scroll() {
  nextTick(() => { if (msgBox.value) msgBox.value.scrollTop = msgBox.value.scrollHeight })
}

function send() {
  const t = inputText.value.trim(); if (!t || sending.value) return
  messages.value.push({ role: 'user', content: t }); inputText.value = ''
  nextTick(() => { inputText.value = '' })
  sending.value = true; streaming.value = true; streamingText.value = ''; scroll()

  const chatController = chatWithCompanionSSE(t, props.plan,
    c => { streamingText.value += c },
    () => {
      if (streamingText.value) messages.value.push({ role: 'assistant', content: streamingText.value })
      streamingText.value = ''; streaming.value = false; sending.value = false; scroll()
    },
    e => {
      messages.value.push({ role: 'assistant', content: '❌ ' + e })
      streamingText.value = ''; streaming.value = false; sending.value = false
    },
  )
  // 保存用于清理：组件卸载时若仍在流式传输则取消
  abortController = chatController
}

function onDown(e: MouseEvent | TouchEvent) {
  e.preventDefault()
  dragging = true; moved = false
  const el = fab.value!
  const rect = el.getBoundingClientRect()
  startLeft = rect.left; startTop = rect.top
  applyFabPos(startLeft, startTop) // 从 bottom/right 切换为 left/top 定位
  const p = e instanceof MouseEvent ? e : e.touches[0]
  startMouseX = p.clientX; startMouseY = p.clientY
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  document.addEventListener('touchmove', onMove, { passive: false })
  document.addEventListener('touchend', onUp)
}

function onMove(e: MouseEvent | TouchEvent) {
  if (!dragging) return
  const p = e instanceof MouseEvent ? e : e.touches[0]
  if (Math.abs(p.clientX - startMouseX) > 3 || Math.abs(p.clientY - startMouseY) > 3) moved = true
  applyFabPos(
    Math.max(0, Math.min(window.innerWidth - 56, startLeft + p.clientX - startMouseX)),
    Math.max(0, Math.min(window.innerHeight - 56, startTop + p.clientY - startMouseY)),
  )
}

function onUp() {
  dragging = false
  if (!moved) visible.value = true
  document.removeEventListener('mousemove', onMove)
  document.removeEventListener('mouseup', onUp)
  document.removeEventListener('touchmove', onMove)
  document.removeEventListener('touchend', onUp)
}

onMounted(() => {
  const tip = props.plan
    ? '你好！我是伴游助手。行程已经生成好了，有任何问题都可以问我。'
    : '你好！我是伴游助手，有任何旅行问题都可以问我。'
  messages.value.push({ role: 'assistant', content: tip })
})

onBeforeUnmount(() => {
  // 取消进行中的 SSE 连接
  if (abortController) {
    abortController.abort()
    abortController = null
  }
  // 清理残留的事件监听器（安全兜底）
  document.removeEventListener('mousemove', onMove)
  document.removeEventListener('mouseup', onUp)
  document.removeEventListener('touchmove', onMove)
  document.removeEventListener('touchend', onUp)
})
</script>

<style scoped>
.fab {
  position: fixed;
  bottom: 80px;
  right: 24px;
  width: 56px;
  height: 56px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea, #764ba2);
  box-shadow: 0 4px 16px rgba(102, 126, 234, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: grab;
  z-index: 9999;
  user-select: none;
  font-size: 22px;
  color: #fff;
}
.fab:active { cursor: grabbing; }

.chat-panel {
  position: fixed;
  bottom: 24px;
  right: 24px;
  width: 400px;
  height: 520px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  z-index: 9998;
  overflow: hidden;
}
.chat-header {
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.chat-title { font-weight: 600; font-size: 15px; }
.close-btn { cursor: pointer; font-size: 18px; opacity: 0.8; }
.close-btn:hover { opacity: 1; }

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.empty-hint { color: #999; text-align: center; margin-top: 40px; font-size: 13px; }
.msg { max-width: 85%; padding: 8px 12px; border-radius: 12px; font-size: 14px; line-height: 1.5; }
.msg.user { align-self: flex-end; background: linear-gradient(135deg, #667eea, #764ba2); color: #fff; }
.msg.assistant { align-self: flex-start; background: #f5f7fa; color: #333; }
.cursor { animation: blink 1s step-end infinite; }
@keyframes blink { 50% { opacity: 0; } }

.input-row {
  padding: 8px;
  border-top: 1px solid #eee;
  display: flex;
  gap: 8px;
  align-items: center;
}
.input-row :deep(.ant-input) { border-radius: 8px; }

@media (max-width: 480px) {
  .chat-panel { width: 100vw; height: 100vh; bottom: 0; right: 0; border-radius: 0; }
}
</style>
