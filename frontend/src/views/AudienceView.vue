<template>
  <div class="audience-page">
    <nav class="site-nav">
      <button class="brand-button" type="button" @click="router.push('/audience')">
        <span class="brand-mark"><img :src="brandMark" alt="MiroFish" /></span>
        <span class="brand-copy">
          <strong>MiroFish</strong>
          <span>Audience Lab</span>
        </span>
      </button>

      <div class="nav-links">
        <button class="nav-link" type="button" @click="router.push('/')">Home</button>
        <button class="nav-link accent" type="button" @click="router.push('/audience/graph')">Graph</button>
      </div>
    </nav>

    <main class="audience-shell">
      <section class="audience-hero">
        <div class="hero-copy">
          <p class="eyebrow">Synthetic reviewer run</p>
          <h1>Pressure-test a topic against the same audience every time.</h1>
          <p>
            Use live personas for content, product, startup, and positioning
            questions. The run records objections, channel fit, similarity,
            reliability, cost, and the next useful move.
          </p>
        </div>

        <aside class="status-panel">
          <div class="status-ring">
            <strong>{{ personaCount }}</strong>
            <span>personas</span>
          </div>
          <div class="status-copy">
            <span class="live-dot"></span>
            <span>{{ runMode === 'live' ? 'live model path' : 'contract test path' }}</span>
          </div>
        </aside>
      </section>

      <section class="audience-grid">
        <form class="run-panel" @submit.prevent="submitRun">
          <div class="panel-head">
            <div>
              <p class="eyebrow">Run setup</p>
              <h2>New topic</h2>
            </div>
            <div class="mode-toggle" role="group" aria-label="Run mode">
              <button type="button" :class="{ active: runMode === 'live' }" @click="runMode = 'live'">
                Live
              </button>
              <button type="button" :class="{ active: runMode === 'fake' }" @click="runMode = 'fake'">
                Test
              </button>
            </div>
          </div>

          <label>
            <span>Title</span>
            <input v-model="form.title" type="text" placeholder="AI workflows for PM teams" />
          </label>

          <label>
            <span>Channel</span>
            <select v-model="form.channel">
              <option value="unknown">Unknown</option>
              <option value="podcast">Podcast</option>
              <option value="linkedin">LinkedIn</option>
              <option value="blog">Blog</option>
              <option value="twitter-x">Twitter/X</option>
              <option value="product-idea">Product idea</option>
            </select>
          </label>

          <label>
            <span>Topic or rough note</span>
            <textarea
              v-model="form.topic"
              rows="10"
              placeholder="Paste a thesis, angle, question, or rough post draft..."
            />
          </label>

          <button class="primary-button" type="submit" :disabled="!canSubmit || loading">
            <span>{{ buttonLabel }}</span>
            <span>→</span>
          </button>

          <p v-if="runStatus" class="status-text">{{ runStatus }}</p>
          <p v-if="error" class="error-text">{{ error }}</p>
        </form>

        <section class="result-panel">
          <div v-if="!result" class="empty-result">
            <div class="empty-orbit">
              <span></span>
              <i></i>
            </div>
            <h2>Run output lands here.</h2>
            <p>
              You will see decision, objections, similarity edges, token usage,
              reliability, model attribution, and reviewer memory in one place.
            </p>
          </div>

          <div v-else class="result-stack">
            <div class="decision-card">
              <span class="decision-pill" :class="`decision-${recommendation.decision || 'unknown'}`">
                {{ recommendation.decision || 'unknown' }}
              </span>
              <h2>{{ recommendation.next_action || 'No next action recorded.' }}</h2>
              <p>{{ recommendation.rationale || 'No rationale recorded.' }}</p>
            </div>

            <section v-if="channelScores.length" class="channel-fit-card">
              <div class="channel-fit-head">
                <div>
                  <h3>Channel fit</h3>
                  <p>Where this idea is most likely to work next.</p>
                </div>
                <span v-if="topChannel" class="channel-badge">
                  Recommended: {{ topChannel.label }}
                </span>
              </div>

              <div class="channel-score-list">
                <div
                  v-for="score in channelScores"
                  :key="score.channel"
                  class="channel-score-row"
                  :class="{ primary: score.channel === topChannel?.channel }"
                >
                  <div class="channel-score-top">
                    <strong>{{ score.label || score.channel }}</strong>
                    <span>{{ score.score }}%</span>
                  </div>
                  <div class="channel-meter" aria-hidden="true">
                    <i :style="{ width: scoreWidth(score.score) }"></i>
                  </div>
                  <div class="channel-score-meta">
                    <small>{{ score.suggested_format }}</small>
                    <small>{{ confidenceLabel(score.confidence) }} confidence</small>
                  </div>
                </div>
              </div>
            </section>

            <div class="metric-row">
              <div>
                <strong>{{ reactions.length }}</strong>
                <span>reactions</span>
              </div>
              <div>
                <strong>{{ objections.length }}</strong>
                <span>objections</span>
              </div>
              <div>
                <strong>{{ similarityEdges.length }}</strong>
                <span>similar</span>
              </div>
              <div>
                <strong>{{ receipt.usage?.total_tokens || 0 }}</strong>
                <span>tokens</span>
              </div>
              <div>
                <strong>{{ reliabilityLabel }}</strong>
                <span>reliability</span>
              </div>
              <div>
                <strong>{{ receipt.pricing || 'unknown' }}</strong>
                <span>pricing</span>
              </div>
            </div>

            <div class="graph-context">
              <div class="context-card">
                <span>Cluster</span>
                <strong>{{ result.topic?.cluster_label || result.topic?.title || 'Unclustered' }}</strong>
              </div>
              <div v-if="similarityEdges.length" class="context-card">
                <span>Top similar topics</span>
                <ul class="similar-topic-list">
                  <li v-for="edge in similarityEdges" :key="edge.target_topic_id">
                    <strong>{{ edge.target_title || edge.target_topic_id }}</strong>
                    <small>{{ scoreLabel(edge.score) }} · {{ edge.method || 'lexical' }}</small>
                    <small v-if="edge.explanation" class="similar-explanation">
                      {{ edge.explanation }}
                    </small>
                  </li>
                </ul>
              </div>
            </div>

            <section class="result-section">
              <h3>Strongest objections</h3>
              <ul class="objection-list">
                <li v-for="item in topObjections" :key="item.id">
                  <span>{{ item.severity }}</span>
                  {{ item.text }}
                </li>
              </ul>
            </section>

            <section class="result-section">
              <h3>Model attribution</h3>
              <div class="persona-list">
                <div v-for="persona in personas.slice(0, 10)" :key="persona.id">
                  <strong>{{ persona.name }}</strong>
                  <span>{{ persona.model_assignment?.model || 'unknown' }}</span>
                  <small v-if="memoryForPersona(persona.id).related_topic_count">
                    seen in {{ memoryForPersona(persona.id).related_topic_count }} related topics
                  </small>
                  <small v-if="memoryForPersona(persona.id).last_related_objection">
                    {{ trimText(memoryForPersona(persona.id).last_related_objection, 120) }}
                  </small>
                </div>
              </div>
            </section>
          </div>
        </section>
      </section>

      <section class="history-panel">
        <div class="section-title">
          <div>
            <p class="eyebrow">Run history</p>
            <h2>Previous topics</h2>
          </div>
          <button class="small-button" type="button" @click="loadHistory">Refresh</button>
        </div>
        <div v-if="history.length === 0" class="history-empty">
          No previous audience runs yet.
        </div>
        <div v-else class="history-list">
          <button
            v-for="item in history"
            :key="item.run_id"
            class="history-item"
            type="button"
            @click="loadRun(item.run_id)"
          >
            <strong>{{ item.title || item.run_id }}</strong>
            <span>{{ item.channel }} · {{ item.decision || 'pending' }} · {{ item.total_tokens || 0 }} tokens</span>
            <span v-if="historyChannelLabel(item)">Best: {{ historyChannelLabel(item) }}</span>
            <span>{{ item.reliability_grade || 'unknown' }} · {{ item.similarity_count || 0 }} similar</span>
            <span v-if="item.cluster_label">Cluster: {{ item.cluster_label }}</span>
            <span v-if="similarTopicsLabel(item)">Similar: {{ similarTopicsLabel(item) }}</span>
          </button>
        </div>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  createFakeAudienceRun,
  createLiveAudienceRun,
  getAudienceRun,
  listAudiencePersonas,
  listAudienceRuns
} from '../api/audience'
import brandMark from './audienceGraph/brand-mark.png'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const error = ref('')
const result = ref(null)
const personaCount = ref(20)
const runMode = ref('live')
const runStatus = ref('')
const history = ref([])

