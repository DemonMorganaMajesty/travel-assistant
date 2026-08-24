<template>
  <div class="home-container">
    <!-- Banner 区域 -->
    <div class="banner-area">
      <!-- 用户登录区域 -->
      <div class="user-area">
        <template v-if="isLoggedIn">
          <span class="user-name">👤 {{ username }}</span>
          <a-button size="small" @click="handleLogout">退出</a-button>
        </template>
        <a-button v-else class="login-btn" @click="showAuthModal = true">登录 / 注册</a-button>
      </div>
      <div class="decor-circle decor-circle-1"></div>
      <div class="decor-circle decor-circle-2"></div>

      <div class="plane-icon">✈️</div>
      <h1 class="main-title">智能旅行助手</h1>
      <p class="sub-title">基于AI的个性化旅行规划，让每一次出行都完美无忧</p>

      <!-- 白色大卡片 -->
      <div class="main-card">
        <!-- 未登录降级提示：不能持久化历史/偏好/伴游，仅一次性使用 -->
        <div v-if="!isLoggedIn" class="anon-notice">
          ⚠️ 当前未登录：<b>不能保存历史行程</b>、<b>不能持久化用户偏好记忆</b>、<b>不能保存聊天伴游历史</b>，本次规划仅为一次性使用。
        </div>
        <!-- 新建会话按钮：清空表单重新填写，废弃内容保存到历史记录 -->
        <div class="new-session-bar">
          <a-button class="new-session-btn" @click="handleNewSession">🆕 新建会话</a-button>
          <span class="new-session-hint">废弃内容会保存到历史记录</span>
        </div>
        <a-form :model="formData" layout="vertical" @finish="handleSubmit">
          <!-- 目的地与日期 -->
          <div class="section-card">
            <div class="section-header">
              <span class="section-icon">📍</span>
              <span class="section-title">目的地与日期</span>
            </div>
            <div class="section-divider"></div>

            <!-- 单城市模式 -->
            <div v-if="!isMultiCity" class="row-single-city">
              <div class="form-item-wrap input-city">
                <div class="label-required">
                  <span class="star">*</span>
                  <span>目的地城市</span>
                </div>
                <a-input v-model:value="formData.city" placeholder="例如: 北京" size="large">
                  <template #prefix>🏙️</template>
                </a-input>
              </div>

              <div class="date-group">
                <div class="form-item-wrap date-item">
                  <div class="label-required">
                    <span class="star">*</span>
                    <span>开始日期</span>
                  </div>
                  <a-date-picker v-model:value="formData.start_date" size="large" placeholder="选择日期" />
                </div>
                <div class="form-item-wrap date-item">
                  <div class="label-required">
                    <span class="star">*</span>
                    <span>结束日期</span>
                  </div>
                  <a-date-picker v-model:value="formData.end_date" size="large" placeholder="选择日期" />
                </div>
                <div class="days-badge-wrap">
                  <div class="days-label">旅行天数</div>
                  <div class="days-badge">
                    <span class="num">{{ formData.travel_days }}</span>
                    <span class="unit">天</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 多城市模式 -->
            <div v-if="isMultiCity">
              <div class="multi-city-box">
                <div class="city-item" v-for="(item, idx) in multiCityList" :key="idx">
                  <!-- 城市输入框，带重复校验 -->
                  <a-input
                    v-model:value="item.city_name"
                    placeholder="城市名称"
                    size="large"
                    :status="isCityDuplicate(item.city_name, idx) ? 'error' : ''"
                  >
                    <template #suffix>
                      <span v-if="isCityDuplicate(item.city_name, idx)" style="color:#ff4d4f;font-size:12px;">
                        ⚠️ 重复
                      </span>
                    </template>
                  </a-input>
                  <a-input-number
                    v-model:value="item.stay_days"
                    :min="1"
                    :max="15"
                    addon-after="天"
                    size="large"
                  />
                  <a-button danger @click="removeCity(idx)">删除</a-button>
                </div>
                <a-button type="dashed" block @click="addCity">+ 添加城市</a-button>
              </div>
              <div class="date-group multi-date-row">
                <div class="form-item-wrap date-item">
                  <div class="label-small">开始日期</div>
                  <a-date-picker v-model:value="formData.start_date" size="large" placeholder="选择日期" />
                </div>
                <div class="form-item-wrap date-item">
                  <div class="label-small">结束日期</div>
                  <!-- 🔥 多城市模式下结束日期禁用编辑 -->
                  <a-date-picker
                    v-model:value="formData.end_date"
                    size="large"
                    placeholder="选择日期"
                    :disabled="isMultiCity"
                  />
                </div>
              </div>
            </div>

            <div class="switch-wrap">
              <a-switch v-model:checked="isMultiCity" />
              <span>多城市模式</span>
            </div>
          </div>

          <!-- 出行信息与方案 -->
          <div class="section-card">
            <div class="section-header">
              <span class="section-icon">🧑‍🤝‍🧑</span>
              <span class="section-title">出行信息与方案</span>
            </div>
            <div class="section-divider"></div>

            <a-row :gutter="16">
              <a-col :span="8">
                <div class="label-required">
                  <span class="star">*</span>
                  <span>出发地点</span>
                </div>
                <a-input v-model:value="formData.origin" placeholder="例如: 上海" size="large">
                  <template #prefix>🚗</template>
                </a-input>
              </a-col>
              <a-col :span="8">
                <div class="label-required">
                  <span class="star">*</span>
                  <span>成人人数</span>
                </div>
                <a-input-number v-model:value="formData.adults" :min="1" :max="50" size="large" style="width:100%" />
              </a-col>
              <a-col :span="8">
                <div class="label-small">儿童人数</div>
                <a-input-number v-model:value="formData.children" :min="0" :max="50" size="large" style="width:100%" />
                <div class="children-hint">有儿童时将考虑儿童友好的路线与景点</div>
              </a-col>
            </a-row>

            <div class="plan-type-row" style="margin-top:16px;">
              <div class="label-small">生成方案数量</div>
              <div class="plan-count-stepper">
                <a-button class="plan-count-btn" :disabled="formData.plan_count <= MIN_PLAN_COUNT" @click="decreasePlanCount">−</a-button>
                <span class="plan-count-value">{{ formData.plan_count }} 个</span>
                <a-button class="plan-count-btn" :disabled="formData.plan_count >= MAX_PLAN_COUNT" @click="increasePlanCount">＋</a-button>
              </div>
              <div class="plan-hint">{{ AUTO_PLAN_HINT }}</div>
            </div>
          </div>

          <!-- 偏好设置 -->
          <div class="section-card">
            <div class="section-header">
              <span class="section-icon">⚙️</span>
              <span class="section-title">偏好设置</span>
            </div>
            <div class="section-divider"></div>

            <a-row :gutter="24">
              <a-col :span="8">
                <div class="label-small">交通方式</div>
                <a-select v-model:value="formData.transportation" size="large" style="width:100%">
                  <a-select-option value="公共交通">🚇 公共交通</a-select-option>
                  <a-select-option value="自驾">🚗 自驾</a-select-option>
                  <a-select-option value="步行">🚶 步行</a-select-option>
                  <a-select-option value="混合">🔀 混合</a-select-option>
                </a-select>
              </a-col>
              <a-col :span="8">
                <div class="label-small">住宿偏好</div>
                <a-select v-model:value="formData.accommodation" size="large" style="width:100%">
                  <a-select-option value="经济型酒店">💰 经济型酒店</a-select-option>
                  <a-select-option value="舒适型酒店">🏨 舒适型酒店</a-select-option>
                  <a-select-option value="豪华酒店">⭐ 豪华酒店</a-select-option>
                  <a-select-option value="民宿">🏡 民宿</a-select-option>
                </a-select>
              </a-col>
              <a-col :span="8">
                <div class="label-small">旅行偏好</div>
                <a-checkbox-group v-model:value="formData.preferences" class="preference-checkbox-group">
                  <a-checkbox value="历史文化">🏛️ 历史文化</a-checkbox>
                  <a-checkbox value="自然风光">🏞️ 自然风光</a-checkbox>
                  <a-checkbox value="美食">🍜 美食</a-checkbox>
                  <a-checkbox value="购物">🛍️ 购物</a-checkbox>
                  <a-checkbox value="艺术">🎨 艺术</a-checkbox>
                  <a-checkbox value="休闲">☕ 休闲</a-checkbox>
                </a-checkbox-group>
              </a-col>
            </a-row>
          </div>

          <!-- 额外要求 -->
          <div class="section-card">
            <div class="section-header">
              <span class="section-icon">💬</span>
              <span class="section-title">额外要求</span>
            </div>
            <div class="section-divider"></div>
            <a-textarea
              v-model:value="formData.free_text_input"
              placeholder="请输入您的额外要求，例如：想去看升旗、需要无障碍设施、对海鲜过敏等..."
              :rows="3"
              size="large"
            />
          </div>

          <a-form-item style="margin-bottom: 0; margin-top: 8px;">
            <a-button
              block
              size="large"
              type="primary"
              html-type="submit"
              :loading="loading"
              class="submit-btn"
            >
              🚀 开始规划我的旅行
            </a-button>
          </a-form-item>

          <div v-if="loading" class="loading-wrap">
            <a-progress
              :percent="loadingProgress"
              status="active"
              :stroke-color="{'0%':'#667eea','100%':'#764ba2'}"
              :stroke-width="8"
            />
            <p class="loading-text">{{ loadingStatus }}</p>
            <p v-if="toolStatus" class="tool-text">{{ toolStatus }}</p>
          </div>
        </a-form>
      </div>
    </div>

    <!-- 登录/注册弹窗：支持手机号/邮箱/用户名，放大字体并采用紫色背景 -->
    <a-modal v-model:open="showAuthModal" :title="authMode === 'login' ? '登录' : '注册'" :footer="null" width="460px" wrap-class-name="auth-modal-wrap">
      <div class="auth-modal-hint">🔐 支持手机号 / 邮箱 / 用户名登录注册</div>
      <a-tabs v-model:activeKey="authMode" class="auth-modal-tabs">
        <a-tab-pane key="login" tab="登录">
          <a-form :model="authForm" layout="vertical" @finish="handleLogin">
            <a-form-item label="手机号 / 邮箱 / 用户名" name="username" :rules="[{ required: true, message: '请输入手机号/邮箱/用户名' }]">
              <a-input v-model:value="authForm.username" size="large" class="auth-input" placeholder="手机号 / 邮箱 / 用户名" />
            </a-form-item>
            <a-form-item label="密码" name="password" :rules="[{ required: true, message: '请输入密码' }]">
              <a-input-password v-model:value="authForm.password" size="large" class="auth-input" placeholder="密码" />
            </a-form-item>
            <a-button type="primary" html-type="submit" block size="large" class="auth-submit-btn" :loading="authLoading">登 录</a-button>
          </a-form>
        </a-tab-pane>
        <a-tab-pane key="register" tab="注册">
          <a-form :model="authForm" layout="vertical" @finish="handleRegister">
            <a-form-item label="手机号 / 邮箱 / 用户名" name="username" :rules="[{ required: true, message: '请输入手机号/邮箱/用户名' }]">
              <a-input v-model:value="authForm.username" size="large" class="auth-input" placeholder="手机号 / 邮箱 / 用户名" />
            </a-form-item>
            <a-form-item label="密码" name="password" :rules="[{ required: true, min: 6, message: '密码至少6位' }]">
              <a-input-password v-model:value="authForm.password" size="large" class="auth-input" placeholder="密码(至少6位)" />
            </a-form-item>
            <a-button type="primary" html-type="submit" block size="large" class="auth-submit-btn" :loading="authLoading">注 册</a-button>
          </a-form>
        </a-tab-pane>
      </a-tabs>
    </a-modal>

    <!-- 历史会话记录侧边栏（隐藏式，点击右侧按钮拉开） -->
    <HistorySidebar ref="historySidebarRef" @select="onSelectHistory" />
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import { generateTripPlan, submitTripPlanTask, fetchTripPlanTask, saveHistory, fetchHistoryDetail, login as loginApi, register as registerApi } from '@/services/api'
import type { TripFormData, CityItem, HistoryItem, PlanItem, TripPlanMulti } from '@/types'
import type { Dayjs } from 'dayjs'
import dayjs from 'dayjs'
import HistorySidebar from '@/components/HistorySidebar.vue'
import { AUTO_PLAN_HINT, DEFAULT_PLAN_TYPE, DEFAULT_PLAN_COUNT, MIN_PLAN_COUNT, MAX_PLAN_COUNT, STORAGE_KEYS, findActivePlan } from '@/constants'

