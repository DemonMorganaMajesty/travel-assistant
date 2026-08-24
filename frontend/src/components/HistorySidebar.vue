<template>
  <div class="history-root">
    <!-- 收起状态：右侧边缘展开按钮，点击拉开 -->
    <div v-if="!visible" class="history-toggle-btn" @click="openPanel" title="展开历史会话记录">
      <span class="toggle-icon">📁</span>
      <span class="toggle-text">历史规划记录</span>
    </div>

    <!-- 展开状态：半透明遮罩，点击关闭 -->
    <div v-if="visible" class="history-mask" @click="visible = false"></div>

    <!-- 侧边栏面板 -->
    <transition name="slide">
      <div v-if="visible" class="history-sidebar">
        <div class="history-header">
          <span class="history-title">📁 历史规划记录</span>
          <div class="history-header-actions">
            <a-button size="small" type="text" @click="refresh" title="刷新">🔄</a-button>
            <a-button size="small" type="text" @click="visible = false" title="收起">✖</a-button>
          </div>
        </div>

        <!-- 未登录：不加载历史列表，提示登录后可查看/保存 -->
        <div v-if="!isLoggedIn" class="history-login-tip">
          🔒 登录后可查看历史规划记录<br />
          <span>未登录时行程仅一次性使用，不会持久化保存</span>
        </div>

        <a-spin v-else :spinning="loading">
          <div class="history-list" v-if="items.length > 0">
            <div class="history-item" v-for="item in items" :key="item.id">
              <div class="history-item-main" @click="onView(item)">
                <div class="history-item-title">{{ item.title }}</div>
                <div class="history-item-time">{{ item.updated_at || item.created_at }}</div>
              </div>
              <div class="history-item-actions">
                <a-tooltip title="查看">
                  <a-button size="small" type="link" @click="onView(item)">👁</a-button>
                </a-tooltip>
                <a-tooltip title="重命名">
                  <a-button size="small" type="link" @click="startRename(item)">✏️</a-button>
                </a-tooltip>
                <a-tooltip title="删除">
                  <a-button size="small" type="link" danger @click="onDelete(item)">🗑</a-button>
                </a-tooltip>
              </div>
              <!-- 重命名输入行 -->
              <div v-if="editingId === item.id" class="rename-row">
                <a-input
                  v-model:value="editTitle"
                  size="small"
                  placeholder="输入新标题"
                  @pressEnter="submitRename(item)"
                />
                <a-button size="small" type="primary" @click="submitRename(item)">保存</a-button>
                <a-button size="small" @click="editingId = null">取消</a-button>
              </div>
            </div>
          </div>
          <a-empty v-else description="暂无历史记录" style="margin: 16px 0" />
        </a-spin>

        <div class="history-pagination" v-if="total > pageSize">
          <a-pagination
            :current="page"
            :page-size="pageSize"
            :total="total"
            size="small"
            @change="onPageChange"
          />
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { message } from 'ant-design-vue'
import { fetchHistoryList, deleteHistory, updateHistory } from '@/services/api'
import { HISTORY_PAGE_SIZE } from '@/constants'
import type { HistoryItem } from '@/types'

const emit = defineEmits<{
  (e: 'select', item: HistoryItem): void
}>()

// 侧边栏展开/收起状态：默认收起，不遮挡用户视线
const visible = ref(false)

const items = ref<HistoryItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(HISTORY_PAGE_SIZE)
const loading = ref(false)
const editingId = ref<number | null>(null)
const editTitle = ref('')
// 登录态：从 localStorage 读取（Home 登录/退出后通过 refresh() 刷新）
const isLoggedIn = ref(!!localStorage.getItem('tripToken'))

// 打开侧边栏并刷新数据
function openPanel() {
  visible.value = true
  refresh()
}

