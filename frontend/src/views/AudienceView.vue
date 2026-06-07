<template>
  <div class="audience-page">
    <nav class="audience-nav">
      <div class="nav-actions">
        <button class="ghost-button" @click="router.push('/')">← Home</button>
        <button class="ghost-button" @click="router.push('/audience/graph')">Graph</button>
      </div>
      <span>Private Audience Graph</span>
    </nav>

    <main class="audience-shell">
      <section class="audience-hero">
        <div>
          <p class="eyebrow">Piotr Durlej / Content and Product Thinking</p>
          <h1>Test a topic against a 20-person synthetic audience.</h1>
          <p class="hero-copy">
            A private, Tailnet-first audience graph for podcast, LinkedIn, blog,
            Twitter/X and product ideas. It uses local graph memory with cloud
            models, then records token usage and reliability so the system can
            earn its keep instead of becoming a shiny cost trap.
          </p>
        </div>
        <div class="status-panel">
          <div class="status-number">{{ personaCount }}</div>
          <div class="status-label">active personas</div>
          <div class="status-note">{{ runMode === 'live' ? 'live model run' : 'fake contract run' }}</div>
        </div>
      </section>

      <section class="audience-grid">
        <form class="run-panel" @submit.prevent="submitRun">
          <div class="mode-toggle">
            <button type="button" :class="{ active: runMode === 'live' }" @click="runMode = 'live'">
              Live
            </button>
            <button type="button" :class="{ active: runMode === 'fake' }" @click="runMode = 'fake'">
              Test
            </button>
          </div>

          <label>
            Title
            <input v-model="form.title" type="text" placeholder="AI harnesses for PMs" />
          </label>

          <label>
            Channel
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
            Topic or rough note
            <textarea
              v-model="form.topic"
              rows="10"
              placeholder="Paste a podcast idea, LinkedIn angle, blog thesis, or product question..."
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
            <h2>Waiting for a topic</h2>
            <p>
              The report will show channel fit, objections, model attribution,
              similarity to previous topics, token usage, reliability and the
              recommended next action.
            </p>
          </div>

          <div v-else>
            <div class="decision-card">
              <span class="decision-pill">{{ recommendation.decision || 'unknown' }}</span>
              <h2>{{ recommendation.next_action || 'No next action recorded.' }}</h2>
              <p>{{ recommendation.rationale || 'No rationale recorded.' }}</p>
            </div>

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
                <span>similar topics</span>
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
              <div>
                <span>Cluster</span>
                <strong>{{ result.topic?.cluster_label || result.topic?.title || 'Unclustered' }}</strong>
              </div>
              <div v-if="similarityEdges.length">
                <span>Similar topics</span>
                <ul class="similar-topic-list">
                  <li v-for="edge in similarityEdges" :key="edge.target_topic_id">
                    <strong>{{ edge.target_title || edge.target_topic_id }}</strong>
                    <span>{{ scoreLabel(edge.score) }} · {{ edge.method || 'lexical' }}</span>
                  </li>
                </ul>
              </div>
            </div>

            <h3>Strongest objections</h3>
            <ul class="objection-list">
              <li v-for="item in topObjections" :key="item.id">
                <span>{{ item.severity }}</span>
                {{ item.text }}
              </li>
            </ul>

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
          </div>
        </section>
      </section>

      <section class="history-panel">
        <div class="section-title">
          <h2>Previous topics</h2>
          <button class="small-button" @click="loadHistory">Refresh</button>
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

const similarTopicsLabel = (item) => {
  return (item.similar_topics || [])
    .slice(0, 2)
    .map((topic) => `${topic.title} (${scoreLabel(topic.score)} ${topic.method || 'lexical'})`)
    .join(', ')
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
  background: #f6f5f1;
  color: #171717;
  font-family: 'Space Grotesk', system-ui, sans-serif;
}

.audience-nav {
  height: 60px;
  padding: 0 40px;
  background: #111;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-family: 'JetBrains Mono', monospace;
}

.nav-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.audience-shell {
  max-width: 1220px;
  margin: 0 auto;
  padding: 48px 32px 72px;
}

.audience-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 32px;
  align-items: end;
  margin-bottom: 32px;
}

