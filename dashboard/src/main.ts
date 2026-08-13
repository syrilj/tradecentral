import { createApp } from 'vue'
import { clerkPlugin } from '@clerk/vue'
import App from './App.vue'
import { router } from './router'
import './styles/base.css'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

if (!publishableKey) {
  throw new Error('VITE_CLERK_PUBLISHABLE_KEY is required. Add it to edge/.env or the GCP build environment.')
}

createApp(App)
  .use(clerkPlugin, {
    publishableKey,
    signInUrl: '/auth',
    signUpUrl: '/auth',
    signInFallbackRedirectUrl: '/flow',
    signUpFallbackRedirectUrl: '/flow',
    appearance: {
      variables: {
        colorPrimary: '#d97757',
        colorBackground: '#faf9f5',
        colorText: '#141413',
        colorTextSecondary: '#6f6c64',
        colorNeutral: '#141413',
        borderRadius: '0px',
        fontFamily: 'Instrument Sans Variable, Instrument Sans, sans-serif',
      },
      elements: {
        rootBox: { width: '100%' },
        cardBox: { width: '100%', boxShadow: 'none' },
        card: { background: 'transparent', boxShadow: 'none', border: '0' },
        headerTitle: { display: 'none' },
        headerSubtitle: { display: 'none' },
        formButtonPrimary: {
          background: '#141413',
          borderRadius: '0',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          fontSize: '10px',
        },
        socialButtonsBlockButton: { borderRadius: '0' },
        formFieldInput: { borderRadius: '0' },
        footer: { background: 'transparent' },
      },
    },
  })
  .use(router)
  .mount('#app')