const form = reactive({
  title: '',
  channel: 'unknown',
  topic: ''
})

const canSubmit = computed(() => form.topic.trim().length >= 12)
const recommendation = computed(() => result.value?.recommendation || {})
const reactions = computed(() => result.value?.reactions || [])
const objections = computed(() => result.value?.objections || [])
const personas = computed(() => result.value?.personas || [])
const topObjections = computed(() => objections.value.slice(0, 6))
const receipt = computed(() => result.value?.receipt || {})
const reliabilityLabel = computed(() => receipt.value.reliability_grade || 'unknown')
const similarityEdges = computed(() => result.value?.similarity_edges || [])
const channelScores = computed(() => {
  const scores = recommendation.value?.channel_scores || []
  return scores
    .map((item) => ({
      ...item,
      score: Math.max(0, Math.min(100, Number(item.score) || 0)),
      confidence: Math.max(0, Math.min(1, Number(item.confidence) || 0))
    }))
    .sort((a, b) => b.score - a.score)
})
const topChannel = computed(() => channelScores.value[0] || null)
const personaMemoryById = computed(() => {
  const pairs = (result.value?.persona_memory || []).map((item) => [item.persona_id, item])
  return new Map(pairs)
})
const buttonLabel = computed(() => {
  if (loading.value) return runMode.value === 'live' ? 'Running live audience...' : 'Running test...'
  return runMode.value === 'live' ? 'Run live audience' : 'Run test contract'
})