// 加载历史记录列表（未登录时仅显示登录提示，不发请求）
async function refresh() {
  isLoggedIn.value = !!localStorage.getItem('tripToken')
  if (!isLoggedIn.value) {
    items.value = []
    total.value = 0
    return
  }
  loading.value = true
  try {
    const data = await fetchHistoryList(page.value, pageSize.value)
    items.value = data.items || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

const loadHistory = refresh

function onPageChange(p: number) {
  page.value = p
  refresh()
}

function onView(item: HistoryItem) {
  emit('select', item)
}

function startRename(item: HistoryItem) {
  editingId.value = item.id
  editTitle.value = item.title || ''
}

async function submitRename(item: HistoryItem) {
  const title = editTitle.value.trim()
  if (!title) {
    message.warning('标题不能为空')
    return
  }
  const ok = await updateHistory(item.id, { title })
  if (ok) {
    message.success('重命名成功')
    editingId.value = null
    refresh()
  } else {
    message.error('重命名失败')
  }
}

function onDelete(item: HistoryItem) {
  Modal.confirm({
    title: '删除历史记录',
    content: `确定删除「${item.title}」吗？删除后不可恢复。`,
    okText: '删除',
    okType: 'danger',
    cancelText: '取消',
    onOk: async () => {
      const ok = await deleteHistory(item.id)
      if (ok) {
        message.success('删除成功')
        // 当前页删空后自动回退一页
        if (items.value.length === 1 && page.value > 1) {
          page.value -= 1
        }
        refresh()
      } else {
        message.error('删除失败')
      }
    },
  })
}

defineExpose({ refresh, loadHistory })

onMounted(() => {
  // 默认不加载，展开时再刷新，减少无效请求
})
</script>

<script lang="ts">
import { defineComponent } from 'vue'
import { Modal } from 'ant-design-vue'

export default defineComponent({
  name: 'HistorySidebar',
})
</script>

<style scoped>
/* 收起按钮：固定在右侧边缘，点击拉开 */
.history-toggle-btn {
  position: fixed;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  z-index: 99;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 14px 8px;
  background: #fff;
  border: 1px solid #e5e5e5;
  border-right: none;
  color: #333;
  border-radius: 10px 0 0 10px;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.12);
  transition: all 0.2s;
  user-select: none;
}
.history-toggle-btn:hover {
  padding-right: 12px;
}
.toggle-icon {
  font-size: 18px;
}
.toggle-text {
  font-size: 12px;
  writing-mode: vertical-lr;
  letter-spacing: 2px;
}

/* 遮罩：点击空白处收起 */
.history-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 100;
}

/* 侧边栏面板：固定右侧全高 */
.history-sidebar {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 340px;
  z-index: 101;
  display: flex;
  flex-direction: column;
  background: #fff;
  box-shadow: -4px 0 20px rgba(0, 0, 0, 0.12);
  padding: 14px;
  box-sizing: border-box;
  overflow: hidden;
}
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
  margin-bottom: 8px;
}
.history-title {
  font-weight: 600;
  font-size: 15px;
}
.history-header-actions {
  display: flex;
  align-items: center;
}
.history-list {
  flex: 1;
  overflow-y: auto;
}
.history-item {
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.2s;
}
.history-item:hover {
  border-color: #d9d9d9;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.history-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.history-item-title {
  font-size: 13px;
  font-weight: 500;
  color: #333;
}
.history-item-time {
  font-size: 11px;
  color: #999;
}
.history-item-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 2px;
}
.rename-row {
  display: flex;
  gap: 6px;
  margin-top: 6px;
  align-items: center;
}
.history-pagination {
  padding-top: 8px;
  border-top: 1px solid #f0f0f0;
  display: flex;
  justify-content: center;
}
.history-login-tip {
  margin: 16px 4px;
  padding: 14px;
  text-align: center;
  font-size: 14px;
  line-height: 1.8;
  color: #6b49b8;
  background: #f6f2ff;
  border: 1px dashed #c9b8ef;
  border-radius: 8px;
}
.history-login-tip span {
  font-size: 12px;
  color: #999;
}

/* 展开动画 */
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.25s ease;
}
.slide-enter-from,
.slide-leave-to {
  transform: translateX(100%);
}
</style>
