<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { SignIn, Waitlist, useAuth, useClerk, useUser } from '@clerk/vue'
import { useRoute, useRouter } from 'vue-router'
import { isAllowedOperatorEmail, isLocalAuthMode, safeRedirect } from '@/auth'
import AppIcon from '@/components/AppIcon.vue'
import OperatorAccessVisual from '@/components/OperatorAccessVisual.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'
import decisionCapture from '@/assets/showcase/decision-live.png'

const route = useRoute()
const router = useRouter()
const localMode = isLocalAuthMode()
const clerk = localMode ? ref(null) : useClerk()
const { isLoaded, isSignedIn } = localMode
  ? { isLoaded: ref(true), isSignedIn: ref(false) }
  : useAuth()
const { isLoaded: isUserLoaded, user } = localMode
  ? { isLoaded: ref(true), user: ref<null>(null) }
  : useUser()
const isPreview = import.meta.env.MODE === 'preview'

onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))

const mode = computed(() =>
  route.name === 'waitlist' || route.query.mode === 'waitlist' ? 'waitlist' : 'signin',
)
const redirectTarget = computed(() => safeRedirect(route.query.redirect, '/flow'))
const email = computed(() => user.value?.primaryEmailAddress?.emailAddress ?? '')
const denied = computed(() =>
  Boolean(isUserLoaded.value && isSignedIn.value && !isAllowedOperatorEmail(email.value)),
)
const unauthorizedAttempt = ref(false)

const hasClerk = computed(() => !localMode && isLoaded.value && clerk.value != null)