onMounted(async () => {
  await Promise.all([loadPersonas(), loadHistory()])
  if (route.query.run) {
    await loadRun(String(route.query.run))
  }
})

const loadPersonas = async () => {
  try {
    const response = await listAudiencePersonas()
    personaCount.value = response.count || response.data?.length || 20
  } catch (_err) {
    personaCount.value = 20
  }
}

const loadHistory = async () => {
  try {
    const response = await listAudienceRuns(25)
    history.value = response.data || []
  } catch (_err) {
    history.value = []
  }
}

const submitRun = async () => {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  error.value = ''
  runStatus.value = ''
  try {
    const payload = {
      title: form.title,
      channel: form.channel,
      topic: form.topic,
      run_seed: `ui-${Date.now()}`
    }
    if (runMode.value === 'fake') {
      const response = await createFakeAudienceRun(payload)
      result.value = response.data
      runStatus.value = 'Test run completed.'
    } else {
      const response = await createLiveAudienceRun(payload)
      await pollRun(response.data.run_id)
    }
    await loadHistory()
  } catch (err) {
    error.value = err?.message || 'Audience run failed'
  } finally {
    loading.value = false
  }
}

const pollRun = async (runId) => {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    const response = await getAudienceRun(runId)
    const record = response.data
    runStatus.value = `Status: ${record.status}`
    if (record.status === 'completed') {
      result.value = record.data
      runStatus.value = 'Live run completed.'
      return
    }
    if (record.status === 'failed') {
      throw new Error(`Live run failed: ${record.error_kind || 'unknown'}`)
    }
    await new Promise((resolve) => setTimeout(resolve, 1500))
  }
  throw new Error('Live run timed out')
}

const loadRun = async (runId) => {
  loading.value = true
  error.value = ''
  try {
    const response = await getAudienceRun(runId)
    const record = response.data
    result.value = record.data || record
    runStatus.value = `Loaded ${runId}`
  } catch (err) {
    error.value = err?.message || 'Could not load run'
  } finally {
    loading.value = false
  }
}

const memoryForPersona = (personaId) => personaMemoryById.value.get(personaId) || {}

const scoreLabel = (score) => {
  const numeric = Number(score)
  if (!Number.isFinite(numeric)) return 'n/a'
  return numeric.toFixed(2)
}

const scoreWidth = (score) => {
  const numeric = Math.max(0, Math.min(100, Number(score) || 0))
  return `${numeric}%`
}

const confidenceLabel = (confidence) => {
  const numeric = Number(confidence)
  if (!Number.isFinite(numeric)) return 'unknown'
  return `${Math.round(Math.max(0, Math.min(1, numeric)) * 100)}%`
}

const similarTopicsLabel = (item) => {
  return (item.similar_topics || [])
    .slice(0, 2)
    .map((topic) => `${topic.title} (${scoreLabel(topic.score)} ${topic.method || 'lexical'})`)
    .join(', ')
}

const historyChannelLabel = (item) => {
  const scores = [...(item.channel_scores || [])].sort((a, b) => Number(b.score || 0) - Number(a.score || 0))
  const top = scores[0]
  if (top) return `${top.label || top.channel} ${Number(top.score || 0)}%`
  return item.best_channel || ''
}

