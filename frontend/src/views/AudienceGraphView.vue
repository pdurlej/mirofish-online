<template>
  <div class="graph-page" :data-theme="view.theme" :style="{ '--accent': view.accent }">
    <!-- ===================== TOP NAV ===================== -->
    <nav class="gnav">
      <div class="gnav-brand">
        <span class="brand-mark"><img :src="brandMark" alt="MiroFish" /></span>
        <span class="brand-text">
          <b>MiroFish</b>
          <span>Audience Graph</span>
        </span>
      </div>
      <div class="gnav-links">
        <button class="btn ghost sm" type="button" @click="router.push('/audience')">‹ <span class="label-hide">Audience</span></button>
        <button class="btn ghost sm" type="button" @click="router.push('/')"><span class="label-hide">Home</span></button>
      </div>
      <div class="gnav-spacer"></div>
      <div class="gnav-stats">
        <div class="gstat"><b>{{ stats.topic_count || 0 }}</b><span>Topics</span></div>
        <div class="gstat"><b>{{ stats.cluster_count || 0 }}</b><span>Clusters</span></div>
        <div class="gstat"><b>{{ stats.similarity_edge_count || 0 }}</b><span>Edges</span></div>
        <div class="gstat" style="align-items:flex-start;">
          <b style="display:flex;align-items:center;gap:7px;"><span class="live-dot"></span></b>
          <span>Live</span>
        </div>
      </div>
    </nav>

    <!-- ===================== TOOLBAR ===================== -->
    <section class="toolbar">
      <button class="btn sm" type="button" @click="railVisible = !railVisible" :title="railVisible ? 'Hide signals' : 'Show signals'">
        <span class="ic" v-html="ICON.menu"></span><span class="label-hide">Signals</span>
      </button>
      <div class="tb-search">
        <span class="ic" v-html="ICON.search"></span>
        <input type="search" v-model="searchQuery" placeholder="Search topics…" />
        <span class="count" v-if="searchQuery">{{ visibleTopics.length }} hit{{ visibleTopics.length === 1 ? '' : 's' }}</span>
      </div>
      <div class="field">
        <label>Min score</label>
        <input class="ctl" type="number" min="0" max="1" step="0.05" v-model.number="minScore" @change="loadGraph" />
      </div>
      <div class="field">
        <label>Last N</label>
        <input class="ctl" type="number" min="1" max="300" step="10" v-model.number="limit" @change="loadGraph" />
      </div>
      <div class="field" :class="{ 'is-active': channelFilter !== 'all' }">
        <label>Channel</label>
        <select class="ctl" v-model="channelFilter">
          <option value="all">All channels</option>
          <option v-for="c in channelOptions" :key="c" :value="c">{{ c }}</option>
        </select>
      </div>
      <div class="field" :class="{ 'is-active': clusterFilter !== 'all' }">
        <label>Cluster</label>
        <select class="ctl" v-model="clusterFilter">
          <option value="all">All clusters</option>
          <option v-for="c in clusterOptions" :key="c.id" :value="c.id">{{ c.label }}</option>
        </select>
      </div>
      <div class="tb-actions">
        <button v-if="activeFilters" class="tb-clear" type="button" @click="clearFilters">Clear ×</button>
        <div class="tb-divider"></div>
        <button class="btn sm" type="button" :class="{ 'is-on': viewOpen }" @click="viewOpen = !viewOpen" title="View options">
          <span class="ic" v-html="ICON.sliders"></span><span class="label-hide">View</span>
        </button>
        <button class="btn sm" type="button" @click="resetZoom" title="Reset zoom">
          <span class="ic" v-html="ICON.target"></span><span class="label-hide">Reset</span>
        </button>
        <button class="btn accent sm" type="button" :disabled="loading" @click="loadGraph">
          <span class="ic" v-html="ICON.refresh"></span>{{ loading ? 'Loading…' : 'Refresh' }}
        </button>
      </div>
    </section>

    <!-- ===================== WORKBENCH ===================== -->
    <section class="workbench" :class="{ 'rail-collapsed': !railVisible, 'rail-open': railVisible, 'panel-collapsed': !panelVisible }">
      <!-- LEFT RAIL — signals & clusters -->
      <aside class="rail">
        <div class="rail-head">
          <h2>Signal</h2>
          <button class="btn ghost sm" type="button" @click="railVisible = false" title="Hide"><span class="ic" v-html="ICON.chevronLeft"></span></button>
        </div>
        <div class="signal">
          <div class="signal-row">
            <div class="signal-tile"><b class="mono">{{ signal.topics }}</b><span>Topics in view</span></div>
            <div class="signal-tile"><b class="mono">{{ signal.clusters }}</b><span>Active clusters</span></div>
          </div>
          <div class="meter-label">Decision mix <em>{{ decPct.validate }}% publish</em></div>
          <div class="bar">
            <i class="seg-validate" :style="{ width: decPct.validate + '%' }"></i>
            <i class="seg-refine" :style="{ width: decPct.refine + '%' }"></i>
            <i class="seg-drop" :style="{ width: decPct.drop + '%' }"></i>
          </div>
          <div class="bar-key">
            <span><i class="seg-validate"></i>{{ signal.dec.validate }} publish</span>
            <span><i class="seg-refine"></i>{{ signal.dec.refine }} revise</span>
            <span><i class="seg-drop"></i>{{ signal.dec.drop }} drop</span>
          </div>
          <div class="meter-label">Reliability <em>{{ gradePct.green }}% green</em></div>
          <div class="bar">
            <i class="seg-validate" :style="{ width: gradePct.green + '%' }"></i>
            <i class="seg-refine" :style="{ width: gradePct.yellow + '%' }"></i>
            <i class="seg-drop" :style="{ width: gradePct.red + '%' }"></i>
          </div>
        </div>
        <div class="rail-head"><h2>Clusters · by size</h2></div>
        <div class="cluster-list">
          <button v-for="c in clusterSummaries" :key="c.id" type="button" class="cluster-row"
                  :class="{ 'is-active': clusterFilter === c.id }" @click="focusCluster(c)">
            <span class="cluster-swatch" :style="{ background: colorFor(c.id), color: colorFor(c.id) }"></span>
            <span class="cluster-meta">
              <b>{{ c.label }}</b>
              <span class="cluster-mini">
                <i class="seg-validate" :style="{ width: pct(c.validate, c.count) + '%' }"></i>
                <i class="seg-refine" :style="{ width: pct(c.refine, c.count) + '%' }"></i>
                <i class="seg-drop" :style="{ width: pct(c.drop, c.count) + '%' }"></i>
              </span>
            </span>
            <span class="cluster-count">{{ c.count }}</span>
          </button>
          <div v-if="!clusterSummaries.length" style="padding:18px 10px;color:var(--ink-faint);font-size:12px;">No clusters in view.</div>
        </div>
      </aside>

      <!-- GRAPH CANVAS (hero) -->
      <div ref="canvasWrap" class="canvas-wrap" :class="{ 'show-grid': view.showGrid }">
        <svg ref="svgEl" class="graph-svg"></svg>

        <div class="canvas-tools">
          <div class="zoom-pill">
            <button type="button" @click="ctrl && ctrl.zoomBy(0.8)" title="Zoom out"><span class="ic" v-html="ICON.minus"></span></button>
            <button type="button" @click="resetZoom" title="Reset"><span class="ic" v-html="ICON.target"></span></button>
            <button type="button" @click="ctrl && ctrl.zoomBy(1.25)" title="Zoom in"><span class="ic" v-html="ICON.plus"></span></button>
          </div>
          <button class="btn icon-btn" type="button" @click="panelVisible = !panelVisible" :title="panelVisible ? 'Hide panel' : 'Show panel'">
            <span class="ic" v-html="panelVisible ? ICON.panelRight : ICON.panelLeft"></span>
          </button>
        </div>

        <div v-if="tip.show && tip.node" class="tip" :style="{ left: tip.x + 'px', top: tip.y + 'px' }">
          <template v-if="tip.node.type === 'topic'">
            <div class="tip-cluster"><i :style="{ background: colorFor(tip.node.cluster_id) }"></i>{{ tip.node.cluster_label }}</div>
            <b>{{ tip.node.title }}</b>
            <div class="tip-foot">
              <span class="chip" :class="decisionClass(tip.node.decision)">{{ decisionLabel(tip.node.decision) }}</span>
              <span class="mono" style="font-size:11px;color:var(--ink-faint);">{{ tip.node.channel }}</span>
            </div>
          </template>
          <template v-else>
            <div class="tip-cluster"><i :style="{ background: colorFor(tip.node.cluster_id) }"></i>Cluster</div>
            <b>{{ tip.node.label }}</b>
            <div class="tip-foot"><span class="mono" style="font-size:11px;color:var(--ink-faint);">{{ tip.node.topic_count }} topics</span></div>
          </template>
        </div>

        <div class="legend" :class="{ collapsed: !legendOpen }">
          <div class="legend-head" @click="legendOpen = !legendOpen">
            <h4>Legend</h4>
            <span class="ic" style="color:var(--ink-faint);width:13px;" v-html="legendOpen ? ICON.chevronDown : ICON.chevronUp"></span>
          </div>
          <div class="legend-body">
            <div class="legend-row"><span class="lg-dot cluster"></span>Cluster anchor</div>
            <div class="legend-row"><span class="lg-dot topic"></span>Topic (test run)</div>
            <div class="legend-row"><span class="lg-line hybrid"></span>Hybrid match</div>
            <div class="legend-row"><span class="lg-line semantic"></span>Semantic match</div>
            <div class="legend-row"><span class="lg-line lexical"></span>Lexical match</div>
            <div class="legend-row"><span class="lg-line cluster"></span>Cluster membership</div>
          </div>
        </div>

        <div v-if="loading" class="cstate">
          <div class="cstate-inner">
            <div class="sonar"><i></i><i></i><i></i><b></b></div>
            <h3>Mapping the audience graph</h3>
            <p>Resolving topics, clusters and similarity edges…</p>
          </div>
        </div>
        <div v-else-if="error" class="cstate">
          <div class="cstate-inner">
            <div class="err-mark"><span class="ic" style="width:22px;" v-html="ICON.alert"></span></div>
            <h3>Graph unavailable</h3>
            <p>{{ error }}</p>
            <button class="btn accent" type="button" @click="loadGraph">Try again</button>
          </div>
        </div>
        <div v-else-if="!visibleGraph.nodes.length" class="cstate">
          <div class="cstate-inner">
            <div class="sonar" style="opacity:.4;"><b></b></div>
            <h3>No topics match</h3>
            <p>Nothing fits the current filters. Lower <b>Min score</b>, widen <b>Last N</b>, or clear filters.</p>
            <button v-if="activeFilters" class="btn" type="button" @click="clearFilters">Clear filters</button>
          </div>
        </div>
      </div>

      <!-- RIGHT DETAIL PANEL -->
      <aside class="panel">
        <div class="panel-inner">
          <!-- TOPIC -->
          <template v-if="selectedNode && selectedNode.type === 'topic'">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
              <div class="panel-kicker"><span class="cluster-swatch" :style="{ background: colorFor(selectedNode.cluster_id) }"></span>{{ selectedNode.cluster_label }}</div>
              <button class="btn ghost sm" type="button" @click="clearSelection" title="Close"><span class="ic" v-html="ICON.close"></span></button>
            </div>
            <h1>{{ selectedNode.title }}</h1>
            <div class="panel-sub">run {{ selectedNode.run_id }} · {{ fmtDate(selectedNode.created_at) }}</div>
            <div class="metric-grid">
              <div class="metric"><span>Channel</span><strong style="text-transform:capitalize;">{{ selectedNode.channel || 'unknown' }}</strong></div>
              <div class="metric"><span>Decision</span><strong><span class="chip" :class="decisionClass(selectedNode.decision)">{{ decisionLabel(selectedNode.decision) }}</span></strong></div>
              <div class="metric"><span>Reliability</span><strong><span class="grade-dot" :class="'grade-' + (selectedNode.reliability_grade || 'unknown')"></span>{{ selectedNode.reliability_grade || 'unknown' }}</strong></div>
              <div class="metric"><span>Tokens</span><strong class="mono">{{ fmtNum(selectedNode.total_tokens) }}</strong></div>
            </div>
            <div class="psection" v-if="selectedNode.next_action">
              <div class="sec-label">Recommended next action</div>
              <div class="next-action"><span class="ic" v-html="ICON.bolt"></span><p>{{ selectedNode.next_action }}</p></div>
            </div>
            <div class="psection" v-if="selectedSimilar.length">
              <div class="sec-label">Top similar topics <em style="font-style:normal;color:var(--ink-faint);">{{ selectedSimilar.length }}</em></div>
              <div class="simlist">
                <div v-for="(s, i) in selectedSimilar" :key="s.title + i" class="simrow" @click="selectByTitle(s.title)">
                  <span class="sim-rank">{{ String(i + 1).padStart(2, '0') }}</span>
                  <span class="sim-main">
                    <span class="sim-title">{{ s.title }}</span>
                    <span class="sim-track"><i :style="{ width: Math.round(s.score * 100) + '%' }"></i></span>
                  </span>
                  <span>
                    <span class="sim-score">{{ scoreLabel(s.score) }}</span>
                    <span class="sim-method" style="display:block;text-align:right;">{{ s.method || 'lexical' }}</span>
                  </span>
                </div>
              </div>
            </div>
            <button v-if="selectedNode.run_id" class="btn accent open-run" type="button" @click="openRun(selectedNode)">
              Open run <span class="ic" v-html="ICON.arrowRight"></span>
            </button>
          </template>

          <!-- CLUSTER -->
          <template v-else-if="selectedNode && selectedNode.type === 'cluster'">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;">
              <div class="panel-kicker"><span class="cluster-swatch" :style="{ background: colorFor(selectedNode.cluster_id) }"></span>Cluster</div>
              <button class="btn ghost sm" type="button" @click="clearSelection"><span class="ic" v-html="ICON.close"></span></button>
            </div>
            <h1>{{ selectedNode.label }}</h1>
            <div class="panel-sub">{{ clusterMembers(selectedNode.cluster_id).length }} topics tested</div>
            <div class="psection">
              <div class="sec-label">Decision mix</div>
              <div class="bar">
                <i class="seg-validate" :style="{ width: clusterDecPct(selectedNode.cluster_id).validate + '%' }"></i>
                <i class="seg-refine" :style="{ width: clusterDecPct(selectedNode.cluster_id).refine + '%' }"></i>
                <i class="seg-drop" :style="{ width: clusterDecPct(selectedNode.cluster_id).drop + '%' }"></i>
              </div>
              <div class="bar-key" style="margin-top:9px;">
                <span><i class="seg-validate"></i>publish</span>
                <span><i class="seg-refine"></i>revise</span>
                <span><i class="seg-drop"></i>drop</span>
              </div>
            </div>
            <div class="psection">
              <div class="sec-label">Member topics</div>
              <div class="member-list">
                <div v-for="m in clusterMembers(selectedNode.cluster_id)" :key="m.id" class="member" @click="select(m)">
                  <span class="grade-dot" :class="'grade-' + (m.reliability_grade || 'unknown')"></span>
                  <b>{{ m.title }}</b>
                  <span class="chip" :class="decisionClass(m.decision)" style="font-size:9.5px;">{{ decisionLabel(m.decision) }}</span>
                </div>
              </div>
            </div>
            <button class="btn open-run" type="button" @click="focusClusterById(selectedNode.cluster_id)">Isolate this cluster</button>
          </template>

          <!-- EMPTY — how to read -->
          <template v-else>
            <div class="panel-kicker">Reading this graph</div>
            <h1 style="font-size:18px;">A map of every audience test</h1>
            <div class="help-block">
              <p class="hint">Each glowing node is one topic you tested against the synthetic audience. Nodes pull toward their <b>cluster anchor</b> — the recurring themes in your thinking. Lines connect topics the model found similar.</p>
              <div class="help-steps">
                <div class="help-step"><i>1</i><span><b style="color:var(--ink);">Scan the rail</b> on the left to see which themes dominate and how decisions are trending.</span></div>
                <div class="help-step"><i>2</i><span><b style="color:var(--ink);">Hover</b> any node for a quick preview — no click needed.</span></div>
                <div class="help-step"><i>3</i><span><b style="color:var(--ink);">Click</b> a node to focus it, highlight its matches, and read the full run here.</span></div>
              </div>
            </div>
            <div class="psection">
              <div class="sec-label">What the lines mean</div>
              <div class="legend-body" style="display:grid;gap:9px;">
                <div class="legend-row"><span class="lg-line hybrid"></span>Hybrid — lexical + semantic agree</div>
                <div class="legend-row"><span class="lg-line semantic"></span>Semantic — meaning is close</div>
                <div class="legend-row"><span class="lg-line lexical"></span>Lexical — wording overlaps</div>
                <div class="legend-row"><span class="lg-line cluster"></span>Cluster membership</div>
              </div>
            </div>
          </template>
        </div>
      </aside>
    </section>

    <!-- ===================== VIEW OPTIONS ===================== -->
    <div class="tweaks" v-show="viewOpen" ref="viewEl">
      <div class="tweaks-head" @mousedown="startDrag">
        <b>View options</b>
        <button type="button" @click="viewOpen = false">×</button>
      </div>
      <div class="tweaks-body">
        <div class="tw-row">
          <label>Theme</label>
          <div class="tw-seg">
            <button v-for="m in ['dark','light']" :key="m" :class="{ on: view.theme === m }" @click="setView('theme', m)">{{ m }}</button>
          </div>
        </div>
        <div class="tw-row">
          <label>Accent</label>
          <div class="tw-swatches">
            <button v-for="a in ACCENTS" :key="a" :class="{ on: view.accent === a }" :style="{ background: a }" @click="setView('accent', a)"></button>
          </div>
        </div>
        <div class="tw-row">
          <label>Node labels</label>
          <div class="tw-seg">
            <button v-for="m in ['always','hover','off']" :key="m" :class="{ on: view.labelDensity === m }" @click="setView('labelDensity', m)">{{ m }}</button>
          </div>
        </div>
        <div class="tw-row">
          <label>Edge emphasis <em>{{ view.edgeEmphasis }}</em></label>
          <input type="range" min="10" max="100" step="1" :value="view.edgeEmphasis" @input="setView('edgeEmphasis', +$event.target.value)" />
        </div>
        <div class="tw-row">
          <label>Graph spacing <em>{{ spacingLabel }}</em></label>
          <input type="range" min="0" max="100" step="1" :value="view.forceSpacing" @input="setView('forceSpacing', +$event.target.value)" />
        </div>
        <div class="tw-row tw-toggle">
          <label style="margin:0;">Cluster halos</label>
          <div class="tw-switch" :class="{ on: view.clusterHull }" @click="setView('clusterHull', !view.clusterHull)"></div>
        </div>
        <div class="tw-row tw-toggle">
          <label style="margin:0;">Background grid</label>
          <div class="tw-switch" :class="{ on: view.showGrid }" @click="setView('showGrid', !view.showGrid)"></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getAudienceGraph } from '../api/audience'
