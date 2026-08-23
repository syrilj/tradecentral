import { createApp } from 'vue'
import { clerkPlugin } from '@clerk/vue'
import App from './App.vue'
import { router } from './router'
import { isLocalAuthMode } from './auth'
import './styles/base.css'

const publishableKey = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

// EDGE_AUTH_MODE=local is the zero-credential workstation posture documented in
// .env.example: the desk runs on a local operator session with the API isolated
// by its 127.0.0.1 bind, so no Clerk publishable key is needed. Any other mode
// keeps the Clerk operator session and still requires the key.
if (!publishableKey && !isLocalAuthMode()) {
  throw new Error('VITE_CLERK_PUBLISHABLE_KEY is required. Add it to edge/.env or the GCP build environment.')
}

if (publishableKey && !isLocalAuthMode()) {
  createApp(App)
    .use(clerkPlugin, {
    publishableKey,
    signInUrl: '/auth',
    signUpUrl: '/auth',
    signInFallbackRedirectUrl: '/flow',
    signUpFallbackRedirectUrl: '/flow',
    // Clerk appearance is anchored to the desk instrument tokens (tokens.css)
    // via var() references so the Clerk UI can never drift from the desk
    // palette. The values resolve at runtime against :root custom properties
    // loaded by base.css — Clerk renders inside the desk DOM tree (and its
    // popover portals at document.body, which still inherits :root tokens).
    appearance: {
      variables: {
        colorPrimary: 'var(--phosphor)',
        colorBackground: 'var(--panel)',
        colorInputBackground: 'var(--void-lift)',
        colorInputText: 'var(--ink)',
        colorText: 'var(--ink)',
        colorTextSecondary: 'var(--ink-dim)',
        colorNeutral: 'var(--ink-faint)',
        colorDanger: 'var(--halt)',
        colorSuccess: 'var(--long)',
        borderRadius: 'var(--r-xs)',
        fontFamily: 'var(--font-ui)',
      },
      elements: {
        rootBox: { width: '100%' },
        cardBox: { width: '100%', boxShadow: 'none' },
        card: { background: 'transparent', boxShadow: 'none', border: '0' },
        headerTitle: { display: 'none' },
        headerSubtitle: { display: 'none' },
        userButtonPopoverCard: {
          background: 'var(--panel)',
          border: 'var(--hair) solid var(--rule-hi)',
          borderRadius: 'var(--r-xs)',
          // Structural-black elevation shadow for the popover overlay (allowed
          // by the guard — pure black with alpha is the neutral substrate of
          // the dark theme, not a palette color).
          boxShadow: '0 8px 32px rgba(0, 0, 0, 0.65)',
        },
        userButtonPopoverFooter: {
          background: 'var(--void-lift)',
          borderTop: 'var(--hair) solid var(--rule)',
        },
        userButtonPopoverActionButton: {
          color: 'var(--ink-soft)',
          borderRadius: 'var(--r-xs)',
          fontFamily: 'var(--font-ui)',
        },
        userPreviewMainIdentifier: {
          color: 'var(--ink)',
          fontFamily: 'var(--font-data)',
          fontSize: 'var(--t-tiny)',
          fontWeight: '600',
        },
        userPreviewSecondaryIdentifier: {
          color: 'var(--ink-dim)',
          fontSize: 'var(--t-micro)',
        },
        userButtonAvatarBox: {
          width: '28px',
          height: '28px',
          borderRadius: 'var(--r-xs)',
        },
        formButtonPrimary: {
          background: 'var(--phosphor)',
          color: 'var(--void)',
          borderRadius: 'var(--r-xs)',
          textTransform: 'uppercase',
          letterSpacing: 'var(--track-label)',
          fontSize: 'var(--t-micro)',
          fontWeight: '700',
        },
        socialButtonsBlockButton: { borderRadius: 'var(--r-xs)' },
        formFieldInput: {
          borderRadius: 'var(--r-xs)',
          borderColor: 'var(--rule-hi)',
          backgroundColor: 'var(--void-lift)',
        },
        footer: { background: 'transparent' },
      },
    },
  })
    .use(router)
    .mount('#app')
} else {
  // Local operator session: no Clerk plugin, so no @clerk/vue composable or
  // component may run (they throw outside the plugin). App.vue branches on the
  // same flag and renders the identical shell with a local identity.
  createApp(App)
    .use(router)
    .mount('#app')
}
