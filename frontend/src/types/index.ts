// 类型定义

export interface Location {
  longitude: number
  latitude: number
}

export interface Attraction {
  name: string
  address: string
  location: Location
  visit_duration: number
  description: string
  category?: string
  rating?: number
  image_url?: string
  ticket_price?: number
}

export interface Meal {
  type: 'breakfast' | 'lunch' | 'dinner' | 'snack'
  name: string
  address?: string
  location?: Location
  description?: string
  estimated_cost?: number
}

export interface Hotel {
  name: string
  address: string
  location?: Location
  price_range: string
  rating: string
  distance: string
  type: string
  estimated_cost?: number
}

export interface Budget {
  total_attractions: number
  total_hotels: number
  total_meals: number
  total_transportation: number
  total: number
}

export interface DayPlan {
  date: string
  day_index: number
  // ✅ 新增：每日归属城市，单/多城市都返回
  city_name: string
  description: string
  transportation: string
  accommodation: string
  hotel?: Hotel
  attractions: Attraction[]
  meals: Meal[]
}

export interface WeatherInfo {
  date: string
  day_weather: string
  night_weather: string
  day_temp: number
  night_temp: number
  wind_direction: string
  wind_power: string
}

// ✅ 多城市子项类型
export interface CityItem {
  city_name: string
  stay_days: number
}

export interface TripPlan {
  city: string
  // ✅ 新增：多城市返回时携带城市列表，单城市为 null
  city_list: CityItem[] | null
  // ✅ 新增：出发地点（返程回到该地点）
  origin?: string
  start_date: string
  end_date: string
  days: DayPlan[]
  weather_info: WeatherInfo[]
  overall_suggestions: string
  budget?: Budget
}

export interface TripFormData {
  city: string
  // ✅ 新增：多城市请求字段，单城市传 null
  city_list: CityItem[] | null
  start_date: string
  end_date: string
  travel_days: number
  transportation: string
  accommodation: string
  preferences: string[]
  free_text_input: string
  // ✅ 新增：出发地点（不为空）、成人人数(>=1)、儿童人数(>=0)、方案类型、方案数量(1-3)
  origin: string
  adults: number
  children: number
  plan_type: string
  plan_count: number
}

// 方案指标：由后端按真实数据计算（通勤总时长/总花费），用于切换条展示
export interface PlanMetrics {
  commute_minutes: number
  total_cost: number
  day_count?: number
}

// ✅ 新增：单个方案项（三方案之一）
export interface PlanItem {
  plan_type: string
  plan_name: string
  plan_desc: string
  plan: TripPlan
  plan_metrics?: PlanMetrics
}

// ✅ 新增：多方案数据（/result 页面自由切换）
export interface TripPlanMulti {
  plans: PlanItem[]
  active_plan_type: string
  request?: Record<string, any>
}

// ✅ 新增：历史会话记录
export interface HistoryItem {
  id: number
  title: string
  request_data: Record<string, any>
  plans: PlanItem[]
  active_plan_type: string
  created_at: string
  updated_at: string
}

export interface HistoryListData {
  items: HistoryItem[]
  total: number
  page: number
  page_size: number
}

export interface TripPlanResponse {
  success: boolean
  message: string
  data?: TripPlan
  plans?: PlanItem[]
  active_plan_type?: string
}