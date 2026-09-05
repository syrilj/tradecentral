<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

withDefaults(
  defineProps<{
    session: string
    sessionLive: boolean
    sessionNote?: string | null
    dataAsof: string
    universe: string
    searchable: string
    readinessLabel: string
    cleared: boolean
    blockers?: number | null
    shadow: string
    gateGo: string
    gateNoGo: string
    gateUnknown: string
    apiDown: boolean
    apiStale: boolean
    contacting: boolean
  }>(),
  {
    sessionNote: null,
    blockers: null,
  },
)
</script>

<template>
  <section class="live-proof" aria-labelledby="live-proof-title">
    <div class="proof-copy">
      <p class="proof-index">LIVE PROOF / 01</p>
      <h2 id="live-proof-title">Context that admits<br />what it does not know.</h2>
      <p>
        The public surface reads the same local resources as the workstation. Missing values stay
        missing; readiness never becomes a marketing claim.
      </p>
      <div class="proof-source">
        <AppIcon name="database" :size="16" />
        <span><strong>Local API</strong><small>127.0.0.1 · measured state only</small></span>
      </div>
    </div>

    <figure class="state-aperture" aria-label="Current measured instrument state">
      <figcaption><span>TC / INSTRUMENT APERTURE</span><span>XNYS · NOW</span></figcaption>

      <div v-if="apiDown" class="aperture-down" role="status">
        <span><AppIcon name="alert" :size="24" /></span>
        <div>
          <small>STATE UNAVAILABLE</small>
          <strong>Local API unavailable</strong>
          <p>Nothing is rendered in its place. Start the workstation to restore measured state.</p>
          <code>bash edge/tools/run_dashboard.sh</code>
        </div>
      </div>

      <div v-else class="aperture-stage">
        <svg
          class="aperture-orbits"
          viewBox="0 0 720 330"
          preserveAspectRatio="none"
          aria-hidden="true"
        >
          <ellipse cx="360" cy="165" rx="165" ry="112" />
          <ellipse cx="360" cy="165" rx="255" ry="145" />
          <path d="M44 165H676M360 18V312" />
          <path class="aperture-sweep" d="M360 165 594 69" />
          <path
            class="aperture-trace"
            d="M42 229C110 204 148 239 202 186s101 4 155-36 98 12 153-49 104-9 168-42"
          />
        </svg>

        <div class="session-core" :class="{ live: sessionLive }">
          <span class="core-ring" aria-hidden="true" />
          <small>MARKET SESSION</small>
          <strong>{{ session }}</strong>
          <p>{{ sessionNote || `As of ${dataAsof}` }}</p>
        </div>

        <dl class="state-node node-universe">
          <dt><AppIcon name="radar" :size="14" />Broad universe</dt>
          <dd>{{ universe }}<small> symbols</small></dd>
        </dl>
        <dl class="state-node node-searchable">
          <dt><AppIcon name="search" :size="14" />Searchable</dt>
          <dd>{{ searchable }}<small> symbols</small></dd>
        </dl>
        <dl class="state-node node-readiness" :class="cleared ? 'is-cleared' : 'is-blocked'">
          <dt><AppIcon name="gate" :size="14" />Live readiness</dt>
          <dd :class="cleared ? 'clear' : 'blocked'">{{ readinessLabel }}</dd>
          <!-- A second <dd>, not a bare <small>: a <dl> may only contain
               dt/dd/div, and the loose <small> made the definition list
               invalid for assistive tech. -->
          <dd v-if="blockers !== null && !cleared" class="blocker-note">
            {{ blockers }} blocking reasons
          </dd>
        </dl>
        <dl class="state-node node-shadow">
          <dt><AppIcon name="session" :size="14" />Shadow evidence</dt>
          <dd>{{ shadow }}<small> sessions</small></dd>
        </dl>
      </div>

      <footer class="aperture-foot">
        <span v-if="apiStale" class="stale">Last-good state · refresh fault</span>
        <span v-else-if="contacting">Contacting local API…</span>
        <span v-else>No illustrative values</span>
        <span class="gate-key"
          ><i class="go" />{{ gateGo }} GO <i class="no" />{{ gateNoGo }} NO-GO <i />{{
            gateUnknown
          }}
          UNKNOWN</span
        >
      </footer>
    </figure>
  </section>
</template>