.eyebrow {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #a43a12;
  margin-bottom: 14px;
}

h1 {
  font-size: clamp(2.2rem, 5vw, 4.8rem);
  line-height: 1.02;
  max-width: 920px;
  margin: 0;
}

.hero-copy {
  max-width: 760px;
  color: #555;
  font-size: 1rem;
  line-height: 1.7;
  margin-top: 20px;
}

.status-panel,
.run-panel,
.result-panel,
.history-panel {
  border: 1px solid #d9d4c8;
  background: #fffdf8;
}

.status-panel,
.run-panel,
.result-panel,
.history-panel {
  padding: 24px;
}

.status-number {
  font-size: 4rem;
  font-weight: 700;
}

.status-label,
.status-note {
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}

.audience-grid {
  display: grid;
  grid-template-columns: 460px minmax(0, 1fr);
  gap: 28px;
}

.mode-toggle {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 8px;
  margin-bottom: 18px;
}

.mode-toggle button,
.small-button {
  border: 1px solid #cbc4b5;
  background: #fff;
  padding: 10px 12px;
  cursor: pointer;
  font: inherit;
}

.mode-toggle button.active {
  background: #111;
  color: #fff;
}

label {
  display: block;
  font-weight: 700;
  margin-bottom: 18px;
}

input,
select,
textarea {
  width: 100%;
  display: block;
  margin-top: 8px;
  border: 1px solid #cbc4b5;
  background: #fff;
  padding: 12px;
  font: inherit;
}

textarea {
  resize: vertical;
}

button {
  font: inherit;
}

.primary-button,
.ghost-button {
  cursor: pointer;
}

.primary-button {
  width: 100%;
  border: 0;
  background: #111;
  color: #fff;
  padding: 16px 18px;
  font-weight: 800;
  display: flex;
  justify-content: space-between;
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.ghost-button {
  border: 1px solid #444;
  color: #fff;
  background: transparent;
  padding: 8px 12px;
}

.status-text {
  color: #555;
  margin-top: 14px;
}

.error-text {
  color: #b42318;
  margin-top: 14px;
}

.empty-result {
  min-height: 360px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  color: #555;
}

.decision-card {
  border-left: 4px solid #ff4500;
  padding-left: 18px;
  margin-bottom: 24px;
}

.decision-pill {
  display: inline-block;
  background: #111;
  color: #fff;
  padding: 4px 8px;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
}

.metric-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}

.metric-row div {
  border: 1px solid #e2ddd2;
  padding: 14px;
}

.metric-row strong,
.metric-row span {
  display: block;
}

.metric-row strong {
  font-size: 1.45rem;
}

.metric-row span {
  color: #666;
}

.objection-list {
  padding-left: 18px;
  line-height: 1.6;
}

.objection-list span {
  font-family: 'JetBrains Mono', monospace;
  color: #a43a12;
  margin-right: 8px;
}

.graph-context {
  border: 1px solid #e2ddd2;
  padding: 14px;
  margin-bottom: 24px;
}

.graph-context > div + div {
  margin-top: 14px;
}

.graph-context span {
  display: block;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
}

.graph-context strong {
  display: block;
  margin-top: 4px;
}

.similar-topic-list {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: grid;
  gap: 8px;
}

.similar-topic-list li {
  border-top: 1px solid #eee8dc;
  padding-top: 8px;
}

.persona-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.persona-list div {
  border: 1px solid #e2ddd2;
  padding: 12px;
}

.persona-list strong,
.persona-list span,
.persona-list small {
  display: block;
}

.persona-list span,
.persona-list small {
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
}

.persona-list small {
  margin-top: 6px;
  line-height: 1.35;
}

.history-panel {
  margin-top: 28px;
}

.section-title {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.history-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.history-item {
  text-align: left;
  border: 1px solid #e2ddd2;
  background: #fff;
  padding: 14px;
  cursor: pointer;
}

.history-item strong,
.history-item span {
  display: block;
}

.history-item span {
  color: #666;
  margin-top: 6px;
}

.history-empty {
  color: #666;
}

@media (max-width: 880px) {
  .audience-hero,
  .audience-grid,
  .history-list {
    grid-template-columns: 1fr;
  }

  .metric-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
