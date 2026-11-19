<script setup>
/**
 * 登录 / 注册页（单页切换，沿用设计稿视觉：暖米背景 + 橙色主按钮 + 大圆角卡片）
 * 表单校验：学号格式、密码长度、两次密码一致；提交按钮 loading 防重复
 */
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import CatIcon from '@/components/CatIcon.vue'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const mode = ref('login') // login | register
const loading = ref(false)
const loginFormRef = ref()
const registerFormRef = ref()

const loginForm = reactive({ account: '', password: '' })
const registerForm = reactive({
  student_no: '',
  nickname: '',
  password: '',
  confirm: '',
  phone: '',
  campus: '东校区',
  college: '',
  gender: 1,
  skill_level: 3
})

const loginRules = {
  account: [
    { required: true, message: '请输入学号或手机号', trigger: 'blur' },
    { min: 3, max: 64, message: '长度 3-64 位', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度 6-64 位', trigger: 'blur' }
  ]
}

const registerRules = {
  student_no: [
    { required: true, message: '请输入学号', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9]{3,32}$/, message: '学号为 3-32 位字母或数字', trigger: 'blur' }
  ],
  nickname: [
    { required: true, message: '请输入昵称', trigger: 'blur' },
    { min: 1, max: 32, message: '昵称 1-32 字', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请设置密码', trigger: 'blur' },
    { min: 6, max: 64, message: '密码长度 6-64 位', trigger: 'blur' }
  ],
  confirm: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_r, v, cb) => (v === registerForm.password ? cb() : cb(new Error('两次输入的密码不一致'))),
      trigger: 'blur'
    }
  ],
  phone: [{ pattern: /^1\d{10}$/, message: '请输入 11 位手机号', trigger: 'blur' }],
  skill_level: [{ required: true, message: '请选择球技水平', trigger: 'change' }]
}

const submitText = computed(() => (mode.value === 'login' ? '登录' : '注册并登录'))

async function onLogin() {
  await loginFormRef.value.validate()
  loading.value = true
  try {
    await store.login(loginForm.account, loginForm.password)
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || '/')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  await registerFormRef.value.validate()
  loading.value = true
  try {
    const { confirm, ...payload } = registerForm
    await store.register({ ...payload, phone: payload.phone || null })
    ElMessage.success('注册成功，正在为你登录')
    await store.login(registerForm.student_no, registerForm.password)
    router.replace(route.query.redirect || '/')
  } catch (e) {
    /* 拦截器已提示 */
  } finally {
    loading.value = false
  }
}

function switchMode() {
  mode.value = mode.value === 'login' ? 'register' : 'login'
}
</script>

