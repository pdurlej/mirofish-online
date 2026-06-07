<template>
  <div class="graph-page">
    <nav class="graph-nav">
      <div class="nav-actions">
        <button type="button" class="ghost-button" @click="router.push('/audience')">Audience</button>
        <button type="button" class="ghost-button" @click="router.push('/')">Home</button>
      </div>
      <div class="nav-title">Global Audience Graph</div>
      <div class="nav-stats">
        <span>{{ graphStats.topic_count || 0 }} topics</span>
        <span>{{ graphStats.similarity_edge_count || 0 }} similarity edges</span>
      </div>
    </nav>

    <main class="graph-shell">
      <section class="toolbar">
        <label>
          Search
          <input v-model="searchQuery" type="search" placeholder="Topic title" />
        </label>
        <label>
          Min score
          <input
            v-model.number="minScore"
            type="number"
            min="0"
            max="1"
            step="0.05"
            @change="loadGraph"
          />
        </label>
        <label>
          Last N
          <input
            v-model.number="limit"
            type="number"
            min="1"
            max="300"
            step="10"
            @change="loadGraph"
          />
        </label>
        <label>
          Channel
          <select v-model="channelFilter">
            <option value="all">All</option>
            <option v-for="channel in channelOptions" :key="channel" :value="channel">
              {{ channel }}
            </option>
          </select>
        </label>
        <label>
          Cluster
          <select v-model="clusterFilter">
            <option value="all">All</option>
            <option v-for="cluster in clusterOptions" :key="cluster.id" :value="cluster.id">
              {{ cluster.label }}
            </option>
          </select>
        </label>
        <div class="toolbar-actions">
          <button type="button" class="small-button" @click="resetZoom">Reset zoom</button>
          <button type="button" class="primary-button" :disabled="loading" @click="loadGraph">
            {{ loading ? 'Loading' : 'Refresh' }}
          </button>
        </div>
      </section>

      <section class="graph-workbench">
        <div ref="graphContainer" class="graph-canvas">
          <svg ref="graphSvg" class="graph-svg" />
          <div v-if="loading" class="graph-state">Loading graph</div>
          <div v-else-if="error" class="graph-state error-state">{{ error }}</div>
          <div v-else-if="visibleGraph.nodes.length === 0" class="graph-state">No graph data</div>
        </div>

        <aside class="detail-panel">
          <template v-if="selectedNode">
            <div class="detail-kicker">{{ selectedNode.type }}</div>
            <h1>{{ selectedNode.title || selectedNode.label }}</h1>

            <div v-if="selectedNode.type === 'topic'" class="detail-grid">
              <div>
                <span>Channel</span>
                <strong>{{ selectedNode.channel || 'unknown' }}</strong>
              </div>
              <div>
                <span>Decision</span>
                <strong>{{ selectedNode.decision || 'unknown' }}</strong>
              </div>
              <div>
                <span>Reliability</span>
                <strong>{{ selectedNode.reliability_grade || 'unknown' }}</strong>
              </div>
              <div>
                <span>Tokens</span>
                <strong>{{ selectedNode.total_tokens || 0 }}</strong>
              </div>
            </div>

            <div class="detail-section">
              <span>Cluster</span>
              <strong>{{ selectedNode.cluster_label || selectedNode.label }}</strong>
            </div>

            <div v-if="selectedNode.next_action" class="detail-section">
              <span>Next action</span>
              <p>{{ selectedNode.next_action }}</p>
            </div>

            <div v-if="selectedSimilarTopics.length" class="detail-section">
              <span>Top similar</span>
              <ul>
                <li v-for="topic in selectedSimilarTopics" :key="`${topic.title}-${topic.score}`">
                  <strong>{{ topic.title }}</strong>
                  <small>{{ scoreLabel(topic.score) }} · {{ topic.method || 'lexical' }}</small>
                </li>
              </ul>
            </div>

            <button
              v-if="selectedNode.run_id"
              type="button"
              class="primary-button detail-button"
              @click="router.push({ name: 'Audience', query: { run: selectedNode.run_id } })"
            >
              Open run
            </button>
          </template>

          <template v-else>
            <div class="detail-kicker">Selection</div>
            <h1>Pick a node</h1>
            <div class="legend">
              <div><span class="legend-line hybrid" /> hybrid</div>
              <div><span class="legend-line semantic" /> semantic</div>
              <div><span class="legend-line lexical" /> lexical</div>
              <div><span class="legend-dot cluster" /> cluster</div>
              <div><span class="legend-dot topic" /> topic</div>
            </div>
          </template>
        </aside>
      </section>
    </main>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as d3 from 'd3'
