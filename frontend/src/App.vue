<template>
  <router-view />
</template>

<script setup>
// Use Vue Router to manage pages
</script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  color-scheme: dark;
  --mf-bg: #050912;
  --mf-bg-soft: #08111d;
  --mf-panel: rgba(10, 23, 36, 0.82);
  --mf-panel-strong: rgba(13, 31, 48, 0.94);
  --mf-border: rgba(132, 184, 209, 0.24);
  --mf-border-strong: rgba(65, 225, 255, 0.48);
  --mf-ink: #edf7ff;
  --mf-ink-muted: #9fb5c8;
  --mf-ink-faint: #6f879a;
  --mf-accent: #38e1ff;
  --mf-accent-soft: rgba(56, 225, 255, 0.16);
  --mf-green: #66f2a7;
  --mf-yellow: #ffd166;
  --mf-red: #ff7a90;
  --mf-violet: #a78bfa;
  --mf-radius: 18px;
  --mf-radius-sm: 10px;
  --mf-shadow: 0 24px 80px rgba(0, 0, 0, 0.38);
  --mf-font-sans: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  --mf-font-mono: 'JetBrains Mono', 'SFMono-Regular', monospace;
}

html {
  min-height: 100%;
  background: var(--mf-bg);
}

body {
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 10%, rgba(42, 177, 232, 0.18), transparent 30%),
    radial-gradient(circle at 84% 18%, rgba(122, 92, 255, 0.16), transparent 28%),
    linear-gradient(135deg, #040811 0%, #081320 52%, #03111a 100%);
  color: var(--mf-ink);
}

#app {
  min-height: 100vh;
  font-family: var(--mf-font-sans);
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  color: var(--mf-ink);
  background: transparent;
}

a {
  color: inherit;
}

input,
select,
textarea,
button {
  font-family: inherit;
}

button {
  color: inherit;
}

::selection {
  background: rgba(56, 225, 255, 0.28);
  color: #ffffff;
}

::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}

::-webkit-scrollbar-track {
  background: #06101a;
}

::-webkit-scrollbar-thumb {
  background: rgba(86, 140, 166, 0.7);
  border-radius: 999px;
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(56, 225, 255, 0.82);
}
</style>
