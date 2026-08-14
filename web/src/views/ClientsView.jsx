/* Connected AI clients.
 *
 * This is where "multiple accounts connected" becomes concrete: each Claude or
 * ChatGPT connection is listed with the context it is currently working in, and
 * that context can be changed here — the click-driven equivalent of asking the
 * agent to call sac_use_context.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from '../api.js'
import { Loading, when } from '../components.jsx'
import ConnectGuide from '../ConnectGuide.jsx'

export default function ClientsView({ contexts, toast }) {
  const [connections, setConnections] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')

  const load = useCallback(async () => {
    try {
      const out = await api.connections()
      setConnections(out.connections)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <div className="page"><div className="notice error">{error}</div></div>
  if (!connections) return <Loading label="Reading connected clients" />

  const active = connections.filter((c) => !c.revoked)
  const revoked = connections.filter((c) => c.revoked)

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>AI clients</h1>
          <p className="sub">
            Every Claude, ChatGPT, or other MCP client you have connected, and
            which context each one is working in.
          </p>
        </div>
      </div>

      {active.length === 0 ? (
        <ConnectGuide />
      ) : (
        <div className="card">
          <div className="list">
            {active.map((conn) => (
              <div className="item" key={conn.id}>
                <div className="item-head">
                  <span className="item-title">{conn.label || 'MCP client'}</span>
                  {conn.provider ? (
                    <span className="badge">{conn.provider}</span>
                  ) : null}
                  {conn.last_seen_at ? (
                    <span className="tiny">seen {when(conn.last_seen_at)}</span>
                  ) : null}
                </div>

                <div className="row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
                  <label
                    htmlFor={`ctx-${conn.id}`}
                    style={{ margin: 0, minWidth: 88 }}
                  >
                    Working in
                  </label>
                  <select
                    id={`ctx-${conn.id}`}
                    value={conn.context_id || ''}
                    disabled={busy === conn.id}
                    onChange={async (event) => {
                      setBusy(conn.id)
                      try {
                        await api.setConnectionContext(conn.id, event.target.value)
                        await load()
                        toast('Client moved')
                      } catch (err) {
                        toast(err.message, 'error')
                      } finally {
                        setBusy('')
                      }
                    }}
                    style={{ width: 'auto', minWidth: 220 }}
                  >
                    <option value="" disabled>
                      Not set — the agent will ask
                    </option>
                    {contexts.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>

                  <div className="topbar-spacer" />
                  <button
                    className="btn danger sm"
                    onClick={async () => {
                      if (
                        !window.confirm(
                          `Revoke "${conn.label}"? It loses access until you reconnect it.`
                        )
                      )
                        return
                      try {
                        await api.revokeConnection(conn.id)
                        await load()
                        toast('Connection revoked')
                      } catch (err) {
                        toast(err.message, 'error')
                      }
                    }}
                  >
                    Revoke
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {active.length > 0 ? (
        <div style={{ marginTop: 24 }}>
          <ConnectGuide compact />
        </div>
      ) : null}

      {revoked.length ? (
        <div className="card" style={{ marginTop: 24 }}>
          <div className="card-head">
            <h2>Revoked</h2>
          </div>
          <div className="list">
            {revoked.map((c) => (
              <div className="item" key={c.id}>
                <span className="sub">{c.label || c.id}</span>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}