const router = useRouter()
const loading = ref(false)
const loadingProgress = ref(0)
const loadingStatus = ref('')
const toolStatus = ref('')

// ========== 登录鉴权 ==========
const TOKEN_KEY = 'tripToken'
const USERNAME_KEY = 'tripUsername'
const showAuthModal = ref(false)
const authMode = ref<'login' | 'register'>('login')
const authLoading = ref(false)
const authForm = reactive({ username: '', password: '' })
const username = ref('')
const isLoggedIn = ref(false)

// 保存登录态并让后续请求自动携带 token
const applyAuth = (token: string, name: string) => {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USERNAME_KEY, name)
  username.value = name
  isLoggedIn.value = true
  // 登录后刷新历史侧栏（未登录时侧栏仅展示登录提示）
  historySidebarRef.value?.refresh()
}

const handleLogin = async () => {
  authLoading.value = true
  try {
    const data = await loginApi(authForm.username.trim(), authForm.password)
    applyAuth(data.token, data.username)
    message.success('登录成功')
    showAuthModal.value = false
    authForm.password = ''
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '登录失败，请重试')
  } finally {
    authLoading.value = false
  }
}

const handleRegister = async () => {
  authLoading.value = true
  try {
    const data = await registerApi(authForm.username.trim(), authForm.password)
    applyAuth(data.token, data.username)
    message.success('注册成功')
    showAuthModal.value = false
    authForm.password = ''
  } catch (error: any) {
    message.error(error?.response?.data?.detail || '注册失败，请重试')
  } finally {
    authLoading.value = false
  }
}

