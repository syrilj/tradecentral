import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'landing',
    component: () => import('@/views/LandingView.vue'),
    meta: { title: 'About', public: true },
  },
  {
    path: '/about',
    redirect: { name: 'landing' },
  },
  {
    path: '/desk',
    name: 'desk',
    component: () => import('@/views/DeskView.vue'),
    meta: { title: 'Desk', index: '01' },
  },
  {
    path: '/market',
    name: 'market',
    component: () => import('@/views/MarketView.vue'),
    meta: { title: 'Market', index: '02' },
  },
  {
    path: '/sectors',
    name: 'sectors',
    component: () => import('@/views/SectorsView.vue'),
    meta: { title: 'Sectors', index: '03' },
  },
  {
    path: '/sentiment',
    name: 'sentiment',
    component: () => import('@/views/SentimentView.vue'),
    meta: { title: 'Pulse', index: '04' },
  },
  /* Legacy path — structure + outliers now live on /sentiment */
  {
    path: '/anomalies',
    name: 'anomalies',
    redirect: (to) => ({
      name: 'sentiment',
      query: { ...to.query, tab: 'outliers' },
    }),
  },
  {
    path: '/options',
    name: 'options',
    component: () => import('@/views/OptionsView.vue'),
    meta: { title: 'Options Drift', index: '05' },
  },
  {
    path: '/flow',
    name: 'flow',
    component: () => import('@/views/FlowView.vue'),
    meta: { title: 'Market Flow', index: '04' },
  },
  {
    path: '/gates',
    name: 'gates',
    component: () => import('@/views/GatesView.vue'),
    meta: { title: 'Gates', index: '06' },
  },
  {
    path: '/cloud',
    name: 'cloud',
    component: () => import('@/views/CloudView.vue'),
    meta: { title: 'Cloud', index: '07' },
  },
  {
    path: '/evolution',
    name: 'evolution',
    component: () => import('@/views/EvolutionView.vue'),
    meta: { title: 'Evolution', index: '08' },
  },
  {
    path: '/research',
    name: 'research',
    component: () => import('@/views/ResearchView.vue'),
    meta: { title: 'Research', index: '09' },
  },
  {
    path: '/graph',
    name: 'graph',
    component: () => import('@/views/GraphView.vue'),
    meta: { title: 'Graph', index: '10' },
  },
  {
    path: '/adaptive',
    name: 'adaptive',
    component: () => import('@/views/AdaptiveView.vue'),
    meta: { title: 'Live Blend', index: '11' },
  },
  {
    path: '/fintel',
    name: 'fintel',
    component: () => import('@/views/FintelView.vue'),
    meta: { title: 'Fintel', index: '12' },
  },
  {
    path: '/changepoints',
    name: 'changepoints',
    component: () => import('@/views/ChangepointsView.vue'),
    meta: { title: 'Breaks', index: '13' },
  },
  {
    path: '/momentum',
    name: 'momentum',
    component: () => import('@/views/MomentumView.vue'),
    meta: { title: 'Momentum', index: '14' },
  },
  {
    path: '/flow-state',
    name: 'flowstate',
    redirect: (to) => ({
      name: 'flow',
      query: { ...to.query, tab: 'states' },
    }),
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.afterEach((to) => {
  const t = to.meta.title as string | undefined
  document.title = t ? `EDGE · ${t.toUpperCase()}` : 'EDGE · INSTRUMENT'
})
