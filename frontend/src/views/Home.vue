<template>
  <div class="home-page">
    <nav class="site-nav">
      <button class="brand-button" type="button" @click="router.push('/')">
        <span class="brand-mark"><img :src="brandMark" alt="MiroFish" /></span>
        <span class="brand-copy">
          <strong>MiroFish</strong>
          <span>Online</span>
        </span>
      </button>

      <div class="nav-links">
        <button class="nav-link" type="button" @click="router.push('/audience')">Audience Lab</button>
        <button class="nav-link accent" type="button" @click="router.push('/audience/graph')">Graph</button>
        <a class="nav-link" href="https://github.com/pdurlej/mirofish-online" target="_blank" rel="noreferrer">
          GitHub
        </a>
      </div>
    </nav>

    <main class="home-shell">
      <section class="hero-grid">
        <div class="hero-copy">
          <p class="eyebrow">Synthetic Audience Graph</p>
          <h1>Test ideas before they spend your attention.</h1>
          <p class="hero-text">
            MiroFish turns rough content, product, and startup questions into
            structured reactions from a stable synthetic audience. Each run
            becomes part of a living graph, so later ideas reveal repeated
            objections, clusters, and promising branches.
          </p>

          <div class="hero-actions">
            <button class="primary-action" type="button" @click="router.push('/audience')">
              Run audience test
              <span>→</span>
            </button>
            <button class="secondary-action" type="button" @click="router.push('/audience/graph')">
              Open graph
            </button>
          </div>
        </div>

        <aside class="signal-card">
          <div class="signal-orbit">
            <img :src="brandMark" alt="" />
            <span class="orbit one"></span>
            <span class="orbit two"></span>
            <span class="node a"></span>
            <span class="node b"></span>
            <span class="node c"></span>
          </div>
          <div class="signal-summary">
            <span class="live-dot"></span>
            <span>Graph memory online</span>
          </div>
          <div class="stat-grid">
            <div>
              <strong>20</strong>
              <span>personas</span>
            </div>
            <div>
              <strong>Neo4j</strong>
              <span>memory</span>
            </div>
            <div>
              <strong>D3</strong>
              <span>map</span>
            </div>
          </div>
        </aside>
      </section>

      <section class="route-grid" aria-label="Primary workspaces">
        <button class="route-card main-route" type="button" @click="router.push('/audience')">
          <span class="card-kicker">01 / Audience Lab</span>
          <strong>Topic tests</strong>
          <span>Run the 20-person reviewer set and get objections, channel fit, reliability, cost, and next action.</span>
        </button>
        <button class="route-card" type="button" @click="router.push('/audience/graph')">
          <span class="card-kicker">02 / Graph</span>
          <strong>Trend map</strong>
          <span>Scan clusters, semantic similarity edges, and previous topic branches across the full run history.</span>
        </button>
        <button class="route-card" type="button" @click="scrollToLab">
          <span class="card-kicker">03 / Document Lab</span>
          <strong>Simulation files</strong>
          <span>Use the older document simulation lane when the input starts as PDFs, markdown, or text files.</span>
        </button>
      </section>

      <section ref="labSection" class="document-lab">
        <div class="lab-intro">
          <p class="eyebrow">Legacy simulation lane</p>
          <h2>Seed a file-backed simulation.</h2>
          <p>
            This lane keeps the existing document workflow available, but the
            main product path is now the audience graph.
          </p>

          <div class="workflow-list">
            <div v-for="step in steps" :key="step.num" class="workflow-item">
              <span>{{ step.num }}</span>
              <div>
                <strong>{{ step.title }}</strong>
                <small>{{ step.desc }}</small>
              </div>
            </div>
          </div>
        </div>

        <form class="lab-console" @submit.prevent="startSimulation">
          <div class="console-header">
            <span>Reality seeds</span>
            <span>PDF / MD / TXT</span>
          </div>

          <div
            class="upload-zone"
            :class="{ active: isDragOver, filled: files.length > 0 }"
            @dragover.prevent="handleDragOver"
            @dragleave.prevent="handleDragLeave"
            @drop.prevent="handleDrop"
            @click="triggerFileInput"
          >
            <input
              ref="fileInput"
              type="file"
              multiple
              accept=".pdf,.md,.txt"
              :disabled="loading"
              @change="handleFileSelect"
            />
            <div v-if="files.length === 0" class="upload-placeholder">
              <strong>Drop files</strong>
              <span>or browse from disk</span>
            </div>
            <div v-else class="file-list">
              <div v-for="(file, index) in files" :key="`${file.name}-${index}`" class="file-item">
                <span class="file-ext">{{ fileExtension(file.name) }}</span>
                <span class="file-name">{{ file.name }}</span>
                <button type="button" class="remove-file" @click.stop="removeFile(index)">×</button>
              </div>
            </div>
          </div>

          <label class="prompt-field">
            <span>Simulation prompt</span>
            <textarea
              v-model="formData.simulationRequirement"
              rows="7"
              placeholder="Describe the simulation goal or prediction question..."
              :disabled="loading"
            />
          </label>

          <button class="primary-action wide" type="submit" :disabled="!canSubmit || loading">
            <span>{{ loading ? 'Starting...' : 'Start document simulation' }}</span>
            <span>→</span>
          </button>
          <p v-if="error" class="error-text">{{ error }}</p>
        </form>
      </section>

      <section class="history-wrap">
        <HistoryDatabase />
      </section>
    </main>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import HistoryDatabase from '../components/HistoryDatabase.vue'
