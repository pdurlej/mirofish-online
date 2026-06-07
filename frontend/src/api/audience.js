import service, { requestWithRetry } from './index'

export const listAudiencePersonas = () => {
  return service.get('/api/audience/personas')
}

export const createFakeAudienceRun = (data) => {
  return requestWithRetry(() => service.post('/api/audience/runs/fake', data), 1, 500)
}

export const createLiveAudienceRun = (data) => {
  return requestWithRetry(() => service.post('/api/audience/runs', data), 1, 500)
}

export const getAudienceRun = (runId) => {
  return service.get(`/api/audience/runs/${runId}`)
}

export const listAudienceRuns = (limit = 25) => {
  return service.get(`/api/audience/runs?limit=${limit}`)
}

export const getAudienceGraph = ({ limit = 120, minScore = 0.35, includePersonas = false } = {}) => {
  const params = new URLSearchParams({
    limit: String(limit),
    min_score: String(minScore),
    include_personas: includePersonas ? 'true' : 'false'
  })
  return service.get(`/api/audience/graph?${params.toString()}`)
}
