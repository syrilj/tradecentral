<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppIcon from '@/components/AppIcon.vue'
import TradeCentralMark from '@/components/TradeCentralMark.vue'

const route = useRoute()
const router = useRouter()

onMounted(() => document.body.classList.add('edge-public-mode'))
onUnmounted(() => document.body.classList.remove('edge-public-mode'))

type Tab = 'license' | 'terms'

const activeTab = ref<Tab>(
  route.name === 'terms' || route.path.startsWith('/terms') ? 'terms' : 'license',
)

watch(
  () => route.path,
  (path) => {
    if (path.startsWith('/terms')) {
      activeTab.value = 'terms'
    } else if (path.startsWith('/license')) {
      activeTab.value = 'license'
    }
  },
)

function setTab(tab: Tab) {
  activeTab.value = tab
  if (tab === 'terms') {
    router.replace({ name: 'terms' })
  } else {
    router.replace({ name: 'license' })
  }
}

const copied = ref(false)
async function copyCurrentDocument() {
  const contentEl = document.getElementById('legal-document-body')
  if (!contentEl) return
  try {
    await navigator.clipboard.writeText(contentEl.innerText)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 2500)
  } catch {
    // Clipboard permission fallback
  }
}

function printDocument() {
  window.print()
}
</script>

<template>
  <div class="legal-page">
    <header class="legal-topbar">
      <div class="topbar-inner">
        <RouterLink class="brand" to="/" aria-label="TradeCentral home">
          <TradeCentralMark :size="26" />
          <span class="wordmark">
            <strong>TradeCentral</strong>
            <small>Legal & Licensing</small>
          </span>
        </RouterLink>

        <div class="topbar-actions">
          <RouterLink class="topbar-link" to="/">
            <AppIcon name="arrow-left" :size="14" />
            <span>Overview</span>
          </RouterLink>
          <RouterLink
            class="topbar-link"
            :to="{ name: 'auth', query: { mode: 'signin', redirect: '/flow' } }"
          >
            <span>Operator access</span>
          </RouterLink>
        </div>
      </div>
    </header>

    <main class="legal-container">
      <aside class="legal-nav-sidebar">
        <div class="sidebar-sticky">
          <div class="doc-badge">GOVERNING LEGAL CONTRACTS</div>
          <h1 class="sidebar-title">Legal Architecture</h1>
          <p class="sidebar-subtitle">
            Binding legal instruments governing the use, evaluation, intellectual property, and
            regulatory posture of TradeCentral.
          </p>

          <nav class="tab-selector" aria-label="Select legal instrument">
            <button
              type="button"
              class="tab-btn"
              :class="{ active: activeTab === 'license' }"
              @click="setTab('license')"
            >
              <span class="tab-index">01</span>
              <span class="tab-label">
                <strong>Software License Agreement</strong>
                <small>Proprietary evaluation & IP terms</small>
              </span>
            </button>

            <button
              type="button"
              class="tab-btn"
              :class="{ active: activeTab === 'terms' }"
              @click="setTab('terms')"
            >
              <span class="tab-index">02</span>
              <span class="tab-label">
                <strong>Terms of Service & Disclaimers</strong>
                <small>Publisher safe harbor & CFTC 4.41</small>
              </span>
            </button>
          </nav>

          <div class="quick-metadata">
            <div class="meta-row">
              <span class="meta-k">Effective date</span>
              <span class="meta-v">September 26, 2026</span>
            </div>
            <div class="meta-row">
              <span class="meta-k">Copyright</span>
              <span class="meta-v">© 2026 Syril Jacob</span>
            </div>
            <div class="meta-row">
              <span class="meta-k">Source posture</span>
              <span class="meta-v">Evaluation only</span>
            </div>
            <div class="meta-row">
              <span class="meta-k">Reuse</span>
              <span class="meta-v">All rights reserved</span>
            </div>
          </div>

          <div class="document-tools">
            <button type="button" class="tool-btn" @click="copyCurrentDocument">
              <AppIcon name="terminal" :size="14" />
              <span>{{ copied ? 'Copied to clipboard' : 'Copy text' }}</span>
            </button>
            <button type="button" class="tool-btn" @click="printDocument">
              <AppIcon name="download" :size="14" />
              <span>Print / PDF</span>
            </button>
          </div>
        </div>
      </aside>

      <section id="legal-document-body" class="legal-document-view" aria-live="polite">
        <!-- TAB 1: SOURCE-AVAILABLE LICENSE -->
        <article v-if="activeTab === 'license'" class="contract-article">
          <header class="contract-header">
            <div class="contract-kicker">SOURCE AVAILABLE</div>
            <h2 class="contract-title">TradeCentral Source-Available Evaluation License</h2>
            <div class="contract-meta-bar">
              <span><strong>Copyright:</strong> 2026 Syril Jacob</span>
              <span class="sep">/</span>
              <span><strong>Posture:</strong> All rights reserved</span>
            </div>
          </header>

          <section class="legal-section">
            <h3>1. Evaluation permission</h3>
            <p>
              This repository is publicly visible for portfolio review, technical evaluation,
              security review, and discussion of employment, collaboration, or licensing. You may
              view the source and make a temporary local copy solely to inspect, test, or evaluate
              it for non-commercial purposes.
            </p>
          </section>

          <section class="legal-section">
            <h3>2. No open-source grant</h3>
            <p>
              This is not an open-source license. Except for the limited evaluation permission
              above, no permission is granted to use, copy, modify, merge, publish, distribute,
              sublicense, sell, host, deploy, commercialize, or create derivative products from
              the Software.
            </p>
          </section>

          <section class="legal-section">
            <h3>3. Restricted uses</h3>
            <p>
              Without prior written permission from the copyright holder, you may not operate the
              Software as a production, hosted, trading, advisory, or commercial service;
              redistribute substantial portions outside ordinary GitHub functionality; incorporate
              it into another product or service; use it or its documentation for machine-learning
              or generative-AI training, fine-tuning, distillation, or evaluation; or remove
              copyright and attribution notices.
            </p>
          </section>

          <section class="legal-section">
            <h3>4. Third-party material</h3>
            <p>
              No rights are granted to third-party software, data, trademarks, publications, market
              data, or other materials referenced by or used with TradeCentral. Their respective
              terms continue to apply.
            </p>
          </section>

          <section class="legal-section">
            <h3>5. Research-only software</h3>
            <p>
              TradeCentral is quantitative research and decision-support software. It does not
              provide investment advice and the checked-in application does not place or route
              broker orders.
            </p>
          </section>

          <section class="legal-section">
            <h3>6. Disclaimer</h3>
            <div class="legal-caps-box">
              THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
              INCLUDING WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE,
              NON-INFRINGEMENT, ACCURACY, OR FITNESS FOR TRADING OR INVESTMENT PURPOSES. TO THE
              MAXIMUM EXTENT PERMITTED BY LAW, THE COPYRIGHT HOLDER SHALL NOT BE LIABLE FOR CLAIMS,
              LOSSES, OR DAMAGES ARISING FROM USE OF OR RELIANCE ON THE SOFTWARE.
            </div>
          </section>
        </article>

        <!-- TAB 2: TERMS OF SERVICE & REGULATORY DISCLAIMERS -->
        <article v-else class="contract-article">
          <header class="contract-header">
            <div class="contract-kicker">RESEARCH & RISK DISCLOSURES</div>
            <h2 class="contract-title">
              Terms of Service & Research Disclaimers
            </h2>
            <div class="contract-meta-bar">
              <span><strong>Product posture:</strong> Impersonal research</span>
              <span class="sep">/</span>
              <span><strong>Execution:</strong> No broker order routing</span>
            </div>
            <div class="binding-callout" role="alert">
              <strong>FINANCIAL RESEARCH NOTICE:</strong>
              TradeCentral is a quantitative decision-support research instrument. It is not
              presented as personalized investment advice, a brokerage service, or an order
              execution gateway. Read these disclosures before interpreting workstation analytics.
            </div>
          </header>

          <section class="legal-section">
            <h3>1. Impersonal quantitative research only</h3>
            <p>
              Quantitative metrics, dealer gamma profiles, options analytics, microstructure
              classifications, volatility regimes, and scanner outputs are general research
              outputs. They are not personalized investment advice, portfolio suitability
              assessments, or instructions to buy or sell a security or derivative.
            </p>
          </section>

          <section class="legal-section">
            <h3>2. Hypothetical and simulated performance</h3>
            <div class="legal-caps-box">
              HYPOTHETICAL OR SIMULATED PERFORMANCE RESULTS HAVE CERTAIN INHERENT LIMITATIONS.
              UNLIKE AN ACTUAL PERFORMANCE RECORD, SIMULATED RESULTS DO NOT REPRESENT ACTUAL
              TRADING. ALSO, SINCE THE TRADES HAVE NOT ACTUALLY BEEN EXECUTED, THE RESULTS MAY HAVE
              UNDER- OR OVER-COMPENSATED FOR THE IMPACT, IF ANY, OF CERTAIN MARKET FACTORS, SUCH AS
              LACK OF LIQUIDITY. SIMULATED TRADING PROGRAMS IN GENERAL ARE ALSO SUBJECT TO THE FACT
              THAT THEY ARE DESIGNED WITH THE BENEFIT OF HINDSIGHT. NO REPRESENTATION IS BEING MADE
              THAT ANY ACCOUNT WILL OR IS LIKELY TO ACHIEVE PROFITS OR LOSSES SIMILAR TO THOSE
              SHOWN.
            </div>
          </section>

          <section class="legal-section">
            <h3>3. Market Data Notice & Latency Disclosures</h3>
            <p>
              3.1 <strong>Delayed and Derived Market Data.</strong> Market quotes, options chains,
              volume prints, and implied volatility metrics rendered in TradeCentral may be delayed
              by fifteen (15) minutes or more pursuant to exchange rules (including OPRA, NASDAQ,
              and NYSE). Workstation analytics are derived values intended for quantitative
              modeling, not execution routing.
            </p>
            <p>
              3.2 <strong>No Guarantee of Timeliness or Continuity.</strong> Licensor does not
              guarantee uninterrupted availability, latency bounds, or numerical accuracy of
              upstream data feeds. Missing or stale data states are rendered explicitly within the
              workstation and shall not be relied upon for time-critical financial operations.
            </p>
          </section>

          <section class="legal-section">
            <h3>4. No Broker-Dealer Relationship or Order Execution</h3>
            <p>
              TradeCentral does NOT accept customer deposits, route orders, hold funds, clear
              securities, or execute transactions. The application explicitly excludes order
              execution pipelines. Users who choose to place real-market orders through their
              independent third-party brokerages do so entirely at their own discretion and sole
              financial risk.
            </p>
          </section>

          <section class="legal-section">
            <h3>5. Substantial Risk of Capital Loss</h3>
            <p>
              Trading equities, options, futures, and derivative contracts involves substantial
              financial risk and is not suitable for all investors. The high degree of leverage that
              is often obtainable in options trading can work against you as well as for you. You
              may sustain a total loss of initial funds and additional capital. Never trade with
              capital you cannot afford to lose completely.
            </p>
          </section>

          <section class="legal-section">
            <h3>6. Operator Credentials and Acceptable Use</h3>
            <p>
              6.1 <strong>Operator Authorization.</strong> Access to non-public workstation surfaces
              requires authorization through the operator access control system. Operators are
              responsible for safeguarding credentials.
            </p>
            <p>
              6.2 <strong>Prohibited Actions.</strong> Users shall not conduct automated scraping,
              denial-of-service attempts, vulnerability probes, or circumvent authentication
              controls.
            </p>
          </section>
        </article>
      </section>
    </main>

    <footer class="legal-footer">
      <div class="footer-inner">
        <span>© 2026 TradeCentral · Syril Jacob · All rights reserved.</span>
        <span>Source available · All rights reserved · Research only</span>
      </div>
    </footer>
  </div>