<style scoped>
.live-proof {
  display: grid;
  grid-template-columns: minmax(250px, 0.42fr) minmax(600px, 1fr);
  gap: clamp(48px, 7vw, 104px);
  align-items: center;
  padding: 74px 0 78px;
  color: var(--ink);
}
.proof-index {
  color: var(--phosphor);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.12em;
}
.proof-copy h2 {
  margin-top: 17px;
  font-family: var(--font-display);
  font-size: clamp(36px, 3.5vw, 52px);
  font-weight: 600;
  letter-spacing: -0.03em;
  line-height: 1.01;
}
.proof-copy > p:not(.proof-index) {
  margin-top: 22px;
  max-width: 42ch;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 14px;
  line-height: 1.7;
}
.proof-source {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 28px;
  padding-top: 18px;
  color: var(--call);
  border-top: 1px solid var(--rule);
}
.proof-source span {
  display: grid;
  gap: 3px;
}
.proof-source strong {
  color: var(--ink);
  font-family: var(--font-ui);
  font-size: 11px;
  font-weight: 650;
}
.proof-source small {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  letter-spacing: 0.07em;
  text-transform: uppercase;
}
.state-aperture {
  position: relative;
  margin: 0;
  padding: 17px 19px 13px;
  overflow: hidden;
  border: 1px solid var(--rule-hi);
  border-top: 2px solid var(--call);
  background: var(--panel);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.18);
}
.state-aperture::before,
.state-aperture::after {
  content: '';
  position: absolute;
  z-index: 4;
  width: 13px;
  height: 13px;
  pointer-events: none;
}
.state-aperture::before {
  top: -1px;
  left: -1px;
  border-top: 1px solid var(--ink);
  border-left: 1px solid var(--ink);
}
.state-aperture::after {
  right: -1px;
  bottom: -1px;
  border-right: 1px solid var(--ink);
  border-bottom: 1px solid var(--ink);
}
figcaption,
.aperture-foot {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}
figcaption {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--rule);
}
.aperture-stage {
  position: relative;
  min-height: 344px;
  overflow: hidden;
  background:
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px);
  background-size: 28px 28px;
}
.aperture-orbits {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  fill: none;
  stroke: var(--rule);
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.aperture-sweep {
  stroke: var(--put);
  stroke-dasharray: 4 5;
}
.aperture-trace {
  stroke: var(--call);
  stroke-width: 1.5;
}
.session-core {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 174px;
  height: 174px;
  display: grid;
  place-content: center;
  text-align: center;
  transform: translate(-50%, -50%);
  color: var(--ink);
  border: 1px solid var(--rule-hi);
  border-radius: 50%;
  background: var(--panel-hi);
}
.core-ring {
  position: absolute;
  inset: 9px;
  border: 1px solid var(--rule);
  border-radius: 50%;
}
.session-core::after {
  content: '';
  position: absolute;
  top: 18px;
  left: 50%;
  width: 7px;
  height: 7px;
  transform: translateX(-50%);
  border-radius: 50%;
  background: var(--ink-ghost);
}
.session-core.live::after {
  background: var(--phosphor);
  animation: aperture-pulse 2s ease-in-out infinite;
}
.session-core small {
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
}
.session-core strong {
  margin-top: 8px;
  font-family: var(--font-data);
  font-size: 20px;
  font-weight: 500;
  letter-spacing: -0.03em;
}
.session-core p {
  margin-top: 5px;
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
}
.state-node {
  position: absolute;
  min-width: 150px;
  padding: 10px 12px;
  border-left: 2px solid var(--call);
  background: var(--panel-hi);
}
.state-node dt {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-dim);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.state-node dd {
  margin-top: 6px;
  color: var(--ink);
  font-family: var(--font-data);
  font-size: 16px;
}
.state-node dd small,
.state-node .blocker-note {
  color: var(--ink-faint);
  font-family: var(--font-data);
  font-size: var(--t-nano);
}
.state-node .blocker-note {
  margin-top: 3px;
}
.node-universe {
  top: 27px;
  left: 22px;
}
.node-searchable {
  top: 27px;
  right: 22px;
}
.node-readiness {
  bottom: 26px;
  left: 22px;
  border-color: var(--put);
}
.node-readiness.is-cleared {
  border-color: var(--call);
}
.node-readiness.is-blocked {
  border-color: var(--put);
}
.node-shadow {
  right: 22px;
  bottom: 26px;
  border-color: var(--phosphor);
}
.state-node .clear {
  color: var(--long);
}
.state-node .blocked {
  color: var(--short);
}
.aperture-foot {
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid var(--rule);
}
.aperture-foot .stale {
  color: var(--warn);
}
.gate-key {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.gate-key i {
  width: 6px;
  height: 6px;
  background: var(--ink-ghost);
}
.gate-key .go {
  background: var(--long);
}
.gate-key .no {
  background: var(--short);
}
.aperture-down {
  min-height: 344px;
  display: grid;
  grid-template-columns: auto 1fr;
  place-content: center;
  gap: 18px;
  padding: 40px;
}
.aperture-down > span {
  width: 50px;
  height: 50px;
  display: grid;
  place-items: center;
  color: var(--short);
  border: 1px solid var(--rule-hi);
}
.aperture-down small {
  color: var(--short);
  font-family: var(--font-data);
  font-size: var(--t-nano);
  font-weight: 700;
  letter-spacing: 0.1em;
}
.aperture-down strong {
  display: block;
  margin-top: 8px;
  font-family: var(--font-display);
  font-size: 23px;
}
.aperture-down p {
  margin-top: 7px;
  max-width: 46ch;
  color: var(--ink-dim);
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.5;
}
.aperture-down code {
  display: inline-block;
  margin-top: 13px;
  padding: 7px 9px;
  border: 1px solid var(--rule-hi);
  font-family: var(--font-data);
  font-size: var(--t-nano);
}
@keyframes aperture-pulse {
  50% {
    opacity: 0.35;
  }
}

@media (max-width: 1080px) {
  .live-proof {
    grid-template-columns: 1fr;
  }
  .proof-copy {
    max-width: 650px;
  }
}
@media (max-width: 680px) {
  .live-proof {
    gap: 38px;
    padding: 64px 0 70px;
  }
  .state-aperture {
    padding-inline: 13px;
  }
  .aperture-stage {
    min-height: 520px;
  }
  .session-core {
    top: 45%;
    width: 150px;
    height: 150px;
  }
  .state-node {
    min-width: 128px;
  }
  .node-universe {
    top: 20px;
    left: 8px;
  }
  .node-searchable {
    top: 20px;
    right: 8px;
  }
  .node-readiness {
    bottom: 24px;
    left: 8px;
  }
  .node-shadow {
    right: 8px;
    bottom: 24px;
  }
  .aperture-foot {
    align-items: flex-start;
    flex-direction: column;
  }
}
@media (prefers-reduced-motion: reduce) {
  .session-core.live::after {
    animation: none;
  }
}
</style>