const handleLogout = () => {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
  username.value = ''
  isLoggedIn.value = false
  historySidebarRef.value?.refresh()
  message.success('已退出登录')
}

// 页面加载时恢复登录态
onMounted(() => {
  const t = localStorage.getItem(TOKEN_KEY)
  const u = localStorage.getItem(USERNAME_KEY)
  if (t && u) {
    isLoggedIn.value = true
    username.value = u
  }
})

// ========== 多城市变量 ==========
const isMultiCity = ref(false)
const multiCityList = ref<CityItem[]>([])

const formData = reactive<Omit<TripFormData, 'start_date' | 'end_date'> & { start_date: Dayjs | null; end_date: Dayjs | null }>({
  city: '',
  city_list: null,
  start_date: null,
  end_date: null,
  travel_days: 1,
  transportation: '公共交通',
  accommodation: '经济型酒店',
  preferences: [],
  free_text_input: '',
  // 新增：出发地点、成人/儿童人数、方案类型
  origin: '',
  adults: 1,
  children: 0,
  plan_type: '',
  plan_count: DEFAULT_PLAN_COUNT
})

// 历史侧边栏组件引用（仅使用 refresh 能力）
const historySidebarRef = ref<{ refresh: () => Promise<void> } | null>(null)

// ========== 辅助函数：根据城市列表更新结束日期 ==========
const updateEndDateByCities = () => {
  if (!isMultiCity.value || !formData.start_date) return
  const totalDays = multiCityList.value.reduce((acc, cur) => acc + Number(cur.stay_days || 1), 0)
  formData.end_date = dayjs(formData.start_date).add(totalDays - 1, 'day')
}

// ========== 监听日期变化（单城市模式） ==========
watch([() => formData.start_date, () => formData.end_date], ([start, end]) => {
  if (isMultiCity.value) return
  if (start && end) {
    const days = end.diff(start, 'day') + 1
    if (days > 0 && days <= 30) {
      formData.travel_days = days
    } else if (days > 30) {
      message.warning('旅行天数不能超过30天')
      formData.end_date = null
    } else {
      message.warning('结束日期不能早于开始日期')
      formData.end_date = null
    }
  }
})