</template>

<style scoped>
.legal-page {
  min-height: 100vh;
  background: #fbfbf8;
  color: #1a1a18;
  font-family:
    -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  line-height: 1.6;
}

.legal-topbar {
  border-bottom: 1px solid #e5e5dc;
  background: #ffffff;
  position: sticky;
  top: 0;
  z-index: 40;
}

.topbar-inner {
  max-width: 1280px;
  margin: 0 auto;
  padding: 14px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  text-decoration: none;
  color: inherit;
}

.wordmark {
  display: flex;
  flex-direction: column;
}

.wordmark strong {
  font-size: 15px;
  letter-spacing: -0.02em;
  color: #111110;
}

.wordmark small {
  font-size: 11px;
  color: #66665e;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.topbar-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #44443e;
  text-decoration: none;
  padding: 6px 10px;
  border-radius: 4px;
  border: 1px solid #e0e0d6;
  background: #fdfdfc;
  transition: all 0.15s ease;
}

.topbar-link:hover {
  background: #f0f0ea;
  color: #111110;
  border-color: #c8c8be;
}

.legal-container {
  max-width: 1280px;
  margin: 0 auto;
  padding: 40px 24px 80px;
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 48px;
}

.legal-nav-sidebar {
  position: relative;
}

.sidebar-sticky {
  position: sticky;
  top: 88px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.doc-badge {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  color: #8c5800;
  background: #fff4d6;
  border: 1px solid #ebd391;
  padding: 3px 8px;
  border-radius: 3px;
  width: fit-content;
}

.sidebar-title {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #111110;
  margin: 0;
}

.sidebar-subtitle {
  font-size: 13px;
  color: #66665e;
  margin: 0;
  line-height: 1.5;
}

.tab-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}

