<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { SignIn, SignUp, useAuth, useClerk, useUser } from '@clerk/vue'
import { useRoute, useRouter } from 'vue-router'
import { isAllowedOperatorEmail, safeRedirect } from '@/auth'
import AppIcon from '@/components/AppIcon.vue'
import OperatorAccessVisual from '@/components/OperatorAccessVisual.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()
const router = useRouter()
const clerk = useClerk()
const { isLoaded, isSignedIn } = useAuth()
const { user } = useUser()

onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))

const mode = computed(() => (route.query.mode === 'setup' ? 'setup' : 'signin'))
const redirectTarget = computed(() => safeRedirect(route.query.redirect, '/flow'))
const email = computed(() => user.value?.primaryEmailAddress?.emailAddress ?? '')
const denied = computed(() => Boolean(isSignedIn.value && !isAllowedOperatorEmail(email.value)))
const unauthorizedAttempt = ref(false)

watch(
  [isLoaded, isSignedIn, denied, redirectTarget],
  async () => {
    if (!isLoaded.value || !isSignedIn.value) return
    if (denied.value) {
      unauthorizedAttempt.value = true
      await clerk.value?.signOut()
      return
    }
    unauthorizedAttempt.value = false
    await router.replace(redirectTarget.value)
  },
  { immediate: true },
)
</script>

<template>
  <div class="auth-page">
    <header class="auth-topbar">
      <RouterLink class="auth-brand" to="/" aria-label="TradeCentral home">
        <TradeCentralMark :size="32" />
        <span class="auth-wordmark">
          <strong>TradeCentral</strong>
          <small>Research instrument</small>
        </span>
      </RouterLink>
      <RouterLink class="back-link" to="/">
        <AppIcon name="arrow-left" :size="15" />
        Back to overview
      </RouterLink>
    </header>

    <main class="auth-shell">
      <section class="auth-context" aria-labelledby="auth-context-title">
        <p class="eyebrow"><span aria-hidden="true" /> Operator access · measured Flow</p>
        <h1 id="auth-context-title">One identity.<br />The full instrument.</h1>
        <p class="context-copy">
          Clerk verifies the operator; TradeCentral preserves the local boundary. After that, Flow
          opens the measured market-wide window—not a demo board, promised return, or trade ticket.
        </p>
        <div class="close-row">
          <span>Next: authenticate</span>
          <i />
          <span>Open Flow</span>
          <i />
          <span>Inspect one chain</span>
        </div>
        <div class="access-route-visual"><OperatorAccessVisual /></div>
      </section>

      <section class="auth-panel" aria-labelledby="auth-title">
        <div class="panel-index" aria-hidden="true">ACCESS / 01</div>
        <nav class="auth-mode-switch" aria-label="Choose access mode">
          <RouterLink
            :class="{ active: mode === 'signin' }"
            :to="{ name: 'auth', query: { mode: 'signin', redirect: redirectTarget } }"
          >
            Sign in
          </RouterLink>
          <RouterLink
            :class="{ active: mode === 'setup' }"
            :to="{ name: 'auth', query: { mode: 'setup', redirect: redirectTarget } }"
          >
            Create access
          </RouterLink>
        </nav>
        <div class="panel-head">
          <p>{{ mode === 'setup' ? 'Create operator access' : 'Continue to Flow' }}</p>
          <h2 id="auth-title">
            {{
              denied
                ? 'This account is not authorized'
                : mode === 'setup'
                  ? 'Create the operator session'
                  : 'Unlock the instrument'
            }}
          </h2>
          <span>
            {{
              denied
                ? 'The signed-in account is not on the operator allowlist. Sign in with the authorized address.'
                : mode === 'setup'
                  ? 'Create a Clerk operator session for this workstation.'
                  : 'Sign in to open the Flow tape and the rest of the desk.'
            }}
          </span>
        </div>

        <div v-if="!isLoaded" class="clerk-wait" role="status">Loading Clerk…</div>
        <p v-else-if="denied || unauthorizedAttempt" class="form-error" role="alert">
          <AppIcon name="alert" :size="15" />
          Access is limited to the configured operator allowlist. This is not a public signup.
        </p>
        <SignUp
          v-else-if="mode === 'setup'"
          path="/auth"
          routing="path"
          :sign-in-url="`/auth?redirect=${encodeURIComponent(redirectTarget)}`"
          :force-redirect-url="redirectTarget"
        />
        <SignIn
          v-else
          path="/auth"
          routing="path"
          :with-sign-up="true"
          :sign-up-url="`/auth?mode=setup&redirect=${encodeURIComponent(redirectTarget)}`"
          :force-redirect-url="redirectTarget"
        />

        <p class="security-note">
          Clerk holds the operator session. The research API still binds to 127.0.0.1. That is a
          workstation lock, not permission to expose the local API on a network.
        </p>
      </section>
    </main>

    <footer class="auth-footer">
      <span>TradeCentral · Research only</span>
      <span>No order routing · No investment advice</span>
    </footer>
  </div>