const trimText = (text, limit) => {
  const cleaned = String(text || '').replace(/\s+/g, ' ').trim()
  if (cleaned.length <= limit) return cleaned
  return `${cleaned.slice(0, limit - 1).trim()}...`
}
</script>

<style scoped>
.audience-page {
  min-height: 100vh;
  color: var(--mf-ink);
  background:
    linear-gradient(rgba(67, 205, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(67, 205, 255, 0.045) 1px, transparent 1px),
    radial-gradient(circle at 18% 0%, rgba(56, 225, 255, 0.15), transparent 32%),
    radial-gradient(circle at 92% 24%, rgba(167, 139, 250, 0.16), transparent 30%),
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
.nav-link,
.mode-toggle,
.status-copy,
.decision-pill,
.metric-row span,
.graph-context span,
.similar-topic-list small,
.objection-list span,
.persona-list span,
.persona-list small {
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
.small-button {
  min-height: 38px;
  border-radius: 999px;
  padding: 0 15px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(132, 184, 209, 0.26);
  background: rgba(255, 255, 255, 0.045);
  color: var(--mf-ink);
  cursor: pointer;
}

.nav-link.accent,
.small-button:hover {
  border-color: rgba(56, 225, 255, 0.54);
  background: var(--mf-accent-soft);
}

.audience-shell {
  width: min(1220px, calc(100% - 36px));
  margin: 0 auto;
  padding: clamp(32px, 5vw, 62px) 0 80px;
}

.audience-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(260px, 330px);
  gap: 24px;
  align-items: end;
  margin-bottom: 24px;
}

.hero-copy h1 {
  max-width: 920px;
  margin: 0;
  font-size: clamp(2.6rem, 6vw, 5.6rem);
  line-height: 0.94;
  letter-spacing: 0;
}

.hero-copy p:not(.eyebrow) {
  max-width: 760px;
  margin: 22px 0 0;
  color: var(--mf-ink-muted);
  font-size: 1rem;
  line-height: 1.7;
}

.eyebrow {
  margin: 0 0 14px;
  color: var(--mf-accent);
  font-size: 0.76rem;
  letter-spacing: 0.15em;
  text-transform: uppercase;
}

.status-panel,
.run-panel,
.result-panel,
.history-panel {
  border: 1px solid var(--mf-border);
  background: linear-gradient(180deg, rgba(10, 24, 38, 0.86), rgba(5, 13, 24, 0.86));
  box-shadow: var(--mf-shadow);
}

.status-panel {
  min-height: 220px;
  border-radius: 24px;
  padding: 22px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.status-ring {
  width: 132px;
  height: 132px;
  border-radius: 50%;
  display: grid;
  place-content: center;
  text-align: center;
  border: 1px solid rgba(56, 225, 255, 0.38);
  background:
    radial-gradient(circle, rgba(56, 225, 255, 0.16), transparent 62%),
    rgba(255, 255, 255, 0.035);
}

.status-ring strong,
.status-ring span {
  display: block;
}

.status-ring strong {
  font-size: 3.2rem;
  line-height: 1;
}

.status-ring span {
  color: var(--mf-ink-faint);
  margin-top: 6px;
}

.status-copy {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--mf-ink-muted);
  font-size: 0.82rem;
}

.live-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--mf-green);
  box-shadow: 0 0 18px rgba(102, 242, 167, 0.8);
}

.audience-grid {
  display: grid;
  grid-template-columns: minmax(340px, 460px) minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}

.run-panel,
.result-panel,
.history-panel {
  border-radius: 24px;
  padding: 22px;
}

.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: start;
  gap: 16px;
  margin-bottom: 20px;
}

h2,
h3 {
  margin: 0;
  letter-spacing: 0;
}

h2 {
  font-size: clamp(1.5rem, 3vw, 2.25rem);
  line-height: 1;
}

h3 {
  font-size: 1rem;
  margin-bottom: 12px;
}

.mode-toggle {
  display: grid;
  grid-template-columns: repeat(2, minmax(70px, 1fr));
  gap: 6px;
  padding: 4px;
  border: 1px solid rgba(132, 184, 209, 0.24);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.04);
}

.mode-toggle button {
  min-height: 34px;
  padding: 0 12px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--mf-ink-muted);
  cursor: pointer;
}

.mode-toggle button.active {
  color: #03111a;
  background: var(--mf-accent);
}

label {
  display: grid;
  gap: 8px;
  color: var(--mf-ink-muted);
  margin-bottom: 16px;
}

