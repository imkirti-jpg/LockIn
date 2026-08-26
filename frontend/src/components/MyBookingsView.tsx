import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Booking, Facility, WaitlistEntry } from '../api/client'
import { useAuth } from '../context/AuthContext'

export const MyBookingsView: React.FC = () => {
  const { token } = useAuth()
  const [bookings, setBookings] = useState<Booking[]>([])
  const [waitlists, setWaitlists] = useState<WaitlistEntry[]>([])
  const [facilities, setFacilities] = useState<Facility[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [cancellingId, setCancellingId] = useState<string | null>(null)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  // QR Modal state
  const [selectedQrBooking, setSelectedQrBooking] = useState<Booking | null>(null)
  const [checkinLoading, setCheckinLoading] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [bRes, wRes, fRes] = await Promise.all([
        api.getMyBookings(token),
        api.getMyWaitlists(token).catch(() => ({ waitlist_entries: [] })),
        api.getFacilities(token).catch(() => ({ facilities: [] })),
      ])
      setBookings(bRes.bookings || [])
      setWaitlists(wRes.waitlist_entries || [])
      setFacilities(fRes.facilities || [])
    } catch {
      setError('Failed to load your reservations.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => {
    loadData()
  }, [token, loadData])

  const handleCancelBooking = async (bookingId: string) => {
    if (!window.confirm('Are you sure you want to cancel this booking?')) return

    setCancellingId(bookingId)
    setActionMessage(null)

    try {
      const res = await api.cancelBooking(bookingId, token)
      if (res.ok) {
        setActionMessage('Booking successfully cancelled.')
        await loadData()
      }
    } catch (err: any) {
      setActionMessage(err.data?.detail?.reason || 'Failed to cancel booking.')
    } finally {
      setCancellingId(null)
    }
  }

  const handleCancelWaitlist = async (entryId: string) => {
    if (!window.confirm('Are you sure you want to leave this waitlist?')) return

    setCancellingId(entryId)
    setActionMessage(null)

    try {
      const res = await api.cancelWaitlistEntry(entryId, token)
      if (res.ok) {
        setActionMessage('Successfully removed from waitlist.')
        await loadData()
      }
    } catch (err: any) {
      setActionMessage(err.data?.detail?.reason || 'Failed to leave waitlist.')
    } finally {
      setCancellingId(null)
    }
  }

  const handleExecuteCheckin = async (booking: Booking) => {
    if (!booking.checkin_token) {
      setActionMessage('Check-in token not available.')
      return
    }

    setCheckinLoading(true)
    setActionMessage(null)

    try {
      const res = await api.executeCheckin(booking.id, booking.checkin_token, token)
      if (res.ok) {
        setActionMessage('Successfully checked in! Attendance recorded.')
        setSelectedQrBooking(null)
        await loadData()
      }
    } catch (err: any) {
      const reason = err.data?.detail?.reason || 'Check-in failed.'
      if (reason === 'too_early') {
        setActionMessage('Check-in window opens 15 minutes before slot start.')
      } else if (reason === 'checkin_window_expired') {
        setActionMessage('Check-in grace period expired. Booking was released.')
      } else {
        setActionMessage(`Check-in failed: ${reason}`)
      }
    } finally {
      setCheckinLoading(false)
    }
  }

  const formatDateTime = (iso: string) => {
    const d = new Date(iso)
    return {
      date: d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }),
      time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false }),
    }
  }

  const getFacilityInfo = (facilityId: string) => {
    const found = facilities.find((f) => f.id === facilityId)
    return found ? { name: found.name, sport: found.sport_type } : { name: 'Facility Court', sport: 'Sports' }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-gray-400 font-mono gap-3">
        <div className="w-6 h-6 border-2 border-[#C97A2B] border-t-transparent rounded-full animate-spin" />
        Loading your reservations...
      </div>
    )
  }

  const activeBookings = bookings.filter((b) => ['confirmed', 'checked_in'].includes(b.status))
  const activeWaitlists = waitlists.filter((w) => ['waiting', 'offered'].includes(w.status))

  return (
    <div className="max-w-4xl mx-auto p-6 flex flex-col gap-6 font-mono">
      <div className="bg-[#1A2024] border border-[#2D373E] p-4 rounded flex justify-between items-center">
        <div>
          <span className="text-xs uppercase text-[#C97A2B]">MY RESERVATIONS</span>
          <h2 className="text-lg font-bold text-white">IIT Guwahati Student Dashboard</h2>
        </div>
        <button
          onClick={loadData}
          className="text-xs text-gray-400 hover:text-white border border-[#2D373E] px-3 py-1.5 rounded"
        >
          Refresh List
        </button>
      </div>

      {actionMessage && (
        <div className="bg-[#16372E] border border-[#1F4B3F] text-emerald-300 p-3 rounded text-xs">
          {actionMessage}
        </div>
      )}

      {error && (
        <div className="bg-red-950/40 border border-red-800 text-red-300 p-3 rounded text-xs">
          {error}
        </div>
      )}

      {/* Active Waitlists Section (Phase 5.1) */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded">
        <h3 className="text-xs font-mono uppercase text-[#C97A2B] mb-4 flex items-center gap-2">
          <span className="w-2 h-2 bg-[#C97A2B] rounded-full animate-pulse" />
          Active Waitlists ({activeWaitlists.length})
        </h3>

        <div className="flex flex-col gap-3">
          {activeWaitlists.map((w) => {
            const startFormat = formatDateTime(w.slot_start)
            const isOffered = w.status === 'offered'
            const fac = getFacilityInfo(w.facility_id)

            return (
              <div
                key={w.id}
                className={`p-4 rounded border flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${
                  isOffered
                    ? 'bg-[#2A1D0E] border-[#C97A2B]'
                    : 'bg-[#121619] border-[#2D373E]'
                }`}
              >
                <div>
                  <div className="text-xs font-bold text-[#C97A2B] uppercase mb-0.5">{fac.name} ({fac.sport})</div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold text-white">{startFormat.date}</span>
                    <span className="text-xs text-[#C97A2B] font-bold">{startFormat.time}</span>
                  </div>
                  <div className="text-[11px] text-gray-400">
                    Queue Position: <span className="font-bold text-white">#{w.position} in line</span>
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  <span
                    className={`text-[10px] font-bold uppercase px-2.5 py-1 rounded ${
                      isOffered
                        ? 'bg-[#C97A2B] text-black font-bold animate-pulse'
                        : 'bg-amber-500/20 text-amber-400 border border-amber-500/30'
                    }`}
                  >
                    {isOffered ? 'CLAIM AVAILABLE' : `WAITLISTED (#${w.position})`}
                  </span>
                  <button
                    disabled={cancellingId === w.id}
                    onClick={() => handleCancelWaitlist(w.id)}
                    className="text-xs bg-red-950/40 hover:bg-red-900/60 border border-red-800 text-red-300 px-3 py-1.5 rounded transition-colors"
                  >
                    Leave Queue
                  </button>
                </div>
              </div>
            )
          })}

          {activeWaitlists.length === 0 && (
            <div className="p-4 text-center text-xs text-gray-500 border border-dashed border-[#2D373E] rounded">
              No active waitlist positions.
            </div>
          )}
        </div>
      </div>

      {/* Upcoming Active Bookings */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded">
        <h3 className="text-xs font-mono uppercase text-gray-400 mb-4 flex items-center gap-2">
          <span className="w-2 h-2 bg-emerald-500 rounded-full" />
          Active Court Bookings ({activeBookings.length})
        </h3>

        <div className="flex flex-col gap-3">
          {activeBookings.map((b) => {
            const startFormat = formatDateTime(b.slot_start)
            const endFormat = formatDateTime(b.slot_end)
            const isCheckedIn = b.status === 'checked_in'
            const fac = getFacilityInfo(b.facility_id)

            return (
              <div
                key={b.id}
                className="bg-[#121619] border border-[#2D373E] p-4 rounded flex flex-col sm:flex-row sm:items-center justify-between gap-4"
              >
                <div>
                  <div className="text-xs font-bold text-[#C97A2B] uppercase mb-0.5">{fac.name} • {fac.sport}</div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-xs font-bold text-white">{startFormat.date}</span>
                    <span className="text-xs text-[#C97A2B] font-bold">
                      {startFormat.time} – {endFormat.time}
                    </span>
                  </div>
                  <div className="text-[11px] text-gray-500 truncate max-w-sm">
                    ID: {b.id} {isCheckedIn && `• Checked in at ${formatDateTime(b.checked_in_at || '').time}`}
                  </div>
                </div>

                <div className="flex items-center gap-3">
                  {isCheckedIn ? (
                    <span className="text-[10px] font-bold uppercase px-2.5 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded">
                      ✓ CHECKED IN
                    </span>
                  ) : (
                    <>
                      <button
                        onClick={() => setSelectedQrBooking(b)}
                        className="text-xs bg-[#C97A2B] hover:bg-[#D98A3B] text-black font-bold px-3 py-1.5 rounded transition-colors"
                      >
                        SHOW QR
                      </button>
                      <button
                        disabled={cancellingId === b.id}
                        onClick={() => handleCancelBooking(b.id)}
                        className="text-xs bg-red-950/40 hover:bg-red-900/60 border border-red-800 text-red-300 px-3 py-1.5 rounded transition-colors"
                      >
                        {cancellingId === b.id ? 'Cancelling...' : 'Cancel'}
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })}

          {activeBookings.length === 0 && (
            <div className="p-6 text-center text-xs text-gray-500 border border-dashed border-[#2D373E] rounded">
              No active court bookings.
            </div>
          )}
        </div>
      </div>

      {/* QR Code Modal (Phase 5.2) */}
      {selectedQrBooking && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded-md max-w-sm w-full font-mono shadow-2xl text-center">
            <div className="flex justify-between items-center border-b border-[#2D373E] pb-3 mb-4">
              <h3 className="text-sm font-bold text-white uppercase">LOCKIN CHECK-IN CREDENTIAL</h3>
              <button
                onClick={() => setSelectedQrBooking(null)}
                className="text-gray-500 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="bg-[#121619] p-4 border border-[#2D373E] rounded flex flex-col items-center gap-3 mb-4">
              {/* Scoreboard QR Code Frame */}
              <div className="w-44 h-44 bg-white p-3 rounded flex flex-col items-center justify-center border-4 border-[#C97A2B]">
                <div className="w-full h-full bg-[#121619] border-2 border-dashed border-gray-400 flex flex-col items-center justify-center p-2 text-center">
                  <span className="text-[10px] text-[#C97A2B] font-bold tracking-widest uppercase mb-1">
                    LOCKIN QR
                  </span>
                  <div className="text-[9px] text-[#C97A2B] font-bold tracking-widest uppercase">
                    SCANNABLE ACCESS TOKEN
                  </div>
                </div>
              </div>

              <div className="text-[11px] text-gray-300 flex flex-col gap-1 w-full text-left font-mono">
                <div>
                  <span className="text-gray-500">FACILITY:</span>{' '}
                  <span className="font-bold text-white">{getFacilityInfo(selectedQrBooking.facility_id).name}</span>
                </div>
                <div>
                  <span className="text-gray-500">DATE:</span>{' '}
                  {formatDateTime(selectedQrBooking.slot_start).date}
                </div>
                <div>
                  <span className="text-gray-500">TIME:</span>{' '}
                  <span className="text-[#C97A2B]">
                    {formatDateTime(selectedQrBooking.slot_start).time} –{' '}
                    {formatDateTime(selectedQrBooking.slot_end).time}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setSelectedQrBooking(null)}
                className="flex-1 bg-[#121619] border border-[#2D373E] text-gray-400 hover:text-white font-bold uppercase text-xs py-2.5 rounded"
              >
                Close
              </button>
              <button
                disabled={checkinLoading}
                onClick={() => handleExecuteCheckin(selectedQrBooking)}
                className="flex-1 bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-2.5 rounded border border-[#2A6354] flex items-center justify-center gap-2"
              >
                {checkinLoading ? (
                  <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                ) : (
                  'VERIFY CHECK-IN'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