import brandMark from './audienceGraph/brand-mark.png'

const steps = [
  { num: '01', title: 'Graph Build', desc: 'Extract entities and relations from source material.' },
  { num: '02', title: 'Environment Setup', desc: 'Generate simulation context and reviewer constraints.' },
  { num: '03', title: 'Simulation', desc: 'Run the multi-agent sequence and collect state changes.' },
  { num: '04', title: 'Report', desc: 'Summarize outcomes into a decision-ready report.' },
  { num: '05', title: 'Interaction', desc: 'Inspect findings or continue with the generated context.' },
]

const router = useRouter()
const formData = ref({ simulationRequirement: '' })
const files = ref([])
const loading = ref(false)
const error = ref('')
const isDragOver = ref(false)
const fileInput = ref(null)
const labSection = ref(null)

const canSubmit = computed(() => {
  return formData.value.simulationRequirement.trim() !== '' && files.value.length > 0
})

const triggerFileInput = () => {
  if (!loading.value) fileInput.value?.click()
}

const handleFileSelect = (event) => {
  addFiles(Array.from(event.target.files || []))
  event.target.value = ''
}

const handleDragOver = () => {
  isDragOver.value = true
}

const handleDragLeave = () => {
  isDragOver.value = false
}

const handleDrop = (event) => {
  isDragOver.value = false
  addFiles(Array.from(event.dataTransfer?.files || []))
}

const addFiles = (newFiles) => {
  const allowed = ['.pdf', '.md', '.txt']
  const valid = newFiles.filter((file) => allowed.some((ext) => file.name.toLowerCase().endsWith(ext)))
  files.value = [...files.value, ...valid]
}

const removeFile = (index) => {
  files.value.splice(index, 1)
}

const scrollToLab = () => {
  labSection.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

const fileExtension = (filename) => {
  return filename.split('.').pop()?.slice(0, 4).toUpperCase() || 'FILE'
}

const startSimulation = () => {
  if (!canSubmit.value || loading.value) return
  import('../store/pendingUpload.js').then(({ setPendingUpload }) => {
    setPendingUpload(files.value, formData.value.simulationRequirement)
    router.push({ name: 'Process', params: { projectId: 'new' } })
  })
}
</script>

<style scoped>
.home-page {
  min-height: 100vh;
  color: var(--mf-ink);
  background:
    linear-gradient(rgba(67, 205, 255, 0.05) 1px, transparent 1px),
    linear-gradient(90deg, rgba(67, 205, 255, 0.05) 1px, transparent 1px),
    radial-gradient(circle at 16% 12%, rgba(56, 225, 255, 0.16), transparent 34%),
    radial-gradient(circle at 82% 0%, rgba(137, 92, 255, 0.18), transparent 28%),
    var(--mf-bg);
  background-size: 44px 44px, 44px 44px, auto, auto, auto;
}

.site-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  height: 72px;
  padding: 0 clamp(18px, 4vw, 48px);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  border-bottom: 1px solid rgba(132, 184, 209, 0.2);
  background: rgba(5, 9, 18, 0.78);
  backdrop-filter: blur(18px);
}

.brand-button {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: grid;
  place-items: center;
  overflow: hidden;
  border: 1px solid rgba(56, 225, 255, 0.34);
  background: rgba(255, 255, 255, 0.04);
  box-shadow: 0 0 32px rgba(56, 225, 255, 0.14);
}

