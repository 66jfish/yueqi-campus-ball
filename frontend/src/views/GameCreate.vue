<script setup>
/**
 * 发起球局表单页
 * 校验要求（需求指定）：
 *   1) 时间不能选过去（日期选择器禁用今天之前的日期 + 提交前再次校验）
 *   2) 人数上限（2-50，且不晚于下限）
 *   3) 必填项（球类/标题/场地/开球时间/结束时间）
 *   4) 提交按钮 loading 防重复提交
 * 冲突类错误（场地冲突 / 时间冲突）由后端返回，统一拦截器已用 Toast 展示原文提示
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { gameApi } from '@/api'

const router = useRouter()
const formRef = ref()
const submitting = ref(false)

const SPORTS = [
  { value: 1, label: '篮球' },
  { value: 2, label: '足球' },
  { value: 3, label: '羽毛球' },
  { value: 4, label: '网球' },
  { value: 5, label: '排球' },
  { value: 6, label: '乒乓球' }
]

const form = reactive({
  sport_type: 3,
  title: '',
  description: '',
  campus: '老校区',
  venue_name: '',
  venue_address: '',
  start_time: '',
  end_time: '',
  signup_deadline: '',
  checkin_start_time: '',
  checkin_end_time: '',
  max_players: 8,
  min_players: 2,
  fee_type: 0,
  fee_amount: null,
  skill_level_limit: 0,
  gender_limit: 0,
  min_credit_score: 0
})

const now = new Date()
/** 校外：场地为自由输入（球馆名/地址） */
const isOffCampus = computed(() => form.campus === '校外')
/** 结束时间不早于开始时间 */
const endDisabled = (date) =>
  !form.start_time || date.getTime() < new Date(String(form.start_time)).setHours(0, 0, 0, 0)

const rules = {
  sport_type: [{ required: true, message: '请选择球类', trigger: 'change' }],
  title: [
    { required: true, message: '请填写球局标题', trigger: 'blur' },
    { min: 2, max: 64, message: '标题 2-64 字', trigger: 'blur' }
  ],
  venue_name: [{ required: true, message: '请填写场地名称（同场地冲突校验需要）', trigger: 'blur' }],
  start_time: [
    { required: true, message: '请选择开球时间', trigger: 'change' },
    {
      validator: (_r, v, cb) => {
        if (!v) return cb()
        return new Date(String(v)).getTime() < Date.now() - 60 * 1000
          ? cb(new Error('开球时间不能早于当前时间'))
          : cb()
      },
      trigger: 'change'
    }
  ],
  end_time: [
    { required: true, message: '请选择结束时间', trigger: 'change' },
    {
      validator: (_r, v, cb) => {
        if (!v || !form.start_time) return cb()
        return new Date(String(v)) <= new Date(String(form.start_time))
          ? cb(new Error('结束时间必须晚于开球时间'))
          : cb()
      },
      trigger: 'change'
    }
  ],
  max_players: [
    { required: true, message: '请填写最大人数', trigger: 'change' },
    {
      validator: (_r, v, cb) => {
        if (v == null) return cb()
        if (v < 2) return cb(new Error('最大人数至少 2 人'))
        if (v > 50) return cb(new Error('最大人数不能超过 50 人'))
        if (v < form.min_players) return cb(new Error('最大人数不能小于最少成局人数'))
        return cb()
      },
      trigger: 'change'
    }
  ],
  min_players: [{ required: true, message: '请填写最少成局人数', trigger: 'change' }],
  fee_amount: [
    {
      validator: (_r, v, cb) =>
        form.fee_type === 1 && (v == null || v < 0) ? cb(new Error('AA 制请填写人均费用')) : cb(),
      trigger: 'change'
    }
  ]
}

const feeTip = computed(() =>
  form.fee_type === 0 ? '免费组织，费用自付' : `人均 ¥${form.fee_amount || 0}，现场 AA`
)

