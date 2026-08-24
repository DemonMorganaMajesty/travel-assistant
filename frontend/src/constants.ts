// 前端业务常量：可修改参数统一提取到这里
import type { PlanItem } from '@/types'

// ============ 方案类型（最多三个方案，统一展示为 方案一/方案二/方案三） ============
export const PLAN_TYPE_OPTIONS: Array<{
  value: string
  label: string
  desc: string
}> = [
  { value: 'plan_1', label: '方案一', desc: '第1套旅行方案（基础完整优化）' },
  { value: 'plan_2', label: '方案二', desc: '第2套旅行方案（在前序方案基础上进一步优化）' },
  { value: 'plan_3', label: '方案三', desc: '第3套旅行方案（在前两套基础上继续拉向最优）' },
]

export const DEFAULT_PLAN_TYPE = 'plan_1'

// 生成方案数量：默认3个，最少1个，最多3个
export const DEFAULT_PLAN_COUNT = 3
export const MIN_PLAN_COUNT = 1
export const MAX_PLAN_COUNT = 3

// 方案数量选择提示文案
export const AUTO_PLAN_HINT = '默认生成3个方案，最少1个、最多3个，可在结果页自由切换'

// ============ 历史会话记录 ============
export const HISTORY_PAGE_SIZE = 10 // 每页最多10条
export const HISTORY_STORAGE_KEY = 'tripHistoryCache'

// ============ 存储键 ============
export const STORAGE_KEYS = {
  tripPlan: 'tripPlan', // 当前激活的单方案
  tripPlanMulti: 'tripPlanMulti', // 三方案数据
}

// ============ 出行人员限制 ============
export const MIN_ADULTS = 1
export const MIN_CHILDREN = 0
export const MAX_ADULTS = 50
export const MAX_CHILDREN = 50

// ============ 工具函数 ============
// 根据方案类型取展示名称
export function planTypeName(planType: string): string {
  const found = PLAN_TYPE_OPTIONS.find((item) => item.value === planType)
  return found ? found.label.replace(/^[^\u4e00-\u9fa5]*/, '') : planType
}

// 根据方案列表找默认激活方案
export function findActivePlan(plans: PlanItem[], activeType?: string): PlanItem | null {
  if (!plans || plans.length === 0) return null
  const target = plans.find((p) => p.plan_type === activeType)
  return target || plans[0] || null
}
