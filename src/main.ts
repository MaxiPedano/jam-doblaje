import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Catalog from './views/Catalog.vue'
import AccessPage from './views/AccessPage.vue'
import Settings from './views/Settings.vue'
import WatchPage from './views/WatchPage.vue'
import Studio from './views/Studio.vue'
import './style.css'
import './subscriptions.css'
import './studio.css'

const router = createRouter({ history: createWebHashHistory(), routes: [
  { path: '/', component: Catalog },
  { path: '/mis-escenas', alias: '/mi-karaoke', component: Catalog, props: { personal: true } },
  { path: '/acceso', component: AccessPage },
  { path: '/configuracion', component: Settings },
  { path: '/doblaje/:id', component: WatchPage },
  { path: '/studio', component: Studio },
  { path: '/:pathMatch(.*)*', redirect: '/' },
] })
createApp(App).use(router).mount('#app')