import { getAudienceGraph } from '../api/audience'

const router = useRouter()
const graphContainer = ref(null)
const graphSvg = ref(null)
const graphData = ref({ nodes: [], edges: [], stats: {}, filters: {} })
const selectedNode = ref(null)
const loading = ref(false)
const error = ref('')
const searchQuery = ref('')
const channelFilter = ref('all')
const clusterFilter = ref('all')
const minScore = ref(0.35)
const limit = ref(120)
const zoomBehavior = ref(null)
let simulation = null

const graphStats = computed(() => graphData.value.stats || {})
const channelOptions = computed(() => graphData.value.filters?.channels || [])
const clusterOptions = computed(() => graphData.value.filters?.clusters || [])
const selectedSimilarTopics = computed(() => (selectedNode.value?.similar_topics || []).slice(0, 5))

const visibleGraph = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const topicNodes = (graphData.value.nodes || []).filter((node) => node.type === 'topic')
  const selectedTopics = topicNodes.filter((node) => {
    const matchesQuery = !query || String(node.title || '').toLowerCase().includes(query)
    const matchesChannel = channelFilter.value === 'all' || node.channel === channelFilter.value
    const matchesCluster = clusterFilter.value === 'all' || node.cluster_id === clusterFilter.value
    return matchesQuery && matchesChannel && matchesCluster
  })
  const topicIds = new Set(selectedTopics.map((node) => node.id))
  const clusterIds = new Set(selectedTopics.map((node) => clusterGraphId(node.cluster_id)))
  const nodes = (graphData.value.nodes || []).filter((node) => {
    if (node.type === 'topic') return topicIds.has(node.id)
    if (node.type === 'cluster') return clusterIds.has(node.id)
    return false
  })
  const nodeIds = new Set(nodes.map((node) => node.id))
  const edges = (graphData.value.edges || []).filter(
    (edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)
  )
  return { nodes, edges }
})

onMounted(async () => {
  await loadGraph()
  window.addEventListener('resize', renderGraph)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', renderGraph)
  if (simulation) simulation.stop()
})

watch(visibleGraph, () => {
  nextTick(renderGraph)
})

const loadGraph = async () => {
  loading.value = true
  error.value = ''
  try {
    const response = await getAudienceGraph({
      limit: clampNumber(limit.value, 1, 300),
      minScore: clampNumber(minScore.value, 0, 1)
    })
    graphData.value = response.data || { nodes: [], edges: [], stats: {}, filters: {} }
    selectedNode.value = null
    await nextTick()
    renderGraph()
  } catch (err) {
    error.value = err?.message || 'Could not load graph'
  } finally {
    loading.value = false
  }
}

