<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

onMounted(() => document.body.classList.add('edge-landing-mode'))
onUnmounted(() => document.body.classList.remove('edge-landing-mode'))

const capabilities = [
  {
    index: '01',
    title: 'Market context',
    copy: 'Start with regime, volatility, breadth and sector leadership before judging a single ticker.',
    route: '/market',
    meta: 'REGIME · BREADTH · SECTORS',
  },
  {
    index: '02',
    title: 'Stock research',
    copy: 'Read price structure, volume, momentum, support, resistance and change points in one symbol workspace.',
    route: '/market',
    meta: 'PRICE · VOLUME · STRUCTURE',
  },
  {
    index: '03',
    title: 'Options positioning',
    copy: 'Map gamma exposure, open interest, implied volatility and strike concentration around the underlying.',
    route: '/options',
    meta: 'GEX · OI · IV · LEVELS',
  },
  {
    index: '04',
    title: 'Flow & anomalies',
    copy: 'Surface unusual options activity and market-wide flow without reducing every print to a bullish or bearish label.',
    route: '/flow',
    meta: 'FLOW · SWEEPS · OUTLIERS',
  },
  {
    index: '05',
    title: 'Positioning risk',
    copy: 'Bring short interest, borrow, ownership and crowding into the same view as the technical setup.',
    route: '/fintel',
    meta: 'SHORT · BORROW · OWNERS',
  },
  {
    index: '06',
    title: 'Research gates',
    copy: 'Keep model evidence separate from conviction with pre-registered tests, holdouts and explicit go / no-go verdicts.',
    route: '/research',
    meta: 'GATES · MODELS · EVIDENCE',
  },
]

const process = [
  ['01', 'Regime', 'Volatility, breadth, sectors and market state'],
  ['02', 'Scan', 'Momentum, anomalies and cross-sectional candidates'],
  ['03', 'Structure', 'Price, volume, levels and regime breaks'],
  ['04', 'Positioning', 'Gamma, open interest, IV and options flow'],
  ['05', 'Evidence', 'Research gates, model confidence and failure conditions'],
]
</script>

