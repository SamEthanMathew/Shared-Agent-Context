/* Workspace billing.
 *
 * Two things this screen has to be honest about, because getting either wrong
 * costs trust rather than just clarity:
 *
 * - **What you will actually be charged.** Seats come from membership, so the
 *   total is shown as an arithmetic sentence (4 members x $8 = $32/month) rather
 *   than a headline price the customer has to multiply themselves.
 * - **What happens when you stop paying.** Nothing is deleted. The copy says so
 *   at the point of cancelling, not buried in a help page.
 */
import { useCallback, useEffect, useState } from 'react'

import { api } from './api.js'
import { Loading } from './components.jsx'

const MONTHLY_CENTS = 800
const ANNUAL_CENTS = 8400

function money(cents) {
  return cents % 100 === 0 ? `$${cents / 100}` : `$${(cents / 100).toFixed(2)}`
}

export default function BillingPanel({ orgId, toast }) {
  const [state, setState] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [interval, setInterval] = useState('month')

  const load = useCallback(async () => {
    try {
      setState(await api.billing(orgId))
    } catch (err) {
      setError(err.message)
    }
  }, [orgId])

  useEffect(() => {
    load()
  }, [load])

  if (error) return <div className="notice error">{error}</div>
  if (!state) return <Loading label="Loading billing" />

  const pro = state.plan === 'pro'
  const seats = Math.max(1, state.seats)
  const perSeat = interval === 'year' ? ANNUAL_CENTS : MONTHLY_CENTS
  const total = seats * perSeat

  const go = async (fn, message) => {
    setBusy(true)
    try {
      const result = await fn()
      if (result?.checkout_url) {
        window.location.href = result.checkout_url
        return
      }
      if (result?.portal_url) {
        window.location.href = result.portal_url
        return
      }
      await load()
      if (message) toast(message)
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-head">
        <h2>Billing</h2>
        <span className={pro ? 'badge owner' : 'badge'}>{state.plan_label}</span>
        {state.test_mode ? (
          <span className="badge" title="No real money moves in test mode">
            test mode
          </span>
        ) : null}
      </div>

      {state.in_grace_period ? (
        <div className="notice warn" style={{ marginBottom: 16 }}>
          <strong>A payment didn’t go through.</strong> Your workspace is still
          fully active while you sort it out — nothing has been switched off and
          nothing will be deleted. Update your card from Manage billing.
        </div>
      ) : null}

      {state.cancel_at_period_end && state.current_period_end ? (
        <div className="notice" style={{ marginBottom: 16 }}>
          Pro ends on{' '}
          {new Date(state.current_period_end).toLocaleDateString(undefined, {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
          })}
          . After that this workspace returns to Free. Your contexts and memory
          stay exactly as they are.
        </div>
      ) : null}

      <UsageAgainstLimits usage={state.usage} limits={state.limits} />

      {!state.billing_configured ? (
        <p className="tiny" style={{ marginTop: 16 }}>
          Billing isn’t configured on this deployment, so everything runs on the
          Free plan.
        </p>
      ) : !state.can_manage ? (
        <p className="tiny" style={{ marginTop: 16 }}>
          Only workspace owners and admins can change the plan.
        </p>
      ) : pro ? (
        <div className="row" style={{ marginTop: 20, flexWrap: 'wrap' }}>
          <button
            className="btn"
            disabled={busy}
            onClick={() => go(() => api.billingPortal(orgId))}
          >
            Manage billing
          </button>
          {!state.cancel_at_period_end ? (
            <button
              className="btn ghost"
              disabled={busy}
              onClick={() => {
                if (
                  window.confirm(
                    'Cancel Pro? It stays active until the end of the period you have paid for. Nothing is deleted — the workspace returns to the Free limits afterwards.'
                  )
                )
                  go(
                    () => api.cancelSubscription(orgId),
                    'Pro will end at the period end'
                  )
              }}
            >
              Cancel subscription
            </button>
          ) : null}
          <div className="topbar-spacer" />
          <span className="tiny">
            {state.billed_seats} seat{state.billed_seats === 1 ? '' : 's'} billed
            {state.interval ? ` · per ${state.interval}` : ''}
          </span>
        </div>
      ) : (
        <Upgrade
          seats={seats}
          interval={interval}
          setInterval={setInterval}
          perSeat={perSeat}
          total={total}
          busy={busy}
          onUpgrade={() => go(() => api.startCheckout(orgId, interval))}
        />
      )}
    </div>
  )
}

function UsageAgainstLimits({ usage, limits }) {
  const rows = [
    ['Contexts', usage.contexts, limits.contexts],
    ['Members', usage.members, limits.members],
    ['Connected agents', usage.agents, limits.agents],
  ]
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Usage</th>
            <th>Now</th>
            <th>Your plan allows</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, used, limit]) => {
            const atLimit = limit !== null && used >= limit
            return (
              <tr key={label}>
                <td>{label}</td>
                <td className={atLimit ? 'mono' : 'mono tiny'}>
                  {used}
                  {atLimit ? (
                    <span className="badge" style={{ marginLeft: 8 }}>
                      at limit
                    </span>
                  ) : null}
                </td>
                <td className="tiny">{limit === null ? 'unlimited' : limit}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Upgrade({ seats, interval, setInterval, perSeat, total, busy, onUpgrade }) {
  const annualSaving = seats * MONTHLY_CENTS * 12 - seats * ANNUAL_CENTS
  return (
    <div className="link-panel" style={{ marginTop: 20 }}>
      <h3 style={{ marginTop: 0, marginBottom: 8 }}>Upgrade to Pro</h3>
      <p className="tiny" style={{ marginTop: 0 }}>
        Unlimited contexts, members, and connected agents.
      </p>

      <div className="row" style={{ margin: '12px 0' }}>
        <select
          value={interval}
          onChange={(e) => setInterval(e.target.value)}
          style={{ width: 'auto' }}
          aria-label="Billing interval"
        >
          <option value="month">Monthly — {money(MONTHLY_CENTS)}/user/month</option>
          <option value="year">Annual — {money(ANNUAL_CENTS)}/user/year</option>
        </select>
      </div>

      {/* Stated as arithmetic, so nobody has to work out their own bill. */}
      <p style={{ margin: '4px 0' }}>
        <strong>
          {seats} member{seats === 1 ? '' : 's'} × {money(perSeat)} ={' '}
          {money(total)}
        </strong>{' '}
        <span className="tiny">per {interval}</span>
      </p>
      {interval === 'year' && annualSaving > 0 ? (
        <p className="tiny" style={{ margin: '4px 0 0' }}>
          Saves {money(annualSaving)} a year compared with monthly.
        </p>
      ) : null}
      <p className="tiny" style={{ margin: '10px 0 0' }}>
        Seats follow your membership automatically — adding someone adds a seat
        and is prorated; removing someone frees the seat at your next renewal.
      </p>

      <button
        className="btn primary"
        style={{ marginTop: 14 }}
        disabled={busy}
        onClick={onUpgrade}
      >
        {busy ? 'Opening checkout…' : 'Upgrade to Pro'}
      </button>
    </div>
  )
}