// ========== 多城市模式开关 ==========
watch(isMultiCity, (newVal) => {
  if (newVal) {
    multiCityList.value = [{ city_name: '', stay_days: 1 }]
    updateEndDateByCities()
  } else {
    multiCityList.value = []
  }
})

// ========== 监听开始日期变化（多城市模式） ==========
watch(
  () => formData.start_date,
  () => {
    if (isMultiCity.value) {
      updateEndDateByCities()
    }
  }
)

// ========== 监听城市列表变化（停留天数或增删） ==========
watch(
  multiCityList,
  () => {
    if (isMultiCity.value) {
      updateEndDateByCities()
    }
  },
  { deep: true }
)

// ========== 多城市操作函数 ==========

// 🔥 重复校验函数
const isCityDuplicate = (cityName: string, currentIdx: number): boolean => {
  if (!cityName.trim()) return false
  const lowerName = cityName.trim().toLowerCase()
  return multiCityList.value.some((item, idx) => {
    return idx !== currentIdx && item.city_name.trim().toLowerCase() === lowerName
  })
}

// 🔥 添加城市（带校验）
const addCity = () => {
  const lastIdx = multiCityList.value.length - 1
  const lastCity = multiCityList.value[lastIdx]
  if (!lastCity.city_name.trim()) {
    message.warning('请先填写当前城市的名称')
    return
  }
  if (isCityDuplicate(lastCity.city_name, lastIdx)) {
    message.warning('该城市已存在，请勿重复添加')
    return
  }
  multiCityList.value.push({ city_name: '', stay_days: 1 })
  updateEndDateByCities()
}

// 删除城市
const removeCity = (idx: number) => {
  if (multiCityList.value.length <= 1) {
    message.warning('至少保留一个城市')
    return
  }
  multiCityList.value.splice(idx, 1)
  updateEndDateByCities()
}

