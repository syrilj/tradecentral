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
              <span class="meta-k">Governing law</span>
              <span class="meta-v">Delaware, USA</span>
            </div>
            <div class="meta-row">
              <span class="meta-k">Licensor</span>
              <span class="meta-v">Syril Jacob</span>
            </div>
            <div class="meta-row">
              <span class="meta-k">Jurisdiction</span>
              <span class="meta-v">AAA Commercial Arbitration</span>
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
        <!-- TAB 1: SOFTWARE LICENSE AGREEMENT -->
        <article v-if="activeTab === 'license'" class="contract-article">
          <header class="contract-header">
            <div class="contract-kicker">INSTRUMENT NO. TC-EULA-2026.09</div>
            <h2 class="contract-title">
              Commercial Proprietary Software License and Evaluation Agreement
            </h2>
            <div class="contract-meta-bar">
              <span><strong>Licensor:</strong> Syril Jacob</span>
              <span class="sep">/</span>
              <span><strong>Product:</strong> TradeCentral Workstation</span>
              <span class="sep">/</span>
              <span><strong>Jurisdiction:</strong> Delaware, USA</span>
            </div>
            <div class="binding-callout" role="alert">
              <strong>CRITICAL NOTICE — LEGALLY BINDING CONTRACT:</strong>
              This Agreement is a legally enforceable contract between you ("Licensee") and Syril
              Jacob ("Licensor"). By cloning, downloading, installing, viewing, compiling,
              executing, or inspecting any source code or artifacts, you unconditionally agree to be
              bound by all terms, restrictions, and disclaimers herein.
            </div>
          </header>

          <section class="legal-section">
            <h3>1. Definitions</h3>
            <p>
              1.1 <strong>"Software"</strong> means the TradeCentral quantitative workstation and
              decision-support suite, encompassing all computer code (source code, object code,
              TypeScript, Vue components, Python research models, compiled scripts), algorithms,
              mathematical formulas, microstructure classification engines, dealer gamma exposure
              (GEX) calculation engines, options surface interpolators, volume-price analysis
              heuristics, configuration files, schemas, APIs, and associated technical
              documentation.
            </p>
            <p>
              1.2 <strong>"Licensor"</strong> means Syril Jacob, the exclusive creator, author, and
              sole holder of all worldwide copyright, patent, trademark, trade secret, and
              proprietary rights in and to the Software.
            </p>
            <p>
              1.3 <strong>"Evaluation Purpose"</strong> means the limited, personal, non-commercial,
              non-production inspection and architectural audit of the source code in a private
              evaluation environment solely for educational study and peer technical review.
            </p>
            <p>
              1.4 <strong>"Quantitative Models and Trade Secrets"</strong> means all regime
              transition matrices, causal envelopes, squeeze calculators, voltrend models, options
              pricing estimators, and alpha extraction heuristics embodied within the Software.
            </p>
          </section>

          <section class="legal-section">
            <h3>2. Limited License Grant & Reservation of Rights</h3>
            <p>
              2.1 <strong>Limited Evaluation Grant.</strong> Subject to the strict covenants and
              conditions set forth herein, Licensor grants to Licensee a personal, non-exclusive,
              non-transferable, non-sublicensable, revocable, royalty-free license solely to
              download or fork a single local copy of the Software source code and view it privately
              for the Evaluation Purpose.
            </p>
            <p>
              2.2 <strong>No Production or Operational Rights.</strong> This Agreement confers NO
              right or license to deploy, execute, host, run, or integrate the Software in any live,
              operational, staging, institutional, multi-user, or commercial environment.
            </p>
            <p>
              2.3 <strong>Absolute Reservation of Rights.</strong> All rights, titles, and interests
              not expressly granted in Section 2.1 are reserved exclusively by Licensor. No rights
              are granted by implication, estoppel, or exhaustion.
            </p>
          </section>

          <section class="legal-section">
            <h3>3. Strict Restrictions and Prohibitions</h3>
            <p>Licensee shall not, directly or indirectly, nor permit any third party to:</p>
            <ul class="legal-list">
              <li>
                <strong>No Live or Algorithmic Trading Execution:</strong> Execute, route, or
                integrate the Software, or any signals, analytics, or alerts generated thereby, into
                any brokerage account, live trading gateway, order routing system, algorithmic
                execution engine, or automated trading infrastructure.
              </li>
              <li>
                <strong>No Commercial Exploitation or Hosting:</strong> Deploy, host, lease, rent,
                sublicense, or distribute the Software as a Software-as-a-Service (SaaS), API
                platform, subscription service, or commercial product over any network or the public
                internet.
              </li>
              <li>
                <strong>No Derivative Works or Reverse Engineering:</strong> Decompile, disassemble,
                reverse engineer, translate, adapt, extract, or build derivative works or
                competitive products based upon the Software or its Quantitative Models.
              </li>
              <li>
                <strong>No Ingestion into AI/LLM Training Sets:</strong> Ingest, scrape, crawl,
                tokenize, process, or utilize any source code, models, heuristics, or documentation
                from the Software to train, fine-tune, benchmark, or evaluate any artificial
                intelligence model, large language model, or neural network.
              </li>
              <li>
                <strong>No Removal of Notices:</strong> Alter, obscure, or remove any copyright
                notices, trademark indicators, or proprietary confidentiality headers present in the
                Software.
              </li>
            </ul>
          </section>

          <section class="legal-section">
            <h3>4. Intellectual Property and Trade Secret Protection</h3>
            <p>
              4.1 <strong>Title.</strong> Licensor retains exclusive ownership of all right, title,
              and interest in and to the Software. This Agreement constitutes a restricted license
              to evaluate, not a conveyance or transfer of title.
            </p>
            <p>
              4.2 <strong>Trade Secret Protection.</strong> The Quantitative Models, microstructure
              heuristics, volume-price analysis algorithms, and signal fusion pipelines represent
              valuable trade secrets of Licensor under the Uniform Trade Secrets Act (UTSA) and 18
              U.S.C. § 1836 (Defend Trade Secrets Act). Licensee shall maintain strict
              confidentiality and protect the Software against unauthorized disclosure using
              reasonable care.
            </p>
          </section>

          <section class="legal-section">
            <h3>5. Disclaimer of Warranties</h3>
            <div class="legal-caps-box">
              THE SOFTWARE IS PROVIDED STRICTLY "AS IS" AND "AS AVAILABLE", WITH ALL FAULTS AND
              DEFECTS, AND WITHOUT WARRANTY OF ANY KIND. LICENSOR EXPRESSLY DISCLAIMS ALL
              WARRANTIES, EXPRESS, IMPLIED, OR STATUTORY, INCLUDING WITHOUT LIMITATION ANY IMPLIED
              WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, ACCURACY,
              QUIET ENJOYMENT, AND NON-INFRINGEMENT. LICENSOR DOES NOT WARRANT THAT THE SOFTWARE
              WILL OPERATE UNINTERRUPTED, ERROR-FREE, OR SECURE, OR THAT ANY MARKET DATA OR
              QUANTITATIVE CALCULATIONS ARE TIMELY, COMPLETE, OR RELIABLE.
            </div>
          </section>

          <section class="legal-section">
            <h3>6. Limitation of Liability</h3>
            <div class="legal-caps-box">
              TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT SHALL LICENSOR BE
              LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, CONSEQUENTIAL, SPECIAL, PUNITIVE, OR
              EXEMPLARY DAMAGES OF ANY KIND, INCLUDING BUT NOT LIMITED TO TRADING LOSSES, CAPITAL
              LOSSES, LOST PROFITS, LOST REVENUES, DATA CORRUPTION, OR SYSTEM DOWNTIME, ARISING OUT
              OF OR RELATED TO THIS AGREEMENT OR THE SOFTWARE, UNDER ANY THEORY OF LIABILITY
              (CONTRACT, TORT, NEGLIGENCE, STRICT LIABILITY, OR STATUTE), EVEN IF ADVISED OF THE
              POSSIBILITY OF SUCH DAMAGES. LICENSOR'S AGGREGATE CUMULATIVE LIABILITY UNDER THIS
              AGREEMENT SHALL BE LIMITED TO ZERO UNITED STATES DOLLARS ($0.00 USD).
            </div>
          </section>

          <section class="legal-section">
            <h3>7. Injunctive Relief and Breach</h3>
            <p>
              Licensee acknowledges that any violation of Sections 2, 3, or 4 will inflict
              immediate, irreparable harm upon Licensor for which monetary damages alone would be
              inadequate. Consequently, Licensor shall be entitled to seek immediate temporary and
              permanent injunctive relief and specific performance in any court of competent
              jurisdiction without the requirement of posting bond or proving actual monetary harm.
            </p>
          </section>

          <section class="legal-section">
            <h3>8. Governing Law, Arbitration, and General Terms</h3>
            <p>
              8.1 <strong>Governing Law.</strong> This Agreement is governed by and construed under
              the substantive laws of the State of Delaware, United States of America, without
              regard to conflict of law rules.
            </p>
            <p>
              8.2 <strong>Binding Arbitration.</strong> Any dispute arising under or relating to
              this Agreement shall be resolved through final and binding arbitration administered by
              the American Arbitration Association (AAA) under its Commercial Arbitration Rules in
              Wilmington, Delaware.
            </p>
            <p>
              8.3 <strong>Class Action and Jury Waiver.</strong> LICENSEE WAIVES ANY RIGHT TO
              PARTICIPATE IN ANY CLASS ACTION, COLLECTIVE ACTION, OR REPRESENTATIVE PROCEEDING
              AGAINST LICENSOR, AND WAIVES ALL RIGHTS TO A JURY TRIAL.
            </p>
            <p>
              8.4 <strong>Severability and Entire Agreement.</strong> If any provision is deemed
              unenforceable, it shall be reformed to the minimum extent necessary to achieve legal
              validity, and all remaining provisions shall remain in full force. This Agreement
              constitutes the entire agreement between the parties regarding its subject matter.
            </p>
          </section>
        </article>

        <!-- TAB 2: TERMS OF SERVICE & REGULATORY DISCLAIMERS -->
        <article v-else class="contract-article">
          <header class="contract-header">
            <div class="contract-kicker">REGULATORY GOVERNANCE & COMPLIANCE</div>
            <h2 class="contract-title">
              Terms of Service, Regulatory Disclaimers & Publisher Safe Harbor
            </h2>
            <div class="contract-meta-bar">
              <span><strong>Compliance Posture:</strong> Impersonal Research</span>
              <span class="sep">/</span>
              <span><strong>Regulatory Exclusion:</strong> Advisers Act § 202(a)(11)(D)</span>
              <span class="sep">/</span>
              <span><strong>CFTC:</strong> Rule 4.41 Compliant</span>
            </div>
            <div class="binding-callout" role="alert">
              <strong>FINANCIAL REGULATORY NOTICE:</strong>
              TradeCentral is a quantitative decision-support research instrument. It is NOT an
              investment advisory service, registered broker-dealer, or order execution gateway.
              Read these disclosures carefully before accessing or interpreting any workstation
              analytics.
            </div>
          </header>

          <section class="legal-section">
            <h3>1. Publisher's Exclusion — Impersonal Quantitative Research Only</h3>
            <p>
              TradeCentral operates under the bona fide newspaper/publisher exclusion provided by
              Section 202(a)(11)(D) of the Investment Advisers Act of 1940 (15 U.S.C. §
              80b-2(a)(11)(D)) and corresponding state securities statutes.
            </p>
            <p>
              All quantitative metrics, dealer gamma profiles, options chain analytics,
              microstructure classifications, volatility regimes, and scanner outputs provided by
              TradeCentral are strictly impersonal, algorithmic, and general in nature. TradeCentral
              does NOT provide personalized investment advice, customized trading recommendations,
              portfolio suitability assessments, or tailored financial strategies to any individual.
              No communication from TradeCentral should be construed as an offer, solicitation, or
              recommendation to buy or sell any security or financial derivative.
            </p>
          </section>

          <section class="legal-section">
            <h3>2. CFTC Rule 4.41 Mandated Disclaimer</h3>
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
        <span>Delaware, USA · AAA Arbitration · Impersonal Research Only</span>
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