import { createGraph } from './audienceGraph/graphEngine'
import brandMark from './audienceGraph/brand-mark.png'

const router = useRouter()

const ICON = {
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
  target: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="7"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-2.6-6.4M21 4v4h-4"/></svg>',
  menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 6h16M4 12h12M4 18h16"/></svg>',
  sliders: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="currentColor" stroke="none"><path d="M13 2L4.5 13.5H11l-1 8.5L19 10h-6.5L13 2z"/></svg>',
  arrowRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  chevronLeft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>',
  chevronDown: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>',
  chevronUp: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  minus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14"/></svg>',
  panelRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/></svg>',
  panelLeft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>',
}
const ACCENTS = ['#38e1ff', '#5ad1c9', '#7aa2ff', '#c084fc', '#e879c9']
const PALETTE = ['#2dd4bf', '#45b3ff', '#8b8cff', '#c084fc', '#22d3ee', '#6ee7b7', '#7aa2ff', '#e879c9']
const VIEW_DEFAULTS = { theme: 'dark', accent: '#38e1ff', edgeEmphasis: 60, labelDensity: 'hover', forceSpacing: 50, clusterHull: true, showGrid: true }

// ---- refs / state ----
const svgEl = ref(null)
const canvasWrap = ref(null)
const viewEl = ref(null)
const graphData = ref({ nodes: [], edges: [], stats: {}, filters: {} })
const selectedNode = ref(null)
const loading = ref(false)
const error = ref('')
const searchQuery = ref('')
const channelFilter = ref('all')
const clusterFilter = ref('all')
const minScore = ref(0.35)
const limit = ref(120)
const railVisible = ref(typeof window !== 'undefined' && window.innerWidth > 1180)
const panelVisible = ref(true)
const legendOpen = ref(false)
const viewOpen = ref(false)
const tip = reactive({ show: false, node: null, x: 0, y: 0 })

