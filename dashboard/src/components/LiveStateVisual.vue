<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'

withDefaults(defineProps<{
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
}>(), {
  sessionNote: null,
  blockers: null,
})
</script>

<template>
  <section class="live-proof" aria-labelledby="live-proof-title">
    <div class="proof-copy">
      <p class="proof-index">LIVE PROOF / 01</p>
      <h2 id="live-proof-title">Context that admits<br>what it does not know.</h2>
      <p>
        The public surface reads the same local resources as the workstation.
        Missing values stay missing; readiness never becomes a marketing claim.
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
        <svg class="aperture-orbits" viewBox="0 0 720 330" preserveAspectRatio="none" aria-hidden="true">
          <ellipse cx="360" cy="165" rx="165" ry="112" />
          <ellipse cx="360" cy="165" rx="255" ry="145" />
          <path d="M44 165H676M360 18V312" />
          <path class="aperture-sweep" d="M360 165 594 69" />
          <path class="aperture-trace" d="M42 229C110 204 148 239 202 186s101 4 155-36 98 12 153-49 104-9 168-42" />
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
        <dl class="state-node node-readiness">
          <dt><AppIcon name="gate" :size="14" />Live readiness</dt>
          <dd :class="cleared ? 'clear' : 'blocked'">{{ readinessLabel }}</dd>
          <small v-if="blockers !== null && !cleared">{{ blockers }} blocking reasons</small>
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
        <span class="gate-key"><i class="go" />{{ gateGo }} GO <i class="no" />{{ gateNoGo }} NO-GO <i />{{ gateUnknown }} UNKNOWN</span>
      </footer>
    </figure>
  </section>
</template>