</template>

<style scoped>
:global(body.edge-public-mode) {
  overflow: auto !important;
  background: #fbfbf8;
}
:global(body.edge-public-mode #app),
:global(body.edge-public-mode .shell) {
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}
:global(body.edge-public-mode .shell) {
  display: block !important;
}
:global(body.edge-public-mode .rail),
:global(body.edge-public-mode .strip),
:global(body.edge-public-mode .foot),
:global(body.edge-public-mode .skip-link) {
  display: none !important;
}
:global(body.edge-public-mode .stage) {
  display: block !important;
  width: 100% !important;
  height: auto !important;
  min-height: 100vh !important;
  padding: 0 !important;
  overflow: visible !important;
}

.auth-page {
  --auth-dark: #18181b;
  --auth-paper: #fbfbf8;
  --auth-muted: #565660;
  --auth-rule: #e4e3de;
  --auth-orange: #ff5229;
  --auth-blue: #0082e6;
  --auth-green: #0f8a5f;
  /* Editorial typography aligned with the landing paper system. */
  --font-display: 'Inter Tight Variable', 'Inter Tight', 'Geist Variable', 'Geist', sans-serif;
  --font-ui: 'Inter Variable', 'Inter', 'Geist Variable', 'Geist', sans-serif;
  --font-data: 'Space Mono', 'IBM Plex Mono', 'Geist Mono Variable', monospace;
  position: relative;
  z-index: 3;
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  overflow-x: hidden;
  color: var(--auth-dark);
  background:
    linear-gradient(rgba(24, 24, 27, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(24, 24, 27, 0.045) 1px, transparent 1px), var(--auth-paper);
  background-size: 40px 40px;
  font-family: var(--font-ui);
}

.auth-topbar,
.auth-shell,
.auth-footer {
  width: min(1240px, calc(100% - 64px));
  margin-inline: auto;
}

.auth-topbar {
  min-height: 80px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--auth-rule);
}

.auth-brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  padding: 8px 12px 8px 9px;
  color: var(--auth-dark);
  border: 1px solid #c9c9c4;
  background: #f5f4ef;
}
.auth-brand:hover {
  text-decoration: none;
}
.auth-wordmark {
  display: grid;
  line-height: 1.05;
}
.auth-wordmark strong {
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.02em;
}
.auth-wordmark small {
  margin-top: 5px;
  color: var(--auth-muted);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.back-link {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--auth-muted);
  font-family: var(--font-ui);
  font-size: 12px;
}
.back-link:hover {
  color: var(--auth-dark);
  text-decoration: none;
}

.auth-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(400px, 470px);
  gap: clamp(40px, 6vw, 88px);
  align-items: start;
  padding-block: clamp(48px, 7vh, 88px);
}

.auth-context {
  max-width: 720px;
}
.eyebrow {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--auth-muted);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.13em;
  text-transform: uppercase;
}
.eyebrow span {
  width: 24px;
  height: 2px;
  background: var(--auth-orange);
}
.auth-context h1 {
  margin-top: 22px;
  max-width: 16ch;
  color: var(--auth-dark);
  font-family: var(--font-display);
  font-size: clamp(38px, 4.8vw, 62px);
  font-weight: 600;
  letter-spacing: -0.04em;
  line-height: 0.99;
}
.context-copy {
  margin-top: 22px;
  max-width: 54ch;
  color: #3f3f46;
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.7;
}
.close-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 24px 0 28px;
  color: #6f6f78;
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.close-row i {
  flex: 1;
  height: 1px;
  background: var(--auth-rule);
}

.access-route-visual {
  max-width: 660px;
}