const stored = (() => { try { return JSON.parse(localStorage.getItem('mf_graph_view') || '{}') } catch (e) { return {} } })()
const view = reactive({ ...VIEW_DEFAULTS, ...stored })

let ctrl = null
let resizeObserver = null
let resizeRaf = null

// ---- computed ----
const stats = computed(() => graphData.value.stats || {})
const channelOptions = computed(() => graphData.value.filters?.channels || [])
const clusterOptions = computed(() => graphData.value.filters?.clusters || [])

const colorMap = computed(() => {
  const ids = [...new Set((graphData.value.nodes || []).filter((n) => n.cluster_id).map((n) => n.cluster_id))].sort()
  const m = {}
  ids.forEach((id, i) => { m[id] = PALETTE[i % PALETTE.length] })
  return m
})
const colorFor = (cid) => colorMap.value[cid] || '#7aa2ff'
const decisionBucket = (decision) => {
  const value = String(decision || '').toLowerCase()
  if (['publish', 'validate', 'ship', 'record'].includes(value)) return 'validate'
  if (['abandon', 'drop'].includes(value)) return 'drop'
  return 'refine'
}
const decisionClass = (decision) => decisionBucket(decision)
const decisionLabel = (decision) => String(decision || 'n/a').replace(/_/g, ' ')