// ========== 提交校验 ==========
const handleSubmit = async () => {
  if (!formData.start_date || !formData.end_date) {
    message.error('请选择日期')
    return
  }

  // 新增校验：出发地点不为空
  if (!formData.origin.trim()) {
    message.error('请填写出发地点')
    return
  }
  if (!formData.adults || formData.adults < 1) {
    message.error('成人人数至少为1人')
    return
  }
  if (formData.children === null || formData.children === undefined || formData.children < 0) {
    message.error('儿童人数不能小于0')
    return
  }

  // 多城市模式校验
  if (isMultiCity.value) {
    if (multiCityList.value.length === 0) {
      message.error('请至少添加一个城市')
      return
    }
    // 检查重复城市名称（忽略空字符串）
    const cityNames = multiCityList.value.map(item => item.city_name.trim().toLowerCase())
    const filtered = cityNames.filter(name => name !== '')
    if (new Set(filtered).size !== filtered.length) {
      message.error('城市名称不能重复，请修改')
      return
    }
    for (const item of multiCityList.value) {
      if (!item.city_name.trim()) {
        message.error('城市名称不能为空')
        return
      }
    }
    // 校验总天数是否与起止日期一致
    const totalDays = multiCityList.value.reduce((acc, cur) => acc + Number(cur.stay_days || 1), 0)
    const realDays = dayjs(formData.end_date).diff(formData.start_date, 'day') + 1
    if (totalDays !== realDays) {
      message.warning('多城市模式日期计算异常，请调整停留天数或开始日期')
      return
    }
  }

  // 未登录弹窗提醒：可选择继续一次性生成，或先去登录
  if (!isLoggedIn.value) {
    const proceed = await new Promise<boolean>((resolve) => {
      Modal.confirm({
        title: '当前未登录',
        content: '登录后可保存历史行程、持久化用户偏好记忆与聊天伴游历史；不登录则本次规划仅一次性使用。是否继续生成？',
        okText: '继续生成',
        cancelText: '去登录',
        centered: true,
        onOk: () => resolve(true),
        onCancel: () => {
          showAuthModal.value = true
          resolve(false)
        },
      })
    })
    if (!proceed) return
  }

  loading.value = true
  loadingProgress.value = 0
  loadingStatus.value = '正在连接服务...'

  const requestData: TripFormData = {
    city: formData.city,
    city_list: isMultiCity.value ? [...multiCityList.value] : null,
    start_date: formData.start_date.format('YYYY-MM-DD'),
    end_date: formData.end_date.format('YYYY-MM-DD'),
    travel_days: formData.travel_days,
    transportation: formData.transportation,
    accommodation: formData.accommodation,
    preferences: formData.preferences,
    free_text_input: formData.free_text_input,
    // 新增：出发地点、成人/儿童人数、方案类型
    origin: formData.origin.trim(),
    adults: formData.adults || 1,
    children: formData.children || 0,
    plan_type: formData.plan_type || '',
    plan_count: formData.plan_count || DEFAULT_PLAN_COUNT
  }

  const stepProgress: Record<string, number> = {
    'research': 25,
    'logistics': 55,
    'planning': 85,
    'critic': 95,
  }

  // ========== 方案B：提交后台任务 + 轮询进度 ==========
  // 生成均为同一表单的唯一幂等键，重复提交（如超时后重试）可复用任务避免重复消耗
  const idempotencyKey = 'trip-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8)
  // 处理最终结果：与旧SSE onResult 逻辑一致（三方案/单方案/兜底校验/持久化/跳转）
  const applyPlanResult = (data: any) => {
    loadingProgress.value = 100
    loadingStatus.value = '完成!'
    const plans: PlanItem[] = data?.plans && data.plans.length > 0 ? data.plans : null
    const isValidPlan = (p: any): boolean =>
      !!(p && typeof p === 'object' && p.city && Array.isArray(p.days) && p.days.length > 0)
    if (plans) {
      const activeType: string = data.active_plan_type || DEFAULT_PLAN_TYPE
      const activePlan = findActivePlan(plans, activeType)
      const target = activePlan?.plan || plans[0]?.plan
      if (!isValidPlan(target)) {
        message.error('生成的行程方案数据无效，请重新生成')
        loading.value = false
        loadingProgress.value = 0
        loadingStatus.value = ''
        return
      }
      const multi: TripPlanMulti = {
        plans,
        active_plan_type: activeType,
        request: data.request || requestData,
      }
      sessionStorage.setItem(STORAGE_KEYS.tripPlanMulti, JSON.stringify(multi))
      sessionStorage.setItem(STORAGE_KEYS.tripPlan, JSON.stringify(target))
      autoSaveHistory(requestData, plans, activeType)
    } else if (isValidPlan(data)) {
      sessionStorage.setItem(STORAGE_KEYS.tripPlan, JSON.stringify(data))
      sessionStorage.removeItem(STORAGE_KEYS.tripPlanMulti)
      autoSaveHistory(requestData, [{ plan_type: DEFAULT_PLAN_TYPE, plan_name: '方案一', plan_desc: '', plan: data }], DEFAULT_PLAN_TYPE)
    } else {
      message.error('行程生成结果无效，请稍后重试')
      loading.value = false
      loadingProgress.value = 0
      loadingStatus.value = ''
      return
    }
    message.success('旅行计划生成成功!')
    setTimeout(() => {
      loading.value = false
      loadingProgress.value = 0
      loadingStatus.value = ''
      router.push('/result')
    }, 800)
  }

  // 同步兜底：任务轮询或提交异常时走同步接口（备用路径，逻辑保持旧版一致）
  async function fallbackSyncPlan(reqData: TripFormData) {
    try {
      loadingProgress.value = 30
      loadingStatus.value = '使用同步模式生成...'
      const response = await generateTripPlan(reqData)
      loadingProgress.value = 100
      loadingStatus.value = '完成!'
      if (response.success && (response.data || response.plans?.length)) {
        // 同步接口已支持多方案：优先使用 plans，其次兼容旧版单方案 data
        const plans: PlanItem[] = response.plans?.length ? response.plans : null
        if (plans) {
          const activeType: string = response.active_plan_type || DEFAULT_PLAN_TYPE
          const activePlan = findActivePlan(plans, activeType)
          const target = activePlan?.plan || plans[0]?.plan
          if (target) {
            const multi: TripPlanMulti = { plans, active_plan_type: activeType, request: reqData }
            sessionStorage.setItem(STORAGE_KEYS.tripPlanMulti, JSON.stringify(multi))
            sessionStorage.setItem(STORAGE_KEYS.tripPlan, JSON.stringify(target))
            autoSaveHistory(reqData, plans, activeType)
          }
        } else if (response.data) {
          sessionStorage.setItem(STORAGE_KEYS.tripPlan, JSON.stringify(response.data))
          sessionStorage.removeItem(STORAGE_KEYS.tripPlanMulti)
          autoSaveHistory(reqData, [{ plan_type: DEFAULT_PLAN_TYPE, plan_name: '方案一', plan_desc: '', plan: response.data }], DEFAULT_PLAN_TYPE)
        }
        message.success('旅行计划生成成功!')
        setTimeout(() => router.push('/result'), 500)
      } else {
        message.error(response.message || '生成失败')
      }
    } catch (error: any) {
      message.error(error.message || '生成旅行计划失败，请稍后重试')
    } finally {
      setTimeout(() => {
        loading.value = false
        loadingProgress.value = 0
        loadingStatus.value = ''
      }, 1000)
    }
  }

  try {
    // 提交后台任务（带幂等键，重复提交复用同一任务）
    const { task_id } = await submitTripPlanTask(requestData, idempotencyKey)
    loadingStatus.value = '任务已提交，正在生成...'

    // 轮询任务状态：指数退避（初始1.5s，最大6s），避免大量重复请求造成轮询风暴；
    // 总超时300秒（5分钟）后切同步模式重试
    const POLL_BASE_INTERVAL_MS = 1500
    const POLL_MAX_INTERVAL_MS = 6000
    const POLL_TIMEOUT_MS = 300000
    const pollStart = Date.now()
    let pollFailStreak = 0

    while (true) {
      if (Date.now() - pollStart > POLL_TIMEOUT_MS) {
        message.warning('任务生成耗时较长，已自动切换为同步模式继续生成，请稍候…')
        fallbackSyncPlan(requestData)
        return
      }
      // 指数退避：连续失败时间隔翻倍（1.5s → 3s → 6s封顶），成功时恢复初始间隔
      const backoffMs = Math.min(
        POLL_BASE_INTERVAL_MS * Math.pow(2, pollFailStreak),
        POLL_MAX_INTERVAL_MS
      )
      await new Promise((r) => setTimeout(r, backoffMs))
      let task
      try {
        task = await fetchTripPlanTask(task_id)
        pollFailStreak = 0
      } catch (pollErr) {
        pollFailStreak = Math.min(pollFailStreak + 1, 4)
        console.warn('轮询任务状态失败，指数退避重试:', pollErr)
        continue
      }
      const status: string = task?.status || ''
      // 按任务节点更新进度条与状态文本
      loadingStatus.value = task?.error ? '生成失败：' + task.error : (task?.node || loadingStatus.value)
      for (const [nodeKey, progress] of Object.entries(stepProgress)) {
        if ((task?.node || '').toLowerCase().includes(nodeKey)) {
          loadingProgress.value = progress as number
        }
      }
      if (status === 'success') {
        applyPlanResult(task?.result)
        return
      }
      if (status === 'failed') {
        message.error(task?.error || '行程生成失败，已切换同步模式重试')
        fallbackSyncPlan(requestData)
        return
      }
    }
  } catch (error: any) {
    console.error('提交/轮询任务失败:', error)
    fallbackSyncPlan(requestData)
  }
}


