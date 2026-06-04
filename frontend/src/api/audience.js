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