const visibleGraph = computed(() => {
  const q = searchQuery.value.trim().toLowerCase()
  const topics = (graphData.value.nodes || []).filter((n) => n.type === 'topic')
  const sel = topics.filter((n) => {
    const mq = !q || String(n.title || '').toLowerCase().includes(q)
    const mc = channelFilter.value === 'all' || n.channel === channelFilter.value
    const mk = clusterFilter.value === 'all' || n.cluster_id === clusterFilter.value
    return mq && mc && mk
  })
  const tIds = new Set(sel.map((n) => n.id))
  const cIds = new Set(sel.map((n) => 'cluster:' + n.cluster_id))
  const nodes = (graphData.value.nodes || []).filter((n) =>
    n.type === 'topic' ? tIds.has(n.id) : n.type === 'cluster' ? cIds.has(n.id) : false)
  const nodeIds = new Set(nodes.map((n) => n.id))
  const edges = (graphData.value.edges || []).filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target))
  return { nodes, edges }
})
const visibleTopics = computed(() => visibleGraph.value.nodes.filter((n) => n.type === 'topic'))

const clusterSummaries = computed(() => {
  const by = {}
  visibleTopics.value.forEach((t) => {
    const c = (by[t.cluster_id] ||= { id: t.cluster_id, label: t.cluster_label, count: 0, validate: 0, refine: 0, drop: 0 })
    c.count += 1
    c[decisionBucket(t.decision)] += 1
  })
  return Object.values(by).sort((a, b) => b.count - a.count)
})

const signal = computed(() => {
  const dec = { validate: 0, refine: 0, drop: 0 }
  const grade = { green: 0, yellow: 0, red: 0, unknown: 0 }
  visibleTopics.value.forEach((t) => {
    dec[decisionBucket(t.decision)] += 1
    grade[t.reliability_grade] = (grade[t.reliability_grade] || 0) + 1
  })
  return { topics: visibleTopics.value.length, clusters: clusterSummaries.value.length, dec, grade }
})

const pct = (n, total) => (total ? Math.round((n / total) * 100) : 0)
const decPct = computed(() => {
  const t = signal.value.dec.validate + signal.value.dec.refine + signal.value.dec.drop
  return { validate: pct(signal.value.dec.validate, t), refine: pct(signal.value.dec.refine, t), drop: pct(signal.value.dec.drop, t) }
})
const gradePct = computed(() => {
  const g = signal.value.grade
  const t = g.green + g.yellow + g.red + g.unknown
  return { green: pct(g.green, t), yellow: pct(g.yellow, t), red: pct(g.red + g.unknown, t) }
})

const selectedSimilar = computed(() => (selectedNode.value?.similar_topics || []).slice(0, 6))
const activeFilters = computed(() => !!searchQuery.value || channelFilter.value !== 'all' || clusterFilter.value !== 'all')
const spacingLabel = computed(() => (view.forceSpacing < 34 ? 'tight' : view.forceSpacing > 66 ? 'loose' : 'balanced'))

const clusterMembers = (cid) => visibleTopics.value.filter((t) => t.cluster_id === cid)
const clusterDecPct = (cid) => {
  const m = clusterMembers(cid)
  const d = { validate: 0, refine: 0, drop: 0 }
  m.forEach((t) => { d[decisionBucket(t.decision)] += 1 })
  const t = m.length || 1
  return { validate: pct(d.validate, t), refine: pct(d.refine, t), drop: pct(d.drop, t) }
}

// ---- graph settings ----
const graphSettings = () => ({
  labelDensity: view.labelDensity,
  edgeEmphasis: view.edgeEmphasis / 100,
  forceSpacing: view.forceSpacing / 100,
  showHull: view.clusterHull,
})
const renderGraph = () => {
  if (!ctrl) return
  ctrl.update(visibleGraph.value, graphSettings())
  ctrl.applySelection(selectedNode.value ? selectedNode.value.id : null)
}

// ---- data load (real API contract: limit + minScore) ----
const clamp = (v, lo, hi) => { const n = Number(v); return Number.isFinite(n) ? Math.min(Math.max(n, lo), hi) : lo }
const loadGraph = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await getAudienceGraph({ limit: clamp(limit.value, 1, 300), minScore: clamp(minScore.value, 0, 1) })
    graphData.value = res.data || { nodes: [], edges: [], stats: {}, filters: {} }
    selectedNode.value = null
    await nextTick()
    renderGraph()
  } catch (e) {
    error.value = (e && e.message) || 'Could not load graph'
  } finally {
    loading.value = false
  }
}

// ---- interaction ----
const select = (node) => { selectedNode.value = node; if (window.innerWidth <= 860) panelVisible.value = true }
const clearSelection = () => { selectedNode.value = null }
const selectByTitle = (title) => {
  const n = (graphData.value.nodes || []).find((x) => x.type === 'topic' && x.title === title)
  if (n) select(n)
}
const onHover = (node, ev) => {
  if (!node) { tip.show = false; if (ctrl) ctrl.applyHover(null); return }
  if (ctrl) ctrl.applyHover(node.id)
  const r = canvasWrap.value.getBoundingClientRect()
  tip.x = ev.clientX - r.left
  tip.y = ev.clientY - r.top
  tip.node = node
  tip.show = true
}
const onBackground = () => { selectedNode.value = null }
const focusCluster = (c) => {
  clusterFilter.value = clusterFilter.value === c.id ? 'all' : c.id
  const node = (graphData.value.nodes || []).find((n) => n.id === 'cluster:' + c.id)
  if (node && clusterFilter.value === c.id) selectedNode.value = node
  else if (clusterFilter.value === 'all') selectedNode.value = null
  if (window.innerWidth <= 1180) railVisible.value = false
}
const focusClusterById = (cid) => { clusterFilter.value = cid; selectedNode.value = null }
const clearFilters = () => { searchQuery.value = ''; channelFilter.value = 'all'; clusterFilter.value = 'all' }
const resetZoom = () => { if (ctrl) ctrl.resetZoom() }
const openRun = (node) => { router.push({ name: 'Audience', query: { run: node.run_id } }) }

// ---- formatting ----
const fmtNum = (n) => Number(n || 0).toLocaleString('en-US')
const scoreLabel = (s) => { const n = Number(s); return Number.isFinite(n) ? n.toFixed(2) : 'n/a' }
const fmtDate = (iso) => { try { return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) } catch (e) { return '' } }