<template>
  <div class="landing-page">
    <header class="landing-nav">
      <RouterLink class="brand" to="/" aria-label="EDGE home">
        <span class="brand-word">EDGE</span>
        <span class="brand-rule" aria-hidden="true" />
        <span class="brand-sub">RESEARCH INSTRUMENT FOR MARKETS</span>
      </RouterLink>

      <nav class="nav-links" aria-label="Landing navigation">
        <a href="#instrument">Instrument</a>
        <RouterLink to="/market">Stocks</RouterLink>
        <RouterLink to="/options">Options</RouterLink>
        <RouterLink to="/research">Research</RouterLink>
      </nav>

      <RouterLink class="nav-cta" to="/desk">
        OPEN THE DESK
        <span aria-hidden="true">→</span>
      </RouterLink>
    </header>

    <main>
      <section class="hero section-shell">
        <div class="hero-copy">
          <div class="eyebrow"><span class="eyebrow-dot" /> CROSS-SECTIONAL EQUITIES + OPTIONS RESEARCH</div>
          <h1>Stocks, measured<br><span>in context.</span></h1>
          <p class="hero-lede">
            EDGE combines market regime, stock structure, options positioning, flow, volatility,
            momentum and research evidence into one desk built for finding and validating setups.
          </p>

          <div class="hero-actions">
            <RouterLink class="button button-primary" to="/desk">OPEN THE DESK <span>→</span></RouterLink>
            <RouterLink class="button button-secondary" to="/flow">INSPECT MARKET FLOW <span>↗</span></RouterLink>
          </div>

          <div class="hero-tags" aria-label="Research coverage">
            <span>US EQUITIES</span>
            <span>OPTIONS</span>
            <span>VOLATILITY</span>
            <span>FLOW</span>
            <span>MODEL RESEARCH</span>
          </div>
        </div>

        <div class="market-field" aria-label="Global market structure visualization">
          <div class="field-label field-label-top">GLOBAL LIQUIDITY FIELD</div>
          <div class="field-label field-label-bottom">VENUES · INDEXES · OPTIONS · CROSS-ASSET CONTEXT</div>

          <svg class="world-field" viewBox="0 0 1000 520" role="img" aria-label="Abstract world map with capital flow paths between major financial centers">
            <defs>
              <filter id="liquid" x="-20%" y="-20%" width="140%" height="140%">
                <feTurbulence type="fractalNoise" baseFrequency="0.008 0.018" numOctaves="2" seed="11" result="noise" />
                <feDisplacementMap in="SourceGraphic" in2="noise" scale="16" xChannelSelector="R" yChannelSelector="G" />
              </filter>
              <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
                <feGaussianBlur stdDeviation="7" />
              </filter>
              <pattern id="mapDots" width="8" height="8" patternUnits="userSpaceOnUse">
                <circle cx="1.5" cy="1.5" r="1.05" fill="currentColor" />
              </pattern>
              <clipPath id="landMask">
                <path d="M92 115 C130 77 177 72 226 90 C250 99 267 116 260 132 C247 151 220 155 205 171 C185 191 180 216 153 226 C137 217 128 198 116 181 C101 159 82 137 92 115 Z" />
                <path d="M225 213 C254 218 277 244 279 274 C279 312 256 351 227 389 C208 370 205 340 195 312 C186 282 191 239 225 213 Z" />
                <path d="M431 112 C455 94 491 94 518 108 C524 122 510 134 495 139 C481 146 467 158 449 151 C438 140 425 126 431 112 Z" />
                <path d="M457 161 C489 151 525 162 543 188 C558 211 558 243 548 273 C534 311 507 341 479 358 C461 335 454 307 443 282 C432 249 425 211 436 183 C441 173 448 166 457 161 Z" />
                <path d="M507 108 C548 83 601 75 651 83 C694 90 733 105 769 122 C803 139 833 154 869 163 C896 171 912 186 903 203 C886 222 855 219 833 230 C809 243 793 264 769 268 C747 257 734 236 713 228 C686 218 657 228 633 216 C610 205 598 183 573 176 C550 169 525 170 510 151 C500 138 495 121 507 108 Z" />
                <path d="M779 298 C803 282 837 281 862 295 C885 309 902 332 897 349 C882 365 854 369 830 360 C807 351 783 334 779 298 Z" />
                <path d="M886 232 C901 223 918 226 925 239 C923 250 911 257 900 254 C891 250 884 242 886 232 Z" />
              </clipPath>
            </defs>

            <g class="latlon" aria-hidden="true">
              <path d="M40 130 H960 M30 205 H970 M25 280 H975 M40 355 H960" />
              <path d="M155 55 C120 180 120 350 160 470 M310 45 C285 180 285 350 315 480 M500 35 V485 M690 45 C715 180 715 350 690 480 M845 55 C880 180 880 350 840 470" />
            </g>

            <g class="liquid-underlay" filter="url(#soft)" aria-hidden="true">
              <path d="M62 175 C214 98 340 121 458 173 C590 230 701 117 944 157" />
              <path d="M78 281 C252 210 348 294 490 251 C625 210 724 238 931 322" />
              <path d="M133 363 C294 302 395 386 548 331 C666 289 763 320 885 397" />
            </g>

            <g class="liquid-lines" filter="url(#liquid)" aria-hidden="true">
              <path d="M50 170 C207 89 342 122 463 177 C596 237 701 111 953 151" />
              <path d="M69 277 C249 201 352 295 491 248 C631 201 731 232 942 322" />
              <path d="M126 360 C291 293 399 385 547 328 C668 281 772 314 895 400" />
              <path d="M189 96 C294 175 368 192 490 182 C619 171 694 210 818 276" />
              <path d="M235 426 C343 331 462 304 574 308 C711 314 788 239 914 208" />
            </g>

            <g class="land" clip-path="url(#landMask)">
              <rect x="0" y="0" width="1000" height="520" fill="url(#mapDots)" />
            </g>
            <g class="coast">
              <path d="M92 115 C130 77 177 72 226 90 C250 99 267 116 260 132 C247 151 220 155 205 171 C185 191 180 216 153 226 C137 217 128 198 116 181 C101 159 82 137 92 115 Z" />
              <path d="M225 213 C254 218 277 244 279 274 C279 312 256 351 227 389 C208 370 205 340 195 312 C186 282 191 239 225 213 Z" />
              <path d="M431 112 C455 94 491 94 518 108 C524 122 510 134 495 139 C481 146 467 158 449 151 C438 140 425 126 431 112 Z" />
              <path d="M457 161 C489 151 525 162 543 188 C558 211 558 243 548 273 C534 311 507 341 479 358 C461 335 454 307 443 282 C432 249 425 211 436 183 C441 173 448 166 457 161 Z" />
              <path d="M507 108 C548 83 601 75 651 83 C694 90 733 105 769 122 C803 139 833 154 869 163 C896 171 912 186 903 203 C886 222 855 219 833 230 C809 243 793 264 769 268 C747 257 734 236 713 228 C686 218 657 228 633 216 C610 205 598 183 573 176 C550 169 525 170 510 151 C500 138 495 121 507 108 Z" />
              <path d="M779 298 C803 282 837 281 862 295 C885 309 902 332 897 349 C882 365 854 369 830 360 C807 351 783 334 779 298 Z" />
            </g>

            <g class="routes" aria-hidden="true">
              <path d="M192 154 Q355 43 469 137" />
              <path d="M192 154 Q501 32 786 157" />
              <path d="M469 137 Q622 70 786 157" />
              <path d="M469 137 Q662 154 835 213" />
              <path d="M786 157 Q813 181 835 213" />
              <path d="M192 154 Q379 252 673 291" />
            </g>

            <g class="nodes">
              <g transform="translate(192 154)"><circle r="8" /><circle r="2.4" /><text x="12" y="-10">NEW YORK</text></g>
              <g transform="translate(161 147)"><circle r="5" /><circle r="1.8" /><text x="-10" y="25" text-anchor="end">CHICAGO</text></g>
              <g transform="translate(469 137)"><circle r="7" /><circle r="2.2" /><text x="10" y="-9">LONDON</text></g>
              <g transform="translate(509 146)"><circle r="5" /><circle r="1.8" /><text x="8" y="21">FRANKFURT</text></g>
              <g transform="translate(786 157)"><circle r="7" /><circle r="2.2" /><text x="11" y="-9">TOKYO</text></g>
              <g transform="translate(835 213)"><circle r="6" /><circle r="2" /><text x="10" y="18">HONG KONG</text></g>
              <g transform="translate(673 291)"><circle r="5" /><circle r="1.8" /><text x="9" y="20">SINGAPORE</text></g>
            </g>
          </svg>

          <div class="field-readout">
            <span><b>01</b> MARKET REGIME</span>
            <span><b>02</b> STOCK STRUCTURE</span>
            <span><b>03</b> OPTIONS POSITIONING</span>
          </div>
        </div>
      </section>

      <section id="instrument" class="discipline section-shell">
        <div class="section-intro">
          <div>
            <span class="section-kicker">THE INSTRUMENT</span>
            <h2>One research desk.<br>Six decision layers.</h2>
          </div>
          <p>
            The point is not another screen full of indicators. Each layer answers a different
            question so market context, ticker structure and positioning do not get collapsed into one score.
          </p>
        </div>

        <div class="capability-grid">
          <RouterLink v-for="item in capabilities" :key="item.index" :to="item.route" class="capability-card">
            <div class="capability-head">
              <span class="cap-index">{{ item.index }}</span>
              <span class="cap-arrow">↗</span>
            </div>
            <h3>{{ item.title }}</h3>
            <p>{{ item.copy }}</p>
            <span class="cap-meta">{{ item.meta }}</span>
          </RouterLink>
        </div>
      </section>

      <section class="workflow section-shell">
        <div class="workflow-head">
          <div>
            <span class="section-kicker">FROM MARKET TO SYMBOL</span>
            <h2>Context first. Setup second.</h2>
          </div>
          <p>A stock is not isolated from its regime, sector, volatility surface or dealer positioning.</p>
        </div>

        <div class="process-strip">
          <div v-for="step in process" :key="step[0]" class="process-step">
            <div class="process-number">{{ step[0] }}</div>
            <div class="process-copy">
              <h3>{{ step[1] }}</h3>
              <p>{{ step[2] }}</p>
            </div>
          </div>
        </div>
      </section>

      <section class="preview section-shell">
        <div class="preview-topline">
          <span>DESK PREVIEW · SYMBOL TRIAGE</span>
          <span>ILLUSTRATIVE INTERFACE — NOT LIVE MARKET DATA</span>
        </div>

        <div class="preview-shell">
          <div class="preview-toolbar">
            <div>
              <span class="micro">WATCH UNIVERSE</span>
              <strong>US LARGE / LIQUID GROWTH</strong>
            </div>
            <div class="preview-tabs">
              <span class="active">SIGNALS</span>
              <span>FLOW</span>
              <span>LEVELS</span>
            </div>
          </div>

          <div class="table-wrap">
            <table class="landing-table">
              <thead>
                <tr>
                  <th>SYMBOL</th>
                  <th>MARKET STRUCTURE</th>
                  <th>OPTIONS FLOW</th>
                  <th>GAMMA</th>
                  <th>IV REGIME</th>
                  <th>RESEARCH STATE</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="symbol">NVDA</td><td>Trend continuation</td><td class="positive">Positive skew</td><td>Positive</td><td>Elevated</td><td><span class="state watch">WATCH</span></td>
                </tr>
                <tr>
                  <td class="symbol">TSLA</td><td>Range / squeeze</td><td class="negative">Put-heavy</td><td>Negative pocket</td><td>High</td><td><span class="state wait">WAIT</span></td>
                </tr>
                <tr>
                  <td class="symbol">AMD</td><td>Breakout test</td><td>Mixed</td><td>Neutral</td><td>Normal</td><td><span class="state review">REVIEW</span></td>
                </tr>
                <tr>
                  <td class="symbol">AAPL</td><td>Support retest</td><td>Balanced</td><td>Positive</td><td>Normal</td><td><span class="state review">REVIEW</span></td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="preview-foot">
            <span>PRICE + VOLUME + OPTIONS + POSITIONING + RESEARCH GATES</span>
            <RouterLink to="/desk">OPEN LIVE DESK →</RouterLink>
          </div>
        </div>
      </section>

      <section class="closing section-shell">
        <div>
          <span class="section-kicker">EDGE · RESEARCH INSTRUMENT</span>
          <h2>Measure the setup.<br>Then decide.</h2>
        </div>
        <div class="closing-copy">
          <p>Built to make stock research more explicit: what moved, where positioning sits, which level matters, and whether the evidence survives testing.</p>
          <RouterLink class="button button-primary closing-cta" to="/desk">ENTER THE INSTRUMENT <span>→</span></RouterLink>
        </div>
      </section>
    </main>

    <footer class="landing-footer section-shell">
      <div class="footer-brand">EDGE</div>
      <div class="footer-copy">RESEARCH ONLY · NO EXECUTION · NO INVESTMENT ADVICE</div>
      <div class="footer-links">
        <RouterLink to="/research">METHOD</RouterLink>
        <RouterLink to="/gates">GATES</RouterLink>
        <RouterLink to="/desk">DESK</RouterLink>
      </div>
    </footer>
  </div>