input,
select,
textarea {
  width: 100%;
  border: 1px solid rgba(132, 184, 209, 0.24);
  border-radius: 14px;
  background: rgba(3, 10, 18, 0.62);
  color: var(--mf-ink);
  padding: 13px 14px;
  outline: none;
}

textarea {
  resize: vertical;
  line-height: 1.55;
}

input:focus,
select:focus,
textarea:focus {
  border-color: var(--mf-accent);
  box-shadow: 0 0 0 3px rgba(56, 225, 255, 0.12);
}

.primary-button {
  width: 100%;
  min-height: 52px;
  border: 1px solid rgba(56, 225, 255, 0.54);
  border-radius: 16px;
  background: linear-gradient(135deg, rgba(56, 225, 255, 0.28), rgba(87, 121, 255, 0.2));
  color: var(--mf-ink);
  padding: 0 18px;
  font-weight: 800;
  display: flex;
  justify-content: space-between;
  align-items: center;
  cursor: pointer;
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.48;
}

.status-text {
  color: var(--mf-ink-muted);
  margin-top: 14px;
}

.error-text {
  color: var(--mf-red);
  margin-top: 14px;
}

.result-panel {
  min-height: 640px;
}

.empty-result {
  min-height: 560px;
  display: grid;
  place-content: center;
  text-align: center;
  color: var(--mf-ink-muted);
}

.empty-result h2 {
  color: var(--mf-ink);
  margin-top: 24px;
}

.empty-result p {
  max-width: 520px;
  margin: 14px auto 0;
  line-height: 1.65;
}

.empty-orbit {
  width: 168px;
  height: 168px;
  margin: 0 auto;
  border-radius: 50%;
  position: relative;
  border: 1px dashed rgba(56, 225, 255, 0.32);
}

.empty-orbit span,
.empty-orbit i {
  position: absolute;
  border-radius: 50%;
}

.empty-orbit span {
  inset: 42px;
  border: 1px solid rgba(56, 225, 255, 0.26);
}

.empty-orbit i {
  width: 13px;
  height: 13px;
  top: 24px;
  right: 34px;
  background: var(--mf-accent);
  box-shadow: 0 0 24px rgba(56, 225, 255, 0.8);
}

.result-stack {
  display: grid;
  gap: 20px;
}

.decision-card {
  border: 1px solid rgba(132, 184, 209, 0.22);
  border-radius: 20px;
  padding: 20px;
  background:
    radial-gradient(circle at 92% 12%, rgba(56, 225, 255, 0.14), transparent 34%),
    rgba(255, 255, 255, 0.04);
}

.decision-card h2 {
  margin-top: 14px;
  line-height: 1.08;
}

.decision-card p {
  margin: 12px 0 0;
  color: var(--mf-ink-muted);
  line-height: 1.6;
}

.decision-pill {
  display: inline-flex;
  border-radius: 999px;
  padding: 6px 10px;
  background: rgba(56, 225, 255, 0.16);
  color: var(--mf-accent);
  text-transform: uppercase;
  font-size: 0.72rem;
}

.decision-abandon,
.decision-drop {
  background: rgba(255, 122, 144, 0.16);
  color: var(--mf-red);
}

.decision-rewrite,
.decision-narrow,
.decision-save_for_later {
  background: rgba(255, 209, 102, 0.16);
  color: var(--mf-yellow);
}

.decision-publish,
.decision-podcast,
.decision-post {
  background: rgba(102, 242, 167, 0.16);
  color: var(--mf-green);
}

.channel-fit-card {
  border: 1px solid rgba(132, 184, 209, 0.2);
  border-radius: 20px;
  padding: 18px;
  background:
    radial-gradient(circle at 8% 0%, rgba(102, 242, 167, 0.1), transparent 32%),
    rgba(255, 255, 255, 0.035);
}

.channel-fit-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.channel-fit-head p {
  margin: 6px 0 0;
  color: var(--mf-ink-faint);
}

.channel-badge {
  flex-shrink: 0;
  border: 1px solid rgba(56, 225, 255, 0.36);
  border-radius: 999px;
  padding: 7px 10px;
  background: rgba(56, 225, 255, 0.1);
  color: var(--mf-accent);
  font-family: var(--mf-font-mono);
  font-size: 0.74rem;
}

.channel-score-list {
  display: grid;
  gap: 10px;
}

.channel-score-row {
  display: grid;
  gap: 8px;
  padding: 12px;
  border: 1px solid rgba(132, 184, 209, 0.16);
  border-radius: 16px;
  background: rgba(3, 10, 18, 0.32);
}