// ---- view options persistence ----
const setView = (key, val) => {
  view[key] = val
  try { localStorage.setItem('mf_graph_view', JSON.stringify({ ...view })) } catch (e) { /* noop */ }
}
const startDrag = (e) => {
  const el = viewEl.value
  if (!el) return
  const r = el.getBoundingClientRect()
  const ox = e.clientX - r.left
  const oy = e.clientY - r.top
  const move = (ev) => {
    el.style.left = Math.max(8, Math.min(window.innerWidth - r.width - 8, ev.clientX - ox)) + 'px'
    el.style.top = Math.max(8, Math.min(window.innerHeight - 60, ev.clientY - oy)) + 'px'
    el.style.right = 'auto'
    el.style.bottom = 'auto'
  }
  const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
  window.addEventListener('mousemove', move)
  window.addEventListener('mouseup', up)
}

// ---- watchers ----
watch(visibleGraph, () => { nextTick(renderGraph) })
watch(selectedNode, (n) => { if (ctrl) ctrl.applySelection(n ? n.id : null) })
watch(() => view.labelDensity, (v) => { if (ctrl) ctrl.tune({ labelDensity: v }) })
watch(() => view.edgeEmphasis, (v) => { if (ctrl) ctrl.tune({ edgeEmphasis: v / 100 }) })
watch(() => view.clusterHull, (v) => { if (ctrl) ctrl.tune({ showHull: v }) })
watch(() => view.forceSpacing, () => { renderGraph() })

// ---- lifecycle ----
onMounted(async () => {
  ctrl = createGraph({ svg: svgEl.value, container: canvasWrap.value, colorFor, onSelect: select, onHover, onBackground })
  await loadGraph()
  resizeObserver = new ResizeObserver(() => {
    if (resizeRaf) cancelAnimationFrame(resizeRaf)
    resizeRaf = requestAnimationFrame(renderGraph)
  })
  resizeObserver.observe(canvasWrap.value)
})
onBeforeUnmount(() => {
  if (resizeObserver) resizeObserver.disconnect()
  if (ctrl) ctrl.destroy()
})
</script>

<style scoped>
/* ============================ TOKENS ============================ */
.graph-page[data-theme='dark'] {
  --water-0:#05090f; --water-1:#0a121b; --water-2:#0e1825; --water-3:#13212f;
  --panel:#0b1521; --panel-2:#0f1c2a; --raised:#142231;
  --hairline:rgba(125,165,195,.12); --hairline-2:rgba(125,165,195,.22);
  --ink:#e9f1f7; --ink-dim:#a2b6c6; --ink-faint:#62798c;
  --edge-semantic:#8b8cff; --edge-lexical:#7d93a6;
  --good:#5fd0a8; --warn:#f1c453; --bad:#ff7a8a;
  --grid:rgba(125,165,195,.055); --ring:rgba(125,165,195,.06);
  --shadow:0 18px 50px -22px rgba(0,0,0,.75);
  color-scheme:dark;
}
.graph-page[data-theme='light'] {
  --water-0:#d7e0e8; --water-1:#edf1f5; --water-2:#ffffff; --water-3:#f3f6fa;
  --panel:#ffffff; --panel-2:#f5f8fb; --raised:#eef3f8;
  --hairline:rgba(20,45,65,.11); --hairline-2:rgba(20,45,65,.2);
  --ink:#0e1b27; --ink-dim:#475c6e; --ink-faint:#7f93a4;
  --edge-semantic:#6a6bef; --edge-lexical:#6b8294;
  --good:#1f9d74; --warn:#c08a16; --bad:#d84a5c;
  --grid:rgba(20,60,90,.06); --ring:rgba(20,60,90,.05);
  --shadow:0 18px 44px -24px rgba(20,45,70,.4);
  color-scheme:light;
}
.graph-page { --accent:#38e1ff; --edge-hybrid:var(--accent); --accent-ink:#04222b; }

/* ============================ SHELL ============================ */
.graph-page, .graph-page * { box-sizing:border-box; }
.graph-page {
  position:fixed; inset:0; display:flex; flex-direction:column;
  background:var(--water-0); color:var(--ink);
  font-family:'Space Grotesk', system-ui, sans-serif; font-size:14px; overflow:hidden;
  -webkit-font-smoothing:antialiased;
}
.mono { font-family:'JetBrains Mono', ui-monospace, monospace; }

.gnav { flex:0 0 auto; height:58px; display:flex; align-items:center; gap:18px; padding:0 18px;
  background:var(--panel); border-bottom:1px solid var(--hairline); }
.gnav-brand { display:flex; align-items:center; gap:11px; min-width:0; }
.brand-mark { width:30px; height:30px; border-radius:8px; flex:0 0 auto; display:grid; place-items:center;
  background:var(--raised); border:1px solid var(--hairline-2); overflow:hidden; }
.brand-mark img { width:100%; height:100%; object-fit:cover; }
.brand-text { display:flex; flex-direction:column; line-height:1.1; min-width:0; }
.brand-text b { font-weight:700; letter-spacing:.01em; font-size:14px; }
.brand-text span { font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-faint); }
.gnav-links { display:flex; gap:6px; margin-left:6px; }
.gnav-spacer { flex:1 1 auto; }
.gnav-stats { display:flex; }
.gstat { display:flex; flex-direction:column; align-items:flex-end; padding:0 14px; border-left:1px solid var(--hairline); }
.gstat b { font-family:'JetBrains Mono',monospace; font-size:15px; font-weight:600; color:var(--ink); line-height:1; }
.gstat span { font-size:9.5px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-faint); margin-top:4px; }
.live-dot { width:6px; height:6px; border-radius:50%; background:var(--accent); animation:pulse 2.6s ease-out infinite; }
@keyframes pulse { 0%{box-shadow:0 0 0 0 color-mix(in srgb,var(--accent) 60%,transparent);} 70%{box-shadow:0 0 0 7px transparent;} 100%{box-shadow:0 0 0 0 transparent;} }

.btn { font:inherit; cursor:pointer; border-radius:8px; border:1px solid var(--hairline-2); background:var(--raised);
  color:var(--ink); padding:8px 13px; display:inline-flex; align-items:center; gap:7px; line-height:1;
  transition:border-color .15s, background .15s, color .15s; white-space:nowrap; }
.btn:hover { border-color:var(--accent); }
.btn.is-on { border-color:var(--accent); color:var(--accent); }
.btn.ghost { background:transparent; border-color:transparent; color:var(--ink-dim); padding:7px 10px; }
.btn.ghost:hover { background:var(--raised); color:var(--ink); }
.btn.accent { background:var(--accent); border-color:var(--accent); color:var(--accent-ink); font-weight:600; box-shadow:0 6px 18px -8px var(--accent); }
.btn.accent:hover { filter:brightness(1.08); }
.btn.accent:disabled { opacity:.45; cursor:not-allowed; box-shadow:none; filter:none; }
.btn.sm { padding:7px 10px; font-size:12.5px; }
.btn .ic, .ic { width:14px; height:14px; flex:0 0 auto; display:inline-flex; }
.ic :deep(svg), .btn .ic :deep(svg) { width:100%; height:100%; }
.icon-btn { width:34px; height:34px; padding:0; justify-content:center; }

/* ============================ TOOLBAR ============================ */
.toolbar { flex:0 0 auto; display:flex; align-items:center; gap:10px; padding:11px 16px;
  background:var(--panel); border-bottom:1px solid var(--hairline); flex-wrap:wrap; }