.tab-btn {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #e5e5dc;
  border-radius: 6px;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tab-btn:hover {
  border-color: #c0c0b4;
  background: #fcfcf9;
}

.tab-btn.active {
  border-color: #111110;
  background: #111110;
  color: #ffffff;
}

.tab-index {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 700;
  opacity: 0.6;
  padding-top: 2px;
}

.tab-label {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.tab-label strong {
  font-size: 13px;
  font-weight: 600;
  line-height: 1.3;
}

.tab-label small {
  font-size: 11px;
  opacity: 0.75;
}

.tab-btn.active .tab-label small {
  opacity: 0.85;
  color: #e5e5dc;
}

.quick-metadata {
  border-top: 1px solid #e5e5dc;
  border-bottom: 1px solid #e5e5dc;
  padding: 14px 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.meta-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.meta-k {
  color: #77776e;
}

.meta-v {
  font-weight: 600;
  color: #22221e;
  text-align: right;
}

.document-tools {
  display: flex;
  gap: 10px;
}

.tool-btn {
  flex: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  font-size: 12px;
  font-weight: 500;
  color: #33332e;
  background: #ffffff;
  border: 1px solid #dcdcd0;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s ease;
}

.tool-btn:hover {
  background: #f2f2eb;
  border-color: #b8b8aa;
}

.legal-document-view {
  background: #ffffff;
  border: 1px solid #e5e5dc;
  border-radius: 8px;
  padding: 48px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.contract-header {
  border-bottom: 2px solid #111110;
  padding-bottom: 24px;
  margin-bottom: 32px;
}

.contract-kicker {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  font-weight: 700;
  color: #88887e;
  letter-spacing: 0.08em;
  margin-bottom: 8px;
}

.contract-title {
  font-size: 26px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: #111110;
  margin: 0 0 16px;
  line-height: 1.25;
}

.contract-meta-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 12px;
  color: #55554e;
  margin-bottom: 20px;
}

.contract-meta-bar .sep {
  color: #c0c0b4;
}

.binding-callout {
  background: #fff8eb;
  border-left: 4px solid #b87a00;
  padding: 14px 18px;
  font-size: 13px;
  color: #4a3400;
  line-height: 1.5;
  border-radius: 0 4px 4px 0;
}

.binding-callout strong {
  display: block;
  font-size: 12px;
  margin-bottom: 4px;
  letter-spacing: 0.04em;
}

.legal-section {
  margin-bottom: 36px;
}

.legal-section h3 {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #111110;
  border-bottom: 1px solid #efefe6;
  padding-bottom: 8px;
  margin: 0 0 16px;
}

.legal-section p {
  font-size: 14px;
  color: #33332e;
  margin: 0 0 14px;
  line-height: 1.65;
}

.legal-list {
  margin: 0 0 16px 20px;
  padding: 0;
  font-size: 14px;
  color: #33332e;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.legal-caps-box {
  background: #f8f8f4;
  border: 1px solid #e0e0d6;
  padding: 16px 20px;
  font-size: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.6;
  color: #22221e;
  letter-spacing: 0.02em;
  border-radius: 4px;
}

.legal-footer {
  border-top: 1px solid #e5e5dc;
  background: #ffffff;
  padding: 24px;
}

.legal-footer .footer-inner {
  max-width: 1280px;
  margin: 0 auto;
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  font-size: 12px;
  color: #77776e;
  gap: 12px;
}

@media (max-width: 900px) {
  .legal-container {
    grid-template-columns: 1fr;
    gap: 32px;
    padding: 24px 16px 60px;
  }
  .sidebar-sticky {
    position: static;
  }
  .legal-document-view {
    padding: 24px 20px;
  }
  .contract-title {
    font-size: 22px;
  }
}

@media print {
  .legal-topbar,
  .legal-nav-sidebar,
  .legal-footer {
    display: none !important;
  }
  .legal-container {
    display: block !important;
    padding: 0 !important;
    max-width: 100% !important;
  }
  .legal-document-view {
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
  }
}
</style>
