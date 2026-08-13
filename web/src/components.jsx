/* Shared pieces: brand mark, switcher, dialog, toasts, small formatters. */
import { useEffect, useRef, useState } from 'react'

/* The Osmos mark: a persistent white axis (the shared project layer) crossed by
 * five violet-to-cyan streams (independent people and agents) converging. Drawn
 * inline so it needs no network request and inherits the page colours. */
export function Mark({ size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <defs>
        <linearGradient id="osmos-flow" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="#B02EFF" />
          <stop offset="25%" stopColor="#8A4DFF" />
          <stop offset="50%" stopColor="#6666FF" />
          <stop offset="75%" stopColor="#3E8CFF" />
          <stop offset="100%" stopColor="#30C4F4" />
        </linearGradient>
      </defs>
      {[4, 8, 12, 16, 20].map((x, i) => (
        <path
          key={x}
          d={`M${x} ${4 + (i % 2) * 1.5}C${x} 9 ${x} 15 ${x} ${20 - (i % 2) * 1.5}`}
          stroke="url(#osmos-flow)"
          strokeWidth="1.8"
          strokeLinecap="round"
          fill="none"
        />
      ))}
      <path
        d="M2 12H22"
        stroke="#F7FAFF"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  )
}

export function Spinner() {
  return <span className="spinner" />
}

export function Loading({ label = 'Loading' }) {
  return (
    <div className="loading-page">
      <Spinner />
      <span>{label}…</span>
    </div>
  )
}

/** Close a popover on outside click and on Escape. */
export function useDismiss(open, close) {
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const onDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) close()
    }
    const onKey = (event) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open, close])
  return ref
}

export function Dialog({ title, onClose, children, footer }) {
  const ref = useDismiss(true, onClose)
  return (
    <div className="scrim">
      <div className="dialog" ref={ref} role="dialog" aria-modal="true">
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="btn ghost sm" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="dialog-body">{children}</div>
        {footer ? <div className="dialog-foot">{footer}</div> : null}
      </div>
    </div>
  )
}

export function Toasts({ items }) {
  if (!items.length) return null
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={t.kind === 'error' ? 'toast error' : 'toast'}>
          {t.message}
        </div>
      ))}
    </div>
  )
}

export function useToasts() {
  const [items, setItems] = useState([])
  const push = (message, kind = 'ok') => {
    const id = Math.random().toString(36).slice(2)
    setItems((current) => [...current, { id, message, kind }])
    setTimeout(
      () => setItems((current) => current.filter((t) => t.id !== id)),
      kind === 'error' ? 5200 : 2800
    )
  }
  return { items, push }
}

/** The header control that answers "which context am I in" and switches it. */
export function ContextSwitcher({ contexts, activeId, onSelect, onCreate }) {
  const [open, setOpen] = useState(false)
  const ref = useDismiss(open, () => setOpen(false))
  const active = contexts.find((c) => c.id === activeId)

  return (
    <div className="switcher" ref={ref}>
      <button
        className="switcher-btn"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="live-dot" />
        <span className="name">{active ? active.name : 'Choose a context'}</span>
        <span className="caret">▾</span>
      </button>

      {open ? (
        <div className="menu" role="listbox">
          <div className="menu-label">Shared contexts</div>
          {contexts.length === 0 ? (
            <div className="menu-item sub">Nothing shared with you yet</div>
          ) : (
            contexts.map((c) => (
              <button
                key={c.id}
                className={c.id === activeId ? 'menu-item active' : 'menu-item'}
                onClick={() => {
                  setOpen(false)
                  onSelect(c)
                }}
                role="option"
                aria-selected={c.id === activeId}
              >
                {c.id === activeId ? (
                  <span className="live-dot" />
                ) : (
                  <span style={{ width: 7 }} />
                )}
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {c.name}
                </span>
                <span className="meta">
                  {accessLabel(c.role)} · r{c.revision}
                </span>
              </button>
            ))
          )}
          <div className="menu-sep" />
          <button
            className="menu-item"
            onClick={() => {
              setOpen(false)
              onCreate()
            }}
          >
            <span style={{ width: 7 }} />
            <span>New context…</span>
          </button>
        </div>
      ) : null}
    </div>
  )
}

/* --- formatters ----------------------------------------------------------- */

export function accessLabel(role) {
  return (
    { owner: 'owner', admin: 'manage', member: 'edit', viewer: 'view' }[role] ||
    role
  )
}

export function when(iso) {
  if (!iso) return ''
  const then = new Date(iso)
  const seconds = Math.round((Date.now() - then.getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

/* Every action the audit trail emits (see `audit.emit` calls in app/). Kept
 * complete on purpose: an unmapped action falls through to its raw dotted name,
 * which is honest but reads like a leaked internal. */
const ACTION_WORDS = {
  'context.create': 'created this context',
  'context.share': 'shared this context with',
  'context.invite': 'invited',
  'context.invite_accepted': 'accepted an invite',
  'context.access_change': 'changed access for',
  'context.access_revoked': 'removed',
  'context.link_access': 'set link access to',
  'context.link_rotate': 'replaced the share link',
  'context.link_join': 'joined via the share link',
  'context.archive': 'archived this context',
  'context.unarchive': 'restored this context',
  'context.switch': 'switched a client to this context',
  'memory.create': 'published a memory',
  'memory.retract': 'retracted a memory',
  'memory.supersede': 'superseded a memory',
  'memory.contradict': 'flagged a contradiction',
}

export function describeAction(event) {
  const base = ACTION_WORDS[event.action] || event.action
  // Only these two are safe to append: an email the actor typed, or an access
  // level. Never dump arbitrary meta into the feed.
  const detail = event.meta?.email || event.meta?.access || ''
  return detail ? `${base} ${detail}` : base
}