.channel-score-row.primary {
  border-color: rgba(56, 225, 255, 0.5);
  background: rgba(56, 225, 255, 0.07);
}

.channel-score-top,
.channel-score-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.channel-score-top span {
  color: var(--mf-accent);
  font-family: var(--mf-font-mono);
}

.channel-meter {
  height: 8px;
  border-radius: 999px;
  overflow: hidden;
  background: rgba(132, 184, 209, 0.16);
}

.channel-meter i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--mf-accent), var(--mf-green));
  box-shadow: 0 0 18px rgba(56, 225, 255, 0.28);
}

.channel-score-meta small {
  color: var(--mf-ink-faint);
  line-height: 1.35;
}

.channel-score-meta small:last-child {
  flex-shrink: 0;
  color: var(--mf-ink-muted);
  font-family: var(--mf-font-mono);
  font-size: 0.72rem;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.metric-row div,
.context-card,
.persona-list div {
  border: 1px solid rgba(132, 184, 209, 0.18);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.035);
}

.metric-row div {
  padding: 14px;
}

.metric-row strong,
.metric-row span {
  display: block;
}

.metric-row strong {
  font-size: 1.35rem;
}

.metric-row span,
.graph-context span {
  color: var(--mf-ink-faint);
  font-size: 0.76rem;
  margin-top: 4px;
}

.graph-context {
  display: grid;
  grid-template-columns: 1fr;
  gap: 10px;
}

.context-card {
  padding: 14px;
}

.context-card strong {
  display: block;
  margin-top: 6px;
}

.similar-topic-list {
  list-style: none;
  padding: 0;
  margin: 10px 0 0;
  display: grid;
  gap: 8px;
}

.similar-topic-list li {
  border-top: 1px solid rgba(132, 184, 209, 0.14);
  padding-top: 8px;
}

.similar-topic-list small {
  display: block;
  margin-top: 4px;
  color: var(--mf-accent);
}

.similar-topic-list .similar-explanation {
  color: var(--mf-ink-faint);
  line-height: 1.35;
}

.result-section {
  display: grid;
  gap: 8px;
}

.objection-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 10px;
}

.objection-list li {
  border-left: 2px solid rgba(56, 225, 255, 0.42);
  padding: 2px 0 2px 12px;
  color: var(--mf-ink-muted);
  line-height: 1.55;
}

.objection-list span {
  color: var(--mf-accent);
  margin-right: 8px;
  font-size: 0.76rem;
}

.persona-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.persona-list div {
  padding: 12px;
}

.persona-list strong,
.persona-list span,
.persona-list small {
  display: block;
}

.persona-list span,
.persona-list small {
  color: var(--mf-ink-faint);
  font-size: 0.76rem;
}

.persona-list small {
  margin-top: 6px;
  line-height: 1.35;
}

.history-panel {
  margin-top: 22px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
  margin-bottom: 18px;
}

.history-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.history-item {
  text-align: left;
  border: 1px solid rgba(132, 184, 209, 0.18);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.035);
  color: var(--mf-ink);
  padding: 14px;
  cursor: pointer;
}

.history-item:hover {
  border-color: rgba(56, 225, 255, 0.48);
}

.history-item strong,
.history-item span {
  display: block;
}

.history-item strong {
  overflow-wrap: anywhere;
}

.history-item span {
  color: var(--mf-ink-faint);
  margin-top: 6px;
  line-height: 1.35;
}

.history-empty {
  color: var(--mf-ink-muted);
}

@media (max-width: 960px) {
  .audience-hero,
  .audience-grid,
  .history-list {
    grid-template-columns: 1fr;
  }

  .status-panel {
    min-height: auto;
    flex-direction: row;
    align-items: center;
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
  }

  .nav-link {
    flex: 1;
  }

  .audience-shell {
    width: min(100% - 24px, 1220px);
    padding-top: 28px;
  }

  .hero-copy h1 {
    font-size: clamp(2.35rem, 14vw, 3.7rem);
  }

  .panel-head,
  .status-panel,
  .channel-fit-head,
  .channel-score-meta,
  .section-title {
    flex-direction: column;
    align-items: stretch;
  }

  .mode-toggle,
  .metric-row,
  .persona-list {
    grid-template-columns: 1fr;
  }

  .run-panel,
  .result-panel,
  .history-panel,
  .status-panel {
    border-radius: 18px;
    padding: 18px;
  }
}
</style>
