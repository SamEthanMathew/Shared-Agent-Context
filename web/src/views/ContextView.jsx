/* One context: what the agents know, who can see it, what happened, and what
 * was actually sent to a model.
 *
 * The last tab is the point of the product's privacy claim, so it is a
 * first-class view rather than a debug page: it shows what each sync included
 * and what it withheld.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from '../api.js'
import {
  Dialog,
  Loading,
  accessLabel,
  describeAction,
  when,
} from '../components.jsx'
import ShareDialog from '../ShareDialog.jsx'

const TABS = [
  ['memory', 'Memory'],
  ['people', 'People'],
  ['activity', 'Activity'],
  ['sent', 'What AI saw'],
]

export default function ContextView({ contextId, me, navigate, toast, onChanged }) {
  const [tab, setTab] = useState('memory')
  const [sharing, setSharing] = useState(false)
  const [info, setInfo] = useState(null)
  const [error, setError] = useState('')

  const context = (me.contexts || []).find((c) => c.id === contextId)

  useEffect(() => {
    api.context(contextId).then(setInfo).catch((err) => setError(err.message))
  }, [contextId])

  if (error) {
    return (
      <div className="page">
        <div className="notice error">{error}</div>
        <p style={{ marginTop: 16 }}>
          <button className="btn" onClick={() => navigate('/')}>
            Back to your contexts
          </button>
        </p>
      </div>
    )
  }
  if (!context || !info) return <Loading label="Opening context" />

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>{context.name}</h1>
          <p className="sub">
            <span className="mono">r{context.revision}</span>
            {' · your access: '}
            {accessLabel(context.role)}
            {' · '}
            {context.member_count}{' '}
            {context.member_count === 1 ? 'member' : 'members'}
          </p>
        </div>
        <button className="btn" onClick={() => setSharing(true)}>
          Share
        </button>
        {context.role === 'owner' ? (
          <button
            className="btn ghost"
            onClick={async () => {
              if (
                !window.confirm(
                  `Archive "${context.name}"? It disappears for everyone and agents stop seeing it. Memory is kept and you can restore it.`
                )
              )
                return
              try {
                await api.archive(contextId)
                await onChanged()
                toast('Context archived')
                navigate('/')
              } catch (err) {
                toast(err.message, 'error')
              }
            }}
          >
            Archive
          </button>
        ) : null}
      </div>

      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button
            key={key}
            className="tab"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'memory' ? (
        <MemoryTab context={context} me={me} toast={toast} />
      ) : null}
      {tab === 'people' ? (
        <PeopleTab context={context} onShare={() => setSharing(true)} />
      ) : null}
      {tab === 'activity' ? <ActivityTab context={context} /> : null}
      {tab === 'sent' ? <SentTab context={context} /> : null}

      {sharing ? (
        <ShareDialog
          context={context}
          onClose={() => setSharing(false)}
          onChanged={onChanged}
          toast={toast}
        />
      ) : null}
    </div>
  )
}

/* --- memory --------------------------------------------------------------- */

