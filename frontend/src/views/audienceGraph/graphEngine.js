/* graphEngine.js — MiroFish Global Audience Graph render engine (D3 7.x).
 *
 * Framework-agnostic controller. AudienceGraphView.vue creates one instance and
 * drives it. Keeps ALL D3 / force-simulation / SVG concerns out of the SFC.
 *
 *   import { createGraph } from './audienceGraph/graphEngine'
 *   const ctrl = createGraph({ svg, container, colorFor, onSelect, onHover, onBackground })
 *   ctrl.update(graphData, settings)   // full (re)render — graphData = { nodes, edges }
 *   ctrl.applySelection(id | null)     // focus + dim connected, no relayout
 *   ctrl.applyHover(id | null)         // hover emphasis, no relayout
 *   ctrl.tune(partialSettings)         // labels / edge emphasis / hull, no relayout
 *   ctrl.resetZoom()                   // re-frame to fit
 *   ctrl.zoomBy(k)                     // zoom in/out
 *   ctrl.destroy()
 *
 * settings = { labelDensity:'always'|'hover'|'off', edgeEmphasis:0..1,
 *              forceSpacing:0..1, showHull:boolean }
 *
 * Data contract (unchanged from /api/audience/graph):
 *   node.type 'topic' | 'cluster'; node.id, node.cluster_id, node.title/label,
 *   topic.reliability_grade 'green'|'yellow'|'red'|'unknown'
 *   edge.type 'SIMILAR_TO' | 'IN_CLUSTER'; SIMILAR_TO.method 'hybrid'|'semantic'|'lexical'
 */
import * as d3 from 'd3'

const METHOD = {
  hybrid: { dash: null },
  semantic: { dash: '7 5' },
  lexical: { dash: '1.5 5' },
}

