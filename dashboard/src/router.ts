import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
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
    path: '/gates',
    name: 'gates',
    component: () => import('@/views/GatesView.vue'),
    meta: { title: 'Gates', index: '04' },
  },
  {
    path: '/cloud',
    name: 'cloud',
    component: () => import('@/views/CloudView.vue'),
    meta: { title: 'Cloud', index: '05' },
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
