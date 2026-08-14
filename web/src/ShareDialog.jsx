/* The share dialog: two independent dials, as in Google Docs.
 *
 *   1. General access — restricted (invited people only) or anyone with the link
 *   2. Per person     — view / edit / manage, where only manage can re-share
 *
 * The link dial deliberately offers no "manage" option, because the server
 * refuses it: a link that granted the right to re-share would propagate access
 * nobody chose. The copy says so rather than leaving the absence unexplained.
 */
import { useEffect, useState } from 'react'

import { api } from './api.js'
import { Dialog, Spinner, accessLabel } from './components.jsx'

const PERSON_LEVELS = [
  ['view', 'Viewer'],
  ['edit', 'Editor'],
  ['manage', 'Manager'],
]

export default function ShareDialog({
  context,
  verified,
  onClose,
  onChanged,
  toast,
}) {
  const [state, setState] = useState(null)
  const [email, setEmail] = useState('')
  const [access, setAccess] = useState('edit')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setState(await api.shares(context.id))
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [context.id])

  const act = async (fn, successMessage) => {
    setBusy(true)
    setError('')
    try {
      const result = await fn()
      await load()
      onChanged?.()
      if (successMessage) toast(successMessage)
      return result
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const invite = async (event) => {
    event.preventDefault()
    const address = email.trim()
    if (!address) return
    const result = await act(() => api.share(context.id, address, access))
    if (result) {
      setEmail('')
      toast(
        result.invited
          ? `Invite created for ${address}`
          : `${address} now has ${access} access`
      )
      if (result.invited && result.invite_link) {
        // Email delivery can be unavailable (unverified sending domain), so the
        // link is surfaced rather than assumed to have arrived.
        setState((s) => ({ ...s, lastInviteLink: result.invite_link }))
      }
    }
  }

  if (!state && !error) {
    return (
      <Dialog title="Share" onClose={onClose}>
        <div className="row">
          <Spinner /> <span className="sub">Loading access…</span>
        </div>
      </Dialog>
    )
  }

  const canShare = state?.can_share
  const link = state?.link || { access: 'none', url: '' }

  return (
    <Dialog
      title={`Share "${context.name}"`}
      onClose={onClose}
      footer={
        <button className="btn primary" onClick={onClose}>
          Done
        </button>
      }
    >
      {error ? <div className="notice error">{error}</div> : null}

      {!canShare ? (
        <div className="notice warn" style={{ marginBottom: 20 }}>
          You have {accessLabel(context.role)} access here, so you can see who
          this context is shared with but cannot change it. Ask an owner or
          manager.
        </div>
      ) : null}

      {canShare && !verified ? (
        // can_share is about role, not about the account. Owning a context no
        // longer needs a verified address, so an owner can reach this form and
        // be answered with a 403 the API flattens to the bare word "forbidden"
        // (app/main.py). Say what is blocked, and what isn't, before the click.
        <div className="notice warn" style={{ marginBottom: 20 }}>
          Sending an invite email needs a verified address — the link is in your
          inbox. The share link further down works now, so a link is the way to
          let someone in meanwhile.
        </div>
      ) : null}

      {canShare ? (
        <form onSubmit={invite} style={{ marginBottom: 24 }}>
          <label htmlFor="share-email">Invite by email</label>
          <div className="row" style={{ alignItems: 'stretch' }}>
            <input
              id="share-email"
              type="email"
              placeholder="person@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="off"
            />
            <select
              value={access}
              onChange={(e) => setAccess(e.target.value)}
              style={{ width: 'auto', minWidth: 118 }}
              aria-label="Access level"
            >
              {PERSON_LEVELS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <button
              className="btn primary"
              disabled={busy || !email.trim() || !verified}
            >
              Invite
            </button>
          </div>
          {state?.lastInviteLink ? (
            <div className="notice" style={{ marginTop: 12 }}>
              Send them this link if the email doesn’t arrive:
              <div className="link-copy">
                <input readOnly value={state.lastInviteLink} />
                <button
                  type="button"
                  className="btn sm"
                  onClick={() => copy(state.lastInviteLink, toast)}
                >
                  Copy
                </button>
              </div>
            </div>
          ) : null}
        </form>
      ) : null}

      <h3 style={{ marginBottom: 4 }}>People with access</h3>
      <div className="list" style={{ marginBottom: 24 }}>
        {(state?.members || []).map((m) => (
          <div className="access-row" key={m.user_id}>
            <div className="who">
              <div className="email">{m.email}</div>
              {m.display_name && m.display_name !== m.email ? (
                <div className="tiny">{m.display_name}</div>
              ) : null}
            </div>
            {m.role === 'owner' ? (
              <span className="badge owner">Owner</span>
            ) : canShare ? (
              <>
                <select
                  value={m.access}
                  onChange={(e) =>
                    act(
                      () => api.changeAccess(context.id, m.user_id, e.target.value),
                      `${m.email} is now ${e.target.value}`
                    )
                  }
                  disabled={busy}
                  aria-label={`Access for ${m.email}`}
                >
                  {PERSON_LEVELS.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
                <button
                  className="btn danger sm"
                  disabled={busy}
                  onClick={() =>
                    act(
                      () => api.revokeAccess(context.id, m.user_id),
                      `Removed ${m.email}`
                    )
                  }
                >
                  Remove
                </button>
              </>
            ) : (
              <span className="badge">{m.access}</span>
            )}
          </div>
        ))}
      </div>

      {(state?.pending_invites || []).length ? (
        <>
          <h3 style={{ marginBottom: 4 }}>Pending invites</h3>
          <div className="list" style={{ marginBottom: 24 }}>
            {state.pending_invites.map((i) => (
              <div className="access-row" key={i.id}>
                <div className="who">
                  <div className="email">{i.email}</div>
                  <div className="tiny">invited as {i.access}</div>
                </div>
                <span className="badge">awaiting</span>
              </div>
            ))}
          </div>
        </>
      ) : null}

      <h3 style={{ marginBottom: 8 }}>General access</h3>
      <div className="link-panel">
        <div className="row">
          <select
            value={link.access}
            onChange={(e) =>
              act(
                () => api.setLink(context.id, e.target.value),
                e.target.value === 'none'
                  ? 'Link sharing turned off'
                  : `Anyone with the link can ${e.target.value}`
              )
            }
            disabled={!canShare || busy}
            style={{ width: 'auto' }}
            aria-label="Link access"
          >
            <option value="none">Restricted — invited people only</option>
            <option value="view">Anyone with the link can view</option>
            <option value="edit">Anyone with the link can edit</option>
          </select>
        </div>

        <p className="tiny" style={{ margin: '10px 0 0' }}>
          {link.access === 'none'
            ? 'Only people invited above can open this context.'
            : 'A link can grant view or edit, never manage — so it can never pass on the ability to share.'}
        </p>

        {link.url ? (
          <>
            <div className="link-copy">
              <input readOnly value={link.url} aria-label="Share link" />
              <button className="btn sm" onClick={() => copy(link.url, toast)}>
                Copy
              </button>
            </div>
            {canShare ? (
              <button
                className="btn ghost sm"
                style={{ marginTop: 8 }}
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      'Replace the link? Everyone still holding the old one loses access. People who already joined keep theirs.'
                    )
                  )
                    act(() => api.rotateLink(context.id), 'New link generated')
                }}
              >
                Generate a new link
              </button>
            ) : null}
          </>
        ) : link.access !== 'none' && !canShare ? (
          <p className="tiny" style={{ margin: '8px 0 0' }}>
            This context is link-shared. Only owners and managers can see the
            link itself.
          </p>
        ) : null}
      </div>

      <OrgSection
        context={context}
        state={state}
        canShare={canShare}
        busy={busy}
        act={act}
      />
    </Dialog>
  )
}