.tb-search { position:relative; flex:1 1 240px; min-width:200px; max-width:380px; }
.tb-search .ic { position:absolute; left:11px; top:50%; transform:translateY(-50%); width:15px; height:15px; color:var(--ink-faint); pointer-events:none; }
.tb-search input { width:100%; padding:9px 64px 9px 34px; }
.tb-search .count { position:absolute; right:10px; top:50%; transform:translateY(-50%); font-family:'JetBrains Mono',monospace; font-size:10.5px; color:var(--ink-faint); letter-spacing:.04em; pointer-events:none; }
.field { display:flex; flex-direction:column; gap:4px; }
.field > label { font-size:9.5px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-faint); font-weight:600; padding-left:1px; }
.field.is-active > label { color:var(--accent); }
.field.is-active .ctl { border-color:color-mix(in srgb,var(--accent) 55%,var(--hairline-2)); }
.graph-page input, .graph-page select { font:inherit; color:var(--ink); background:var(--water-3); border:1px solid var(--hairline-2);
  border-radius:8px; padding:8px 10px; outline:none; transition:border-color .15s, box-shadow .15s; }
.graph-page input:focus, .graph-page select:focus { border-color:var(--accent); box-shadow:0 0 0 3px color-mix(in srgb,var(--accent) 18%,transparent); }
.graph-page input[type='number'] { width:78px; }
.graph-page select { width:148px; cursor:pointer; -webkit-appearance:none; appearance:none;
  background-image:linear-gradient(45deg,transparent 50%,var(--ink-faint) 50%),linear-gradient(135deg,var(--ink-faint) 50%,transparent 50%);
  background-position:calc(100% - 16px) 52%, calc(100% - 11px) 52%; background-size:5px 5px, 5px 5px; background-repeat:no-repeat; padding-right:30px; }
.tb-divider { width:1px; align-self:stretch; background:var(--hairline); margin:2px 2px; }
.tb-actions { display:flex; align-items:center; gap:8px; margin-left:auto; }
.tb-clear { font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--accent); background:none; border:none; cursor:pointer; padding:6px 8px; letter-spacing:.04em; }
.tb-clear:hover { text-decoration:underline; }

/* ============================ WORKBENCH ============================ */
.workbench { flex:1 1 auto; min-height:0; position:relative; display:grid;
  grid-template-columns:var(--rail-w,266px) minmax(0,1fr) var(--panel-w,374px); }
.workbench.rail-collapsed { --rail-w:0px; }
.workbench.panel-collapsed { --panel-w:0px; }

.rail { min-width:0; overflow:hidden auto; background:var(--panel); border-right:1px solid var(--hairline); display:flex; flex-direction:column; }
.rail-collapsed .rail { display:none; }
.rail-head { display:flex; align-items:center; justify-content:space-between; padding:15px 16px 10px; }
.rail-head h2 { margin:0; font-size:11px; letter-spacing:.18em; text-transform:uppercase; color:var(--ink-faint); font-weight:700; }
.signal { padding:4px 16px 16px; border-bottom:1px solid var(--hairline); }
.signal-row { display:flex; gap:9px; margin-bottom:13px; }
.signal-tile { flex:1; background:var(--water-3); border:1px solid var(--hairline); border-radius:9px; padding:10px 11px; }
.signal-tile b { font-family:'JetBrains Mono',monospace; font-size:21px; font-weight:600; line-height:1; display:block; }
.signal-tile span { font-size:9.5px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-faint); margin-top:6px; display:block; }
.meter-label { display:flex; justify-content:space-between; align-items:baseline; font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink-faint); margin:14px 0 7px; font-weight:600; }
.meter-label em { font-style:normal; font-family:'JetBrains Mono',monospace; color:var(--ink-dim); letter-spacing:0; }
.bar { height:8px; border-radius:6px; overflow:hidden; display:flex; background:var(--water-3); border:1px solid var(--hairline); }
.bar > i { height:100%; display:block; }
.seg-validate { background:var(--good); } .seg-refine { background:var(--warn); } .seg-drop { background:var(--bad); }
.bar-key { display:flex; gap:14px; margin-top:8px; flex-wrap:wrap; }
.bar-key span { display:inline-flex; align-items:center; gap:6px; font-size:10.5px; color:var(--ink-dim); font-family:'JetBrains Mono',monospace; }
.bar-key i { width:8px; height:8px; border-radius:2px; }
.cluster-list { padding:8px; display:flex; flex-direction:column; gap:2px; flex:1; }
.cluster-row { display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:10px; padding:9px 9px; border-radius:9px; cursor:pointer; border:1px solid transparent; text-align:left; background:none; color:inherit; font:inherit; width:100%; transition:background .14s, border-color .14s; }
.cluster-row:hover { background:var(--water-3); }
.cluster-row.is-active { border-color:color-mix(in srgb,var(--accent) 45%,var(--hairline-2)); background:color-mix(in srgb,var(--accent) 8%,transparent); }
.cluster-swatch { width:11px; height:11px; border-radius:50%; flex:0 0 auto; box-shadow:0 0 9px -1px currentColor; }
.cluster-meta { min-width:0; }
.cluster-meta b { font-size:12.5px; font-weight:600; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.cluster-mini { height:4px; border-radius:3px; overflow:hidden; display:flex; margin-top:6px; background:var(--water-1); }
.cluster-mini > i { height:100%; }
.cluster-count { font-family:'JetBrains Mono',monospace; font-size:12px; color:var(--ink-dim); flex:0 0 auto; }

/* ============================ CANVAS ============================ */
.canvas-wrap { position:relative; min-width:0; overflow:hidden; background:var(--water-1); }
.canvas-wrap.show-grid { background-image:linear-gradient(var(--grid) 1px,transparent 1px),linear-gradient(90deg,var(--grid) 1px,transparent 1px); background-size:27px 27px; }
.canvas-wrap::before { content:''; position:absolute; inset:0; pointer-events:none; background:repeating-radial-gradient(circle at 50% 44%, var(--ring) 0 1px, transparent 1px 98px); opacity:.7; }
.canvas-wrap::after { content:''; position:absolute; inset:0; pointer-events:none; z-index:3; background:radial-gradient(125% 92% at 50% -8%, transparent 42%, var(--water-0) 100%); opacity:.85; }
.graph-svg { position:absolute; inset:0; width:100%; height:100%; z-index:2; display:block; }

.canvas-tools { position:absolute; top:12px; right:12px; z-index:5; display:flex; gap:7px; }
.zoom-pill { display:flex; background:var(--panel); border:1px solid var(--hairline-2); border-radius:9px; overflow:hidden; box-shadow:var(--shadow); }
.zoom-pill button { background:none; border:none; color:var(--ink-dim); cursor:pointer; padding:8px 11px; font:inherit; display:inline-flex; }
.zoom-pill button + button { border-left:1px solid var(--hairline); }
.zoom-pill button:hover { color:var(--ink); background:var(--raised); }

.tip { position:absolute; z-index:6; pointer-events:none; max-width:250px; background:var(--panel); border:1px solid var(--hairline-2); border-radius:10px; padding:10px 12px; box-shadow:var(--shadow); transform:translate(-50%,calc(-100% - 14px)); }
.tip:after { content:''; position:absolute; left:50%; bottom:-5px; width:9px; height:9px; background:var(--panel); border-right:1px solid var(--hairline-2); border-bottom:1px solid var(--hairline-2); transform:translateX(-50%) rotate(45deg); }
.tip .tip-cluster { display:flex; align-items:center; gap:6px; font-size:9.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint); margin-bottom:5px; }
.tip .tip-cluster i { width:8px; height:8px; border-radius:50%; }
.tip b { font-size:13px; font-weight:600; display:block; line-height:1.25; }
.tip .tip-foot { display:flex; gap:8px; align-items:center; margin-top:8px; }