watch(
  [isLoaded, isUserLoaded, isSignedIn, denied, redirectTarget],
  async () => {
    if (!isLoaded.value || !isUserLoaded.value || !isSignedIn.value) return
    if (denied.value) {
      unauthorizedAttempt.value = true
      await clerk.value?.signOut()
      await router.replace({ name: 'waitlist' })
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
        <template v-if="mode === 'waitlist'">
          <p class="eyebrow"><span aria-hidden="true" /> Private preview · Access request</p>
          <h1 id="auth-context-title">A clearer view of options positioning.</h1>
          <p class="context-copy">
            TradeCentral brings dealer gamma, options flow, and research provenance into one
            workstation. Request access to the private preview; each request is reviewed before an
            invitation is issued.
          </p>
          <div class="close-row">
            <span>01 Request access</span>
            <i aria-hidden="true" />
            <span>02 Verification</span>
            <i aria-hidden="true" />
            <span>03 Invitation</span>
          </div>
          <div class="waitlist-benefits-grid" aria-label="Private preview inclusions">
            <div class="benefit-item">
              <span class="benefit-dot" aria-hidden="true" />
              <div>
                <strong>Dealer positioning</strong>
                <p>Gamma exposure, flip levels, and key positioning zones.</p>
              </div>
            </div>
            <div class="benefit-item">
              <span class="benefit-dot" aria-hidden="true" />
              <div>
                <strong>Options flow</strong>
                <p>Trade direction with source and confidence context.</p>
              </div>
            </div>
            <div class="benefit-item">
              <span class="benefit-dot" aria-hidden="true" />
              <div>
                <strong>Research evidence</strong>
                <p>Methodology and out-of-sample results alongside each view.</p>
              </div>
            </div>
          </div>
          <figure class="preview-capture">
            <img
              :src="decisionCapture"
              alt="Actual TradeCentral decision workspace showing a SPY standby reading when independent research lenses are unavailable"
              width="1440"
              height="900"
              loading="lazy"
              decoding="async"
            />
            <figcaption>
              From the workstation · SPY decision view · captured local session
            </figcaption>
          </figure>
          <div class="preview-note">
            <span class="preview-note-index">PREVIEW / 01</span>
            <p>
              Built for market research and decision support. TradeCentral does not route orders.
            </p>
          </div>
        </template>
        <template v-else>
          <p class="eyebrow"><span aria-hidden="true" /> Operator access · measured Flow</p>
          <h1 id="auth-context-title">One identity.<br />The full instrument.</h1>
          <p class="context-copy">
            <template v-if="isPreview">
              This public preview accepts access requests. Live research is offline while the
              private API remains on the local workstation.
            </template>
            <template v-else>
              Clerk verifies the operator; TradeCentral preserves the local boundary. After that,
              Flow opens the measured market-wide window—not a demo board, promised return, or trade
              ticket.
            </template>
          </p>
          <div class="close-row">
            <span>Next: authenticate</span>
            <i aria-hidden="true" />
            <span>Open Flow</span>
            <i aria-hidden="true" />
            <span>Inspect one chain</span>
          </div>
          <div class="access-route-visual"><OperatorAccessVisual mode="signin" /></div>
        </template>
      </section>

      <section class="auth-panel" aria-labelledby="auth-title">
        <div class="panel-index" aria-hidden="true">
          {{ mode === 'waitlist' ? 'WAITLIST / 01' : 'ACCESS / 01' }}
        </div>
        <nav class="auth-mode-switch" aria-label="Choose access mode">
          <RouterLink
            :class="{ active: mode === 'signin' }"
            :to="{ name: 'auth', query: { mode: 'signin', redirect: redirectTarget } }"
          >
            Sign in
          </RouterLink>
          <RouterLink
            :class="{ active: mode === 'waitlist' }"
            :to="{ name: 'waitlist', query: { redirect: redirectTarget } }"
          >
            Request access
          </RouterLink>
        </nav>
        <div class="panel-head">
          <p>{{ mode === 'waitlist' ? 'Private preview' : 'Continue to Flow' }}</p>
          <h2 id="auth-title">
            {{
              denied
                ? 'This account is not authorized'
                : mode === 'waitlist'
                  ? 'Request preview access'
                  : 'Unlock the instrument'
            }}
          </h2>
          <span>
            {{
              denied
                ? 'The signed-in account is not on the operator allowlist. Sign in with the authorized address.'
                : mode === 'waitlist'
                  ? 'Share your email. We review requests on a rolling basis and contact selected applicants.'
                  : 'Sign in to open the Flow tape and the rest of the desk.'
            }}
          </span>
        </div>

        <!-- Feedback alerts -->
        <div
          v-if="unauthorizedAttempt && mode === 'waitlist'"
          class="waitlist-notice"
          role="status"
        >
          <AppIcon name="shield" :size="16" />
          <div class="notice-text">
            <strong>Operator allowlist check</strong>
            <p>
              Your address is not currently on the operator allowlist. Submit your email below to
              request an operator invitation.
            </p>
          </div>
        </div>

        <p
          v-else-if="(denied || unauthorizedAttempt) && mode !== 'waitlist'"
          class="form-error"
          role="alert"
        >
          <AppIcon name="alert" :size="15" />
          Access requires an authorized operator account. This is not a public signup.
        </p>

        <!-- Waitlist Mode Content -->
        <template v-if="mode === 'waitlist'">
          <div v-if="!isLoaded" class="clerk-wait" role="status">Loading access portal…</div>
          <Waitlist v-else-if="hasClerk" sign-in-url="/auth" />
          <div v-else class="waitlist-unavailable" role="status">
            <strong>Waitlist unavailable</strong>
            <p v-if="localMode">
              Waitlist requests require Clerk, which is not configured in local mode. No request has
              been submitted.
            </p>
            <p v-else>Clerk is not available in this session. No request has been submitted.</p>
          </div>
        </template>

        <!-- Sign-in Mode Content -->
        <template v-else>
          <div v-if="!isLoaded" class="clerk-wait" role="status">Loading Clerk…</div>
          <div v-else-if="localMode" class="local-session-box">
            <div class="local-status">
              <span class="status-indicator-dot" aria-hidden="true" />
              <strong>Local operator session active</strong>
            </div>
            <p>
              The research API is bound to 127.0.0.1. No external authentication credentials
              required.
            </p>
            <RouterLink class="btn-continue-flow" :to="redirectTarget">
              Continue to Flow
              <svg
                class="px-arrow"
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <rect x="1" y="8" width="10" height="4" />
                <rect x="11" y="4" width="4" height="4" />
                <rect x="11" y="12" width="4" height="4" />
                <rect x="15" y="8" width="4" height="4" />
              </svg>
            </RouterLink>
          </div>
          <SignIn
            v-else
            path="/auth"
            routing="path"
            :with-sign-up="false"
            :force-redirect-url="redirectTarget"
          />
        </template>

        <p class="security-note">
          <template v-if="isPreview">
            Preview mode · The research API is disabled. Operator watchlists can sync through Convex
            after sign-in. Joining the waitlist does not grant dashboard access.
          </template>
          <template v-else>
            Clerk holds the operator session. The research API still binds to 127.0.0.1. That is a
            workstation lock, not permission to expose the local API on a network.
          </template>
        </p>

        <p class="legal-consent-notice">
          By signing in or requesting access, you acknowledge and agree to the
          <RouterLink to="/terms">Terms of Service</RouterLink> and
          <RouterLink to="/license">Source-Available License</RouterLink>. TradeCentral provides
          quantitative research tools only and does not offer financial advice or broker execution.
        </p>
      </section>
    </main>

    <footer class="auth-footer">
      <span>
        TradeCentral · Research only ·
        <RouterLink to="/license">License</RouterLink> ·
        <RouterLink to="/terms">Terms</RouterLink>
      </span>
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
  --font-data: var(--font-ui);
  position: relative;
  z-index: 3;
  min-height: 100vh;
  display: grid;
  grid-template-rows: auto 1fr auto;
  overflow-x: hidden;
  color: var(--auth-dark);
  background: var(--auth-paper);
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
  border-color: var(--auth-dark);
  background: #fffefa;
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
.auth-page a:focus-visible,
.auth-page button:focus-visible,
.auth-page :deep(button:focus-visible),
.auth-page :deep(a:focus-visible),
.auth-page :deep(input:focus-visible) {
  outline: 2px solid var(--auth-orange);
  outline-offset: 3px;
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
  text-wrap: balance;
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
  box-shadow: 12px 14px 0 rgba(24, 24, 27, 0.07);
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
  transition:
    color 140ms ease,
    background-color 140ms ease;
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
  line-height: 1.08;
  text-wrap: balance;
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
.waitlist-unavailable {
  display: grid;
  gap: 7px;
  margin-top: 22px;
  padding: 16px;
  border: 1px solid var(--auth-rule);
  border-left: 3px solid var(--auth-orange);
  background: #f5f4ef;
}
.waitlist-unavailable strong {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
}
.waitlist-unavailable p {
  margin: 0;
  color: var(--auth-muted);
  font-size: 13px;
  line-height: 1.5;
}
.form-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-top: 24px;
  padding: 11px 12px;
  color: #812e35;
  background: #f3e4e3;
  border-left: 1px solid #b94d56;
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
  border: 1px solid #5e5b53;
  border-radius: 0;
  background: #fffefa;
  box-shadow: none;
}
.auth-panel :deep(.cl-formFieldInput::placeholder) {
  color: #5e5b53;
  opacity: 1;
}
.auth-panel :deep(.cl-formFieldInput:focus) {
  border-color: #c93a10;
  box-shadow: 0 0 0 2px rgba(255, 82, 41, 0.18);
}
.auth-panel :deep(.cl-formButtonPrimary) {
  min-height: 47px;
  color: #fbfbf8;
  border-left: 1px solid #ff5229;
  border-radius: 0;
  background: #09090b;
  box-shadow: none;
}
.auth-panel :deep(.cl-formButtonPrimary:hover) {
  background: #26262c;
}
.auth-panel :deep(button:disabled),
.auth-panel :deep([aria-disabled='true']) {
  cursor: not-allowed;
  opacity: 0.58;
}
.auth-panel :deep(.cl-socialButtonsBlockButton) {
  min-height: 46px;
  color: #292923;
  border: 1px solid #5e5b53;
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

/* Clerk Waitlist specific overrides */
.auth-panel :deep(.cl-waitlist-root),
.auth-panel :deep(.cl-waitlistSuccess) {
  width: 100%;
}
.auth-panel :deep(.cl-waitlistSuccessTitle) {
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 600;
  color: var(--auth-dark);
}
.auth-panel :deep(.cl-waitlistSuccessText) {
  color: #565660;
  font-size: 13px;
  line-height: 1.5;
}

/* Waitlist Benefits Grid on Context Side */
.waitlist-benefits-grid {
  display: grid;
  grid-template-columns: 1fr;
  margin: 26px 0 0;
  border-top: 1px solid var(--auth-rule);
}
.benefit-item {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 15px 0;
  border-bottom: 1px solid var(--auth-rule);
}
.benefit-dot {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  background: var(--auth-orange);
  flex-shrink: 0;
}
.benefit-item strong {
  display: block;
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: -0.015em;
  color: var(--auth-dark);
  line-height: 1.25;
}
.benefit-item p {
  margin: 3px 0 0;
  font-family: var(--font-ui);
  font-size: 13px;
  color: var(--auth-muted);
  line-height: 1.35;
}

.preview-capture {
  margin: 28px 0 0;
  border: 1px solid var(--auth-rule);
  background: #101217;
}
.preview-capture img {
  display: block;
  width: 100%;
  height: auto;
}
.preview-capture figcaption {
  padding: 10px 12px;
  border-top: 1px solid #33363a;
  color: #d5d6d9;
  font-family: var(--font-ui);
  font-size: 11px;
  line-height: 1.45;
}

.preview-note {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin-top: 24px;
  padding-top: 14px;
  border-top: 1px solid var(--auth-rule);
}
.preview-note-index {
  flex: 0 0 auto;
  color: var(--auth-orange);
  font-size: 10px;
  font-weight: 650;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
.preview-note p {
  margin: 0;
  color: var(--auth-muted);
  font-size: 12px;
  line-height: 1.5;
}

/* Waitlist Notice Banner */
.waitlist-notice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 20px;
  padding: 12px 14px;
  background: #fdfaf3;
  border: 1px solid #f3d79f;
  border-left: 3px solid #d97706;
  color: #92400e;
}
.waitlist-notice .notice-text strong {
  display: block;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.waitlist-notice .notice-text p {
  margin: 3px 0 0;
  font-size: 12px;
  line-height: 1.45;
  color: #78350f;
}

/* Local Session Box */
.local-session-box {
  margin-top: 22px;
  padding: 16px;
  background: #f8f8f4;
  border: 1px solid var(--auth-rule);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.local-status {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-indicator-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--auth-green);
}
.local-status strong {
  font-family: var(--font-display);
  font-size: 13px;
  font-weight: 600;
  color: var(--auth-dark);
}
.local-session-box p {
  margin: 0;
  font-size: 12px;
  color: #565660;
  line-height: 1.45;
}
.btn-continue-flow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 42px;
  margin-top: 4px;
  padding: 8px 14px;
  color: #fbfbf8;
  background: #09090b;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-decoration: none;
}
.btn-continue-flow:hover {
  background: #26262c;
  text-decoration: none;
}
.btn-continue-flow:active {
  transform: translateY(1px);
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

.legal-consent-notice {
  margin-top: 12px;
  font-family: var(--font-ui);
  font-size: 11px;
  line-height: 1.5;
  color: #71717a;
}
.legal-consent-notice a {
  color: #111110;
  text-decoration: underline;
  text-underline-offset: 2px;
  font-weight: 500;
}
.legal-consent-notice a:hover {
  color: #000000;
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
.auth-footer a {
  color: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}
.auth-footer a:hover {
  color: #111110;
}

@media (max-width: 980px) {
  .preview-capture {
    display: none;
  }
  .auth-shell {
    grid-template-columns: 1fr;
    gap: 36px;
  }
  .auth-panel {
    position: relative;
    max-width: 560px;
    width: 100%;
    justify-self: center;
  }
}

@media (min-width: 981px) and (max-width: 1100px) {
  .auth-shell {
    grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
    gap: 32px;
  }
  .auth-panel {
    padding-inline: 24px;
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
    box-shadow: 6px 7px 0 rgba(24, 24, 27, 0.07);
  }
  .close-row {
    flex-wrap: wrap;
    gap: 8px;
    line-height: 1.5;
  }
  .close-row i {
    flex-basis: 18px;
  }
  .preview-note {
    align-items: flex-start;
    flex-direction: column;
    gap: 6px;
  }
  .panel-index {
    top: -22px;
    font-size: 9px;
  }
  .auth-footer {
    flex-direction: column;
    align-items: flex-start;
    justify-content: center;
    padding-block: 18px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .auth-page *,
  .auth-page *::before,
  .auth-page *::after {
    scroll-behavior: auto !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