<template>
  <div class="page auth">
    <!-- 左侧品牌区（桌面）+ 右侧表单卡（移动端上下堆叠） -->
    <el-row :gutter="20" align="middle">
      <el-col :xs="24" :md="11" class="auth__brand-col">
        <div class="auth__brand">
          <CatIcon :size="56" color="#DB9A64" />
          <h1 class="t-hero">和校猫一起<br />约一场不掉线的球</h1>
          <p class="t-body">在月球，找到你的约球搭子 —— 签到核销、失信小黑屋、AI 信誉画像，一个都不少。</p>
          <ul class="auth__points">
            <li><span class="pill pill--green">签到 +2</span>按时到场，信誉分会慢慢涨</li>
            <li><span class="pill pill--danger">缺席 -10</span>放鸽子会被关进小黑屋禁赛 3 天</li>
            <li><span class="pill pill--blue">退出 -2</span>来不了请提前请假，别硬扛</li>
          </ul>
        </div>
      </el-col>

      <el-col :xs="24" :md="13">
        <div class="card auth__card">
          <div class="auth__tabs">
            <button :class="{ 'is-active': mode === 'login' }" @click="mode = 'login'">登录</button>
            <button :class="{ 'is-active': mode === 'register' }" @click="mode = 'register'">注册</button>
          </div>

          <!-- 登录 -->
          <el-form
            v-if="mode === 'login'"
            ref="loginFormRef"
            :model="loginForm"
            :rules="loginRules"
            label-position="top"
            size="large"
            @submit.prevent="onLogin"
          >
            <el-form-item label="学号 / 手机号" prop="account">
              <el-input v-model="loginForm.account" placeholder="如 20230001" clearable>
                <template #prefix><el-icon><User /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-form-item label="密码" prop="password">
              <el-input
                v-model="loginForm.password"
                type="password"
                show-password
                placeholder="6-64 位"
                @keyup.enter="onLogin"
              >
                <template #prefix><el-icon><Lock /></el-icon></template>
              </el-input>
            </el-form-item>
            <el-button type="primary" size="large" round class="auth__submit" :loading="loading" @click="onLogin">
              {{ loading ? '登录中…' : '登录' }}
            </el-button>
            <p class="auth__tip">
              还没有账号？<a @click="switchMode">立即注册</a>
            </p>
          </el-form>

          <!-- 注册 -->
          <el-form
            v-else
            ref="registerFormRef"
            :model="registerForm"
            :rules="registerRules"
            label-position="top"
            size="large"
          >
            <el-row :gutter="12">
              <el-col :xs="24" :sm="12">
                <el-form-item label="学号" prop="student_no">
                  <el-input v-model="registerForm.student_no" placeholder="校内唯一" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="昵称" prop="nickname">
                  <el-input v-model="registerForm.nickname" placeholder="球局里展示的名字" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="密码" prop="password">
                  <el-input v-model="registerForm.password" type="password" show-password placeholder="6-64 位" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="确认密码" prop="confirm">
                  <el-input v-model="registerForm.confirm" type="password" show-password placeholder="再次输入" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="手机号（选填）" prop="phone">
                  <el-input v-model="registerForm.phone" placeholder="可作为登录账号" />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="校区" prop="campus">
                  <el-select v-model="registerForm.campus" style="width: 100%">
                    <el-option label="东校区" value="东校区" />
                    <el-option label="西校区" value="西校区" />
                    <el-option label="南区" value="南区" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="性别" prop="gender">
                  <el-radio-group v-model="registerForm.gender">
                    <el-radio :value="1">男</el-radio>
                    <el-radio :value="2">女</el-radio>
                    <el-radio :value="0">不填</el-radio>
                  </el-radio-group>
                </el-form-item>
              </el-col>
              <el-col :xs="24" :sm="12">
                <el-form-item label="球技水平" prop="skill_level">
                  <el-select v-model="registerForm.skill_level" style="width: 100%">
                    <el-option label="新手" :value="1" />
                    <el-option label="初级" :value="2" />
                    <el-option label="中级" :value="3" />
                    <el-option label="高级" :value="4" />
                    <el-option label="大神" :value="5" />
                  </el-select>
                </el-form-item>
              </el-col>
            </el-row>
            <el-button
              type="primary"
              size="large"
              round
              class="auth__submit"
              :loading="loading"
              @click="onRegister"
            >
              {{ loading ? '注册中…' : submitText }}
            </el-button>
            <p class="auth__tip">注册即表示同意《校园约球文明公约》</p>
          </el-form>
        </div>
      </el-col>
    </el-row>
  </div>
</template>

<style scoped lang="scss">
.auth {
  padding-top: var(--sp-6);
}
.auth__brand-col {
  margin-bottom: var(--sp-5);
}
.auth__brand {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.auth__points {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  color: var(--c-text-sub);
}
.auth__points li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.auth__card {
  padding: var(--sp-5);
}
.auth__tabs {
  display: flex;
  gap: 6px;
  background: var(--c-primary-tint);
  border-radius: var(--r-pill);
  padding: 4px;
  margin-bottom: var(--sp-4);
}
.auth__tabs button {
  flex: 1;
  border: none;
  background: transparent;
  height: 38px;
  border-radius: var(--r-pill);
  font-size: 14px;
  font-weight: 700;
  color: var(--c-text-sub);
  cursor: pointer;
  transition: all 0.16s ease;
}
.auth__tabs button.is-active {
  background: var(--c-primary);
  color: #fff;
  box-shadow: var(--sh-primary);
}
.auth__submit {
  width: 100%;
  margin-top: 4px;
}
.auth__tip {
  text-align: center;
  font-size: 12.5px;
  color: var(--c-text-muted);
  margin: 12px 0 0;
}
</style>