.chip { display:inline-flex; align-items:center; gap:5px; font-family:'JetBrains Mono',monospace; font-size:10.5px; letter-spacing:.03em; padding:3px 8px; border-radius:20px; border:1px solid var(--hairline-2); color:var(--ink-dim); text-transform:capitalize; }
.chip.validate { color:var(--good); border-color:color-mix(in srgb,var(--good) 45%,transparent); background:color-mix(in srgb,var(--good) 10%,transparent); }
.chip.refine { color:var(--warn); border-color:color-mix(in srgb,var(--warn) 45%,transparent); background:color-mix(in srgb,var(--warn) 10%,transparent); }
.chip.drop { color:var(--bad); border-color:color-mix(in srgb,var(--bad) 45%,transparent); background:color-mix(in srgb,var(--bad) 10%,transparent); }
.grade-dot { width:8px; height:8px; border-radius:50%; flex:0 0 auto; }
.grade-green { background:var(--good); } .grade-yellow { background:var(--warn); } .grade-red { background:var(--bad); } .grade-unknown { background:var(--ink-faint); }

.cstate { position:absolute; inset:0; z-index:7; display:grid; place-items:center; }
.cstate-inner { text-align:center; max-width:330px; padding:24px; }
.cstate-inner h3 { margin:14px 0 7px; font-size:16px; font-weight:600; }
.cstate-inner p { margin:0; color:var(--ink-dim); font-size:13px; line-height:1.5; }
.cstate-inner .btn { margin-top:16px; display:inline-flex; }
.sonar { width:54px; height:54px; margin:0 auto; position:relative; }
.sonar i { position:absolute; inset:0; border-radius:50%; border:1.5px solid var(--accent); animation:sonar 2s ease-out infinite; opacity:0; }
.sonar i:nth-child(2){ animation-delay:.66s; } .sonar i:nth-child(3){ animation-delay:1.32s; }
.sonar b { position:absolute; inset:42%; border-radius:50%; background:var(--accent); box-shadow:0 0 14px var(--accent); }
@keyframes sonar { 0%{transform:scale(.25);opacity:.9;} 100%{transform:scale(1);opacity:0;} }
.err-mark { width:46px; height:46px; margin:0 auto; border-radius:50%; display:grid; place-items:center; color:var(--bad); border:1.5px solid color-mix(in srgb,var(--bad) 55%,transparent); }

.legend { position:absolute; left:12px; bottom:12px; z-index:5; background:var(--panel); border:1px solid var(--hairline); border-radius:11px; padding:11px 13px; box-shadow:var(--shadow); min-width:190px; }
.legend-head { display:flex; align-items:center; justify-content:space-between; gap:12px; cursor:pointer; }
.legend-head h4 { margin:0; font-size:9.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-faint); font-weight:700; }
.legend-body { margin-top:10px; display:grid; gap:7px; }
.legend.collapsed .legend-body { display:none; }
.legend-row { display:flex; align-items:center; gap:9px; font-size:11px; color:var(--ink-dim); font-family:'JetBrains Mono',monospace; }
.lg-line { width:26px; height:0; border-top-width:2px; border-top-style:solid; flex:0 0 auto; }
.lg-line.hybrid { border-color:var(--edge-hybrid); border-top-width:2.5px; }
.lg-line.semantic { border-color:var(--edge-semantic); border-top-style:dashed; }
.lg-line.lexical { border-color:var(--edge-lexical); border-top-style:dotted; }
.lg-line.cluster { border-color:var(--ink-faint); border-top-style:dotted; opacity:.7; }
.lg-dot { width:13px; height:13px; border-radius:50%; flex:0 0 auto; }
.lg-dot.cluster { border:1.5px solid var(--ink-dim); position:relative; }
.lg-dot.cluster:after { content:''; position:absolute; inset:3px; border-radius:50%; background:var(--ink-dim); }
.lg-dot.topic { background:radial-gradient(circle at 38% 35%, #fff 0 30%, var(--edge-semantic) 70%); }

/* ============================ DETAIL PANEL ============================ */
.panel { min-width:0; overflow:hidden auto; background:var(--panel); border-left:1px solid var(--hairline); }
.panel-collapsed .panel { display:none; }
.panel-inner { padding:20px 20px 28px; }
.panel-kicker { display:flex; align-items:center; gap:8px; font-family:'JetBrains Mono',monospace; font-size:10px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-faint); }
.panel-kicker .cluster-swatch { width:9px; height:9px; }
.panel h1 { font-size:21px; line-height:1.18; margin:11px 0 4px; font-weight:600; text-wrap:pretty; }
.panel-sub { color:var(--ink-faint); font-family:'JetBrains Mono',monospace; font-size:11px; }
.metric-grid { display:grid; grid-template-columns:1fr 1fr; gap:9px; margin:18px 0; }
.metric { background:var(--water-3); border:1px solid var(--hairline); border-radius:10px; padding:11px 12px; min-width:0; }
.metric span { display:block; font-size:9.5px; letter-spacing:.11em; text-transform:uppercase; color:var(--ink-faint); margin-bottom:7px; }
.metric strong { font-size:14px; font-weight:600; display:flex; align-items:center; gap:7px; overflow-wrap:anywhere; }
.psection { margin-top:18px; }
.psection > .sec-label { font-size:10px; letter-spacing:.13em; text-transform:uppercase; color:var(--ink-faint); font-weight:600; margin-bottom:10px; display:flex; justify-content:space-between; align-items:baseline; }
.next-action { background:color-mix(in srgb,var(--accent) 7%,transparent); border:1px solid color-mix(in srgb,var(--accent) 25%,var(--hairline)); border-radius:10px; padding:12px 13px; display:flex; gap:11px; align-items:flex-start; }
.next-action .ic { color:var(--accent); flex:0 0 auto; margin-top:1px; }
.next-action p { margin:0; line-height:1.45; font-size:13px; }
.simlist { display:flex; flex-direction:column; }
.simrow { display:grid; grid-template-columns:18px 1fr auto; gap:10px; align-items:center; padding:9px 0; border-top:1px solid var(--hairline); cursor:pointer; }
.simrow:first-child { border-top:none; }
.simrow:hover .sim-title { color:var(--accent); }
.sim-rank { font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--ink-faint); }
.sim-main { min-width:0; }
.sim-title { font-size:12.5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; transition:color .14s; }
.sim-track { height:4px; border-radius:3px; background:var(--water-3); margin-top:6px; overflow:hidden; }
.sim-track > i { height:100%; display:block; background:var(--accent); border-radius:3px; }
.sim-score { font-family:'JetBrains Mono',monospace; font-size:11.5px; color:var(--ink-dim); text-align:right; }
.sim-method { font-size:9px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink-faint); }
.member-list { display:flex; flex-direction:column; gap:1px; }
.member { display:flex; align-items:center; gap:9px; padding:8px 8px; border-radius:8px; cursor:pointer; }
.member:hover { background:var(--water-3); }
.member b { font-size:12.5px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; min-width:0; flex:1; }
.open-run { width:100%; justify-content:center; margin-top:20px; padding:12px; }
.help-block .hint { color:var(--ink-dim); font-size:13px; line-height:1.55; margin:10px 0 20px; }
.help-steps { display:grid; gap:11px; margin-top:4px; }
.help-step { display:flex; gap:11px; align-items:flex-start; font-size:12.5px; color:var(--ink-dim); }
.help-step i { width:22px; height:22px; border-radius:7px; flex:0 0 auto; display:grid; place-items:center; background:var(--water-3); border:1px solid var(--hairline); color:var(--accent); font-family:'JetBrains Mono',monospace; font-size:11px; font-style:normal; }