export function createGraph(opts) {
  const svg = d3.select(opts.svg)
  const colorFor = opts.colorFor || (() => '#7aa2ff')
  let simulation = null
  let zoom = null
  let root = null
  const layers = {}
  let nodesSel = null
  let linksSel = null
  let hullsSel = null
  let labelsSel = null
  let data = { nodes: [], edges: [] }
  let settings = { labelDensity: 'hover', edgeEmphasis: 0.6, forceSpacing: 0.5, showHull: true }
  let selectedId = null
  let hoverId = null
  let adjacency = new Map()

  const methodColor = (method) =>
    method === 'hybrid' ? 'var(--edge-hybrid)' : method === 'semantic' ? 'var(--edge-semantic)' : 'var(--edge-lexical)'

  function defs() {
    if (!svg.select('defs').empty()) return
    const d = svg.append('defs')
    const glow = d.append('filter').attr('id', 'mf-glow').attr('x', '-60%').attr('y', '-60%').attr('width', '220%').attr('height', '220%')
    glow.append('feGaussianBlur').attr('stdDeviation', '3.4').attr('result', 'b')
    const m = glow.append('feMerge'); m.append('feMergeNode').attr('in', 'b'); m.append('feMergeNode').attr('in', 'SourceGraphic')
    const sel = d.append('filter').attr('id', 'mf-glow-strong').attr('x', '-120%').attr('y', '-120%').attr('width', '340%').attr('height', '340%')
    sel.append('feGaussianBlur').attr('stdDeviation', '7').attr('result', 'b')
    const m2 = sel.append('feMerge'); m2.append('feMergeNode').attr('in', 'b'); m2.append('feMergeNode').attr('in', 'SourceGraphic')
  }

  function buildAdjacency() {
    adjacency = new Map()
    data.nodes.forEach((n) => adjacency.set(n.id, new Set()))
    data.edges.forEach((e) => {
      const s = typeof e.source === 'object' ? e.source.id : e.source
      const t = typeof e.target === 'object' ? e.target.id : e.target
      if (adjacency.has(s)) adjacency.get(s).add(t)
      if (adjacency.has(t)) adjacency.get(t).add(s)
    })
  }

  function spacing() {
    const s = settings.forceSpacing
    return { linkSim: 70 + s * 130, linkCluster: 40 + s * 60, charge: -(95 + s * 300), collide: 17 + s * 16, clusterGravity: 0.12 - s * 0.05 }
  }

  function clusterCentroids(width, height) {
    const clusters = data.nodes.filter((n) => n.type === 'cluster')
    const R = Math.min(width, height) * 0.27
    const cx = width / 2
    const cy = height / 2
    const map = new Map()
    clusters.forEach((c, i) => {
      const a = (i / Math.max(clusters.length, 1)) * Math.PI * 2 - Math.PI / 2
      map.set(c.cluster_id, { x: cx + R * Math.cos(a), y: cy + R * Math.sin(a) })
    })
    return map
  }

  function nodeRadius(n) {
    if (n.type === 'cluster') return Math.min(30, 15 + Number(n.topic_count || 1) * 1.7)
    return n.reliability_grade === 'yellow' ? 7.5 : n.reliability_grade === 'red' ? 7 : 6.5
  }

  function update(nextData, nextSettings) {
    if (nextData) data = { nodes: nextData.nodes.map((n) => ({ ...n })), edges: nextData.edges.map((e) => ({ ...e })) }
    if (nextSettings) settings = { ...settings, ...nextSettings }
    render()
  }

  function render() {
    const rect = opts.container.getBoundingClientRect()
    const width = Math.max(rect.width, 320)
    const height = Math.max(rect.height, 360)
    svg.attr('width', width).attr('height', height).attr('viewBox', `0 0 ${width} ${height}`)
    svg.selectAll('g.mf-root').remove()
    defs()
    if (simulation) simulation.stop()
    if (!data.nodes.length) return

    buildAdjacency()
    root = svg.append('g').attr('class', 'mf-root')
    layers.hull = root.append('g').attr('class', 'mf-hulls')
    layers.link = root.append('g').attr('class', 'mf-links')
    layers.node = root.append('g').attr('class', 'mf-nodes')
    layers.label = root.append('g').attr('class', 'mf-labels')

    zoom = d3.zoom().scaleExtent([0.25, 5]).on('zoom', (ev) => root.attr('transform', ev.transform))
    svg.call(zoom).on('dblclick.zoom', null)
    svg.on('click', () => { if (opts.onBackground) opts.onBackground() })

    const sp = spacing()
    const centroids = clusterCentroids(width, height)

    simulation = d3.forceSimulation(data.nodes)
      .force('link', d3.forceLink(data.edges).id((n) => n.id)
        .distance((e) => (e.type === 'IN_CLUSTER' ? sp.linkCluster : sp.linkSim))
        .strength((e) => (e.type === 'IN_CLUSTER' ? 0.35 : 0.12 + Number(e.score || 0) * 0.3)))
      .force('charge', d3.forceManyBody().strength((n) => (n.type === 'cluster' ? sp.charge * 1.8 : sp.charge)))
      .force('collide', d3.forceCollide().radius((n) => nodeRadius(n) + sp.collide))
      .force('x', d3.forceX((n) => (centroids.get(n.cluster_id) || { x: width / 2 }).x).strength(sp.clusterGravity))
      .force('y', d3.forceY((n) => (centroids.get(n.cluster_id) || { y: height / 2 }).y).strength(sp.clusterGravity))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.04))

    linksSel = layers.link.selectAll('line').data(data.edges, (e) => e.id).enter().append('line')
      .attr('class', (e) => 'mf-edge mf-edge-' + (e.type === 'IN_CLUSTER' ? 'cluster' : e.method))
      .attr('stroke', (e) => (e.type === 'IN_CLUSTER' ? colorFor(clusterOf(e)) : methodColor(e.method)))
      .attr('stroke-dasharray', (e) => (e.type === 'IN_CLUSTER' ? '1 6' : (METHOD[e.method] ? METHOD[e.method].dash : null)))
      .attr('stroke-linecap', 'round')

    hullsSel = layers.hull.selectAll('path')

    const ng = layers.node.selectAll('g').data(data.nodes, (n) => n.id).enter().append('g')
      .attr('class', (n) => 'mf-node mf-node-' + n.type)
      .style('cursor', 'pointer')
      .on('click', (ev, n) => { ev.stopPropagation(); if (opts.onSelect) opts.onSelect(n) })
      .on('mouseenter', (ev, n) => { if (opts.onHover) opts.onHover(n, ev) })
      .on('mousemove', (ev, n) => { if (opts.onHover) opts.onHover(n, ev) })
      .on('mouseleave', () => { if (opts.onHover) opts.onHover(null) })
      .call(d3.drag().on('start', dStart).on('drag', dDrag).on('end', dEnd))

    ng.filter((n) => n.type === 'cluster').each(function (n) {
      const g = d3.select(this)
      const r = nodeRadius(n)
      g.append('circle').attr('class', 'mf-cluster-halo').attr('r', r + 8).attr('fill', 'none').attr('stroke', colorFor(n.cluster_id))
      g.append('circle').attr('class', 'mf-cluster-core').attr('r', r).attr('fill', colorFor(n.cluster_id)).attr('fill-opacity', 0.16).attr('stroke', colorFor(n.cluster_id)).attr('stroke-width', 2)
      g.append('circle').attr('class', 'mf-cluster-pip').attr('r', Math.max(3, r * 0.3)).attr('fill', colorFor(n.cluster_id))
    })
    ng.filter((n) => n.type === 'topic').each(function (n) {
      const g = d3.select(this)
      const r = nodeRadius(n)
      g.append('circle').attr('class', 'mf-topic-dot').attr('r', r).attr('fill', colorFor(n.cluster_id)).attr('stroke', colorFor(n.cluster_id)).attr('filter', 'url(#mf-glow)')
      g.append('circle').attr('class', 'mf-topic-core').attr('r', Math.max(2, r - 3.4)).attr('fill', '#ffffff').attr('opacity', 0.85)
      if (n.reliability_grade === 'yellow' || n.reliability_grade === 'red') {
        g.append('circle').attr('class', 'mf-topic-warn mf-warn-' + n.reliability_grade).attr('r', r + 3).attr('fill', 'none')
      }
    })
    nodesSel = ng

    labelsSel = layers.label.selectAll('text').data(data.nodes, (n) => n.id).enter().append('text')
      .attr('class', (n) => 'mf-label mf-label-' + n.type)
      .attr('text-anchor', (n) => (n.type === 'cluster' ? 'middle' : 'start'))
      .text((n) => trim(n.label || n.title, n.type === 'cluster' ? 22 : 26))

    applyLabelVisibility()
    applyEdgeEmphasis()

    function ticked() {
      linksSel.attr('x1', (e) => e.source.x).attr('y1', (e) => e.source.y).attr('x2', (e) => e.target.x).attr('y2', (e) => e.target.y)
      nodesSel.attr('transform', (n) => `translate(${n.x},${n.y})`)
      labelsSel
        .attr('x', (n) => (n.type === 'cluster' ? n.x : n.x + nodeRadius(n) + 7))
        .attr('y', (n) => (n.type === 'cluster' ? n.y + nodeRadius(n) + 15 : n.y + 4))
      if (settings.showHull) drawHulls()
    }

    // Settle synchronously for a calm, framed first paint (no perpetual drift; drag still re-warms).
    simulation.on('tick', ticked)
    simulation.stop()
    for (let i = 0; i < 320; i += 1) simulation.tick()
    ticked()
    fitToView()
    applySelection(selectedId)

    function dStart(ev) { if (!ev.active) simulation.alphaTarget(0.25).restart(); ev.subject.fx = ev.subject.x; ev.subject.fy = ev.subject.y }
    function dDrag(ev) { ev.subject.fx = ev.x; ev.subject.fy = ev.y }
    function dEnd(ev) { if (!ev.active) simulation.alphaTarget(0); ev.subject.fx = null; ev.subject.fy = null }
  }

  function clusterOf(edge) {
    const t = typeof edge.target === 'object' ? edge.target : data.nodes.find((n) => n.id === edge.target)
    return t ? t.cluster_id : null
  }

  function drawHulls() {
    const groups = d3.group(data.nodes.filter((n) => n.x != null), (n) => n.cluster_id)
    const paths = []
    groups.forEach((members, cid) => { if (cid) paths.push({ cid, pts: members.map((m) => [m.x, m.y]) }) })
    hullsSel = layers.hull.selectAll('path').data(paths, (d) => d.cid)
    hullsSel.exit().remove()
    const enter = hullsSel.enter().append('path').attr('class', 'mf-hull').attr('fill', (d) => colorFor(d.cid)).attr('stroke', (d) => colorFor(d.cid))
    hullsSel = enter.merge(hullsSel)
    hullsSel.attr('d', (d) => hullPath(d.pts))
  }

  function hullPath(points) {
    if (points.length === 0) return ''
    const cx = d3.mean(points, (p) => p[0])
    const cy = d3.mean(points, (p) => p[1])
    let ring
    if (points.length < 3) {
      const r = points.length === 1 ? 30 : 38
      ring = d3.range(12).map((i) => {
        const a = (i / 12) * Math.PI * 2
        return [cx + Math.cos(a) * r + (points[0][0] - cx) * 0.2, cy + Math.sin(a) * r + (points[0][1] - cy) * 0.2]
      })
    } else {
      const hull = d3.polygonHull(points) || points
      const pad = 26
      ring = hull.map((p) => {
        const dx = p[0] - cx, dy = p[1] - cy
        const len = Math.hypot(dx, dy) || 1
        return [p[0] + (dx / len) * pad, p[1] + (dy / len) * pad]
      })
    }
    return d3.line().curve(d3.curveCatmullRomClosed.alpha(0.6))(ring)
  }

  function applyLabelVisibility() {
    if (!labelsSel) return
    const mode = settings.labelDensity
    labelsSel.classed('is-hidden', (n) => {
      if (n.type === 'cluster') return false
      if (mode === 'always') return false
      if (mode === 'off') return true
      if (selectedId) {
        if (n.id === selectedId) return false
        return !(adjacency.get(selectedId) && adjacency.get(selectedId).has(n.id))
      }
      return n.id !== hoverId
    })
  }

  function applyEdgeEmphasis() {
    if (!linksSel) return
    const e = settings.edgeEmphasis
    linksSel.each(function (d) {
      const sel = d3.select(this)
      if (d.type === 'IN_CLUSTER') {
        sel.attr('stroke-width', 1).attr('stroke-opacity', 0.1 + (1 - e) * 0.16)
      } else {
        const base = d.method === 'hybrid' ? 1.6 : 1.1
        sel.attr('stroke-width', base + Number(d.score || 0) * (1.5 + e * 4)).attr('stroke-opacity', 0.28 + e * 0.5 + (d.method === 'hybrid' ? 0.08 : 0))
      }
    })
  }

  function applySelection(id) {
    selectedId = id
    if (!nodesSel) return
    const neigh = id && adjacency.get(id) ? adjacency.get(id) : null
    const dim = !!id
    nodesSel.classed('is-dim', (n) => dim && n.id !== id && !(neigh && neigh.has(n.id)))
      .classed('is-selected', (n) => n.id === id)
      .classed('is-neighbor', (n) => !!(neigh && neigh.has(n.id)))
    if (linksSel) {
      linksSel.classed('is-dim', (e) => {
        if (!dim) return false
        const s = e.source.id || e.source, t = e.target.id || e.target
        return !(s === id || t === id)
      }).classed('is-active', (e) => {
        if (!dim) return false
        const s = e.source.id || e.source, t = e.target.id || e.target
        return s === id || t === id
      })
    }
    if (hullsSel && hullsSel.classed) {
      hullsSel.classed('is-dim', (d) => {
        if (!dim) return false
        const node = data.nodes.find((n) => n.id === id)
        return !(node && node.cluster_id === d.cid)
      })
    }
    applyLabelVisibility()
  }

  function applyHover(id) {
    hoverId = id
    if (!nodesSel) return
    nodesSel.classed('is-hover', (n) => n.id === id)
    applyLabelVisibility()
  }

  function fitToView(animate) {
    if (!zoom) return
    const rect = opts.container.getBoundingClientRect()
    const w = Math.max(rect.width, 320)
    const h = Math.max(rect.height, 360)
    const xs = data.nodes.map((n) => n.x).filter((v) => v != null)
    const ys = data.nodes.map((n) => n.y).filter((v) => v != null)
    if (!xs.length) return
    const minX = Math.min(...xs), maxX = Math.max(...xs)
    const minY = Math.min(...ys), maxY = Math.max(...ys)
    const bw = Math.max(maxX - minX, 10), bh = Math.max(maxY - minY, 10)
    const pad = 90
    const scale = Math.min((w - pad) / bw, (h - pad) / bh, 1.9)
    const tx = (w - scale * (minX + maxX)) / 2
    const ty = (h - scale * (minY + maxY)) / 2
    const target = d3.zoomIdentity.translate(tx, ty).scale(scale)
    if (animate) svg.transition().duration(280).call(zoom.transform, target)
    else svg.call(zoom.transform, target)
  }

  function resetZoom() { fitToView(true) }
  function zoomBy(k) { if (zoom) svg.transition().duration(180).call(zoom.scaleBy, k) }
  function destroy() { if (simulation) simulation.stop(); svg.selectAll('*').remove() }

  function trim(v, n) {
    const s = String(v || '').replace(/\s+/g, ' ').trim()
    return s.length <= n ? s : s.slice(0, n - 1).trim() + '…'
  }

  function tune(partial) {
    settings = { ...settings, ...partial }
    applyEdgeEmphasis()
    applyLabelVisibility()
    if (!layers.hull) return
    if (settings.showHull) drawHulls()
    else layers.hull.selectAll('*').remove()
  }

  return { update, tune, applySelection, applyHover, resetZoom, zoomBy, destroy }
}