/** 提交前把 datetime 统一成后端格式 YYYY-MM-DDTHH:mm:ss */
function toApi(v) {
  if (!v) return null
  const d = new Date(String(v))
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:00`
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = {
      ...form,
      start_time: toApi(form.start_time),
      end_time: toApi(form.end_time),
      signup_deadline: toApi(form.signup_deadline),
      checkin_start_time: toApi(form.checkin_start_time),
      checkin_end_time: toApi(form.checkin_end_time),
      description: form.description || null,
      fee_amount: form.fee_type === 1 ? form.fee_amount : null
    }
    const game = await gameApi.create(payload)
    ElMessage.success('球局创建成功')
    router.replace({ name: 'game-detail', params: { id: game.id } })
  } catch (e) {
    // 场地/时间冲突等业务错误：弹窗展示后端完整提示，便于用户直接处理
    if (e?.code === 40900) {
      ElMessageBox.alert(e.message, '发起失败', { confirmButtonText: '去修改', type: 'warning' }).catch(() => {})
    }
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="page">
    <div class="section-head">
      <h2 class="t-section">发起球局</h2>
      <span class="t-meta">填好后点「发布球局」，同场地同时段会被自动拦截</span>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :md="15">
        <el-form ref="formRef" :model="form" :rules="rules" label-position="top" size="large" class="card">
          <el-form-item label="球类" prop="sport_type">
            <el-radio-group v-model="form.sport_type">
              <el-radio-button v-for="s in SPORTS" :key="s.value" :value="s.value">{{ s.label }}</el-radio-button>
            </el-radio-group>
          </el-form-item>

          <el-form-item label="球局标题" prop="title">
            <el-input v-model="form.title" maxlength="64" show-word-limit placeholder="请填写球局标题" />
          </el-form-item>

          <el-form-item label="球局描述">
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="水平要求、装备要求、注意事项…"
            />
          </el-form-item>

          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="校区">
                <el-select v-model="form.campus" style="width: 100%">
                  <el-option label="老校区" value="老校区" />
                  <el-option label="新校区" value="新校区" />
                  <el-option label="校外" value="校外" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item :label="isOffCampus ? '球馆 / 地址（自填）' : '场地名称'" prop="venue_name">
                <el-input
                  v-model="form.venue_name"
                  :placeholder="isOffCampus ? '请填写校外球馆名称或详细地址' : '请填写校内场地名称'"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="详细地址">
            <el-input v-model="form.venue_address" placeholder="选填，便于定位打卡" />
          </el-form-item>

          <el-row :gutter="12">
            <el-col :xs="24" :sm="12">
              <el-form-item label="开球时间" prop="start_time">
                <el-date-picker
                  v-model="form.start_time"
                  type="datetime"
                  placeholder="选择开球时间"
                  style="width: 100%"
                  :disabled-date="(d) => d.getTime() < new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="结束时间" prop="end_time">
                <el-date-picker
                  v-model="form.end_time"
                  type="datetime"
                  placeholder="选择结束时间"
                  style="width: 100%"
                  :disabled-date="endDisabled"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="报名截止时间">
                <el-date-picker
                  v-model="form.signup_deadline"
                  type="datetime"
                  placeholder="不填则不限制"
                  style="width: 100%"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="核销开放时间">
                <el-date-picker
                  v-model="form.checkin_start_time"
                  type="datetime"
                  placeholder="默认开球前 30 分钟"
                  style="width: 100%"
                  value-format="YYYY-MM-DDTHH:mm:ss"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-row :gutter="12">
            <el-col :xs="12" :sm="8">
              <el-form-item label="最大人数" prop="max_players">
                <el-input-number v-model="form.max_players" :min="2" :max="50" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="12" :sm="8">
              <el-form-item label="最少成局人数" prop="min_players">
                <el-input-number v-model="form.min_players" :min="2" :max="50" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="8">
              <el-form-item label="费用">
                <el-radio-group v-model="form.fee_type">
                  <el-radio :value="0">免费</el-radio>
                  <el-radio :value="1">AA 制</el-radio>
                </el-radio-group>
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item v-if="form.fee_type === 1" label="人均费用（元）" prop="fee_amount">
            <el-input-number v-model="form.fee_amount" :min="0" :precision="2" style="width: 200px" />
            <span class="t-caption fee-tip">{{ feeTip }}</span>
          </el-form-item>
        </el-form>
      </el-col>

      <el-col :xs="24" :md="9">
        <div class="card side">
          <h3 class="t-card-title">报名门槛（可选）</h3>
          <el-form label-position="top">
            <el-form-item label="最低水平要求">
              <el-select v-model="form.skill_level_limit" style="width: 100%">
                <el-option label="不限" :value="0" />
                <el-option label="初级" :value="2" />
                <el-option label="中级" :value="3" />
                <el-option label="高级" :value="4" />
                <el-option label="大神" :value="5" />
              </el-select>
            </el-form-item>
            <el-form-item label="性别限制">
              <el-radio-group v-model="form.gender_limit">
                <el-radio-button :value="0">不限</el-radio-button>
                <el-radio-button :value="1">仅男生</el-radio-button>
                <el-radio-button :value="2">女生友好</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="最低信誉分">
              <el-slider v-model="form.min_credit_score" :min="0" :max="140" :step="10" show-input />
            </el-form-item>
          </el-form>

          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="发布后会做三项校验"
            description="① 同场地同时段冲突 ② 你自己在该时段是否已报名其它球局 ③ 时间/人数合法性"
          />

          <el-button
            type="primary"
            size="large"
            round
            class="side__submit"
            :loading="submitting"
            @click="submit"
          >
            {{ submitting ? '发布中…' : '发布球局' }}
          </el-button>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.card {
  padding: var(--sp-5);
}
.side {
  position: sticky;
  top: calc(var(--top-h) + 16px);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.side__submit {
  width: 100%;
  margin-top: var(--sp-3);
}
.fee-tip {
  margin-left: 10px;
}
</style>
