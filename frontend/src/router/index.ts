import { createRouter, createWebHistory } from 'vue-router'
export default createRouter({ history: createWebHistory(), routes: [
  { path: '/sales', component: () => import('@/views/AfterSalesView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/sales' },
] })