const renderGraph = () => {
  if (!graphSvg.value || !graphContainer.value) return
  const rect = graphContainer.value.getBoundingClientRect()
  const width = Math.max(rect.width, 320)
  const height = Math.max(rect.height, 420)
  const nodes = visibleGraph.value.nodes.map((node) => ({ ...node }))
  const edges = visibleGraph.value.edges.map((edge) => ({ ...edge }))
  const svg = d3.select(graphSvg.value)
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)

  svg.selectAll('*').remove()
  if (simulation) simulation.stop()
  if (!nodes.length) return

  const color = clusterColorScale(nodes)
  const g = svg.append('g')
  zoomBehavior.value = d3.zoom()
    .scaleExtent([0.2, 5])
    .on('zoom', (event) => {
      g.attr('transform', event.transform)
    })
  svg.call(zoomBehavior.value)

  simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id((node) => node.id).distance((edge) => edge.type === 'IN_CLUSTER' ? 72 : 130).strength((edge) => edge.type === 'IN_CLUSTER' ? 0.2 : 0.45))
    .force('charge', d3.forceManyBody().strength((node) => node.type === 'cluster' ? -460 : -220))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collision', d3.forceCollide().radius((node) => node.type === 'cluster' ? 46 : 28))
    .force('x', d3.forceX(width / 2).strength(0.035))
    .force('y', d3.forceY(height / 2).strength(0.035))

  const links = g.append('g')
    .attr('class', 'graph-links')
    .selectAll('line')
    .data(edges)
    .enter()
    .append('line')
    .attr('stroke', (edge) => edgeColor(edge, color))
    .attr('stroke-opacity', (edge) => edge.type === 'IN_CLUSTER' ? 0.22 : 0.72)
    .attr('stroke-width', (edge) => edge.type === 'IN_CLUSTER' ? 1 : 1.5 + Number(edge.score || 0) * 4)
    .attr('stroke-dasharray', edgeDash)

  const nodeGroups = g.append('g')
    .attr('class', 'graph-nodes')
    .selectAll('g')
    .data(nodes)
    .enter()
    .append('g')
    .attr('class', 'graph-node')
    .on('click', (event, node) => {
      event.stopPropagation()
      selectedNode.value = node
    })
    .call(d3.drag()
      .on('start', dragStarted)
      .on('drag', dragged)
      .on('end', dragEnded))

  nodeGroups.append('circle')
    .attr('r', nodeRadius)
    .attr('fill', (node) => node.type === 'cluster' ? color(node.cluster_id) : '#fffdf8')
    .attr('stroke', (node) => color(node.cluster_id))
    .attr('stroke-width', (node) => node.type === 'cluster' ? 0 : 3)

  nodeGroups.append('text')
    .attr('x', (node) => node.type === 'cluster' ? 0 : 16)
    .attr('y', (node) => node.type === 'cluster' ? 4 : 4)
    .attr('text-anchor', (node) => node.type === 'cluster' ? 'middle' : 'start')
    .text((node) => trimLabel(node.label || node.title, node.type === 'cluster' ? 16 : 22))

  nodeGroups.append('title')
    .text((node) => node.title || node.label)

  svg.on('click', () => {
    selectedNode.value = null
  })

  simulation.on('tick', () => {
    links
      .attr('x1', (edge) => edge.source.x)
      .attr('y1', (edge) => edge.source.y)
      .attr('x2', (edge) => edge.target.x)
      .attr('y2', (edge) => edge.target.y)

    nodeGroups.attr('transform', (node) => `translate(${node.x},${node.y})`)
  })

  function dragStarted(event) {
    if (!event.active) simulation.alphaTarget(0.3).restart()
    event.subject.fx = event.subject.x
    event.subject.fy = event.subject.y
  }

  function dragged(event) {
    event.subject.fx = event.x
    event.subject.fy = event.y
  }

  function dragEnded(event) {
    if (!event.active) simulation.alphaTarget(0)
    event.subject.fx = null
    event.subject.fy = null
  }
}

const resetZoom = () => {
  if (!graphSvg.value || !zoomBehavior.value) return
  d3.select(graphSvg.value).transition().duration(220).call(zoomBehavior.value.transform, d3.zoomIdentity)
}

const clusterColorScale = (nodes) => {
  const clusterIds = [...new Set(nodes.map((node) => node.cluster_id).filter(Boolean))]
  return d3.scaleOrdinal()
    .domain(clusterIds)
    .range(['#0f766e', '#b45309', '#4338ca', '#be123c', '#166534', '#7c3aed', '#0369a1', '#a16207'])
}

const edgeColor = (edge, color) => {
  if (edge.type === 'IN_CLUSTER') return '#9a9284'
  const target = (graphData.value.nodes || []).find((node) => node.id === edge.target)
  return target?.cluster_id ? color(target.cluster_id) : '#333'
}

const edgeDash = (edge) => {
  if (edge.type === 'IN_CLUSTER') return '2 8'
  if (edge.method === 'semantic') return '8 5'
  if (edge.method === 'lexical') return '3 5'
  return ''
}

const nodeRadius = (node) => {
  if (node.type === 'cluster') return Math.min(34, 18 + Number(node.topic_count || 1) * 2)
  return node.reliability_grade === 'yellow' ? 10 : 8
}

const clusterGraphId = (clusterId) => `cluster:${clusterId}`

const clampNumber = (value, min, max) => {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return min
  return Math.min(Math.max(numeric, min), max)
}

const scoreLabel = (score) => {
  const numeric = Number(score)
  if (!Number.isFinite(numeric)) return 'n/a'
  return numeric.toFixed(2)
}

const trimLabel = (value, limit) => {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= limit) return text
  return `${text.slice(0, limit - 1).trim()}...`
}
</script>

<style scoped>
.graph-page {
  min-height: 100vh;
  background: #f6f5f1;
  color: #171717;
  font-family: 'Space Grotesk', system-ui, sans-serif;
}

