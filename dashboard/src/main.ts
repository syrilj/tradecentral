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
        colorPrimary: '#a9c46c',
        colorBackground: '#14161d',
        colorInputBackground: '#0e1015',
        colorInputText: '#e9ecf2',
        colorText: '#e9ecf2',
        colorTextSecondary: '#9aa3b4',
        colorNeutral: '#7d879a',
        colorDanger: '#cf5f6b',
        colorSuccess: '#4fae80',
        borderRadius: '2px',
        fontFamily: 'Geist Variable, Geist, Instrument Sans, sans-serif',
      },
      elements: {
        rootBox: { width: '100%' },
        cardBox: { width: '100%', boxShadow: 'none' },
        card: { background: 'transparent', boxShadow: 'none', border: '0' },
        headerTitle: { display: 'none' },
        headerSubtitle: { display: 'none' },
        userButtonPopoverCard: {
          background: '#14161d',
          border: '1px solid #39404f',
          borderRadius: '2px',
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.65)',
        },
        userButtonPopoverFooter: {
          background: '#0e1015',
          borderTop: '1px solid #262a36',
        },
        userButtonPopoverActionButton: {
          color: '#c3c9d6',
          borderRadius: '2px',
          fontFamily: 'Geist Variable, Geist, Instrument Sans, sans-serif',
        },
        userPreviewMainIdentifier: {
          color: '#e9ecf2',
          fontFamily: 'Geist Mono Variable, Geist Mono, monospace',
          fontSize: '12px',
          fontWeight: '600',
        },
        userPreviewSecondaryIdentifier: {
          color: '#9aa3b4',
          fontSize: '11px',
        },
        userButtonAvatarBox: {
          width: '28px',
          height: '28px',
          borderRadius: '2px',
        },
        formButtonPrimary: {
          background: '#a9c46c',
          color: '#0a0b0f',
          borderRadius: '2px',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          fontSize: '10px',
          fontWeight: '700',
        },
        socialButtonsBlockButton: { borderRadius: '2px' },
        formFieldInput: { borderRadius: '2px', borderColor: '#39404f', backgroundColor: '#0e1015' },
        footer: { background: 'transparent' },
      },
    },
  })
  .use(router)
  .mount('#app')
