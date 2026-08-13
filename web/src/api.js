/* The /v1 client.
 *
 * Authentication is the session cookie, which the browser attaches for us. The
 * only thing we have to do by hand is echo the CSRF token on writes: the cookie
 * is ambient, so the server requires a value that a hostile origin cannot read.
 * See app/browser.py.
 */

const CSRF_COOKIE = 'sac_csrf'

function csrfToken() {
  const match = document.cookie.match(
    new RegExp('(?:^|; )' + CSRF_COOKIE + '=([^;]*)')
  )
  return match ? decodeURIComponent(match[1]) : ''
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(detail || `request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request(method, path, body) {
  const headers = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (method !== 'GET') headers['X-SAC-CSRF'] = csrfToken()

  const response = await fetch(path, {
    method,
    headers,
    credentials: 'same-origin',
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401) {
    // The session is gone. Hand off to the server-rendered sign-in page and
    // come back here afterwards.
    const back = encodeURIComponent(
      window.location.pathname + window.location.search
    )
    window.location.href = `/auth/login?next=${back}`
    throw new ApiError(401, 'signed out')
  }

  let payload = null
  const text = await response.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = null
    }
  }

  if (!response.ok) {
    throw new ApiError(response.status, payload?.detail || response.statusText)
  }
  return payload
}

export const api = {
  me: () => request('GET', '/v1/me'),

  contexts: () => request('GET', '/v1/contexts'),
  createContext: (name, description = '') =>
    request('POST', '/v1/contexts', { name, description }),
  context: (id) => request('GET', `/v1/projects/${id}`),
  archive: (id) => request('POST', `/v1/contexts/${id}/archive`),
  unarchive: (id) => request('POST', `/v1/contexts/${id}/unarchive`),

  memories: (id, { status = 'active', scope, limit = 100 } = {}) => {
    const q = new URLSearchParams({ status, limit: String(limit) })
    if (scope) q.set('scope', scope)
    return request('GET', `/v1/projects/${id}/memories?${q}`)
  },
  memory: (id, memoryId) =>
    request('GET', `/v1/projects/${id}/memories/${memoryId}?include_versions=true`),
  retract: (id, memoryId) =>
    request('POST', `/v1/projects/${id}/memories/${memoryId}/retract`),

  shares: (id) => request('GET', `/v1/contexts/${id}/shares`),
  share: (id, email, access) =>
    request('POST', `/v1/contexts/${id}/shares`, { email, access }),
  changeAccess: (id, userId, access) =>
    request('PATCH', `/v1/contexts/${id}/shares/${userId}`, { access }),
  revokeAccess: (id, userId) =>
    request('DELETE', `/v1/contexts/${id}/shares/${userId}`),

  link: (id) => request('GET', `/v1/contexts/${id}/link`),
  setLink: (id, access) => request('PUT', `/v1/contexts/${id}/link`, { access }),
  rotateLink: (id) => request('POST', `/v1/contexts/${id}/link/rotate`),

  activity: (id) => request('GET', `/v1/contexts/${id}/activity`),
  snapshots: (id) => request('GET', `/v1/contexts/${id}/snapshots`),
  snapshot: (id, snapshotId) =>
    request('GET', `/v1/projects/${id}/snapshots/${snapshotId}`),

  connections: () => request('GET', '/v1/connections'),
  revokeConnection: (connId) =>
    request('POST', `/v1/connections/${connId}/revoke`),
  setConnectionContext: (connId, context) =>
    request('PUT', `/v1/connections/${connId}/context`, { context }),
}