.graph-nav {
  min-height: 60px;
  padding: 0 32px;
  background: #111;
  color: #fff;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  gap: 18px;
  align-items: center;
  font-family: 'JetBrains Mono', monospace;
}

.nav-actions,
.nav-stats {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-stats {
  justify-content: flex-end;
  color: #cfcfcf;
  font-size: 0.78rem;
}

.nav-title {
  font-weight: 800;
}

.graph-shell {
  height: calc(100vh - 60px);
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
}

.toolbar {
  display: grid;
  grid-template-columns: minmax(180px, 1.2fr) 110px 100px minmax(140px, 0.8fr) minmax(180px, 1fr) auto;
  gap: 12px;
  align-items: end;
  padding: 16px 22px;
  border-bottom: 1px solid #d9d4c8;
  background: #fffdf8;
}

label {
  display: block;
  color: #555;
  font-size: 0.76rem;
  font-weight: 800;
  text-transform: uppercase;
}

input,
select {
  width: 100%;
  display: block;
  margin-top: 6px;
  border: 1px solid #cbc4b5;
  background: #fff;
  color: #171717;
  padding: 10px;
  font: inherit;
  text-transform: none;
}

button {
  font: inherit;
  cursor: pointer;
}

.ghost-button,
.small-button,
.primary-button {
  border: 1px solid #444;
  padding: 9px 12px;
}

.ghost-button {
  color: #fff;
  background: transparent;
}

.small-button {
  border-color: #cbc4b5;
  background: #fff;
  color: #171717;
}

.primary-button {
  border-color: #111;
  background: #111;
  color: #fff;
  font-weight: 800;
}

.primary-button:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.toolbar-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.graph-workbench {
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
}

.graph-canvas {
  position: relative;
  min-height: 0;
  overflow: hidden;
  background:
    linear-gradient(rgba(17, 17, 17, 0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(17, 17, 17, 0.04) 1px, transparent 1px),
    #f6f5f1;
  background-size: 24px 24px;
}

.graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.graph-state {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}

.error-state {
  color: #b42318;
}

.detail-panel {
  min-width: 0;
  overflow: auto;
  border-left: 1px solid #d9d4c8;
  background: #fffdf8;
  padding: 24px;
}

.detail-kicker {
  color: #a43a12;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem;
  font-weight: 800;
  text-transform: uppercase;
}

.detail-panel h1 {
  font-size: 1.55rem;
  line-height: 1.15;
  margin: 10px 0 22px;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.detail-grid div,
.detail-section {
  border: 1px solid #e2ddd2;
  padding: 12px;
}

.detail-section {
  margin-top: 12px;
}

.detail-grid span,
.detail-section span {
  display: block;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.72rem;
  margin-bottom: 5px;
}

.detail-grid strong,
.detail-section strong {
  display: block;
  overflow-wrap: anywhere;
}

.detail-section p {
  margin: 0;
  line-height: 1.45;
}

.detail-section ul {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  gap: 10px;
}

.detail-section li {
  border-top: 1px solid #eee8dc;
  padding-top: 8px;
}

.detail-section small {
  display: block;
  margin-top: 4px;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}

.detail-button {
  width: 100%;
  margin-top: 16px;
}

.legend {
  display: grid;
  gap: 12px;
  color: #555;
}

.legend-line,
.legend-dot {
  display: inline-block;
  margin-right: 8px;
  vertical-align: middle;
}

.legend-line {
  width: 34px;
  border-top: 3px solid #0f766e;
}

.legend-line.semantic {
  border-top-style: dashed;
}

.legend-line.lexical {
  border-top-style: dotted;
}

.legend-dot {
  width: 13px;
  height: 13px;
  border-radius: 50%;
  border: 2px solid #0f766e;
}

.legend-dot.cluster {
  background: #0f766e;
}

.legend-dot.topic {
  background: #fffdf8;
}

:deep(.graph-node) {
  cursor: pointer;
}

:deep(.graph-node text) {
  fill: #171717;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  paint-order: stroke;
  stroke: #fffdf8;
  stroke-width: 3px;
  stroke-linejoin: round;
}

@media (max-width: 960px) {
  .graph-nav,
  .toolbar,
  .graph-workbench {
    grid-template-columns: 1fr;
  }

  .nav-stats {
    justify-content: flex-start;
  }

  .graph-shell {
    height: auto;
  }

  .graph-canvas {
    height: 70vh;
  }

  .detail-panel {
    border-left: 0;
    border-top: 1px solid #d9d4c8;
  }
}
</style>
