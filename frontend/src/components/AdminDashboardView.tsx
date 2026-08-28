import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { AnalyticsData, Facility, FacilityBlock } from '../api/client'
import { useAuth } from '../context/AuthContext'

export const AdminDashboardView: React.FC = () => {
  const { token } = useAuth()
  const [facilities, setFacilities] = useState<Facility[]>([])
  const [blocks, setBlocks] = useState<FacilityBlock[]>([])
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null)
  const [adminRole, setAdminRole] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  // Block Creation Form
  const [selectedFacilityId, setSelectedFacilityId] = useState<string>('')
  const [blockStartTime, setBlockStartTime] = useState<string>('')
  const [blockEndTime, setBlockEndTime] = useState<string>('')
  const [blockReason, setBlockReason] = useState<string>('')
  const [blockType, setBlockType] = useState<'maintenance' | 'event' | 'admin_hold'>('maintenance')
  const [creatingBlock, setCreatingBlock] = useState(false)

  const loadData = async () => {
    setLoading(true)
    setError(null)
    try {
      const [facData, analyticsData] = await Promise.all([
        api.getAdminFacilities(token),
        api.getAdminAnalytics('2026-08-01', '2026-08-31', token).catch(() => null),
      ])
      setFacilities(facData.facilities || [])
      setBlocks(facData.active_blocks || [])
      setAdminRole(facData.admin_role || 'sports_admin')
      if (facData.facilities.length > 0 && !selectedFacilityId) {
        setSelectedFacilityId(facData.facilities[0].id)
      }
      setAnalytics(analyticsData)
    } catch (err: any) {
      if (err.status === 403) {
        setError('403 Forbidden: Access Denied. Admin privileges required.')
      } else {
        setError('Failed to load admin operations data.')
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [token])

  const handleStatusChange = async (facilityId: string, newStatus: string) => {
    setActionMessage(null)
    try {
      const res = await api.updateFacilityStatus(facilityId, newStatus, token)
      if (res.ok) {
        setActionMessage(`Facility status updated to ${newStatus}.`)
        await loadData()
      }
    } catch (err: any) {
      setActionMessage(err.data?.detail?.reason || 'Failed to update facility status.')
    }
  }

  const handleCreateBlock = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedFacilityId || !blockStartTime || !blockEndTime || !blockReason) {
      setActionMessage('Please complete all block fields.')
      return
    }

    setCreatingBlock(true)
    setActionMessage(null)

    try {
      const res = await api.createFacilityBlock(
        selectedFacilityId,
        blockStartTime,
        blockEndTime,
        blockReason,
        blockType,
        token
      )
      if (res.ok) {
        let msg = `Facility block created successfully.`
        if (res.affected_bookings_count > 0) {
          msg += ` Warning: overlaps ${res.affected_bookings_count} confirmed student bookings.`
        }
        setActionMessage(msg)
        setBlockReason('')
        await loadData()
      }
    } catch (err: any) {
      setActionMessage(err.data?.detail?.reason || 'Failed to create block.')
    } finally {
      setCreatingBlock(false)
    }
  }

  const handleDeleteBlock = async (blockId: string) => {
    if (!window.confirm('Are you sure you want to remove this facility block?')) return

    setActionMessage(null)
    try {
      const res = await api.deleteFacilityBlock(blockId, token)
      if (res.ok) {
        setActionMessage('Facility block removed successfully.')
        await loadData()
      }
    } catch (err: any) {
      setActionMessage(err.data?.detail?.reason || 'Failed to remove block.')
    }
  }

  const formatDateTime = (iso: string) => {
    const d = new Date(iso)
    return {
      date: d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }),
      time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }),
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-soft)] gap-3">
        <div className="w-5 h-5 border-2 border-[var(--color-ember)] border-t-transparent rounded-full animate-spin" />
        <span className="eyebrow">Loading ops console</span>
      </div>
    )
  }

  if (error && error.includes('403')) {
    return (
      <div className="max-w-lg mx-auto px-6 py-24 text-center">
        <h2 className="font-[var(--font-display)] text-3xl text-[var(--color-status-full)] mb-3">Access denied</h2>
        <p className="text-sm text-[var(--color-ink-soft)]">
          Student account detected. Facility manager or Sports Board admin privileges are required to view operational controls.
        </p>
      </div>
    )
  }

  const inputCls = 'field-underline w-full text-[var(--color-ink)]'
  const labelCls = 'text-sm text-[var(--color-ink-soft)] block mb-1.5'

  return (
    <div className="max-w-5xl mx-auto px-6 md:px-10 py-14">
      <div className="flex items-end justify-between mb-10">
        <div>
          <span className="eyebrow text-[var(--color-ember)]">{adminRole || 'Sports Admin'}</span>
          <h2 className="font-[var(--font-display)] text-[40px] leading-tight text-[var(--color-ink)]">
            Ops console
          </h2>
        </div>
        <button onClick={loadData} className="btn-ghost text-sm">
          Refresh
        </button>
      </div>

      {actionMessage && <p className="mb-8 text-sm text-[var(--color-status-open)]">{actionMessage}</p>}

      {/* Operational Analytics — typographic stat row, not four identical cards */}
      {analytics && (
        <section className="mb-14 pb-10 hair">
          <h3 className="eyebrow text-[var(--color-ink-soft)] mb-6">
            Utilization · {analytics.from_date} to {analytics.to_date}
          </h3>
          <div className="flex flex-wrap gap-x-14 gap-y-8">
            <div>
              <div className="font-[var(--font-display)] text-5xl text-[var(--color-ink)]">
                {analytics.total_bookings}
              </div>
              <span className="eyebrow text-[var(--color-ink-soft)]">Total bookings</span>
            </div>
            <div>
              <div className="font-[var(--font-display)] text-5xl text-[var(--color-status-full)]">
                {analytics.no_show_rate_percent}%
              </div>
              <span className="eyebrow text-[var(--color-ink-soft)]">No-show rate</span>
            </div>
            <div>
              <div className="font-[var(--font-display)] text-5xl text-[var(--color-ember)]">
                {analytics.peak_hour}
              </div>
              <span className="eyebrow text-[var(--color-ink-soft)]">Peak hour</span>
            </div>
            <div>
              <div className="font-[var(--font-display)] text-3xl text-[var(--color-status-open)] max-w-[14ch] leading-tight">
                {analytics.top_facility}
              </div>
              <span className="eyebrow text-[var(--color-ink-soft)]">Top facility</span>
            </div>
          </div>
        </section>
      )}

      {/* Facility Status & Control */}
      <section className="mb-14 pb-10 hair">
        <h3 className="eyebrow text-[var(--color-ink-soft)] mb-4">
          Facility control ({facilities.length})
        </h3>

        <div>
          {facilities.map((fac, i) => (
            <div
              key={fac.id}
              className={`flex items-center justify-between gap-4 py-4 ${
                i !== facilities.length - 1 ? 'hair' : ''
              }`}
            >
              <div>
                <span className="eyebrow text-[var(--color-ember)]">{fac.sport_type}</span>
                <h4 className="font-[var(--font-display)] text-xl text-[var(--color-ink)]">{fac.name}</h4>
              </div>

              <div className="flex items-center gap-3">
                <span
                  className="text-sm capitalize"
                  style={{
                    color:
                      fac.status === 'open'
                        ? 'var(--color-status-open)'
                        : fac.status === 'maintenance'
                        ? 'var(--color-status-filling)'
                        : 'var(--color-status-full)',
                  }}
                >
                  {fac.status}
                </span>
                <select
                  value={fac.status}
                  onChange={(e) => handleStatusChange(fac.id, e.target.value)}
                  className="field-underline text-sm text-[var(--color-ink)] cursor-pointer"
                >
                  <option value="open">Open</option>
                  <option value="maintenance">Maintenance</option>
                  <option value="closed">Closed</option>
                </select>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Block Management */}
      <section className="mb-14 pb-10 hair grid grid-cols-1 md:grid-cols-2 gap-12">
        <div>
          <h3 className="eyebrow text-[var(--color-ember)] mb-5">Create facility block</h3>

          <form onSubmit={handleCreateBlock} className="flex flex-col gap-5">
            <div>
              <label className={labelCls}>Target facility</label>
              <select
                value={selectedFacilityId}
                onChange={(e) => setSelectedFacilityId(e.target.value)}
                className={inputCls + ' cursor-pointer'}
              >
                {facilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.sport_type})
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelCls}>Start time</label>
                <input
                  type="datetime-local"
                  value={blockStartTime}
                  onChange={(e) => setBlockStartTime(e.target.value)}
                  className={inputCls}
                />
              </div>
              <div>
                <label className={labelCls}>End time</label>
                <input
                  type="datetime-local"
                  value={blockEndTime}
                  onChange={(e) => setBlockEndTime(e.target.value)}
                  className={inputCls}
                />
              </div>
            </div>

            <div>
              <label className={labelCls}>Block type</label>
              <select
                value={blockType}
                onChange={(e) => setBlockType(e.target.value as any)}
                className={inputCls + ' cursor-pointer'}
              >
                <option value="maintenance">Maintenance</option>
                <option value="event">Tournament / event</option>
                <option value="admin_hold">Admin hold</option>
              </select>
            </div>

            <div>
              <label className={labelCls}>Reason</label>
              <input
                type="text"
                placeholder="e.g. Inter-IIT badminton tournament"
                value={blockReason}
                onChange={(e) => setBlockReason(e.target.value)}
                className={inputCls}
              />
            </div>

            <button
              type="submit"
              disabled={creatingBlock}
              className="btn-primary text-sm py-2.5 mt-1"
            >
              {creatingBlock ? 'Creating block…' : 'Create facility block'}
            </button>
          </form>
        </div>

        <div>
          <h3 className="eyebrow text-[var(--color-ink-soft)] mb-5">
            Active blocks ({blocks.length})
          </h3>

          <div className="flex flex-col max-h-96 overflow-y-auto">
            {blocks.map((b, i) => {
              const startF = formatDateTime(b.start_time)
              const endF = formatDateTime(b.end_time)
              const fName = facilities.find((f) => f.id === b.facility_id)?.name || 'Facility'

              return (
                <div
                  key={b.id}
                  className={`flex justify-between items-center gap-3 py-3 ${
                    i !== blocks.length - 1 ? 'hair' : ''
                  }`}
                >
                  <div>
                    <div className="text-[var(--color-ink)] font-medium">{fName}</div>
                    <div className="text-sm text-[var(--color-ink-soft)]">
                      {startF.date} ({startF.time}–{endF.time})
                    </div>
                    <div className="text-sm text-[var(--color-ember)]">{b.reason}</div>
                  </div>

                  <button onClick={() => handleDeleteBlock(b.id)} className="btn-ghost text-sm shrink-0">
                    Remove
                  </button>
                </div>
              )
            })}

            {blocks.length === 0 && (
              <p className="py-4 text-sm text-[var(--color-ink-soft)]">No active facility blocks.</p>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
