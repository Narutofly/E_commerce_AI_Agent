import { createApp } from 'vue'

import App from './App.vue'
import router from './router'

const app = createApp(App)

// Report unexpected Vue errors; request errors are rendered by the sales page.
app.config.errorHandler = (err, _instance, info) => {
  console.error('[N/CARE] Vue error:', info, err)
}

app.use(router)

app.mount('#app')
