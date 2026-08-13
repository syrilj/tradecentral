<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { SignIn, SignUp, useAuth, useClerk, useUser } from '@clerk/vue'
import { useRoute, useRouter } from 'vue-router'
import { isAllowedOperatorEmail, safeRedirect } from '@/auth'
import AppIcon from '@/components/AppIcon.vue'
import FlowWorkspaceMockup from '@/components/FlowWorkspaceMockup.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()
const router = useRouter()
const clerk = useClerk()
const { isLoaded, isSignedIn } = useAuth()
const { user } = useUser()

onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))

const mode = computed(() => route.query.mode === 'setup' ? 'setup' : 'signin')
const redirectTarget = computed(() => safeRedirect(route.query.redirect, '/flow'))
const email = computed(() => user.value?.primaryEmailAddress?.emailAddress ?? '')
const denied = computed(() => Boolean(isSignedIn.value && !isAllowedOperatorEmail(email.value)))

watch(
  [isLoaded, isSignedIn, denied, redirectTarget],
  async () => {
    if (!isLoaded.value || !isSignedIn.value) return
    if (denied.value) {
      await clerk.value?.signOut()
      return
    }
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
        <p class="eyebrow"><span aria-hidden="true" /> Sign in · then open Flow</p>
        <h1 id="auth-context-title">The tape is on the other side of this form.</h1>
        <p class="context-copy">
          Clerk verifies the operator. After that, Flow shows the measured
          market-wide window from the local API — not a demo board, not a
          promised return, not a trade ticket.
        </p>
        <div class="close-row">
          <span>Next: authenticate</span>
          <i />
          <span>Open Flow</span>
          <i />
          <span>Inspect one chain</span>
        </div>
        <FlowWorkspaceMockup compact />
      </section>

      <section class="auth-panel" aria-labelledby="auth-title">
        <div class="panel-index" aria-hidden="true">ACCESS / 01</div>
        <div class="panel-head">
          <p>{{ mode === 'setup' ? 'Create operator access' : 'Continue to Flow' }}</p>
          <h2 id="auth-title">
            {{ denied ? 'This account is not authorized' : mode === 'setup' ? 'Create the operator session' : 'Unlock the instrument' }}
          </h2>
          <span>
            {{ denied
              ? 'The signed-in account is not on the operator allowlist. Sign in with the authorized address.'
              : mode === 'setup'
                ? 'Create a Clerk operator session for this workstation.'
                : 'Sign in to open the Flow tape and the rest of the desk.' }}
          </span>
        </div>

        <div v-if="!isLoaded" class="clerk-wait" role="status">Loading Clerk…</div>
        <p v-else-if="denied" class="form-error" role="alert">
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
          Clerk holds the operator session for this dashboard. The research API
          still binds to 127.0.0.1. That is a workstation lock, not permission
          to expose the local API on a network.
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
  background: #141413;
}
:global(body.edge-public-mode #app),
:global(body.edge-public-mode .shell) {
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}
:global(body.edge-public-mode .shell) { display: block !important; }
:global(body.edge-public-mode .rail),
:global(body.edge-public-mode .strip),
:global(body.edge-public-mode .foot),
:global(body.edge-public-mode .skip-link) { display: none !important; }
:global(body.edge-public-mode .stage) {
  display: block !important;
  width: 100% !important;
  height: auto !important;
  min-height: 100vh !important;
  padding: 0 !important;
  overflow: visible !important;
}

.auth-page {
  --auth-dark: #141413;
  --auth-paper: #faf9f5;
  --auth-muted: #b0aea5;
  --auth-rule: #363531;
  --auth-orange: #d97757;
  --auth-blue: #6a9bcc;
  --auth-green: #788c5d;
  position: relative;
  z-index: 3;
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  color: var(--auth-paper);
  background:
    linear-gradient(rgba(250, 249, 245, 0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(250, 249, 245, 0.025) 1px, transparent 1px),
    var(--auth-dark);
  background-size: 40px 40px;
  font-family: 'Lora', Georgia, var(--font-ui);
}

.auth-topbar,
.auth-shell,
.auth-footer {
  width: min(1240px, calc(100% - 64px));
  margin-inline: auto;
}

.auth-topbar {
  min-height: 76px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--auth-rule);
}

.auth-brand {
  display: inline-flex;
  align-items: center;
  gap: 11px;
  color: var(--auth-paper);
}
.auth-brand:hover { text-decoration: none; }
.auth-wordmark { display: grid; line-height: 1.05; }
.auth-wordmark strong {
  font-family: 'Poppins', var(--font-ui);
  font-size: 15px;
  font-weight: 650;
  letter-spacing: -0.02em;
}
.auth-wordmark small {
  margin-top: 5px;
  color: var(--auth-muted);
  font-family: var(--font-display);
  font-size: 9px;
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
.back-link:hover { color: var(--auth-paper); text-decoration: none; }

.auth-shell {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(390px, 460px);
  gap: clamp(40px, 6vw, 88px);
  align-items: start;
  padding-block: clamp(48px, 7vh, 88px);
}

.auth-context { max-width: 720px; }
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
.eyebrow span { width: 24px; height: 2px; background: var(--auth-orange); }
.auth-context h1 {
  margin-top: 22px;
  max-width: 16ch;
  color: var(--auth-paper);
  font-family: 'Poppins', var(--font-ui);
  font-size: clamp(38px, 4.8vw, 62px);
  font-weight: 560;
  letter-spacing: -0.055em;
  line-height: 0.99;
}
.context-copy {
  margin-top: 22px;
  max-width: 54ch;
  color: #cfcdc5;
  font-family: var(--font-ui);
  font-size: 16px;
  line-height: 1.7;
}
.close-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 24px 0 28px;
  color: #8a877f;
  font-family: var(--font-display);
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.close-row i { flex: 1; height: 1px; background: var(--auth-rule); }

.auth-panel {
  position: sticky;
  top: 28px;
  padding: 34px 32px 28px;
  color: var(--auth-dark);
  background: var(--auth-paper);
  border-top: 4px solid var(--auth-orange);
}
.panel-index {
  position: absolute;
  top: 17px;
  right: 20px;
  color: #8d8a82;
  font-family: var(--font-display);
  font-size: 9px;
  letter-spacing: 0.1em;
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
  font-family: 'Poppins', var(--font-ui);
  font-size: 28px;
  font-weight: 620;
  letter-spacing: -0.035em;
}
.panel-head > span {
  display: block;
  margin-top: 8px;
  color: #68665f;
  font-family: var(--font-ui);
  font-size: 13px;
  line-height: 1.5;
}

.clerk-wait {
  margin-top: 28px;
  color: #6f6c64;
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
.auth-panel :deep(.cl-rootBox) { margin-top: 22px; }
.auth-panel :deep(.cl-cardBox),
.auth-panel :deep(.cl-card) { width: 100%; }

.security-note {
  margin-top: 26px;
  padding-top: 18px;
  color: #817e76;
  border-top: 1px solid #ddd9d0;
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
  color: #85827a;
  border-top: 1px solid var(--auth-rule);
  font-family: var(--font-display);
  font-size: 9px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

@media (max-width: 980px) {
  .auth-shell { grid-template-columns: 1fr; gap: 36px; }
  .auth-panel { position: static; max-width: 560px; }
}

@media (max-width: 620px) {
  .auth-topbar,
  .auth-shell,
  .auth-footer { width: min(100% - 32px, 1240px); }
  .auth-wordmark small { display: none; }
  .back-link { font-size: 0; gap: 0; }
  .auth-context h1 { font-size: clamp(34px, 12vw, 48px); }
  .auth-panel { padding: 28px 20px 22px; }
  .auth-footer { flex-direction: column; align-items: flex-start; justify-content: center; padding-block: 18px; }
}
</style>