/* The third dial: everyone in the organisation that owns this context.
 *
 * Same rule as the link dial, for the same reason — it can grant view or edit,
 * never manage, so group membership can never pass on the ability to share. */
function OrgSection({ context, state, canShare, busy, act }) {
  const org = state?.org || { id: null, name: '', access: 'none' }
  const yourOrgs = state?.your_orgs || []
  const isOwner = state?.your_role === 'owner'

  if (!org.id && !yourOrgs.length) return null

  return (
    <>
      <h3 style={{ margin: '24px 0 8px' }}>Organisation</h3>
      <div className="link-panel">
        {org.id ? (
          <>
            <p className="tiny" style={{ margin: '0 0 10px' }}>
              Owned by <strong>{org.name}</strong>.
            </p>
            <div className="row">
              <select
                value={org.access}
                onChange={(e) =>
                  act(
                    () => api.setContextOrgAccess(context.id, e.target.value),
                    e.target.value === 'none'
                      ? 'Organisation access turned off'
                      : `Everyone in ${org.name} can ${e.target.value}`
                  )
                }
                disabled={!canShare || busy}
                style={{ width: 'auto' }}
                aria-label="Organisation access"
              >
                <option value="none">No access — invited people only</option>
                <option value="view">Everyone in the organisation can view</option>
                <option value="edit">Everyone in the organisation can edit</option>
              </select>
            </div>
            <p className="tiny" style={{ margin: '10px 0 0' }}>
              {org.access === 'none'
                ? 'Belonging to the organisation grants nothing here on its own.'
                : 'Applies to everyone in the organisation, now and as people join. Like a link, it can never grant manage.'}
            </p>
            {isOwner ? (
              <button
                className="btn ghost sm"
                style={{ marginTop: 10 }}
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      `Remove this context from ${org.name}? People who only had access through the organisation will lose it. Anyone invited individually keeps theirs.`
                    )
                  )
                    act(
                      () => api.setContextOrg(context.id, null),
                      'Context is personal again'
                    )
                }}
              >
                Remove from {org.name}
              </button>
            ) : null}
          </>
        ) : (
          <>
            <p className="tiny" style={{ margin: '0 0 10px' }}>
              This context belongs to you personally. Moving it into an
              organisation lets you grant its whole group access at once.
            </p>
            <div className="row">
              <select
                defaultValue=""
                disabled={busy}
                style={{ width: 'auto', minWidth: 200 }}
                aria-label="Move into organisation"
                onChange={(e) => {
                  if (!e.target.value) return
                  const chosen = yourOrgs.find((o) => o.id === e.target.value)
                  act(
                    () => api.setContextOrg(context.id, e.target.value),
                    `Moved into ${chosen?.name || 'the organisation'}`
                  )
                }}
              >
                <option value="">Move into an organisation…</option>
                {yourOrgs.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
            <p className="tiny" style={{ margin: '10px 0 0' }}>
              Moving it in grants nobody anything by itself — you choose the
              access level afterwards.
            </p>
          </>
        )}
      </div>
    </>
  )
}

async function copy(text, toast) {
  try {
    await navigator.clipboard.writeText(text)
    toast('Copied to clipboard')
  } catch {
    toast('Press Ctrl+C to copy', 'error')
  }
}