.brand-mark img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.brand-copy {
  display: grid;
  gap: 2px;
  text-align: left;
}

.brand-copy strong {
  font-weight: 800;
  letter-spacing: 0;
}

.brand-copy span,
.eyebrow,
.card-kicker,
.console-header,
.workflow-item span,
.file-ext {
  font-family: var(--mf-font-mono);
}

.brand-copy span {
  color: var(--mf-ink-faint);
  font-size: 0.78rem;
}

.nav-links {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-link,
.primary-action,
.secondary-action {
  min-height: 38px;
  border-radius: 999px;
  padding: 0 15px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px solid rgba(132, 184, 209, 0.26);
  background: rgba(255, 255, 255, 0.045);
  color: var(--mf-ink);
  text-decoration: none;
  cursor: pointer;
  transition: transform 160ms ease, border-color 160ms ease, background 160ms ease;
}

.nav-link:hover,
.secondary-action:hover,
.primary-action:hover:not(:disabled) {
  transform: translateY(-1px);
  border-color: rgba(56, 225, 255, 0.62);
}

.nav-link.accent,
.primary-action {
  border-color: rgba(56, 225, 255, 0.54);
  background: linear-gradient(135deg, rgba(56, 225, 255, 0.26), rgba(87, 121, 255, 0.18));
  box-shadow: 0 0 34px rgba(56, 225, 255, 0.12);
}

.home-shell {
  width: min(1220px, calc(100% - 36px));
  margin: 0 auto;
  padding: clamp(36px, 6vw, 78px) 0 80px;
}

.hero-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 410px);
  align-items: stretch;
  gap: clamp(22px, 4vw, 42px);
}

.hero-copy {
  min-height: 520px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.eyebrow {
  margin: 0 0 16px;
  color: var(--mf-accent);
  font-size: 0.78rem;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

h1,
h2 {
  margin: 0;
  letter-spacing: 0;
}

h1 {
  max-width: 820px;
  font-size: clamp(3rem, 8vw, 7.3rem);
  line-height: 0.9;
  font-weight: 800;
}

h2 {
  font-size: clamp(2rem, 4vw, 3.6rem);
  line-height: 1;
}

.hero-text {
  max-width: 720px;
  margin: 28px 0 0;
  color: var(--mf-ink-muted);
  font-size: 1.05rem;
  line-height: 1.75;
}

.hero-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 34px;
}

.primary-action {
  min-height: 48px;
  padding: 0 20px;
  font-weight: 800;
}

.primary-action.wide {
  width: 100%;
  justify-content: space-between;
  border-radius: 14px;
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.secondary-action {
  min-height: 48px;
  padding: 0 20px;
}

.signal-card,
.route-card,
.document-lab,
.lab-console {
  border: 1px solid var(--mf-border);
  background: linear-gradient(180deg, rgba(11, 26, 41, 0.82), rgba(6, 14, 24, 0.82));
  box-shadow: var(--mf-shadow);
}

.signal-card {
  min-height: 520px;
  border-radius: 28px;
  padding: 28px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  overflow: hidden;
  position: relative;
}

.signal-card::before {
  content: '';
  position: absolute;
  inset: -30% -20% auto auto;
  width: 320px;
  height: 320px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(56, 225, 255, 0.22), transparent 62%);
}

.signal-orbit {
  position: relative;
  min-height: 330px;
  display: grid;
  place-items: center;
}

.signal-orbit img {
  width: 104px;
  height: 104px;
  border-radius: 26px;
  object-fit: cover;
  position: relative;
  z-index: 2;
  box-shadow: 0 0 48px rgba(56, 225, 255, 0.22);
}

.orbit,
.node {
  position: absolute;
  border-radius: 50%;
}

.orbit {
  border: 1px solid rgba(108, 190, 231, 0.23);
}

.orbit.one {
  width: 220px;
  height: 220px;
}

.orbit.two {
  width: 300px;
  height: 300px;
  border-style: dashed;
}

.node {
  width: 12px;
  height: 12px;
  background: var(--mf-accent);
  box-shadow: 0 0 22px currentColor;
}

.node.a {
  top: 54px;
  right: 64px;
  color: #38e1ff;
}

.node.b {
  left: 46px;
  bottom: 82px;
  color: #a78bfa;
  background: #a78bfa;
}

.node.c {
  right: 92px;
  bottom: 48px;
  color: #66f2a7;
  background: #66f2a7;
}

.signal-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--mf-ink-muted);
  font-family: var(--mf-font-mono);
  font-size: 0.82rem;
}

