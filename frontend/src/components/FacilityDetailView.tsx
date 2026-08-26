import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Facility, Slot, WaitlistEntry } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useRealtimeAvailability } from '../realtime/useRealtimeAvailability'

interface FacilityDetailViewProps {
  facilityId: string
  onBack: () => void
  onBookingSuccess: () => void
  onRequestAuth?: (prompt?: string) => void
}

export const FacilityDetailView: React.FC<FacilityDetailViewProps> = ({
  facilityId,
  onBack,
  onBookingSuccess,
  onRequestAuth,
}) => {
  const { token, isAuthenticated } = useAuth()
  const [facility, setFacility] = useState<Facility | null>(null)
  const [slots, setSlots] = useState<Slot[]>([])
  const [waitlistEntries, setWaitlistEntries] = useState<WaitlistEntry[]>([])
  const [isPriorityEligible, setIsPriorityEligible] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Date selection (defaults to Today YYYY-MM-DD)
  const todayStr = new Date().toISOString().split('T')[0]
  const [selectedDate, setSelectedDate] = useState<string>(todayStr)

  // Selected slot for booking or claiming modal
  const [selectedSlot, setSelectedSlot] = useState<Slot | null>(null)
  const [offeredWaitlistEntry, setOfferedWaitlistEntry] = useState<WaitlistEntry | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState<string>('')
  const [actionLoading, setActionLoading] = useState(false)
  const [actionMessage, setActionMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const loadFacilityAndSlots = useCallback(
    async (fId: string, date: string) => {
      try {
        const [facData, slotData, waitlistData, priorityData] = await Promise.all([
          api.getFacility(fId, token),
          api.getFacilitySlots(fId, date, token),
          api.getMyWaitlists(token).catch(() => ({ waitlist_entries: [] })),
          api.getMyPriorityEligibility(token).catch(() => ({ is_priority_eligible: false })),
        ])
        setFacility(facData.facility)
        setSlots(slotData.slots || [])
        setWaitlistEntries(waitlistData.waitlist_entries || [])
        setIsPriorityEligible(priorityData.is_priority_eligible || false)
      } catch {
        setError('Failed to load facility details or slot availability.')
      } finally {
        setLoading(false)
      }
    },
    [token]
  )

  const handleRealtimeUpdate = useCallback(() => {
    if (facilityId && selectedDate) {
      loadFacilityAndSlots(facilityId, selectedDate)
    }
  }, [facilityId, selectedDate, loadFacilityAndSlots])

  const { status: realtimeStatus } = useRealtimeAvailability(handleRealtimeUpdate)

  useEffect(() => {
    setLoading(true)
    loadFacilityAndSlots(facilityId, selectedDate)
  }, [facilityId, selectedDate, loadFacilityAndSlots])

  const handleOpenConfirmModal = (slot: Slot, offeredEntry?: WaitlistEntry) => {
    if (!isAuthenticated && onRequestAuth) {
      onRequestAuth('Sign in to book this court slot.')
      return
    }
    setSelectedSlot(slot)
    setOfferedWaitlistEntry(offeredEntry || null)
    setIdempotencyKey(crypto.randomUUID())
    setActionMessage(null)
  }

  const handleJoinWaitlist = async (slot: Slot) => {
    if (!isAuthenticated && onRequestAuth) {
      onRequestAuth('Sign in to join the waitlist for this court slot.')
      return
    }
    if (!facility) return
    setActionLoading(true)
    setActionMessage(null)

    try {
      const res = await api.joinWaitlist(facility.id, slot.start_time, slot.end_time, token)
      if (res.ok) {
        setActionMessage({
          type: 'success',
          text: `Joined waitlist! You are #${res.waitlist_entry.position} in line.`,
        })
        await loadFacilityAndSlots(facility.id, selectedDate)
      }
    } catch (err: any) {
      setActionMessage({
        type: 'error',
        text: err.data?.detail?.reason || 'Failed to join waitlist.',
      })
    } finally {
      setActionLoading(false)
    }
  }

  const handleConfirmAction = async () => {
    if (!selectedSlot || !facility) return

    setActionLoading(true)
    setActionMessage(null)

    try {
      if (offeredWaitlistEntry) {
        // Claim waitlist slot
        const res = await api.claimWaitlistSlot(offeredWaitlistEntry.id, idempotencyKey, token)
        if (res.ok) {
          setActionMessage({ type: 'success', text: 'Waitlist slot claimed & booking confirmed!' })
          await loadFacilityAndSlots(facility.id, selectedDate)
          setTimeout(() => {
            setSelectedSlot(null)
            onBookingSuccess()
          }, 1200)
        }
      } else {
        // Normal booking
        const res = await api.createBooking(
          facility.id,
          selectedSlot.start_time,
          selectedSlot.end_time,
          idempotencyKey,
          token
        )

        if (res.ok) {
          const msg =
            res.reason === 'idempotent_replay'
              ? 'Booking confirmed (Idempotent Replay).'
              : 'Booking successfully confirmed!'
          setActionMessage({ type: 'success', text: msg })
          await loadFacilityAndSlots(facility.id, selectedDate)
          setTimeout(() => {
            setSelectedSlot(null)
            onBookingSuccess()
          }, 1200)
        }
      }
    } catch (err: any) {
      const reason = err.data?.detail?.reason || err.data?.reason || 'Action failed.'
      if (reason === 'booking_window_not_open' || err.status === 409 && reason === 'booking_window_not_open') {
        setActionMessage({
          type: 'error',
          text: 'BOOKING WINDOW NOT OPEN: This slot requires priority eligibility or earlier booking window.',
        })
      } else if (err.status === 409) {
        setActionMessage({
          type: 'error',
          text: 'Slot just taken! Another student won the race.',
        })
      } else if (err.status === 410) {
        setActionMessage({
          type: 'error',
          text: 'Claim window expired. Slot was offered to next student.',
        })
      } else {
        setActionMessage({
          type: 'error',
          text: reason,
        })
      }
    } finally {
      setActionLoading(false)
    }
  }

  const formatTime = (iso: string) => {
    const d = new Date(iso)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
  }

  if (loading && !facility) {
    return (
      <div className="flex flex-col items-center justify-center p-12 text-gray-400 font-mono gap-3">
        <div className="w-6 h-6 border-2 border-[#C97A2B] border-t-transparent rounded-full animate-spin" />
        Loading facility schedule...
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto p-6 flex flex-col gap-6">
      {/* Top Header & Back Button */}
      <div className="flex items-center justify-between border-b border-[#2D373E] pb-4">
        <button
          onClick={onBack}
          className="text-xs font-mono uppercase text-[#C97A2B] hover:underline flex items-center gap-1"
        >
          ← Back to Discovery
        </button>
        <div className="flex items-center gap-3 text-xs font-mono">
          {isPriorityEligible && (
            <span className="bg-[#C97A2B] text-black font-bold uppercase text-[10px] px-2 py-0.5 rounded">
              ★ PRIORITY ELIGIBLE
            </span>
          )}
          <div className="flex items-center gap-1.5 bg-[#121619] border border-[#2D373E] px-2.5 py-1 rounded">
            <span
              className={`w-2 h-2 rounded-full ${
                realtimeStatus === 'connected'
                  ? 'bg-emerald-500 animate-pulse'
                  : realtimeStatus === 'connecting'
                  ? 'bg-amber-500'
                  : 'bg-red-500'
              }`}
            />
            <span className="text-[10px] uppercase font-bold text-gray-300">
              REALTIME: {realtimeStatus}
            </span>
          </div>
        </div>
      </div>

      {facility && (
        <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <span className="text-xs font-mono uppercase text-[#C97A2B]">{facility.sport_type}</span>
            <h2 className="text-2xl font-bold text-white font-mono">{facility.name}</h2>
            <p className="text-xs text-gray-400 font-mono mt-1">
              Slot Duration: {facility.slot_length_minutes} Minutes • Normal Window: 24h • Priority Window: 72h
            </p>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs">
            <label className="text-gray-400 uppercase">Date:</label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="bg-[#121619] border border-[#2D373E] text-white px-3 py-1.5 rounded focus:outline-none focus:border-[#1F4B3F]"
            />
          </div>
        </div>
      )}

      {actionMessage && (
        <div
          className={`p-3 rounded text-xs font-mono ${
            actionMessage.type === 'success'
              ? 'bg-emerald-950 border border-emerald-800 text-emerald-300'
              : 'bg-red-950 border border-red-800 text-red-300'
          }`}
        >
          {actionMessage.text}
        </div>
      )}

      {error && (
        <div className="p-4 bg-red-950/40 border border-red-800 rounded font-mono text-red-300 text-xs">
          {error}
        </div>
      )}

      {/* Slot Grid Section */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded">
        <h3 className="text-xs font-mono uppercase tracking-wider text-gray-400 mb-4 flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="w-2 h-2 bg-[#C97A2B]" />
            Available Time Slots ({selectedDate})
          </span>
          <span className="text-[10px] text-gray-500 font-normal">FIFO Waitlist & Priority Windows Active</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {slots.map((slot) => {
            const isOpen = slot.status === 'open'
            const isFull = slot.status === 'full'

            // Check if current user has an active waitlist entry for this slot
            const userWaitlist = waitlistEntries.find(
              (w) =>
                w.facility_id === facility?.id &&
                w.slot_start === slot.start_time &&
                ['waiting', 'offered'].includes(w.status)
            )

            const isOffered = userWaitlist?.status === 'offered'

            return (
              <div
                key={slot.slot_id}
                className={`p-3 rounded border font-mono text-xs flex flex-col justify-between gap-3 transition-all ${
                  isOffered
                    ? 'bg-[#2A1D0E] border-[#C97A2B] text-white shadow-lg'
                    : isOpen
                    ? 'bg-[#16372E]/50 border-[#1F4B3F] text-white'
                    : isFull
                    ? 'bg-[#121619] border-[#2D373E] text-gray-400'
                    : 'bg-[#121619] border-[#2D373E] text-gray-500'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-bold text-sm">
                    {formatTime(slot.start_time)} – {formatTime(slot.end_time)}
                  </span>
                  <span
                    className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded ${
                      isOffered
                        ? 'bg-[#C97A2B] text-black font-bold animate-pulse'
                        : isOpen
                        ? 'bg-[#10B981]/20 text-[#10B981]'
                        : isFull
                        ? 'bg-red-500/20 text-red-400'
                        : 'bg-gray-800 text-gray-500'
                    }`}
                  >
                    {isOffered ? 'CLAIM AVAILABLE' : slot.status}
                  </span>
                </div>

                {isOffered ? (
                  <button
                    onClick={() => handleOpenConfirmModal(slot, userWaitlist)}
                    className="w-full bg-[#C97A2B] hover:bg-[#D98A3B] text-black font-bold uppercase text-xs py-2 rounded transition-colors"
                  >
                    CLAIM SLOT NOW
                  </button>
                ) : isOpen ? (
                  <button
                    onClick={() => handleOpenConfirmModal(slot)}
                    className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-2 rounded transition-colors border border-[#2A6354]"
                  >
                    BOOK SLOT
                  </button>
                ) : isFull ? (
                  userWaitlist ? (
                    <div className="text-[11px] text-[#C97A2B] font-semibold text-center py-1 bg-[#121619] border border-[#2D373E] rounded">
                      WAITLISTED (#{userWaitlist.position} IN LINE)
                    </div>
                  ) : (
                    <button
                      disabled={actionLoading}
                      onClick={() => handleJoinWaitlist(slot)}
                      className="w-full bg-[#121619] hover:bg-gray-800 text-[#C97A2B] border border-[#C97A2B]/40 font-bold uppercase text-xs py-2 rounded transition-colors"
                    >
                      + JOIN WAITLIST
                    </button>
                  )
                ) : (
                  <div className="text-[10px] text-gray-500 text-center py-1">UNAVAILABLE</div>
                )}
              </div>
            )
          })}
        </div>

        {slots.length === 0 && !loading && (
          <div className="p-8 text-center font-mono text-xs text-gray-500">
            No time slots generated for this date.
          </div>
        )}
      </div>

      {/* Confirmation / Claim Modal */}
      {selectedSlot && facility && (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[#1A2024] border border-[#2D373E] p-6 rounded-md max-w-md w-full font-mono shadow-2xl">
            <div className="flex justify-between items-start border-b border-[#2D373E] pb-3 mb-4">
              <h3 className="text-base font-bold text-white uppercase">
                {offeredWaitlistEntry ? 'CLAIM WAITLIST SLOT' : 'CONFIRM BOOKING'}
              </h3>
              <button
                onClick={() => setSelectedSlot(null)}
                className="text-gray-500 hover:text-white text-sm"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col gap-3 text-xs text-gray-300 mb-6 bg-[#121619] p-4 border border-[#2D373E] rounded">
              <div className="flex justify-between">
                <span className="text-gray-500">FACILITY:</span>
                <span className="font-bold text-white">{facility.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">DATE:</span>
                <span className="text-white">{selectedDate}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">TIME SLOT:</span>
                <span className="text-[#C97A2B] font-bold">
                  {formatTime(selectedSlot.start_time)} – {formatTime(selectedSlot.end_time)}
                </span>
              </div>

            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setSelectedSlot(null)}
                className="flex-1 bg-[#121619] border border-[#2D373E] hover:border-gray-500 text-gray-300 font-bold uppercase text-xs py-2.5 rounded transition-colors"
              >
                Cancel
              </button>
              <button
                disabled={actionLoading}
                onClick={handleConfirmAction}
                className="flex-1 bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-2.5 rounded transition-colors flex items-center justify-center gap-2 border border-[#2A6354]"
              >
                {actionLoading ? (
                  <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
                ) : offeredWaitlistEntry ? (
                  'Confirm Claim'
                ) : (
                  'Confirm Slot'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
