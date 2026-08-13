/* Organisations — a group of people who share contexts.
 *
 * The distinction this screen has to make legible: administering a group is not
 * the same as being able to read what is inside it. An org admin sees every
 * context here, with the access level each one grants, and can read none of them
 * unless that level or an individual invitation says so. The copy states it
 * rather than leaving it to be discovered.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from '../api.js'
import BillingPanel from '../BillingPanel.jsx'
import { Dialog, Loading } from '../components.jsx'
import { Link } from '../router.jsx'

const ORG_ROLES = [
  ['member', 'Member'],
  ['admin', 'Admin'],
  ['owner', 'Owner'],
]

export default function OrgsView({ navigate, toast, onChanged }) {
  const [orgs, setOrgs] = useState(null)
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const out = await api.orgs()
      setOrgs(out.orgs)
      setSelected((current) => current || out.orgs[0]?.id || null)
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (error)
    return (
      <div className="page">
        <div className="notice error">{error}</div>
      </div>
    )
  if (!orgs) return <Loading label="Loading organisations" />

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Organisations</h1>
          <p className="sub">
            A group of people who share contexts. Everyone in an organisation can
            be given access to its contexts at once, instead of one invitation at
            a time.
          </p>
        </div>
        <button className="btn primary" onClick={() => setCreating(true)}>
          New organisation
        </button>
      </div>

      {orgs.length === 0 ? (
        <div className="empty">
          <h2>You’re not in an organisation yet</h2>
          <p>
            Create one if you work with the same group of people across several
            contexts. If you only share the occasional context, invitations and
            share links are simpler.
          </p>
          <button className="btn primary" onClick={() => setCreating(true)}>
            Create an organisation
          </button>
        </div>
      ) : (
        <>
          {orgs.length > 1 ? (
            <div className="tabs" role="tablist">
              {orgs.map((o) => (
                <button
                  key={o.id}
                  className="tab"
                  role="tab"
                  aria-selected={o.id === selected}
                  onClick={() => setSelected(o.id)}
                >
                  {o.name}
                </button>
              ))}
            </div>
          ) : null}
          {selected ? (
            <OrgDetail
              key={selected}
              orgId={selected}
              navigate={navigate}
              toast={toast}
              onChanged={async () => {
                await load()
                await onChanged?.()
              }}
            />
          ) : null}
        </>
      )}

      {creating ? (
        <CreateOrgDialog
          onClose={() => setCreating(false)}
          onCreated={async (id) => {
            setCreating(false)
            await load()
            setSelected(id)
            toast('Organisation created')
          }}
        />
      ) : null}
    </div>
  )
}

function OrgDetail({ orgId, navigate, toast, onChanged }) {
  const [detail, setDetail] = useState(null)
  const [email, setEmail] = useState('')
  const [orgRole, setOrgRole] = useState('member')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setDetail(await api.org(orgId))
    } catch (err) {
      setError(err.message)
    }
  }, [orgId])

  useEffect(() => {
    load()
  }, [load])

  const act = async (fn, successMessage) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
      await onChanged?.()
      if (successMessage) toast(successMessage)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (error) return <div className="notice error">{error}</div>
  if (!detail) return <Loading label="Loading organisation" />

  const canAdmin = detail.your_role === 'owner' || detail.your_role === 'admin'

  return (
    <div className="stack">
      <div className="card">
        <div className="card-head">
          <h2>People</h2>
          <span className="badge">{detail.your_role}</span>
        </div>

        {canAdmin ? (
          <form
            style={{ marginBottom: 20 }}
            onSubmit={(event) => {
              event.preventDefault()
              const address = email.trim()
              if (!address) return
              act(
                () => api.addOrgMember(orgId, address, orgRole),
                `${address} added`
              ).then(() => setEmail(''))
            }}
          >
            <label htmlFor="org-email">Add someone</label>
            <div className="row" style={{ alignItems: 'stretch' }}>
              <input
                id="org-email"
                type="email"
                placeholder="person@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="off"
              />
              <select
                value={orgRole}
                onChange={(e) => setOrgRole(e.target.value)}
                style={{ width: 'auto', minWidth: 112 }}
                aria-label="Organisation role"
              >
                {ORG_ROLES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
              <button className="btn primary" disabled={busy || !email.trim()}>
                Add
              </button>
            </div>
            <p className="tiny" style={{ margin: '8px 0 0' }}>
              They need a verified Osmos account first. Adding someone gives them
              whatever access each context below already grants — nothing more.
            </p>
          </form>
        ) : null}

        <div className="list">
          {detail.members.map((m) => (
            <div className="access-row" key={m.user_id}>
              <div className="who">
                <div className="email">{m.email}</div>
                {m.display_name && m.display_name !== m.email ? (
                  <div className="tiny">{m.display_name}</div>
                ) : null}
              </div>
              <span className={m.org_role === 'owner' ? 'badge owner' : 'badge'}>
                {m.org_role}
              </span>
              {canAdmin && m.org_role !== 'owner' ? (
                <button
                  className="btn danger sm"
                  disabled={busy}
                  onClick={() => {
                    if (
                      !window.confirm(
                        `Remove ${m.email}? They lose access granted through this organisation. Contexts they were invited to individually are unaffected.`
                      )
                    )
                      return
                    act(
                      () => api.removeOrgMember(orgId, m.user_id),
                      `Removed ${m.email}`
                    )
                  }}
                >
                  Remove
                </button>
              ) : null}
            </div>
          ))}
        </div>
      </div>

      <BillingPanel orgId={orgId} toast={toast} />

      <div className="card">
        <div className="card-head">
          <h2>Contexts</h2>
        </div>

        {detail.contexts.length === 0 ? (
          <p className="sub" style={{ marginTop: 0 }}>
            No contexts belong to this organisation yet. Open a context you own
            and move it in from its Share dialog.
          </p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Context</th>
                    <th>Everyone here gets</th>
                    <th>Revision</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.contexts.map((ctx) => (
                    <tr key={ctx.id}>
                      <td>
                        <Link to={`/c/${ctx.id}`} navigate={navigate}>
                          {ctx.name}
                        </Link>
                        {ctx.archived ? (
                          <span className="badge" style={{ marginLeft: 8 }}>
                            archived
                          </span>
                        ) : null}
                      </td>
                      <td>
                        {ctx.org_access === 'none' ? (
                          <span className="tiny">nothing — invited people only</span>
                        ) : (
                          ctx.org_access
                        )}
                      </td>
                      <td className="mono tiny">r{ctx.revision}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="tiny" style={{ marginTop: 12 }}>
              Being an organisation admin lets you see which contexts exist and
              how they are shared. It does not let you read them — that still
              needs the access level above, or an invitation of your own.
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function CreateOrgDialog({ onClose, onCreated }) {
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const out = await api.createOrg(name.trim())
      onCreated(out.org.id)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <Dialog
      title="New organisation"
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
      {error ? (
        <div className="notice error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      ) : null}
      <form onSubmit={submit}>
        <div className="field">
          <label htmlFor="org-name">Name</label>
          <input
            id="org-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Inc"
            autoFocus
          />
        </div>
        <p className="tiny">
          You’ll be its owner. Creating an organisation grants nobody access to
          anything — you choose that per context afterwards.
        </p>
      </form>
    </Dialog>
  )
}