function MemoryTab({ context, me, toast }) {
  const [memories, setMemories] = useState(null)
  const [scope, setScope] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      const out = await api.memories(context.id, { scope: scope || undefined })
      setMemories(out.memories)
    } catch (err) {
      setError(err.message)
    }
  }, [context.id, scope])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <div className="notice error">{error}</div>
  if (!memories) return <Loading label="Reading memory" />

  const canWrite = context.role !== 'viewer'

  return (
    <>
      <div className="row" style={{ marginBottom: 16 }}>
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          style={{ width: 'auto' }}
          aria-label="Filter by scope"
        >
          <option value="">Shared and your private</option>
          <option value="shared">Shared only</option>
          <option value="private">Your private only</option>
        </select>
        <div className="topbar-spacer" />
        <span className="tiny">
          {memories.length} {memories.length === 1 ? 'memory' : 'memories'}
        </span>
      </div>

      {memories.length === 0 ? (
        <div className="empty">
          <h2>Nothing here yet</h2>
          <p>
            Memory arrives when an agent publishes something durable — a
            decision, a requirement, a finding. Connect an AI client and start a
            conversation.
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="list">
            {memories.map((m) => (
              <MemoryRow
                key={m.id}
                memory={m}
                context={context}
                me={me}
                canWrite={canWrite}
                onRetracted={async () => {
                  await load()
                  toast('Memory retracted')
                }}
                toast={toast}
              />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function MemoryRow({ memory, context, me, canWrite, onRetracted, toast }) {
  const mine = memory.provenance?.created_by_user_id === me.user.id
  return (
    <div className="item">
      <div className="item-head">
        <span className="badge">{memory.kind}</span>
        {memory.scope === 'private' ? (
          <span className="badge scope-private">private</span>
        ) : null}
        {/* Knowledge that moved: published by someone else's agent, now here. */}
        {!mine && memory.scope === 'shared' ? (
          <span className="badge handoff">from a teammate</span>
        ) : null}
        <span className="badge rev">r{memory.revision}</span>
        <div className="topbar-spacer" />
        {canWrite ? (
          <button
            className="btn danger sm"
            onClick={async () => {
              if (!window.confirm('Retract this? Agents stop seeing it.')) return
              try {
                await api.retract(context.id, memory.id)
                onRetracted()
              } catch (err) {
                toast(err.message, 'error')
              }
            }}
          >
            Retract
          </button>
        ) : null}
      </div>
      <div>{memory.summary}</div>
      {memory.details ? (
        <div className="tiny" style={{ marginTop: 6, whiteSpace: 'pre-wrap' }}>
          {memory.details}
        </div>
      ) : null}
      <div className="tiny" style={{ marginTop: 8 }}>
        {memory.tags?.length ? `${memory.tags.join(' · ')} — ` : ''}
        {when(memory.provenance?.created_at)}
      </div>
    </div>
  )
}

/* --- people --------------------------------------------------------------- */

function PeopleTab({ context, onShare }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.shares(context.id).then(setState).catch((e) => setError(e.message))
  }, [context.id])

  if (error) return <div className="notice error">{error}</div>
  if (!state) return <Loading label="Reading access" />

  return (
    <div className="card">
      <div className="card-head">
        <h2>Who can see this context</h2>
        <button className="btn sm" onClick={onShare}>
          Manage sharing
        </button>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Person</th>
              <th>Access</th>
              <th>Can re-share</th>
            </tr>
          </thead>
          <tbody>
            {state.members.map((m) => (
              <tr key={m.user_id}>
                <td>{m.email}</td>
                <td>{m.access}</td>
                <td className="tiny">
                  {m.role === 'owner' || m.role === 'admin' ? 'yes' : 'no'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="tiny" style={{ marginTop: 16 }}>
        {state.link?.access === 'none'
          ? 'Restricted: only the people listed here can open it.'
          : `Anyone with the link can ${state.link.access}.`}
      </p>
    </div>
  )
}

/* --- activity ------------------------------------------------------------- */

function ActivityTab({ context }) {
  const [events, setEvents] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .activity(context.id)
      .then((out) => setEvents(out.events))
      .catch((e) => setError(e.message))
  }, [context.id])

  if (error) return <div className="notice error">{error}</div>
  if (!events) return <Loading label="Reading activity" />
  if (!events.length)
    return (
      <div className="empty">
        <h2>No activity yet</h2>
        <p>Sharing, access changes, and archiving all show up here.</p>
      </div>
    )

  return (
    <div className="card">
      <div className="list">
        {events.map((e) => (
          <div className="item" key={e.id}>
            <div className="row">
              <span className="grow">
                <strong style={{ fontWeight: 500 }}>{e.actor}</strong>{' '}
                {describeAction(e)}
              </span>
              <span className="tiny">{when(e.created_at)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* --- what AI saw ---------------------------------------------------------- */

function SentTab({ context }) {
  const [snaps, setSnaps] = useState(null)
  const [open, setOpen] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .snapshots(context.id)
      .then((out) => setSnaps(out.snapshots))
      .catch((e) => setError(e.message))
  }, [context.id])

  if (error) return <div className="notice error">{error}</div>
  if (!snaps) return <Loading label="Reading sync records" />

  return (
    <>
      <div className="notice" style={{ marginBottom: 16 }}>
        One row per sync: exactly what was compiled into your agent’s context,
        and what was held back. These records are yours alone — not even an owner
        can read someone else’s, because they enumerate private memory.
      </div>

      {snaps.length === 0 ? (
        <div className="empty">
          <h2>No syncs recorded</h2>
          <p>
            When one of your AI clients pulls this context, what it received is
            recorded here.
          </p>
        </div>
      ) : (
        <div className="card">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Revision</th>
                  <th>Included</th>
                  <th>Withheld</th>
                  <th>Tokens</th>
                  <th>When</th>
                </tr>
              </thead>
              <tbody>
                {snaps.map((s) => (
                  <tr
                    key={s.id}
                    onClick={() => setOpen(s)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td>
                      {s.task || <span className="tiny">—</span>}
                      {/* The row worth opening. Without it, a sync that had to
                       * leave memory out looks exactly like one that did not. */}
                      {s.truncated ? (
                        <span className="badge" style={{ marginLeft: 8 }}>
                          cut short
                        </span>
                      ) : null}
                    </td>
                    <td className="mono">r{s.project_revision}</td>
                    <td>{s.included_count}</td>
                    <td>
                      {s.withheld_private ? (
                        <span title="Other members' private memory, never named">
                          {s.withheld_private} private
                        </span>
                      ) : (
                        <span className="tiny">none</span>
                      )}
                    </td>
                    <td className="tiny">{s.token_estimate}</td>
                    <td className="tiny">{when(s.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {open ? (
        <SnapshotDialog
          contextId={context.id}
          snapshot={open}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </>
  )
}

function SnapshotDialog({ contextId, snapshot, onClose }) {
  const [detail, setDetail] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .snapshot(contextId, snapshot.id)
      .then(setDetail)
      .catch((e) => setError(e.message))
  }, [contextId, snapshot.id])

  return (
    <Dialog title={snapshot.task || 'Sync record'} onClose={onClose}>
      {error ? <div className="notice error">{error}</div> : null}
      {!detail && !error ? <Loading label="Loading manifest" /> : null}
      {detail ? (
        <>
          <p className="tiny" style={{ marginTop: 0 }}>
            <span className="mono">r{detail.snapshot.project_revision}</span>
            {` · ~${detail.snapshot.token_estimate} of `}
            {detail.snapshot.budget_tokens} tokens ·{' '}
            {when(detail.snapshot.created_at)}
          </p>

          <Funnel funnel={detail.snapshot.funnel} />

          <h3 style={{ marginBottom: 8 }}>
            Included ({detail.included.length})
          </h3>
          <ManifestList entries={detail.included} emptyLabel="Nothing included" />

          <h3 style={{ margin: '20px 0 8px' }}>
            Withheld ({detail.withheld.length})
          </h3>
          <ManifestList entries={detail.withheld} emptyLabel="Nothing withheld" />
        </>
      ) : null}
    </Dialog>
  )
}

/* Where the memory went — the funnel the compiler recorded for this sync.
 *
 * The lists below say what got in and what was named as withheld. This says
 * what happened to everything else: how much was considered, how much was never
 * this person's to see, how much lost its place in ranking, how much had faded,
 * and how much simply did not fit. Rows that are zero are left out, and a
 * snapshot recorded before the compiler counted any of this renders nothing at
 * all — an empty funnel is silence, not a wall of confident zeroes.
 */
function Funnel({ funnel }) {
  if (!funnel || !Object.keys(funnel).length) return null
  const shown = funnel.resolutions || {}
  const stages = [
    ['Considered', funnel.candidates_considered],
    // Other members' private memory. A count, never a name — the server never
    // sends the ids, and this must never become the place they appear.
    ['Not yours to see', funnel.filtered_permission],
    ['Outranked', funnel.dropped_ranking],
    ['Repeated something already included', funnel.dropped_redundant],
    ['Faded with age', funnel.omitted_faded],
    ['Did not fit the budget', funnel.dropped_budget],
    ['Shown in full', shown.full],
    ['Shown as one line', shown.summary],
    ['Shown as a trace', shown.trace],
  ].filter(([, count]) => count)

  return (
    <>
      {funnel.budget_unsatisfiable ? (
        <div className="notice warn" style={{ marginBottom: 12 }}>
          This sync was refused rather than cut down: the task and the memories
          in unresolved conflict needed about {funnel.required_tokens} tokens,
          and those are never dropped quietly. The agent was told to ask again
          with a larger budget.
        </div>
      ) : null}
      {stages.length ? (
        <div className="list" style={{ marginBottom: 20 }}>
          {stages.map(([label, count]) => (
            <div className="item row" key={label} style={{ padding: '6px 0' }}>
              <span className="grow tiny">{label}</span>
              <span className="mono">{count}</span>
            </div>
          ))}
        </div>
      ) : null}
    </>
  )
}

function ManifestList({ entries, emptyLabel }) {
  if (!entries.length) return <p className="tiny">{emptyLabel}</p>
  return (
    <div className="list">
      {entries.map((entry, i) => (
        <div
          className="item"
          key={entry.memory_id || `agg-${i}`}
          style={{ padding: '10px 0' }}
        >
          {entry.aggregate ? (
            // Deliberately unnamed: other people's private memory is reported as
            // a count and nothing more.
            <div className="sub">
              {entry.count} × {entry.detail.replace(/_/g, ' ')}
            </div>
          ) : (
            <>
              <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
                {entry.kind ? <span className="badge">{entry.kind}</span> : null}
                <span className="grow">
                  {entry.summary || (
                    <span className="tiny">(no longer visible to you)</span>
                  )}
                </span>
                {entry.detail ? (
                  <span className="tiny">{entry.detail}</span>
                ) : null}
              </div>
            </>
          )}
        </div>
      ))}
    </div>
  )
}
