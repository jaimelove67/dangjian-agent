<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '@/api/http'
import AppIcon from '@/components/AppIcon.vue'
import { session } from '@/stores/session'

/**
 * 登录页。
 *
 * 版面决策（编辑式浅色，非营销页）：
 *   左栏是"文件封面"式的品牌与合规声明区，右栏是表单。
 *   刻意不做：居中卡片 + 渐变背景 + 大插画 —— 那是 SaaS 落地页套路。
 *   移动端：左栏收起为顶部标题块，表单优先。
 *
 * 不预填任何账号密码。既有的 frontend-test 里硬编码了 admin/admin123，
 * 这是明确要修掉的问题：凭据出现在源码里既不合规也误导使用者。
 */

const route = useRoute()
const router = useRouter()

const form = reactive({ username: '', password: '' })
const submitting = ref(false)
const errorMessage = ref('')
const showPassword = ref(false)

const touched = reactive({ username: false, password: false })

const usernameError = computed(() => {
  if (!touched.username) return ''
  if (!form.username.trim()) return '请输入用户名'
  return ''
})

const passwordError = computed(() => {
  if (!touched.password) return ''
  if (!form.password) return '请输入密码'
  return ''
})

const canSubmit = computed(
  () => form.username.trim().length > 0 && form.password.length > 0 && !submitting.value,
)

async function onSubmit(): Promise<void> {
  touched.username = true
  touched.password = true
  errorMessage.value = ''

  if (!canSubmit.value) return

  submitting.value = true
  try {
    await session.signIn(form.username.trim(), form.password)
    const next = typeof route.query.next === 'string' ? route.query.next : '/ask'
    await router.replace(next)
  } catch (err) {
    // 后端对用户名/密码错误返回同一句提示（防枚举），此处原样呈现
    errorMessage.value =
      err instanceof ApiError ? err.message : '登录失败，请稍后重试'
    form.password = ''
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login">
    <!-- 左栏：品牌与边界声明。承载"这是什么、不能做什么"的说明职责。 -->
    <section class="pane">
      <header class="pane__head">
        <span class="pane__mark" aria-hidden="true">党</span>
        <span class="u-eyebrow">党建工作智能体</span>
      </header>

      <h1 class="pane__title">
        制度问答
        <br />
        与依据溯源
      </h1>

      <p class="pane__lede">
        面向高校党组织，把党内法规与校内制度沉淀为可检索、可核验的知识底座。
        每一个回答都附带原文出处，便于逐条核对。
      </p>

      <dl class="pane__facts">
        <div class="pane__fact">
          <dt><AppIcon name="quote" :size="15" /> 句句有出处</dt>
          <dd>回答中的引用角标对应可展开的原文片段与发文信息，可逐条回溯。</dd>
        </div>
        <div class="pane__fact">
          <dt><AppIcon name="shield" :size="15" /> 分级不出网</dt>
          <dd>敏感与涉密材料仅由本地模型处理，出网闸门在服务端强制校验。</dd>
        </div>
        <div class="pane__fact">
          <dt><AppIcon name="people" :size="15" /> 辅助不代决</dt>
          <dd>不输出组织认定、选拔结论或阶段流转决定，最终判断由人工依规作出。</dd>
        </div>
      </dl>

      <footer class="pane__foot">
        使用前请确认已获得所在党组织的授权，并遵守信息系统安全保密管理规定。
      </footer>
    </section>

    <!-- 右栏：表单 -->
    <section class="form-pane">
      <div class="form-pane__inner">
        <h2 class="form-pane__title">登录</h2>
        <p class="form-pane__sub">请使用组织部门统一分配的账号登录。</p>

        <form class="login-form" novalidate @submit.prevent="onSubmit">
          <div class="field">
            <label class="field__label" for="username">用户名</label>
            <input
              id="username"
              v-model="form.username"
              class="input"
              type="text"
              name="username"
              autocomplete="username"
              spellcheck="false"
              placeholder="请输入用户名"
              :aria-invalid="Boolean(usernameError)"
              :aria-describedby="usernameError ? 'username-error' : undefined"
              @blur="touched.username = true"
            />
            <p v-if="usernameError" id="username-error" class="field__error">
              <AppIcon name="alert" :size="13" />
              {{ usernameError }}
            </p>
          </div>

          <div class="field">
            <label class="field__label" for="password">密码</label>
            <div class="pw">
              <input
                id="password"
                v-model="form.password"
                class="input pw__input"
                :type="showPassword ? 'text' : 'password'"
                name="password"
                autocomplete="current-password"
                placeholder="请输入密码"
                :aria-invalid="Boolean(passwordError)"
                :aria-describedby="passwordError ? 'password-error' : undefined"
                @blur="touched.password = true"
              />
              <button
                class="btn btn--quiet pw__toggle"
                type="button"
                @click="showPassword = !showPassword"
              >
                {{ showPassword ? '隐藏' : '显示' }}
              </button>
            </div>
            <p v-if="passwordError" id="password-error" class="field__error">
              <AppIcon name="alert" :size="13" />
              {{ passwordError }}
            </p>
          </div>

          <div v-if="errorMessage" class="login-error" role="alert">
            <AppIcon name="error" :size="15" />
            <span>{{ errorMessage }}</span>
          </div>

          <button class="btn btn--primary btn--lg btn--block" type="submit" :disabled="!canSubmit">
            {{ submitting ? '正在登录' : '登录' }}
          </button>

          <p class="login-form__note">
            忘记密码或账号未开通，请联系本单位组织部门管理员。
          </p>
        </form>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  min-height: 100dvh;
}

/* ------------------------------ 左栏 -------------------------------- */
.pane {
  display: flex;
  flex-direction: column;
  gap: var(--space-6);
  padding: var(--space-12) var(--space-16) var(--space-8);
  background: var(--paper-dim);
  border-right: var(--border);
}

.pane__head {
  display: flex;
  align-items: center;
  gap: var(--space-3);
}

.pane__mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  font-family: var(--font-serif);
  font-size: var(--text-md);
  font-weight: 600;
  color: #fff;
  background: var(--accent);
  border-radius: var(--radius-sm);
}

