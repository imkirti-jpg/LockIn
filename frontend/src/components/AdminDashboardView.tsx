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
        setActionMessage(`Facility status updated to ${newStatus.toUpperCase()}`)
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
          msg += ` WARNING: This block overlaps ${res.affected_bookings_count} confirmed student bookings!`
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
      <div className="flex flex-col items-center justify-center p-12 text-gray-400 font-mono gap-3">
        <div className="w-6 h-6 border-2 border-[#C97A2B] border-t-transparent rounded-full animate-spin" />
        Loading Admin Operations Console...
      </div>
    )
  }

  if (error && error.includes('403')) {
    return (
      <div className="max-w-2xl mx-auto p-12 font-mono text-center">
        <div className="bg-red-950/40 border border-red-800 p-8 rounded text-red-300 flex flex-col items-center gap-3">
          <span className="text-3xl">🚫</span>
          <h2 className="text-lg font-bold">403 FORBIDDEN: ACCESS DENIED</h2>
          <p className="text-xs text-gray-400">
            Student account detected. Facility Manager or Sports Admin privileges required to access operational controls.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto p-6 flex flex-col gap-6 font-mono">
      {/* Admin Ops Header */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-4 rounded flex justify-between items-center">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase text-[#C97A2B] font-bold">LOCKIN OPERATIONAL OPS</span>
            <span className="bg-[#C97A2B] text-black font-bold uppercase text-[9px] px-2 py-0.5 rounded">
              {adminRole?.toUpperCase() || 'SPORTS ADMIN'}
            </span>
          </div>
          <h2 className="text-lg font-bold text-white">IIT Guwahati Facility Operations Console</h2>
        </div>
        <button
          onClick={loadData}
          className="text-xs text-gray-400 hover:text-white border border-[#2D373E] px-3 py-1.5 rounded"
        >
          Refresh Ops Data
        </button>
      </div>

      {actionMessage && (
        <div className="bg-[#16372E] border border-[#1F4B3F] text-emerald-300 p-3 rounded text-xs">
          {actionMessage}
        </div>
      )}

      {/* Facilities Status & Controls Grid */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded">
        <h3 className="text-xs uppercase text-gray-400 mb-4 flex items-center gap-2">
          <span className="w-2 h-2 bg-emerald-500 rounded-full" />
          Facility Status & Live Control ({facilities.length})
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {facilities.map((fac) => (
            <div key={fac.id} className="bg-[#121619] border border-[#2D373E] p-4 rounded flex flex-col gap-3">
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-[10px] text-[#C97A2B] uppercase font-bold">{fac.sport_type}</span>
                  <h4 className="text-sm font-bold text-white">{fac.name}</h4>
                </div>
                <span
                  className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded ${
                    fac.status === 'open'
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                      : fac.status === 'maintenance'
                      ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                      : 'bg-red-500/20 text-red-400 border border-red-500/30'
                  }`}
                >
                  {fac.status}
                </span>
              </div>

              <div className="flex items-center gap-2 pt-2 border-t border-[#2D373E]/60 text-xs">
                <span className="text-gray-500 uppercase text-[10px]">Change Status:</span>
                <select
                  value={fac.status}
                  onChange={(e) => handleStatusChange(fac.id, e.target.value)}
                  className="bg-[#1A2024] border border-[#2D373E] text-white px-2 py-1 rounded text-xs focus:outline-none"
                >
                  <option value="open">OPEN</option>
                  <option value="maintenance">MAINTENANCE</option>
                  <option value="closed">CLOSED</option>
                </select>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Block Management Section */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded flex flex-col md:flex-row gap-6">
        {/* Create Block Form */}
        <div className="flex-1 flex flex-col gap-3">
          <h3 className="text-xs uppercase text-[#C97A2B] font-bold flex items-center gap-2">
            <span className="w-2 h-2 bg-[#C97A2B] rounded-full" />
            Create Facility / Time Block
          </h3>

          <form onSubmit={handleCreateBlock} className="flex flex-col gap-3 text-xs">
            <div>
              <label className="text-gray-400 uppercase text-[10px] block mb-1">Target Facility:</label>
              <select
                value={selectedFacilityId}
                onChange={(e) => setSelectedFacilityId(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white p-2 rounded focus:outline-none"
              >
                {facilities.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name} ({f.sport_type})
                  </option>
                ))}
              </select>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="text-gray-400 uppercase text-[10px] block mb-1">Start Time (ISO):</label>
                <input
                  type="datetime-local"
                  value={blockStartTime}
                  onChange={(e) => setBlockStartTime(e.target.value)}
                  className="w-full bg-[#121619] border border-[#2D373E] text-white p-2 rounded focus:outline-none"
                />
              </div>
              <div>
                <label className="text-gray-400 uppercase text-[10px] block mb-1">End Time (ISO):</label>
                <input
                  type="datetime-local"
                  value={blockEndTime}
                  onChange={(e) => setBlockEndTime(e.target.value)}
                  className="w-full bg-[#121619] border border-[#2D373E] text-white p-2 rounded focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="text-gray-400 uppercase text-[10px] block mb-1">Block Type:</label>
              <select
                value={blockType}
                onChange={(e) => setBlockType(e.target.value as any)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white p-2 rounded focus:outline-none"
              >
                <option value="maintenance">MAINTENANCE</option>
                <option value="event">TOURNAMENT / EVENT</option>
                <option value="admin_hold">ADMIN HOLD</option>
              </select>
            </div>

            <div>
              <label className="text-gray-400 uppercase text-[10px] block mb-1">Reason / Description:</label>
              <input
                type="text"
                placeholder="e.g. Inter-IIT Badminton Tournament"
                value={blockReason}
                onChange={(e) => setBlockReason(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white p-2 rounded focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={creatingBlock}
              className="bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-2.5 rounded transition-colors border border-[#2A6354] mt-2"
            >
              {creatingBlock ? 'Creating Block...' : 'CREATE FACILITY BLOCK'}
            </button>
          </form>
        </div>

        {/* Active Blocks List */}
        <div className="flex-1 flex flex-col gap-3">
          <h3 className="text-xs uppercase text-gray-400 font-bold flex items-center gap-2">
            Active Administrative Blocks ({blocks.length})
          </h3>

          <div className="flex flex-col gap-2 max-h-80 overflow-y-auto">
            {blocks.map((b) => {
              const startF = formatDateTime(b.start_time)
              const endF = formatDateTime(b.end_time)
              const fName = facilities.find((f) => f.id === b.facility_id)?.name || 'Facility'

              return (
                <div key={b.id} className="bg-[#121619] border border-[#2D373E] p-3 rounded text-xs flex justify-between items-center">
                  <div>
                    <div className="font-bold text-white">{fName}</div>
                    <div className="text-[10px] text-gray-400 font-mono">
                      {startF.date} ({startF.time} – {endF.time})
                    </div>
                    <div className="text-[10px] text-[#C97A2B] uppercase">{b.reason}</div>
                  </div>

                  <button
                    onClick={() => handleDeleteBlock(b.id)}
                    className="text-[10px] bg-red-950/40 hover:bg-red-900/60 border border-red-800 text-red-300 px-2 py-1 rounded"
                  >
                    Remove
                  </button>
                </div>
              )
            })}

            {blocks.length === 0 && (
              <div className="p-6 text-center text-xs text-gray-500 border border-dashed border-[#2D373E] rounded">
                No active facility blocks.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Operational Analytics Section */}
      {analytics && (
        <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded flex flex-col gap-4">
          <h3 className="text-xs uppercase text-gray-400 font-bold flex items-center gap-2">
            <span className="w-2 h-2 bg-[#C97A2B]" />
            Operational Metrics & Utilization ({analytics.from_date} to {analytics.to_date})
          </h3>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
            <div className="bg-[#121619] border border-[#2D373E] p-3 rounded">
              <span className="text-[10px] text-gray-500 uppercase block">Total Bookings</span>
              <span className="text-lg font-bold text-white">{analytics.total_bookings}</span>
            </div>
            <div className="bg-[#121619] border border-[#2D373E] p-3 rounded">
              <span className="text-[10px] text-gray-500 uppercase block">No-Show Rate</span>
              <span className="text-lg font-bold text-red-400">{analytics.no_show_rate_percent}%</span>
            </div>
            <div className="bg-[#121619] border border-[#2D373E] p-3 rounded">
              <span className="text-[10px] text-gray-500 uppercase block">Peak Hour</span>
              <span className="text-lg font-bold text-[#C97A2B]">{analytics.peak_hour}</span>
            </div>
            <div className="bg-[#121619] border border-[#2D373E] p-3 rounded">
              <span className="text-[10px] text-gray-500 uppercase block">Top Facility</span>
              <span className="text-xs font-bold text-emerald-400 truncate block mt-1">{analytics.top_facility}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