.live-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--mf-green);
  box-shadow: 0 0 18px rgba(102, 242, 167, 0.8);
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 18px;
}

.stat-grid div {
  border: 1px solid rgba(132, 184, 209, 0.18);
  border-radius: 14px;
  padding: 13px;
  background: rgba(255, 255, 255, 0.04);
}

.stat-grid strong,
.stat-grid span {
  display: block;
}

.stat-grid strong {
  font-family: var(--mf-font-mono);
}

.stat-grid span {
  margin-top: 4px;
  color: var(--mf-ink-faint);
  font-size: 0.78rem;
}

.route-grid {
  margin-top: 22px;
  display: grid;
  grid-template-columns: 1.1fr 1fr 1fr;
  gap: 14px;
}

.route-card {
  min-height: 190px;
  border-radius: 22px;
  padding: 22px;
  text-align: left;
  color: var(--mf-ink);
  cursor: pointer;
}

.route-card:hover {
  border-color: var(--mf-border-strong);
  transform: translateY(-2px);
}

.route-card strong,
.route-card span {
  display: block;
}

.card-kicker {
  color: var(--mf-accent);
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.route-card strong {
  margin-top: 22px;
  font-size: 1.4rem;
}

.route-card > span:last-child {
  margin-top: 12px;
  color: var(--mf-ink-muted);
  line-height: 1.55;
}

.main-route {
  background:
    radial-gradient(circle at 88% 12%, rgba(56, 225, 255, 0.22), transparent 30%),
    linear-gradient(180deg, rgba(15, 38, 58, 0.96), rgba(7, 19, 32, 0.92));
}

.document-lab {
  margin-top: 24px;
  border-radius: 28px;
  padding: clamp(18px, 3vw, 28px);
  display: grid;
  grid-template-columns: minmax(0, 0.78fr) minmax(320px, 1.22fr);
  gap: 24px;
}

.lab-intro {
  padding: 12px 6px;
}

.lab-intro p:not(.eyebrow) {
  color: var(--mf-ink-muted);
  line-height: 1.7;
  margin-top: 18px;
}

.workflow-list {
  margin-top: 26px;
  display: grid;
  gap: 12px;
}

.workflow-item {
  display: grid;
  grid-template-columns: 38px 1fr;
  gap: 12px;
  align-items: start;
  padding: 12px;
  border: 1px solid rgba(132, 184, 209, 0.18);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.035);
}

.workflow-item > span {
  color: var(--mf-accent);
  font-size: 0.76rem;
}

.workflow-item strong,
.workflow-item small {
  display: block;
}

.workflow-item small {
  margin-top: 4px;
  color: var(--mf-ink-faint);
  line-height: 1.4;
}

.lab-console {
  border-radius: 22px;
  padding: 20px;
}

.console-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--mf-ink-faint);
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  margin-bottom: 14px;
}

.upload-zone {
  min-height: 190px;
  border: 1px dashed rgba(132, 184, 209, 0.34);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.035);
  display: grid;
  place-items: center;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

.upload-zone.active,
.upload-zone:hover {
  border-color: var(--mf-accent);
  background: rgba(56, 225, 255, 0.08);
}

.upload-zone.filled {
  place-items: stretch;
}

.upload-zone input {
  display: none;
}

.upload-placeholder {
  display: grid;
  gap: 6px;
  text-align: center;
}

.upload-placeholder strong {
  font-size: 1.1rem;
}

.upload-placeholder span {
  color: var(--mf-ink-faint);
}

.file-list {
  width: 100%;
  max-height: 220px;
  overflow: auto;
  display: grid;
  gap: 10px;
  padding: 14px;
}

.file-item {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px;
  border: 1px solid rgba(132, 184, 209, 0.2);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.045);
}

.file-ext {
  color: var(--mf-accent);
  font-size: 0.68rem;
}

.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.remove-file {
  width: 28px;
  height: 28px;
  border: 1px solid rgba(132, 184, 209, 0.25);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.04);
  cursor: pointer;
}

.prompt-field {
  display: grid;
  gap: 10px;
  margin: 18px 0;
  color: var(--mf-ink-muted);
}

textarea {
  width: 100%;
  border: 1px solid rgba(132, 184, 209, 0.24);
  border-radius: 16px;
  background: rgba(3, 10, 18, 0.62);
  color: var(--mf-ink);
  padding: 16px;
  resize: vertical;
  outline: none;
}