/* ============================ VIEW OPTIONS ============================ */
.tweaks { position:fixed; right:18px; bottom:18px; z-index:50; width:268px; background:var(--panel); border:1px solid var(--hairline-2); border-radius:14px; box-shadow:0 24px 60px -20px rgba(0,0,0,.7); overflow:hidden; font-family:'Space Grotesk',sans-serif; }
.tweaks-head { display:flex; align-items:center; justify-content:space-between; padding:12px 14px; border-bottom:1px solid var(--hairline); cursor:grab; }
.tweaks-head b { font-size:11px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink-dim); }
.tweaks-head button { background:none; border:none; color:var(--ink-faint); cursor:pointer; font-size:17px; line-height:1; padding:2px 4px; }
.tweaks-body { padding:14px; display:flex; flex-direction:column; gap:15px; max-height:min(72vh,560px); overflow:auto; }
.tw-row { display:flex; flex-direction:column; gap:8px; }
.tw-row > label { font-size:10px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink-faint); font-weight:600; display:flex; justify-content:space-between; }
.tw-row > label em { font-style:normal; color:var(--ink-dim); font-family:'JetBrains Mono',monospace; letter-spacing:0; }
.tw-seg { display:flex; background:var(--water-3); border:1px solid var(--hairline); border-radius:9px; padding:3px; gap:3px; }
.tw-seg button { flex:1; background:none; border:none; color:var(--ink-dim); cursor:pointer; font:inherit; font-size:11.5px; padding:6px 4px; border-radius:6px; text-transform:capitalize; transition:background .14s, color .14s; }
.tw-seg button.on { background:var(--accent); color:var(--accent-ink); font-weight:600; }
.tw-swatches { display:flex; gap:8px; }
.tw-swatches button { width:30px; height:30px; border-radius:50%; cursor:pointer; border:2px solid transparent; padding:0; transition:transform .12s; }
.tw-swatches button:hover { transform:scale(1.1); }
.tw-swatches button.on { border-color:var(--ink); box-shadow:0 0 0 2px var(--panel) inset; }
.graph-page input[type='range'] { -webkit-appearance:none; appearance:none; width:100%; height:4px; border-radius:3px; background:var(--water-3); border:1px solid var(--hairline); padding:0; }
.graph-page input[type='range']::-webkit-slider-thumb { -webkit-appearance:none; width:16px; height:16px; border-radius:50%; background:var(--accent); cursor:pointer; box-shadow:0 0 10px -2px var(--accent); }
.graph-page input[type='range']::-moz-range-thumb { width:16px; height:16px; border:none; border-radius:50%; background:var(--accent); cursor:pointer; }
.tw-toggle { display:flex; align-items:center; justify-content:space-between; }
.tw-switch { width:40px; height:23px; border-radius:20px; background:var(--water-3); border:1px solid var(--hairline-2); position:relative; cursor:pointer; transition:background .16s; flex:0 0 auto; }
.tw-switch:after { content:''; position:absolute; top:2px; left:2px; width:17px; height:17px; border-radius:50%; background:var(--ink-dim); transition:transform .16s, background .16s; }
.tw-switch.on { background:color-mix(in srgb,var(--accent) 35%,var(--water-3)); border-color:var(--accent); }
.tw-switch.on:after { transform:translateX(17px); background:var(--accent); }

/* ============================ SVG GRAPH (D3-injected → :deep) ============================ */
:deep(.mf-edge) { transition:stroke-opacity .25s; }
:deep(.mf-edge.is-dim) { stroke-opacity:.05 !important; }
:deep(.mf-node) { transition:opacity .25s; }
:deep(.mf-node.is-dim) { opacity:.13; }
:deep(.mf-topic-dot) { transition:stroke-width .15s; }
:deep(.mf-node.is-hover .mf-topic-dot) { stroke:#fff; stroke-width:2.4; }
:deep(.mf-node.is-neighbor .mf-topic-dot) { stroke-width:2; }
:deep(.mf-node.is-selected .mf-topic-dot) { stroke:var(--accent); stroke-width:3; filter:url(#mf-glow-strong); }
:deep(.mf-node.is-selected .mf-cluster-core) { filter:url(#mf-glow-strong); }
:deep(.mf-node.is-hover .mf-cluster-halo), :deep(.mf-node.is-selected .mf-cluster-halo) { opacity:.85; stroke-width:2; }
:deep(.mf-cluster-halo) { opacity:.45; }
:deep(.mf-warn-yellow) { stroke:var(--warn); stroke-width:1.4; opacity:.85; }
:deep(.mf-warn-red) { stroke:var(--bad); stroke-width:1.6; opacity:.95; }
:deep(.mf-hull) { fill-opacity:.05; stroke-opacity:.2; stroke-width:1.2; transition:fill-opacity .3s, stroke-opacity .3s; }
:deep(.mf-hull.is-dim) { fill-opacity:.015; stroke-opacity:.05; }
:deep(.mf-label) { font-family:'JetBrains Mono',monospace; font-size:10px; fill:var(--ink); paint-order:stroke; stroke:var(--water-1); stroke-width:3.4px; stroke-linejoin:round; pointer-events:none; }
:deep(.mf-label.is-hidden) { display:none; }
:deep(.mf-label-cluster) { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:10.5px; letter-spacing:.09em; text-transform:uppercase; fill:var(--ink-dim); }

/* ============================ RESPONSIVE ============================ */
@media (max-width:1180px) {
  .workbench { grid-template-columns:minmax(0,1fr) var(--panel-w,360px); }
  .rail { position:absolute; z-index:20; top:0; bottom:0; left:0; width:280px; box-shadow:var(--shadow); transform:translateX(-102%); transition:transform .22s; display:flex; border-right:1px solid var(--hairline-2); }
  .workbench.rail-open .rail { transform:translateX(0); }
  .rail-collapsed .rail { display:flex; }
}
@media (max-width:860px) {
  .workbench { grid-template-columns:1fr; grid-auto-rows:min-content; overflow:auto; }
  .canvas-wrap { height:62vh; min-height:380px; }
  .panel { border-left:none; border-top:1px solid var(--hairline-2); }
  .panel-collapsed .panel { display:block; }
  .toolbar { flex-wrap:nowrap; overflow-x:auto; }
  .gnav-stats .gstat:first-child { border-left:none; }
  .tweaks { left:12px; right:12px; width:auto; }
}
@media (max-width:560px) {
  .gnav-stats { display:none; }
  .gnav-links .label-hide { display:none; }
}
</style>
