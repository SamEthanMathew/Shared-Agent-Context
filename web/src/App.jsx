import { useCallback, useEffect, useState } from 'react'

import { api } from './api.js'
import {
  ContextSwitcher,
  Dialog,
  Loading,
  Mark,
  Toasts,
  useToasts,
} from './components.jsx'
import ContextView from './views/ContextView.jsx'
import ContextsView from './views/ContextsView.jsx'
import ClientsView from './views/ClientsView.jsx'
import OrgsView from './views/OrgsView.jsx'
import { Link, contextIdFrom, useRoute } from './router.jsx'

export default function App() {
  const { path, navigate } = useRoute()
  const { items: toasts, push } = useToasts()

  const [me, setMe] = useState(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setMe(await api.me())
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  if (error) {
    return (
      <div className="page">
        <div className="notice error">{error}</div>
      </div>
    )
  }
  if (!me) return <Loading label="Loading your contexts" />

  const activeId = contextIdFrom(path)
  const contexts = me.contexts || []

  return (
    <div className="shell">
      <header className="topbar">
        <Link to="/" navigate={navigate} className="brand">
          <Mark />
          <span>Osmos</span>
        </Link>

        <ContextSwitcher
          contexts={contexts}
          activeId={activeId}
          onSelect={(c) => navigate(`/c/${c.id}`)}
          onCreate={() => setCreating(true)}
        />

        <div className="topbar-spacer" />

        <Link to="/orgs" navigate={navigate} className="btn ghost sm">
          Organisations
        </Link>
        <Link to="/clients" navigate={navigate} className="btn ghost sm">
          AI clients
        </Link>
        <span className="tiny" style={{ marginLeft: 4 }}>
          {me.user.email}
        </span>
        <form method="post" action="/auth/logout" style={{ margin: 0 }}>
          <button className="btn ghost sm" type="submit">
            Sign out
          </button>
        </form>
      </header>

      {!me.user.email_verified ? (
        <div className="page" style={{ padding: '16px 24px 0' }}>
          <div className="notice warn">
            Check your inbox to verify <strong>{me.user.email}</strong>. Until
            you do, you can read shared contexts but not create one or accept a
            share.
          </div>
        </div>
      ) : null}

      {activeId ? (
        <ContextView
          key={activeId}
          contextId={activeId}
          me={me}
          navigate={navigate}
          toast={push}
          onChanged={refresh}
        />
      ) : path === '/clients' ? (
        <ClientsView contexts={contexts} toast={push} navigate={navigate} />
      ) : path === '/orgs' ? (
        <OrgsView navigate={navigate} toast={push} onChanged={refresh} />
      ) : (
        <ContextsView
          me={me}
          navigate={navigate}
          toast={push}
          onChanged={refresh}
          onCreate={() => setCreating(true)}
        />
      )}

      {creating ? (
        <CreateContextDialog
          verified={me.user.email_verified}
          onClose={() => setCreating(false)}
          onCreated={async (id) => {
            setCreating(false)
            await refresh()
            navigate(`/c/${id}`)
            push('Context created')
          }}
          toast={push}
        />
      ) : null}

      <Toasts items={toasts} />
    </div>
  )
}

function CreateContextDialog({ verified, onClose, onCreated, toast }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const result = await api.createContext(name.trim(), description.trim())
      // The endpoint answers with the context it just switched to.
      const id = result.active_context?.id
      if (!id) throw new Error('The server did not return the new context')
      onCreated(id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="New shared context"
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={submit}
            disabled={busy || !name.trim() || !verified}
          >
            {busy ? 'Creating…' : 'Create'}
          </button>
        </>
      }
    >
      {!verified ? (
        <div className="notice warn" style={{ marginBottom: 16 }}>
          Verify your email address first — the link is in your inbox.
        </div>
      ) : null}
      {error ? (
        <div className="notice error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      ) : null}
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="ctx-name">Name</label>
          <input
            id="ctx-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Desktop App"
            autoFocus
          />
        </div>
        <div className="field">
          <label htmlFor="ctx-desc">What is it for? (optional)</label>
          <input
            id="ctx-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Everything the team decides about the desktop client"
          />
        </div>
        <p className="tiny">
          You’ll be its owner. Everyone you share it with works from the same
          continuously updated knowledge, whichever AI client they use.
        </p>
      </form>
    </Dialog>
  )
}