/* 主标题用衬线 + 大字号，这是全站唯一的大字号标题，且不是营销标语 */
.pane__title {
  font-family: var(--font-serif);
  font-size: var(--text-3xl);
  font-weight: 600;
  line-height: 1.18;
  letter-spacing: var(--tracking-tight);
  color: var(--ink);
}

.pane__lede {
  max-width: 44ch;
  font-size: var(--text-md);
  line-height: var(--leading-loose);
  color: var(--ink-soft);
}

.pane__facts {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
  max-width: 52ch;
  margin-top: var(--space-2);
}

.pane__fact {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
}

.pane__fact dt {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ink);
}

.pane__fact dd {
  padding-left: 23px;
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--ink-muted);
}

.pane__foot {
  margin-top: auto;
  padding-top: var(--space-5);
  border-top: var(--border);
  max-width: 52ch;
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-faint);
}

/* ------------------------------ 右栏 -------------------------------- */
.form-pane {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-10) var(--space-6);
  background: var(--paper);
}

.form-pane__inner {
  width: 100%;
  max-width: 348px;
}

.form-pane__title {
  font-family: var(--font-serif);
  font-size: var(--text-xl);
  font-weight: 600;
  color: var(--ink);
}

.form-pane__sub {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--ink-muted);
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
  margin-top: var(--space-6);
}

.pw {
  position: relative;
  display: flex;
  align-items: center;
}

.pw__input {
  padding-right: 60px;
}

.pw__toggle {
  position: absolute;
  right: 4px;
}

.login-error {
  display: flex;
  align-items: flex-start;
  gap: var(--space-2);
  padding: var(--space-3);
  background: var(--bad-wash);
  border: 1px solid var(--bad-edge);
  border-radius: var(--radius-sm);
  font-size: var(--text-sm);
  line-height: var(--leading-normal);
  color: var(--bad-ink);
}

.login-form__note {
  font-size: var(--text-xs);
  line-height: var(--leading-normal);
  color: var(--ink-faint);
}

/* ------------------------------ 响应式 ------------------------------ */
@media (max-width: 940px) {
  .login {
    grid-template-columns: 1fr;
  }

  .pane {
    padding: var(--space-8) var(--space-6) var(--space-6);
    border-right: 0;
    border-bottom: var(--border);
  }

  .pane__title {
    font-size: var(--text-2xl);
  }

  /* 窄屏下声明区收起为一行摘要，把首屏空间让给表单 */
  .pane__facts,
  .pane__foot {
    display: none;
  }

  .form-pane {
    padding: var(--space-8) var(--space-6) var(--space-12);
  }

  .form-pane__inner {
    max-width: 100%;
  }
}
</style>
