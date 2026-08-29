<script setup lang="ts">
import AppIcon from '@/components/AppIcon.vue'
</script>

<template>
  <figure class="access-visual" aria-labelledby="access-visual-title">
    <figcaption id="access-visual-title">IDENTITY / BOUNDARY / EVIDENCE</figcaption>
    <svg viewBox="0 0 620 360" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <circle class="orbit orbit-outer" cx="310" cy="180" r="150" />
      <circle class="orbit" cx="310" cy="180" r="104" />
      <path
        class="access-trace"
        d="M50 243C115 208 142 252 199 182s92 17 143-37 98 23 143-39 65-25 91-3"
      />
      <path class="access-dash" d="M86 282C151 313 198 263 257 293s116 20 170-24 74-28 111-8" />
      <path class="register" d="M34 38h25M34 38v25M561 322h25M586 297v25" />
    </svg>
    <div class="access-core">
      <span><AppIcon name="shield" :size="30" /></span>
      <small>01 / IDENTITY</small>
      <strong>Operator session</strong>
    </div>
    <div class="access-point point-api">
      <span><AppIcon name="database" :size="17" /></span>
      <small>02 / BOUNDARY</small>
      <strong>Local research API</strong>
      <p>127.0.0.1 remains local.</p>
    </div>
    <div class="access-point point-flow">
      <span><AppIcon name="flow" :size="17" /></span>
      <small>03 / EVIDENCE</small>
      <strong>Measured Flow</strong>
      <p>The returned tape, with context.</p>
    </div>
    <footer>No demo tape or trade ticket · authenticate, preserve the boundary, inspect.</footer>
  </figure>
</template>

<style scoped>
.access-visual {
  position: relative;
  min-height: 405px;
  margin: 31px 0 0;
  overflow: hidden;
  color: #18181b;
}
.access-visual::before {
  content: '';
  position: absolute;
  inset: 22px 2px 35px;
  background: radial-gradient(circle at 50% 46%, rgba(0, 130, 230, 0.08), transparent 44%);
}
figcaption {
  position: absolute;
  z-index: 3;
  top: 0;
  left: 0;
  color: #6f6f78;
  font-family: var(--font-display);
  font-size: 8px;
  font-weight: 700;
  letter-spacing: 0.12em;
}
svg {
  position: absolute;
  inset: 6px 0 30px;
  width: 100%;
  height: calc(100% - 36px);
  fill: none;
  stroke: #c9c9c4;
  stroke-width: 1;
  vector-effect: non-scaling-stroke;
}
.orbit-outer {
  stroke-dasharray: 3 7;
}
.access-trace {
  stroke: #0082e6;
  stroke-width: 1.6;
}
.access-dash {
  stroke: #ff5229;
  stroke-dasharray: 5 7;
}
.register {
  stroke: #a8a8a2;
}
.access-core {
  position: absolute;
  z-index: 2;
  top: 49%;
  left: 50%;
  width: 180px;
  height: 180px;
  display: grid;
  place-content: center;
  justify-items: center;
  transform: translate(-50%, -50%);
  border: 1px solid #c9c9c4;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.92);
}
.access-core::before {
  content: '';
  position: absolute;
  inset: 10px;
  border: 1px solid #e4e3de;
  border-radius: 50%;
}
.access-core > span {
  width: 52px;
  height: 52px;
  display: grid;
  place-items: center;
  color: #0f8a5f;
  border: 1px solid #c9c9c4;
}
.access-core small,
.access-point small {
  margin-top: 12px;
  color: #c93a10;
  font-family: var(--font-display);
  font-size: 7px;
  font-weight: 700;
  letter-spacing: 0.09em;
}
.access-core strong {
  margin-top: 5px;
  font-family: var(--font-display);
  font-size: 15px;
  font-weight: 600;
}
.access-point {
  position: absolute;
  z-index: 3;
  width: 184px;
  display: grid;
  grid-template-columns: 31px 1fr;
  grid-template-rows: auto auto auto;
  column-gap: 9px;
  padding: 13px;
  border-left: 2px solid #0082e6;
  background: #f5f4ef;
}
.access-point > span {
  grid-row: 1 / 3;
  width: 31px;
  height: 31px;
  display: grid;
  place-items: center;
  color: #0082e6;
  border: 1px solid #c9c9c4;
}
.access-point small {
  grid-column: 2;
  display: block;
  margin-top: 0;
}
.access-point strong {
  grid-column: 2;
  display: block;
  margin-top: 3px;
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
}
.access-point p {
  grid-column: 1 / -1;
  padding-top: 8px;
  color: #565660;
  font-family: var(--font-ui);
  font-size: 9px;
}
.point-api {
  top: 50px;
  left: 3px;
}
.point-flow {
  right: 4px;
  bottom: 58px;
  border-color: #0f8a5f;
}
.point-flow > span {
  color: #0f8a5f;
}
footer {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  padding-top: 12px;
  color: #6f6f78;
  border-top: 1px solid #e4e3de;
  font-family: var(--font-display);
  font-size: 8px;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

@media (max-width: 620px) {
  .access-visual {
    min-height: 510px;
  }
  .access-core {
    top: 45%;
    width: 158px;
    height: 158px;
  }
  .access-point {
    width: 190px;
  }
  .access-point strong {
    font-size: 11px;
  }
  .point-api {
    top: 42px;
  }
  .point-flow {
    bottom: 70px;
  }
}
</style>