<style scoped>
.live-proof {
  display: grid;
  grid-template-columns: minmax(250px, .42fr) minmax(600px, 1fr);
  gap: clamp(48px, 7vw, 104px);
  align-items: center;
  padding: 74px 0 78px;
  color: #141413;
}
.proof-index { color: #d97757; font-family: var(--font-display); font-size: 9px; font-weight: 700; letter-spacing: .12em; }
.proof-copy h2 { margin-top: 17px; font-family: var(--font-ui); font-size: clamp(36px, 3.5vw, 52px); font-weight: 570; letter-spacing: -.052em; line-height: 1.01; }
.proof-copy > p:not(.proof-index) { margin-top: 22px; max-width: 42ch; color: #65635d; font-family: var(--font-ui); font-size: 14px; line-height: 1.7; }
.proof-source { display: flex; align-items: center; gap: 12px; margin-top: 28px; padding-top: 18px; color: #567c9c; border-top: 1px solid #cbc8be; }
.proof-source span { display: grid; gap: 3px; }
.proof-source strong { color: #34342f; font-family: var(--font-ui); font-size: 11px; font-weight: 650; }
.proof-source small { color: #817e75; font-family: var(--font-display); font-size: 8px; letter-spacing: .07em; text-transform: uppercase; }
.state-aperture { position: relative; margin: 0; padding: 17px 19px 13px; overflow: hidden; border: 1px solid #c5c1b7; border-top: 2px solid #6a9bcc; background: #eeece4; box-shadow: 18px 20px 0 rgba(106, 155, 204, .14); }
.state-aperture::before,
.state-aperture::after { content: ''; position: absolute; z-index: 4; width: 13px; height: 13px; pointer-events: none; }
.state-aperture::before { top: -1px; left: -1px; border-top: 1px solid #141413; border-left: 1px solid #141413; }
.state-aperture::after { right: -1px; bottom: -1px; border-right: 1px solid #141413; border-bottom: 1px solid #141413; }
figcaption,
.aperture-foot { display: flex; justify-content: space-between; gap: 18px; color: #6f6d65; font-family: var(--font-display); font-size: 8px; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; }
figcaption { padding-bottom: 12px; border-bottom: 1px solid #c9c6bd; }
.aperture-stage { position: relative; min-height: 344px; overflow: hidden; background: linear-gradient(rgba(20,20,19,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(20,20,19,.045) 1px, transparent 1px); background-size: 28px 28px; }
.aperture-orbits { position: absolute; inset: 0; width: 100%; height: 100%; fill: none; stroke: rgba(20,20,19,.16); stroke-width: 1; vector-effect: non-scaling-stroke; }
.aperture-sweep { stroke: #d97757; stroke-dasharray: 4 5; }
.aperture-trace { stroke: #6a9bcc; stroke-width: 1.5; }
.session-core { position: absolute; top: 50%; left: 50%; width: 174px; height: 174px; display: grid; place-content: center; text-align: center; transform: translate(-50%, -50%); color: #141413; border: 1px solid #77746c; border-radius: 50%; background: rgba(250,249,245,.9); }
.core-ring { position: absolute; inset: 9px; border: 1px solid #c1beb4; border-radius: 50%; }
.session-core::after { content: ''; position: absolute; top: 18px; left: 50%; width: 7px; height: 7px; transform: translateX(-50%); border-radius: 50%; background: #77746c; }
.session-core.live::after { background: #788c5d; animation: aperture-pulse 2s ease-in-out infinite; }
.session-core small { font-family: var(--font-display); font-size: 8px; font-weight: 700; letter-spacing: .1em; }
.session-core strong { margin-top: 8px; font-family: var(--font-data); font-size: 20px; font-weight: 600; letter-spacing: -.03em; }
.session-core p { margin-top: 5px; color: #716f67; font-family: var(--font-data); font-size: 8px; }
.state-node { position: absolute; min-width: 150px; padding: 10px 12px; border-left: 2px solid #6a9bcc; background: rgba(250,249,245,.92); }
.state-node dt { display: flex; align-items: center; gap: 6px; color: #68665f; font-family: var(--font-display); font-size: 7px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
.state-node dd { margin-top: 6px; color: #24241f; font-family: var(--font-data); font-size: 16px; }
.state-node dd small,
.state-node > small { color: #77746d; font-family: var(--font-data); font-size: 8px; }
.node-universe { top: 27px; left: 22px; }
.node-searchable { top: 27px; right: 22px; }
.node-readiness { bottom: 26px; left: 22px; border-color: #d97757; }
.node-shadow { right: 22px; bottom: 26px; border-color: #788c5d; }
.state-node .clear { color: #657b4d; }
.state-node .blocked { color: #a56045; }
.aperture-foot { align-items: center; padding-top: 12px; border-top: 1px solid #c9c6bd; }
.aperture-foot .stale { color: #9b632f; }
.gate-key { display: inline-flex; align-items: center; gap: 6px; }
.gate-key i { width: 6px; height: 6px; background: #8a8880; }
.gate-key .go { background: #788c5d; }
.gate-key .no { background: #d97757; }
.aperture-down { min-height: 344px; display: grid; grid-template-columns: auto 1fr; place-content: center; gap: 18px; padding: 40px; }
.aperture-down > span { width: 50px; height: 50px; display: grid; place-items: center; color: #9a4f39; border: 1px solid #bdb9af; }
.aperture-down small { color: #9a4f39; font-family: var(--font-display); font-size: 8px; font-weight: 700; letter-spacing: .1em; }
.aperture-down strong { display: block; margin-top: 8px; font-family: var(--font-ui); font-size: 23px; }
.aperture-down p { margin-top: 7px; max-width: 46ch; color: #68665f; font-family: var(--font-ui); font-size: 12px; line-height: 1.5; }
.aperture-down code { display: inline-block; margin-top: 13px; padding: 7px 9px; border: 1px solid #bdb9af; font-family: var(--font-data); font-size: 9px; }
@keyframes aperture-pulse { 50% { opacity: .35; } }

@media (max-width: 1080px) {
  .live-proof { grid-template-columns: 1fr; }
  .proof-copy { max-width: 650px; }
}
@media (max-width: 680px) {
  .live-proof { gap: 38px; padding: 64px 0 70px; }
  .state-aperture { padding-inline: 13px; box-shadow: 9px 11px 0 rgba(106,155,204,.14); }
  .aperture-stage { min-height: 520px; }
  .session-core { top: 45%; width: 150px; height: 150px; }
  .state-node { min-width: 128px; }
  .node-universe { top: 20px; left: 8px; }
  .node-searchable { top: 20px; right: 8px; }
  .node-readiness { bottom: 24px; left: 8px; }
  .node-shadow { right: 8px; bottom: 24px; }
  .aperture-foot { align-items: flex-start; flex-direction: column; }
}
@media (prefers-reduced-motion: reduce) { .session-core.live::after { animation: none; } }
</style>