</template>

<style scoped>
:global(body.edge-landing-mode) {
  overflow: auto !important;
  background: #090b0f;
}

:global(body.edge-landing-mode #app) {
  height: auto;
  min-height: 100vh;
  overflow: visible !important;
}

:global(body.edge-landing-mode .shell) {
  display: block !important;
  height: auto !important;
  min-height: 100vh;
  overflow: visible !important;
}

:global(body.edge-landing-mode .rail),
:global(body.edge-landing-mode .strip),
:global(body.edge-landing-mode .foot),
:global(body.edge-landing-mode .skip-link) {
  display: none !important;
}

:global(body.edge-landing-mode .stage) {
  display: block !important;
  width: 100% !important;
  height: auto !important;
  min-height: 100vh !important;
  padding: 0 !important;
  overflow: visible !important;
}

.landing-page {
  --landing-max: 1440px;
  position: relative;
  z-index: 3;
  min-height: 100vh;
  color: var(--ink);
  background:
    radial-gradient(circle at 78% 10%, rgba(169, 196, 108, 0.045), transparent 28%),
    linear-gradient(180deg, rgba(10, 12, 17, 0.5), rgba(8, 10, 14, 0.92));
}

.section-shell,
.landing-nav {
  width: min(var(--landing-max), calc(100% - 72px));
  margin-inline: auto;
}

