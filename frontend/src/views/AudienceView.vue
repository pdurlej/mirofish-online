<template>
  <div class="audience-page">
    <nav class="audience-nav">
      <button class="ghost-button" @click="router.push('/')">← Home</button>
      <span>Private Audience Graph</span>
    </nav>

    <main class="audience-shell">
      <section class="audience-hero">
        <div>
          <p class="eyebrow">Piotr Durlej / Content and Product Thinking</p>
          <h1>Test a topic against the first 20-person synthetic audience.</h1>
          <p class="hero-copy">
            This is the safe contract flow: no live OASIS, no public exposure,
            no raw prompt storage. It proves the graph-shaped product loop before
            we spend real model budget.
          </p>
        </div>
        <div class="status-panel">
          <div class="status-number">{{ personaCount }}</div>
          <div class="status-label">active personas</div>
          <div class="status-note">fake run / graph contract</div>
        </div>
      </section>

      <section class="audience-grid">
        <form class="run-panel" @submit.prevent="submitRun">
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
            <span>{{ loading ? 'Running audience...' : 'Run audience graph smoke' }}</span>
            <span>→</span>
          </button>

          <p v-if="error" class="error-text">{{ error }}</p>
        </form>

        <section class="result-panel">
          <div v-if="!result" class="empty-result">
            <h2>Waiting for a topic</h2>
            <p>
              The first report will show channel fit, objections, model attribution,
              similarity edges, and the recommended next action.
            </p>
          </div>

          <div v-else>
            <div class="decision-card">
              <span class="decision-pill">{{ result.recommendation.decision }}</span>
              <h2>{{ result.recommendation.next_action }}</h2>
              <p>{{ result.recommendation.rationale }}</p>
            </div>

            <div class="metric-row">
              <div>
                <strong>{{ result.reactions.length }}</strong>
                <span>reactions</span>
              </div>
              <div>
                <strong>{{ result.objections.length }}</strong>
                <span>objections</span>
              </div>
              <div>
                <strong>{{ result.similarity_edges.length }}</strong>
                <span>similar topics</span>
              </div>
            </div>

            <h3>Strongest objections</h3>
            <ul class="objection-list">
              <li v-for="item in topObjections" :key="item.id">
                <span>{{ item.severity }}</span>
                {{ item.text }}
              </li>
            </ul>

            <h3>Persona/model attribution</h3>
            <div class="persona-list">
              <div v-for="persona in result.personas.slice(0, 8)" :key="persona.id">
                <strong>{{ persona.name }}</strong>
                <span>{{ persona.model_assignment.model }}</span>
              </div>
            </div>
          </div>
        </section>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createFakeAudienceRun, listAudiencePersonas } from '../api/audience'

const router = useRouter()
const loading = ref(false)
const error = ref('')
const result = ref(null)
const personaCount = ref(20)

const form = reactive({
  title: '',
  channel: 'unknown',
  topic: ''
})

const canSubmit = computed(() => form.topic.trim().length >= 12)
const topObjections = computed(() => result.value?.objections.slice(0, 6) || [])

onMounted(async () => {
  try {
    const response = await listAudiencePersonas()
    personaCount.value = response.count || response.data?.length || 20
  } catch (_err) {
    personaCount.value = 20
  }
})

const submitRun = async () => {
  if (!canSubmit.value || loading.value) return
  loading.value = true
  error.value = ''
  try {
    const response = await createFakeAudienceRun({
      title: form.title,
      channel: form.channel,
      topic: form.topic,
      run_seed: 'ui'
    })
    result.value = response.data
  } catch (err) {
    error.value = err?.message || 'Audience run failed'
  } finally {
    loading.value = false
  }
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
  max-width: 720px;
  color: #555;
  font-size: 1rem;
  line-height: 1.7;
  margin-top: 20px;
}

.status-panel,
.run-panel,
.result-panel {
  border: 1px solid #d9d4c8;
  background: #fffdf8;
}

.status-panel {
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

.run-panel,
.result-panel {
  padding: 24px;
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
  font-size: 1.8rem;
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
.persona-list span {
  display: block;
}

.persona-list span {
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.78rem;
}

@media (max-width: 880px) {
  .audience-hero,
  .audience-grid {
    grid-template-columns: 1fr;
  }
}
</style>