// ========== 新建会话 ==========

// 判断表单是否完全为空（没有任何填写内容）
const isFormEmpty = (): boolean => {
  return (
    !formData.city.trim() &&
    !formData.origin.trim() &&
    !formData.start_date &&
    !formData.end_date &&
    formData.preferences.length === 0 &&
    !formData.free_text_input.trim() &&
    multiCityList.value.length === 0
  )
}

// 重置表单为初始状态
const resetForm = () => {
  formData.city = ''
  formData.city_list = null
  formData.start_date = null
  formData.end_date = null
  formData.travel_days = 1
  formData.transportation = '公共交通'
  formData.accommodation = '经济型酒店'
  formData.preferences = []
  formData.free_text_input = ''
  formData.origin = ''
  formData.adults = 1
  formData.children = 0
  formData.plan_type = ''
  formData.plan_count = DEFAULT_PLAN_COUNT
  isMultiCity.value = false
  multiCityList.value = []
}

// ========== 方案数量（默认3个，最多3个，最少1个） ==========
const increasePlanCount = () => {
  if (formData.plan_count < MAX_PLAN_COUNT) formData.plan_count += 1
}
const decreasePlanCount = () => {
  if (formData.plan_count > MIN_PLAN_COUNT) formData.plan_count -= 1
}

// 新建会话：保存当前填写到一半的废弃会话（不删除），然后清空表单重新开始
async function handleNewSession() {
  try {
    if (!isFormEmpty()) {
      // 组装废弃会话的请求参数（日期转为字符串）
      const requestData: Record<string, any> = {
        city: formData.city,
        city_list: isMultiCity.value
          ? multiCityList.value.map((item) => ({ city_name: item.city_name, stay_days: item.stay_days }))
          : null,
        start_date: formData.start_date ? formData.start_date.format('YYYY-MM-DD') : '',
        end_date: formData.end_date ? formData.end_date.format('YYYY-MM-DD') : '',
        travel_days: formData.travel_days,
        transportation: formData.transportation,
        accommodation: formData.accommodation,
        preferences: formData.preferences,
        free_text_input: formData.free_text_input,
        origin: formData.origin,
        adults: formData.adults,
        children: formData.children,
        plan_type: formData.plan_type,
        plan_count: formData.plan_count || DEFAULT_PLAN_COUNT,
      }

      // 带上当前已有的方案（如果有）
      let plans: PlanItem[] = []
      const multiRaw = sessionStorage.getItem(STORAGE_KEYS.tripPlanMulti)
      if (multiRaw) {
        try {
          const multi = JSON.parse(multiRaw)
          plans = multi.plans || []
        } catch (e) { /* ignore */ }
      } else {
        const planRaw = sessionStorage.getItem(STORAGE_KEYS.tripPlan)
        if (planRaw) {
          try {
            plans = [{ plan_type: DEFAULT_PLAN_TYPE, plan_name: '方案一', plan_desc: '', plan: JSON.parse(planRaw) }]
          } catch (e) { /* ignore */ }
        }
      }

      const cityName = isMultiCity.value
        ? multiCityList.value.map((item) => item.city_name.trim()).filter(Boolean).join('/')
        : formData.city.trim()
      const title = `[未完成] ${cityName || '草稿'} ${formData.travel_days}天`

      // 未登录不允许持久化：废弃会话不写入历史记录，仅一次性使用
      if (isLoggedIn.value) {
        await saveHistory({
          title,
          request_data: requestData,
          plans,
          active_plan_type: formData.plan_type || DEFAULT_PLAN_TYPE,
        })
        message.success('已保存废弃会话到历史记录')
      }
    }
  } catch (e) {
    console.error('保存废弃会话失败:', e)
  }

  // 清空表单，开始新会话
  resetForm()
  historySidebarRef.value?.refresh()
  message.info('已新建会话，请重新填写')
}

// ========== 历史会话记录 ==========

// 自动保存历史记录（生成方案成功后调用），并刷新侧边栏
async function autoSaveHistory(requestData: TripFormData, plans: PlanItem[], activeType: string) {
  // 未登录不允许持久化历史：方案仅为一次性使用
  if (!isLoggedIn.value) {
    console.log('[history] 未登录，跳过历史记录持久化（仅一次性使用）')
    return
  }
  try {
    await saveHistory({
      request_data: requestData as unknown as Record<string, any>,
      plans,
      active_plan_type: activeType || DEFAULT_PLAN_TYPE,
    })
    historySidebarRef.value?.refresh()
  } catch (e) {
    console.error('自动保存历史记录失败:', e)
  }
}