.landing-nav {
  height: 72px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  border-bottom: 1px solid var(--rule);
}

.brand {
  justify-self: start;
  display: inline-flex;
  align-items: center;
  gap: 10px;
  color: var(--ink);
  text-decoration: none;
}

.brand:hover { text-decoration: none; }
.brand-word {
  font-family: var(--font-ui);
  font-size: 16px;
  font-weight: 760;
  letter-spacing: -0.035em;
}
.brand-rule { width: 1px; height: 18px; background: var(--rule-hi); }
.brand-sub {
  font-family: var(--font-display);
  font-size: 8px;
  letter-spacing: 0.13em;
  color: var(--ink-faint);
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 30px;
}
.nav-links a {
  color: var(--ink-dim);
  font: 500 11px var(--font-ui);
  text-decoration: none;
}
.nav-links a:hover { color: var(--ink); text-decoration: none; }

.nav-cta {
  justify-self: end;
  min-height: 34px;
  display: inline-flex;
  align-items: center;
  gap: 15px;
  padding: 0 14px;
  border: 1px solid var(--phosphor-dim);
  color: #0a0b0f;
  background: var(--phosphor);
  font: 700 9px var(--font-display);
  letter-spacing: 0.08em;
  text-decoration: none;
}
.nav-cta:hover { text-decoration: none; background: #b4cd7d; }

.hero {
  min-height: 660px;
  display: grid;
  grid-template-columns: minmax(420px, 0.82fr) minmax(620px, 1.18fr);
  align-items: center;
  gap: 42px;
  padding: 78px 0 64px;
  border-bottom: 1px solid var(--rule);
}

.hero-copy { position: relative; z-index: 2; max-width: 590px; }
.eyebrow,
.section-kicker,
.preview-topline,
.micro {
  font-family: var(--font-display);
  font-size: 9px;
  font-weight: 600;
  letter-spacing: 0.12em;
  color: var(--ink-faint);
  text-transform: uppercase;
}
.eyebrow { display: flex; align-items: center; gap: 8px; margin-bottom: 26px; }
.eyebrow-dot { width: 5px; height: 5px; background: var(--phosphor); }

h1,
h2,
h3 { margin: 0; }

.hero h1 {
  font-family: var(--font-ui);
  font-size: clamp(64px, 6vw, 96px);
  line-height: 0.92;
  letter-spacing: -0.065em;
  font-weight: 690;
  max-width: 720px;
}
.hero h1 span { color: var(--phosphor); font-weight: 620; }
.hero-lede {
  max-width: 610px;
  margin-top: 30px;
  color: var(--ink-soft);
  font-size: 16px;
  line-height: 1.65;
}

.hero-actions { display: flex; gap: 10px; margin-top: 30px; }
.button {
  min-height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 18px;
  padding: 0 17px;
  border: 1px solid var(--rule-hi);
  font: 700 9px var(--font-display);
  letter-spacing: 0.08em;
  text-decoration: none;
}
.button:hover { text-decoration: none; }
.button-primary { color: #0a0b0f; background: var(--phosphor); border-color: var(--phosphor); }
.button-primary:hover { background: #b4cd7d; }
.button-secondary { color: var(--ink); background: rgba(20, 22, 29, 0.56); }
.button-secondary:hover { border-color: var(--ink-faint); }

.hero-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0;
  margin-top: 37px;
  padding-top: 16px;
  border-top: 1px solid var(--rule-faint);
}
.hero-tags span {
  padding-right: 13px;
  margin-right: 13px;
  border-right: 1px solid var(--rule);
  font: 600 8px var(--font-display);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.hero-tags span:last-child { border-right: 0; }

.market-field {
  position: relative;
  min-width: 0;
  height: 500px;
  overflow: hidden;
  border: 1px solid var(--rule-faint);
  background: rgba(9, 12, 17, 0.55);
}
.market-field::before,
.market-field::after {
  content: '';
  position: absolute;
  z-index: 2;
  width: 12px;
  height: 12px;
  pointer-events: none;
}
.market-field::before { inset: 0 auto auto 0; border-top: 1px solid var(--phosphor-dim); border-left: 1px solid var(--phosphor-dim); }
.market-field::after { inset: auto 0 0 auto; border-right: 1px solid var(--phosphor-dim); border-bottom: 1px solid var(--phosphor-dim); }
.field-label {
  position: absolute;
  z-index: 3;
  left: 16px;
  font: 600 8px var(--font-display);
  letter-spacing: 0.10em;
  color: var(--ink-faint);
}
.field-label-top { top: 14px; }
.field-label-bottom { bottom: 15px; }

.world-field { width: 100%; height: 100%; color: rgba(195, 201, 214, 0.33); }
.latlon path { fill: none; stroke: rgba(154, 163, 180, 0.085); stroke-width: 0.8; }
.land { color: rgba(195, 201, 214, 0.34); }
.coast path { fill: none; stroke: rgba(195, 201, 214, 0.19); stroke-width: 0.8; }
.liquid-underlay path { fill: none; stroke: rgba(169, 196, 108, 0.22); stroke-width: 10; }
.liquid-lines path { fill: none; stroke: rgba(169, 196, 108, 0.46); stroke-width: 1.3; }
.routes path { fill: none; stroke: rgba(169, 196, 108, 0.38); stroke-width: 0.9; stroke-dasharray: 4 5; }
.nodes circle:first-child { fill: rgba(169, 196, 108, 0.08); stroke: rgba(169, 196, 108, 0.48); stroke-width: 0.8; }
.nodes circle:nth-child(2) { fill: var(--phosphor); stroke: none; }
.nodes text { fill: rgba(195, 201, 214, 0.72); font: 600 8px var(--font-display); letter-spacing: 0.08em; }
.field-readout {
  position: absolute;
  right: 15px;
  bottom: 13px;
  display: flex;
  gap: 15px;
  font: 600 7px var(--font-display);
  letter-spacing: 0.08em;
  color: var(--ink-faint);
}
.field-readout b { color: var(--phosphor); font-weight: 600; margin-right: 4px; }

.discipline,
.workflow,
.preview,
.closing { padding: 88px 0; border-bottom: 1px solid var(--rule); }

.section-intro,
.workflow-head,
.closing {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 80px;
  align-items: end;
}
.section-intro h2,
.workflow-head h2,
.closing h2 {
  margin-top: 14px;
  font-family: var(--font-ui);
  font-size: clamp(38px, 4vw, 58px);
  font-weight: 620;
  line-height: 1.02;
  letter-spacing: -0.045em;
}
.section-intro > p,
.workflow-head > p,
.closing-copy > p {
  max-width: 590px;
  color: var(--ink-dim);
  font-size: 15px;
  line-height: 1.7;
}

.capability-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin-top: 48px;
  border-top: 1px solid var(--rule);
  border-left: 1px solid var(--rule);
}
.capability-card {
  min-height: 250px;
  display: flex;
  flex-direction: column;
  padding: 22px;
  border-right: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
  color: var(--ink);
  background: rgba(20, 22, 29, 0.32);
  text-decoration: none;
  transition: background var(--dur-fast) ease, border-color var(--dur-fast) ease;
}
.capability-card:hover { text-decoration: none; background: rgba(26, 29, 38, 0.66); }
.capability-head { display: flex; align-items: center; justify-content: space-between; }
.cap-index { font: 500 16px var(--font-data); color: var(--ink-faint); }
.cap-arrow { color: var(--phosphor); opacity: 0; transition: opacity var(--dur-fast) ease; }
.capability-card:hover .cap-arrow { opacity: 1; }
.capability-card h3 { margin-top: 48px; font-family: var(--font-ui); font-size: 20px; font-weight: 590; letter-spacing: -0.02em; }
.capability-card p { margin-top: 12px; max-width: 360px; color: var(--ink-dim); line-height: 1.55; }
.cap-meta { margin-top: auto; padding-top: 24px; font: 600 8px var(--font-display); letter-spacing: 0.10em; color: var(--phosphor-dim); }

.workflow-head { align-items: center; }
.process-strip {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  margin-top: 45px;
  border-top: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}
.process-step {
  position: relative;
  min-height: 176px;
  display: grid;
  grid-template-rows: auto 1fr;
  gap: 28px;
  padding: 17px 18px 22px;
  border-right: 1px solid var(--rule);
}
.process-step:last-child { border-right: none; }
.process-number { font: 500 10px var(--font-data); color: var(--phosphor); }
.process-copy h3 { font-size: 14px; font-weight: 600; }
.process-copy p { margin-top: 8px; color: var(--ink-faint); font-size: 12px; line-height: 1.55; }
.process-step:not(:last-child)::after {
  content: '→';
  position: absolute;
  z-index: 2;
  right: -8px;
  top: 50%;
  color: var(--ink-faint);
  background: #090b0f;
  font: 500 11px var(--font-data);
}

.preview { padding-top: 72px; }
.preview-topline { display: flex; justify-content: space-between; padding-bottom: 13px; }
.preview-shell { border: 1px solid var(--rule-hi); background: rgba(15, 17, 23, 0.76); }
.preview-toolbar {
  min-height: 72px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
  border-bottom: 1px solid var(--rule);
}
.preview-toolbar > div:first-child { display: grid; gap: 5px; }
.preview-toolbar strong { font: 600 12px var(--font-data); letter-spacing: 0.02em; }
.preview-tabs { display: flex; align-self: stretch; }
.preview-tabs span {
  min-width: 82px;
  display: grid;
  place-items: center;
  border-left: 1px solid var(--rule);
  color: var(--ink-faint);
  font: 600 8px var(--font-display);
  letter-spacing: 0.08em;
}
.preview-tabs .active { color: var(--ink); border-bottom: 2px solid var(--phosphor); background: var(--phosphor-wash); }
.table-wrap { overflow-x: auto; }
.landing-table { width: 100%; border-collapse: collapse; min-width: 940px; }
.landing-table th,
.landing-table td { height: 48px; padding: 0 17px; text-align: left; border-bottom: 1px solid var(--rule-faint); }
.landing-table th { color: var(--ink-faint); font: 600 8px var(--font-display); letter-spacing: 0.08em; }
.landing-table td { color: var(--ink-dim); font: 400 12px var(--font-data); }
.landing-table .symbol { color: var(--ink); font-weight: 600; }
.positive { color: var(--long) !important; }
.negative { color: var(--short) !important; }
.state { display: inline-flex; min-width: 58px; justify-content: center; padding: 4px 6px; border: 1px solid var(--rule-hi); font: 600 8px var(--font-display); letter-spacing: 0.06em; }
.state.watch { color: var(--phosphor); border-color: var(--phosphor-dim); }
.state.wait { color: var(--ink-faint); }
.state.review { color: var(--call-hi); border-color: rgba(91, 149, 181, 0.5); }
.preview-foot { min-height: 48px; display: flex; align-items: center; justify-content: space-between; padding: 0 17px; color: var(--ink-faint); font: 600 8px var(--font-display); letter-spacing: 0.08em; }
.preview-foot a { color: var(--phosphor); text-decoration: none; }

.closing { align-items: center; }
.closing-copy { display: flex; flex-direction: column; align-items: flex-start; gap: 25px; }
.closing-cta { min-width: 205px; }

.landing-footer {
  min-height: 90px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  color: var(--ink-faint);
}
.footer-brand { font: 760 14px var(--font-ui); color: var(--ink); }
.footer-copy { font: 600 8px var(--font-display); letter-spacing: 0.08em; }
.footer-links { justify-self: end; display: flex; gap: 22px; }
.footer-links a { color: var(--ink-faint); font: 600 8px var(--font-display); letter-spacing: 0.08em; text-decoration: none; }
.footer-links a:hover { color: var(--ink); }

@media (max-width: 1180px) {
  .landing-nav { grid-template-columns: 1fr auto; }
  .nav-links { display: none; }
  .hero { grid-template-columns: 1fr; padding-top: 64px; }
  .hero-copy { max-width: 760px; }
  .market-field { height: 470px; }
  .capability-grid { grid-template-columns: repeat(2, 1fr); }
  .process-strip { grid-template-columns: 1fr; }
  .process-step { min-height: 108px; grid-template-columns: 48px 1fr; grid-template-rows: 1fr; align-items: center; border-right: 0; border-bottom: 1px solid var(--rule); }
  .process-step:last-child { border-bottom: 0; }
  .process-step::after { display: none; }
}

@media (max-width: 760px) {
  .section-shell,
  .landing-nav { width: min(100% - 32px, var(--landing-max)); }
  .brand-sub,
  .brand-rule { display: none; }
  .nav-cta { min-height: 32px; padding-inline: 10px; }
  .hero { min-height: 0; padding: 54px 0 40px; gap: 38px; }
  .hero h1 { font-size: clamp(52px, 16vw, 72px); }
  .hero-lede { font-size: 14px; }
  .hero-actions { flex-direction: column; align-items: stretch; }
  .button { justify-content: space-between; }
  .market-field { height: 360px; margin-inline: -8px; }
  .field-readout { display: none; }
  .discipline,
  .workflow,
  .preview,
  .closing { padding: 62px 0; }
  .section-intro,
  .workflow-head,
  .closing { grid-template-columns: 1fr; gap: 24px; }
  .capability-grid { grid-template-columns: 1fr; }
  .capability-card { min-height: 220px; }
  .preview-topline { gap: 18px; }
  .preview-topline span:last-child { text-align: right; }
  .preview-tabs { display: none; }
  .preview-foot { gap: 18px; }
  .landing-footer { grid-template-columns: 1fr auto; }
  .footer-copy { display: none; }
}
</style>
