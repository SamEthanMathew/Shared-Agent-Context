/* The home screen: every context available to you. */
import { accessLabel } from '../components.jsx'
import ConnectGuide from '../ConnectGuide.jsx'
import { Link } from '../router.jsx'

export default function ContextsView({ me, navigate, onCreate }) {
  const contexts = me.contexts || []

  if (!contexts.length) {
    return (
      <div className="page">
        <div className="empty">
          <h2>No shared contexts yet</h2>
          <p>
            A context is the project knowledge your agents read and write. Create
            one, then share it — everyone in it works from the same understanding,
            whichever AI client they use.
          </p>
          <button className="btn primary" onClick={onCreate}>
            Create your first context
          </button>
        </div>

        {/* The other half of the first run. Nothing here works until an AI
          * client is pointed at the MCP URL, and this is the screen a new
          * account lands on — leaving the instructions behind a nav link they
          * have no reason to click is how people stall. */}
        <div style={{ maxWidth: 560, margin: '0 auto' }}>
          <ConnectGuide />
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Your contexts</h1>
          <p className="sub">
            Shared project knowledge. Pick one to see what your agents know.
          </p>
        </div>
        <button className="btn primary" onClick={onCreate}>
          New context
        </button>
      </div>

      <div className="ctx-grid">
        {contexts.map((c) => (
          <Link
            key={c.id}
            to={`/c/${c.id}`}
            navigate={navigate}
            className="ctx-card"
          >
            <div className="item-head" style={{ marginBottom: 10 }}>
              <span className="item-title">{c.name}</span>
              <span className={c.role === 'owner' ? 'badge owner' : 'badge'}>
                {accessLabel(c.role)}
              </span>
            </div>
            <div className="tiny">
              <span className="mono">r{c.revision}</span>
              {' · '}
              {c.member_count} {c.member_count === 1 ? 'member' : 'members'}
            </div>
            {c.description ? (
              <div className="tiny" style={{ marginTop: 6 }}>
                {c.description}
              </div>
            ) : null}
          </Link>
        ))}
      </div>
    </div>
  )
}