// 点击历史记录：加载方案并跳转到结果页
async function onSelectHistory(item: HistoryItem) {
  try {
    // 列表数据已含 plans；若缺失则拉取详情
    let record = item
    if (!record.plans || record.plans.length === 0) {
      const detail = await fetchHistoryDetail(item.id)
      if (detail) record = detail
    }
    const plans: PlanItem[] = record.plans || []
    if (plans.length === 0) {
      message.warning('该历史记录没有可用的方案数据')
      return
    }
    const activeType = record.active_plan_type || DEFAULT_PLAN_TYPE
    const activePlan = findActivePlan(plans, activeType)
    const multi: TripPlanMulti = {
      plans,
      active_plan_type: activeType,
      request: record.request_data || {},
    }
    sessionStorage.setItem(STORAGE_KEYS.tripPlanMulti, JSON.stringify(multi))
    sessionStorage.setItem(STORAGE_KEYS.tripPlan, JSON.stringify(activePlan?.plan || plans[0].plan))
    message.success('已加载历史方案')
    router.push('/result')
  } catch (e) {
    console.error('加载历史记录失败:', e)
    message.error('加载历史记录失败')
  }
}
</script>

<style>
/* 全局重置 */
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
}
</style>

<style scoped>
.home-container {
  width: 100vw;
  margin-left: calc(50% - 50vw);
  min-height: 100vh;
}

