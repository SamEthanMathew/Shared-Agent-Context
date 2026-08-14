/* How to point an AI client at Osmos.
 *
 * Its own module because three screens need it — the AI clients page, the home
 * screen before there is anything on it, and a context with no memory yet. A
 * new account's whole problem is that the MCP URL lives one nav click away from
 * everywhere they land, and copying this per screen is how the instructions
 * drift apart.
 */
export default function ConnectGuide({ compact = false, title }) {
  const url = `${window.location.origin}/mcp`
  return (
    <div className={compact ? 'card tight' : 'card'}>
      <div className="card-head">
        <h2>
          {title || (compact ? 'Connect another client' : 'Connect your first AI client')}
        </h2>
      </div>
      {!compact ? (
        <p className="sub" style={{ marginTop: 0 }}>
          Osmos works through MCP, so the same context reaches whichever assistant
          you use.
        </p>
      ) : null}
      <div className="link-copy" style={{ marginBottom: 16 }}>
        <input readOnly value={url} aria-label="MCP server URL" />
        <button
          className="btn sm"
          onClick={() => navigator.clipboard?.writeText(url)}
        >
          Copy
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <tbody>
            <tr>
              <td style={{ width: 96 }}>
                <strong style={{ fontWeight: 500 }}>Claude</strong>
              </td>
              <td className="tiny">
                Settings → Connectors → Add custom connector → paste the URL
                above. Sign in when it asks, then approve access.
              </td>
            </tr>
            <tr>
              <td>
                <strong style={{ fontWeight: 500 }}>ChatGPT</strong>
              </td>
              <td className="tiny">
                Settings → Apps → Advanced → Developer mode → add a connector
                with the URL above and OAuth authentication.
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