.auth-panel {
  position: sticky;
  top: 28px;
  padding: 28px 32px 30px;
  color: var(--auth-dark);
  background: #ffffff;
  border: 1px solid #c9c9c4;
  border-top: 3px solid var(--auth-orange);
  box-shadow: 18px 22px 0 rgba(0, 130, 230, 0.1);
}
.auth-panel::before,
.auth-panel::after {
  content: '';
  position: absolute;
  width: 13px;
  height: 13px;
  pointer-events: none;
}
.auth-panel::before {
  top: -3px;
  left: -1px;
  border-top: 1px solid #18181b;
  border-left: 1px solid #18181b;
}
.auth-panel::after {
  right: -1px;
  bottom: -1px;
  border-right: 1px solid #18181b;
  border-bottom: 1px solid #18181b;
}
.panel-index {
  position: absolute;
  top: -24px;
  right: 0;
  color: #6f6f78;
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.1em;
}
.auth-mode-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  margin: 0 0 27px;
  padding: 4px;
  border: 1px solid #c9c9c4;
  background: #ebe9e0;
}
.auth-mode-switch a {
  min-height: 38px;
  display: grid;
  place-items: center;
  color: #565660;
  font-family: var(--font-display);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
.auth-mode-switch a:hover {
  color: #18181b;
  text-decoration: none;
}
.auth-mode-switch a.active {
  color: #fbfbf8;
  background: #09090b;
}
.panel-head p {
  color: var(--auth-orange);
  font-family: var(--font-display);
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.panel-head h2 {
  margin-top: 11px;
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  letter-spacing: -0.03em;
}
.panel-head > span {
  display: block;
  margin-top: 8px;
  color: #3f3f46;
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.5;
}

.clerk-wait {
  margin-top: 28px;
  color: #6f6f78;
  font-family: var(--font-ui);
  font-size: 13px;
}
.form-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 24px;
  padding: 11px 12px;
  color: #812e35;
  background: #f3e4e3;
  border-left: 3px solid #b94d56;
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.45;
}
.auth-panel :deep(.cl-rootBox) {
  margin-top: 22px;
}
.auth-panel :deep(.cl-cardBox),
.auth-panel :deep(.cl-card) {
  width: 100%;
}
.auth-panel :deep(.cl-rootBox) {
  color: #252521;
  font-family: var(--font-ui);
}
.auth-panel :deep(.cl-formFieldLabel) {
  color: #3e3c36;
  font-size: 12px;
  font-weight: 650;
}
.auth-panel :deep(.cl-formFieldInput) {
  min-height: 46px;
  padding-inline: 13px;
  color: #1f201d;
  border: 1px solid #76736a;
  border-radius: 0;
  background: #fffefa;
  box-shadow: none;
}
.auth-panel :deep(.cl-formFieldInput::placeholder) {
  color: #77746c;
  opacity: 1;
}
.auth-panel :deep(.cl-formFieldInput:focus) {
  border-color: #c93a10;
  box-shadow: 0 0 0 2px rgba(255, 82, 41, 0.18);
}
.auth-panel :deep(.cl-formButtonPrimary) {
  min-height: 47px;
  color: #fbfbf8;
  border-left: 3px solid #ff5229;
  border-radius: 0;
  background: #09090b;
  box-shadow: none;
}
.auth-panel :deep(.cl-formButtonPrimary:hover) {
  background: #26262c;
}
.auth-panel :deep(.cl-socialButtonsBlockButton) {
  min-height: 46px;
  color: #292923;
  border: 1px solid #76736a;
  border-radius: 0;
  background: #fffefa;
  box-shadow: none;
}
.auth-panel :deep(.cl-socialButtonsBlockButton:hover) {
  color: #1e1f1b;
  border-color: #3f3e38;
  background: #f0eee8;
}
.auth-panel :deep(.cl-dividerLine) {
  background: #c7c3b9;
}
.auth-panel :deep(.cl-dividerText),
.auth-panel :deep(.cl-footerActionText),
.auth-panel :deep(.cl-identityPreviewText) {
  color: #5e5b53;
}
.auth-panel :deep(.cl-footerActionLink),
.auth-panel :deep(.cl-formResendCodeLink),
.auth-panel :deep(.cl-identityPreviewEditButton) {
  color: #c93a10;
  font-weight: 700;
}
.auth-panel :deep(.cl-alertText) {
  color: #7d2931;
}

.security-note {
  margin-top: 26px;
  padding-top: 18px;
  color: #6f6f78;
  border-top: 1px solid #e4e3de;
  font-family: var(--font-ui);
  font-size: 10px;
  line-height: 1.55;
}

.auth-footer {
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  color: #6f6f78;
  border-top: 1px solid var(--auth-rule);
  font-family: var(--font-display);
  font-size: var(--t-nano);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

@media (max-width: 980px) {
  .auth-shell {
    grid-template-columns: 1fr;
    gap: 36px;
  }
  .auth-panel {
    position: relative;
    max-width: 560px;
  }
}

@media (max-width: 620px) {
  .auth-topbar,
  .auth-shell,
  .auth-footer {
    width: min(100% - 32px, 1240px);
  }
  .auth-wordmark small {
    display: none;
  }
  .back-link {
    font-size: 0;
    gap: 0;
  }
  .auth-context h1 {
    font-size: clamp(34px, 12vw, 48px);
  }
  .auth-panel {
    padding: 22px 18px 24px;
    box-shadow: 9px 11px 0 rgba(0, 130, 230, 0.1);
  }
  .auth-footer {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    padding-block: 18px;
  }
}
</style>