textarea:focus {
  border-color: var(--mf-accent);
  box-shadow: 0 0 0 3px rgba(56, 225, 255, 0.12);
}

.error-text {
  margin-top: 12px;
  color: var(--mf-red);
}

.history-wrap {
  margin-top: 30px;
  border: 1px solid var(--mf-border);
  border-radius: 28px;
  background: rgba(5, 13, 23, 0.72);
  overflow: hidden;
}

.history-wrap :deep(.history-database) {
  margin-top: 0;
  padding: 28px 0 38px;
}

.history-wrap :deep(.grid-pattern) {
  background-image:
    linear-gradient(to right, rgba(56, 225, 255, 0.07) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(56, 225, 255, 0.07) 1px, transparent 1px);
}

.history-wrap :deep(.gradient-overlay) {
  background:
    linear-gradient(to right, rgba(5, 13, 23, 0.96) 0%, transparent 18%, transparent 82%, rgba(5, 13, 23, 0.96) 100%),
    linear-gradient(to bottom, rgba(5, 13, 23, 0.9) 0%, transparent 22%, transparent 78%, rgba(5, 13, 23, 0.9) 100%);
}

.history-wrap :deep(.section-title) {
  color: var(--mf-ink-muted);
}

.history-wrap :deep(.section-line) {
  background: linear-gradient(90deg, transparent, rgba(56, 225, 255, 0.32), transparent);
}

.history-wrap :deep(.project-card),
.history-wrap :deep(.modal-content),
.history-wrap :deep(.modal-header),
.history-wrap :deep(.modal-actions),
.history-wrap :deep(.modal-playback-hint) {
  background: #0b1726;
  color: var(--mf-ink);
  border-color: rgba(132, 184, 209, 0.2);
}

.history-wrap :deep(.project-card:hover) {
  border-color: rgba(56, 225, 255, 0.55);
  box-shadow: 0 18px 42px rgba(0, 0, 0, 0.28);
}

.history-wrap :deep(.card-title),
.history-wrap :deep(.modal-id),
.history-wrap :deep(.modal-label),
.history-wrap :deep(.btn-text) {
  color: var(--mf-ink);
}

.history-wrap :deep(.card-id),
.history-wrap :deep(.card-desc),
.history-wrap :deep(.card-footer),
.history-wrap :deep(.file-name),
.history-wrap :deep(.modal-create-time),
.history-wrap :deep(.modal-file-name),
.history-wrap :deep(.modal-requirement),
.history-wrap :deep(.hint-text) {
  color: var(--mf-ink-muted);
}

.history-wrap :deep(.card-files-wrapper),
.history-wrap :deep(.file-item),
.history-wrap :deep(.modal-requirement),
.history-wrap :deep(.modal-empty),
.history-wrap :deep(.modal-file-item),
.history-wrap :deep(.modal-btn) {
  background: rgba(255, 255, 255, 0.045);
  border-color: rgba(132, 184, 209, 0.18);
}

.history-wrap :deep(.card-bottom-line) {
  background-color: var(--mf-accent);
}

@media (max-width: 980px) {
  .hero-grid,
  .document-lab,
  .route-grid {
    grid-template-columns: 1fr;
  }

  .hero-copy,
  .signal-card {
    min-height: auto;
  }

  .signal-card {
    min-height: 420px;
  }
}

@media (max-width: 640px) {
  .site-nav {
    height: auto;
    padding: 12px 14px;
    align-items: flex-start;
    flex-direction: column;
  }

  .nav-links {
    width: 100%;
    overflow-x: auto;
    padding-bottom: 2px;
  }

  .nav-link {
    white-space: nowrap;
  }

  .home-shell {
    width: min(100% - 24px, 1220px);
    padding-top: 28px;
  }

  h1 {
    font-size: clamp(2.7rem, 17vw, 4rem);
  }

  .hero-actions,
  .stat-grid {
    grid-template-columns: 1fr;
  }

  .hero-actions {
    display: grid;
  }

  .signal-orbit {
    min-height: 260px;
  }

  .orbit.one {
    width: 180px;
    height: 180px;
  }

  .orbit.two {
    width: 240px;
    height: 240px;
  }

  .document-lab,
  .signal-card,
  .route-card,
  .lab-console {
    border-radius: 18px;
  }
}
</style>
