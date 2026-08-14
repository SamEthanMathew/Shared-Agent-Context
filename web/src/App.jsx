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
  const { path, query, navigate } = useRoute()
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

  // Verification happens in whichever tab opened the email, so this one can sit
  // on a stale "unverified" until someone thinks to reload. A failure here is
  // swallowed rather than routed through refresh(): a blip while the tab was in
  // the background must not replace a working screen with the error page.
  useEffect(() => {
    const recheck = () => {
      api.me().then(setMe, () => {})
    }
    window.addEventListener('focus', recheck)
    return () => window.removeEventListener('focus', recheck)
  }, [])

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
          <UnverifiedBanner email={me.user.email} />
        </div>
      ) : null}

      {activeId ? (
        <ContextView
          key={activeId}
          contextId={activeId}
          me={me}
          joined={query.get('joined') === '1'}
          navigate={navigate}
          toast={push}
          onChanged={refresh}
        />
      ) : path === '/clients' ? (
        <ClientsView contexts={contexts} toast={push} navigate={navigate} />
      ) : path === '/orgs' ? (
        <OrgsView
          navigate={navigate}
          toast={push}
          onChanged={refresh}
          verified={me.user.email_verified}
        />
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

/* The banner an unverified account lives under, and the way out of it.
 *
 * The first verification email can bounce, sit in spam, or have been sent to an
 * address with a typo in it; without a resend the only route forward is a
 * second account. Both outcomes are stated here rather than raised as a toast,
 * because this banner is what the question "did that do anything" is asked of.
 */
function UnverifiedBanner({ email }) {
  const [busy, setBusy] = useState(false)
  const [asked, setAsked] = useState(false)
  const [error, setError] = useState('')

  const resend = async () => {
    setBusy(true)
    setError('')
    try {
      await api.resendVerification()
      setAsked(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="notice warn">
        Check your inbox to verify <strong>{email}</strong>. Contexts of your
        own already work, share link and all. Until you verify you cannot send
        email invites, accept an invite or a share link from someone else, or
        create an organisation.
        <div className="row" style={{ marginTop: 10, flexWrap: 'wrap' }}>
          <button className="btn sm" onClick={resend} disabled={busy}>
            {busy ? 'Sending…' : 'Resend verification email'}
          </button>
          {asked ? (
            // Not "Sent", and not "on its way": /auth/verify/resend answers with
            // the same 303-to-200 whether it mailed anything, found no unverified
            // account, or refused the click as too frequent. Nothing in that
            // reply distinguishes them, so this reports the request and no more.
            // The button stays live for the same reason — latching it on a click
            // that sent nothing leaves the only way forward a second account.
            <span className="tiny">
              Asked for a new link to {email}. If one was sent it should arrive
              within a minute or two — check spam, and give it a moment before
              asking again, as only a few resends an hour are accepted. Links
              last 24 hours.
            </span>
          ) : null}
        </div>
      </div>
      {error ? (
        <div className="notice error" style={{ marginTop: 8 }}>
          {error}
        </div>
      ) : null}
    </>
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
            disabled={busy || !name.trim()}
          >
            {busy ? 'Creating…' : 'Create'}
          </button>
        </>
      }
    >
      {!verified ? (
        // Creating your own context no longer waits on verification, and neither
        // does putting a link on it. Naming the three things that do beats the
        // old blanket "sharing needs verification", which sent people to their
        // inbox for something they could already do.
        <div className="notice warn" style={{ marginBottom: 16 }}>
          Go ahead — this one is yours to make, and you can put a share link on
          it straight away. Email invites, accepting someone else’s invite or
          link, and organisations are what wait on a verified address; the link
          is in your inbox.
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