.banner-area {
  position: relative;
  background: linear-gradient(135deg, #7b73e8 0%, #6b49b8 100%);
  padding: 50px 40px 100px;
  overflow: hidden;
  text-align: center;
  min-height: 100vh;
}

.decor-circle {
  position: absolute;
  border-radius: 50%;
  background: rgba(255,255,255,0.06);
  pointer-events: none;
}
.decor-circle-1 {
  width: 320px;
  height: 320px;
  top: -80px;
  left: -80px;
}
.decor-circle-2 {
  width: 200px;
  height: 200px;
  bottom: 60px;
  right: 80px;
  background: rgba(255,255,255,0.04);
}

.plane-icon {
  font-size: 72px;
  margin-bottom: 16px;
  display: inline-block;
  animation: planeFly 3.5s ease-in-out infinite;
  filter: drop-shadow(0 4px 12px rgba(0,0,0,0.15));
}
@keyframes planeFly {
  0%, 100% { transform: translateY(0) rotate(0deg) scale(1); }
  20% { transform: translateY(-20px) rotate(-8deg) scale(1.05); }
  40% { transform: translateY(-6px) rotate(5deg) scale(1); }
  60% { transform: translateY(-18px) rotate(-4deg) scale(1.03); }
  80% { transform: translateY(-8px) rotate(3deg) scale(1); }
}

.main-title {
  margin: 0 0 14px;
  font-size: 56px;
  font-weight: 700;
  color: #fff;
  text-shadow: 2px 2px 14px rgba(0,0,0,0.4);
  letter-spacing: 6px;
}
.sub-title {
  color: rgba(255,255,255,0.92);
  margin: 0 0 50px;
  font-size: 18px;
  letter-spacing: 1px;
}

.main-card {
  position: relative;
  z-index: 5;
  max-width: 1400px;
  margin: 0 auto;
  background: #fff;
  border-radius: 24px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
  padding: 40px 48px;
  text-align: left;
}

.section-card {
  background: #fff;
  border: 1px solid #f0f0f0;
  border-radius: 16px;
  padding: 28px 32px;
  margin-bottom: 28px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  transition: box-shadow 0.3s;
}
.section-card:hover {
  box-shadow: 0 4px 16px rgba(0,0,0,0.06);
}
.section-card:last-of-type {
  margin-bottom: 16px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 2px;
}
.section-icon {
  font-size: 18px;
}
.section-title {
  font-size: 18px;
  font-weight: 600;
  color: #333;
}

.section-divider {
  height: 2px;
  background: linear-gradient(90deg, #667eea, #764ba2);
  margin: 14px 0 20px;
  border-radius: 1px;
  opacity: 0.5;
}

.form-item-wrap {
  display: flex;
  flex-direction: column;
}
.label-required, .label-small {
  font-size: 14px;
  color: #555;
  margin-bottom: 6px;
}
.label-required {
  display: flex;
  align-items: center;
  gap: 2px;
}
.star {
  color: #ff4d4f;
  font-size: 14px;
}

.row-single-city {
  display: flex;
  align-items: flex-end;
  gap: 20px;
  flex-wrap: wrap;
}
.input-city {
  flex: 1.2;
  min-width: 260px;
}
.date-group {
  display: flex;
  gap: 16px;
  align-items: flex-end;
  flex: 2;
  flex-wrap: wrap;
}
.date-item {
  flex: 1;
  min-width: 180px;
}

.days-badge-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.days-label {
  font-size: 13px;
  color: #666;
  margin-bottom: 6px;
  white-space: nowrap;
}
.days-badge {
  min-width: 110px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 20px;
  background: linear-gradient(90deg, #667eea, #764ba2);
  color: white;
  gap: 4px;
  font-size: 14px;
}
.days-badge .num {
  font-size: 20px;
  font-weight: bold;
}

.multi-date-row {
  margin-top: 16px;
}
.multi-city-box {
  border: 1px dashed #b4b0e2;
  border-radius: 10px;
  padding: 14px;
}
.city-item {
  display: flex;
  gap: 10px;
  margin-bottom: 10px;
  align-items: center;
}

.switch-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 16px;
  font-size: 14px;
  color: #555;
}

.preference-checkbox-group {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 24px;
}
.preference-checkbox-group :deep(.ant-checkbox-wrapper) {
  margin-left: 0 !important;
  font-size: 14px;
  color: #444;
}

.submit-btn {
  height: 52px;
  font-size: 17px;
  border: none;
  border-radius: 26px;
  background: linear-gradient(90deg, #667eea, #764ba2);
  font-weight: 600;
  letter-spacing: 1px;
}

.loading-wrap {
  margin-top: 16px;
}
.loading-text, .tool-text {
  text-align: center;
  margin: 6px 0;
  color: #666;
}

/* 新增：出行信息提示与方案选择 */
.children-hint {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}
.plan-hint {
  font-size: 12px;
  color: #999;
  margin-top: 6px;
}

/* 方案数量步进器 */
.plan-count-stepper {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 6px;
}
.plan-count-btn {
  width: 40px;
  height: 40px;
  font-size: 20px;
  font-weight: 700;
  border-radius: 8px;
  color: #6b49b8;
  border-color: #d8ccf5;
  background: #fff;
}
.plan-count-btn:hover {
  color: #fff;
  border-color: transparent;
  background: linear-gradient(180deg, #7b73e8, #6b49b8);
}
.plan-count-value {
  font-size: 18px;
  font-weight: 600;
  color: #333;
  min-width: 56px;
  text-align: center;
}

/* 新建会话按钮栏 */
.new-session-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  justify-content: flex-end;
}
.new-session-btn {
  background: linear-gradient(180deg, #7b73e8, #6b49b8) !important;
  border-color: transparent !important;
  color: #fff !important;
  font-size: 16px;
  font-weight: 600;
  height: 40px;
  padding: 0 20px;
  border-radius: 8px;
  box-shadow: 0 4px 14px rgba(107, 73, 184, 0.35);
}
.new-session-btn:hover {
  background: linear-gradient(180deg, #8b83f0, #7b59c8) !important;
  border-color: transparent !important;
  color: #fff !important;
}
.new-session-hint {
  font-size: 12px;
  color: #999;
}

/* 用户登录区域 */
.user-area {
  position: absolute;
  top: 16px;
  right: 20px;
  z-index: 5;
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-name {
  color: #fff;
  font-size: 14px;
  font-weight: 500;
}

/* 登录/注册按钮：放大 */
.login-btn {
  height: 38px;
  padding: 0 22px;
  font-size: 15px;
  font-weight: 600;
  color: #6b49b8 !important;
  border-color: #d8ccf5 !important;
  background: rgba(255, 255, 255, 0.92) !important;
  border-radius: 8px;
}
.login-btn:hover {
  color: #fff !important;
  border-color: transparent !important;
  background: linear-gradient(180deg, #7b73e8, #6b49b8) !important;
}

/* 未登录降级提示条 */
.anon-notice {
  margin-bottom: 14px;
  padding: 12px 16px;
  border-radius: 8px;
  background: #fdf0f0;
  border: 1px solid #f5c6c6;
  color: #c0392b;
  font-size: 15px;
  line-height: 1.8;
  font-weight: 500;
}

/* 登录/注册弹窗：紫色背景、放大字体 */
.auth-modal-wrap .ant-modal-content {
  background: linear-gradient(180deg, #7b73e8, #6b49b8) !important;
  border-radius: 14px;
  padding: 26px 28px;
}
.auth-modal-wrap .ant-modal-header {
  background: transparent !important;
  border-bottom: none !important;
}
.auth-modal-wrap .ant-modal-title {
  color: #fff !important;
  font-size: 22px !important;
  font-weight: 600;
  text-align: center;
}
.auth-modal-wrap .ant-modal-close {
  color: rgba(255, 255, 255, 0.85) !important;
}
.auth-modal-hint {
  text-align: center;
  color: #fff;
  font-size: 14px;
  margin-bottom: 10px;
  padding: 7px 10px;
  background: rgba(255, 255, 255, 0.18);
  border-radius: 8px;
}
.auth-modal-wrap .ant-tabs-tab {
  color: rgba(255, 255, 255, 0.75) !important;
  font-size: 16px !important;
}
.auth-modal-wrap .ant-tabs-tab-active .ant-tabs-tab-btn {
  color: #fff !important;
  font-weight: 600;
}
.auth-modal-wrap .ant-tabs-ink-bar {
  background: #fff !important;
}
.auth-modal-wrap .ant-form-item-label > label {
  color: #fff !important;
  font-size: 14px;
}
.auth-modal-wrap .auth-input,
.auth-modal-wrap .ant-input-password {
  height: 44px !important;
  display: flex !important;
  align-items: center !important;
  font-size: 15px;
  border-radius: 8px;
}
.auth-modal-wrap .auth-submit-btn {
  height: 46px;
  font-size: 17px;
  font-weight: 600;
  border-radius: 8px;
  background: #fff !important;
  border-color: #fff !important;
  color: #6b49b8 !important;
}
.auth-modal-wrap .auth-submit-btn:hover {
  background: #f3efff !important;
  border-color: #f3efff !important;
  color: #6b49b8 !important;
}
</style>