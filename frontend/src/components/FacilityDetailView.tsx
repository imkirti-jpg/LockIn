import React, { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Facility, Slot, WaitlistEntry } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useRealtimeAvailability } from '../realtime/useRealtimeAvailability'
import { getFacilityImages } from '../assets/facilities'

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
          text: 'Booking window not open: this slot requires priority eligibility or an earlier booking window.',
        })
      } else if (err.status === 409) {
        setActionMessage({
          type: 'error',
          text: 'Slot just taken — another student won the race.',
        })
      } else if (err.status === 410) {
        setActionMessage({
          type: 'error',
          text: 'Claim window expired. Slot was offered to the next student.',
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
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-soft)] gap-3">
        <div className="w-5 h-5 border-2 border-[var(--color-ember)] border-t-transparent rounded-full animate-spin" />
        <span className="eyebrow">Loading schedule</span>
      </div>
    )
  }

  return (
    <div>
      {/* Full-bleed hero banner, breaks out of the reading column for a magazine feel */}
      {facility && (
        <div
          className="w-full h-[260px] md:h-[340px] bg-cover bg-center relative"
          style={{ backgroundImage: `url(${getFacilityImages(facility.sport_type).hero})` }}
        >
          <div className="absolute inset-0 bg-gradient-to-t from-[var(--color-forest-deep)]/85 via-[var(--color-forest-deep)]/15 to-transparent" />
          <div className="relative max-w-4xl mx-auto px-6 md:px-10 h-full flex flex-col justify-between py-6">
            <button
              onClick={onBack}
              className="text-sm text-[var(--color-cream)]/80 hover:text-[var(--color-cream)] transition-colors inline-flex items-center gap-1 w-fit"
            >
              ← Back to discovery
            </button>
            <div>
              <span className="eyebrow text-[var(--color-ember)] capitalize">{facility.sport_type}</span>
              <h2 className="font-[var(--font-display)] text-[40px] leading-tight text-[var(--color-cream)]">
                {facility.name}
              </h2>
            </div>
          </div>
        </div>
      )}

      <div className="max-w-4xl mx-auto px-6 md:px-10 py-10">

      {facility && (
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-8 hair mb-8">
          <p className="text-sm text-[var(--color-ink-soft)]">
            {facility.slot_length_minutes} minute slots · normal window 24h · priority window 72h
            {isPriorityEligible && <span className="text-[var(--color-status-open)]"> · you have priority access</span>}
          </p>

          <div className="flex items-center gap-2">
            <label className="text-sm text-[var(--color-ink-soft)]">Date</label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="field-underline text-[var(--color-ink)]"
            />
          </div>
        </div>
      )}

      {actionMessage && (
        <p
          className="mb-6 text-sm"
          style={{
            color: actionMessage.type === 'success' ? 'var(--color-status-open)' : 'var(--color-status-full)',
          }}
        >
          {actionMessage.text}
        </p>
      )}

      {error && <p className="mb-6 text-sm text-[var(--color-status-full)]">{error}</p>}

      {/* Time slots — plain buttons distinguished by an underline, not a boxed grid */}
      <div className="mb-4 flex items-center justify-between">
        <h3 className="eyebrow text-[var(--color-ink-soft)]">Available time slots</h3>
        <span className="eyebrow text-[var(--color-ink-soft)]/60">
          {realtimeStatus === 'connected' ? 'Live' : 'Syncing'}
        </span>
      </div>

      <div className="flex flex-wrap gap-2.5">
        {slots.map((slot) => {
          const isOpen = slot.status === 'open'
          const isFull = slot.status === 'full'

          const userWaitlist = waitlistEntries.find(
            (w) =>
              w.facility_id === facility?.id &&
              w.slot_start === slot.start_time &&
              ['waiting', 'offered'].includes(w.status)
          )

          const isOffered = userWaitlist?.status === 'offered'

          const label = `${formatTime(slot.start_time)}–${formatTime(slot.end_time)}`

          if (isOffered) {
            return (
              <button
                key={slot.slot_id}
                onClick={() => handleOpenConfirmModal(slot, userWaitlist)}
                className="btn-primary px-4 py-2.5 text-sm animate-pulse"
              >
                {label} · Claim now
              </button>
            )
          }

          if (isOpen) {
            return (
              <button
                key={slot.slot_id}
                onClick={() => handleOpenConfirmModal(slot)}
                className="px-4 py-2.5 text-sm text-[var(--color-ink)] border-b-2 border-[var(--color-status-open)] hover:bg-[var(--color-paper-dim)] transition-colors rounded-t-sm"
              >
                {label}
              </button>
            )
          }

          if (isFull && userWaitlist) {
            return (
              <div
                key={slot.slot_id}
                className="px-4 py-2.5 text-sm text-[var(--color-status-filling)] border-b-2 border-[var(--color-status-filling)]"
              >
                {label} · #{userWaitlist.position} in line
              </div>
            )
          }

          if (isFull) {
            return (
              <button
                key={slot.slot_id}
                disabled={actionLoading}
                onClick={() => handleJoinWaitlist(slot)}
                className="px-4 py-2.5 text-sm text-[var(--color-ink-soft)] border-b-2 border-[var(--color-status-full)] hover:text-[var(--color-ink)] transition-colors"
              >
                {label} · Join waitlist
              </button>
            )
          }

          return (
            <div key={slot.slot_id} className="px-4 py-2.5 text-sm text-[var(--color-ink-soft)]/50 line-through">
              {label}
            </div>
          )
        })}
      </div>

      {slots.length === 0 && !loading && (
        <p className="py-10 text-center text-sm text-[var(--color-ink-soft)]">
          No time slots generated for this date.
        </p>
      )}
      </div>

      {/* Confirmation / Claim Modal */}
      {selectedSlot && facility && (
        <div className="fixed inset-0 bg-[var(--color-forest-deep)]/85 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--color-paper)] max-w-md w-full p-8 rounded-sm shadow-2xl">
            <div className="flex justify-between items-start mb-6">
              <h3 className="font-[var(--font-display)] text-2xl text-[var(--color-ink)]">
                {offeredWaitlistEntry ? 'Claim your slot' : 'Confirm booking'}
              </h3>
              <button
                onClick={() => setSelectedSlot(null)}
                className="text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col gap-2.5 text-sm mb-8 pb-6 hair">
              <div className="flex justify-between">
                <span className="text-[var(--color-ink-soft)]">Facility</span>
                <span className="text-[var(--color-ink)] font-medium">{facility.name}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-ink-soft)]">Date</span>
                <span className="text-[var(--color-ink)]">{selectedDate}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[var(--color-ink-soft)]">Time</span>
                <span className="text-[var(--color-ember)] font-medium">
                  {formatTime(selectedSlot.start_time)} – {formatTime(selectedSlot.end_time)}
                </span>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setSelectedSlot(null)}
                className="flex-1 btn-ghost text-sm py-2.5"
              >
                Cancel
              </button>
              <button
                disabled={actionLoading}
                onClick={handleConfirmAction}
                className="flex-1 btn-primary text-sm py-2.5 flex items-center justify-center gap-2"
              >
                {actionLoading ? (
                  <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
                ) : offeredWaitlistEntry ? (
                  'Confirm claim'
                ) : (
                  'Confirm slot'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
