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

  const isCheckinEarly = (slotStartIso: string) => {
    const startMs = new Date(slotStartIso).getTime()
    const windowOpenMs = startMs - 15 * 60 * 1000
    return Date.now() < windowOpenMs
  }

  const getEarlyMinutesLeft = (slotStartIso: string) => {
    const startMs = new Date(slotStartIso).getTime()
    const windowOpenMs = startMs - 15 * 60 * 1000
    const diffMs = windowOpenMs - Date.now()
    return Math.max(1, Math.ceil(diffMs / (60 * 1000)))
  }

  const handleExecuteCheckin = async (booking: Booking) => {
    if (!booking.checkin_token) {
      setActionMessage('Check-in token not available.')
      return
    }

    if (isCheckinEarly(booking.slot_start)) {
      const mins = getEarlyMinutesLeft(booking.slot_start)
      setActionMessage(`⚠️ Warning: You are attempting to check in too early. Check-in opens 15 minutes before your slot start time (${mins} mins remaining).`)
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
      const customMsg = err.data?.detail?.message || err.data?.message
      if (reason === 'too_early') {
        const mins = err.data?.detail?.minutes_remaining
        setActionMessage(customMsg || `⚠️ Warning: Check-in is only allowed within 15 minutes of slot start time.${mins ? ` (${mins} mins remaining)` : ''}`)
      } else if (reason === 'checkin_window_expired') {
        setActionMessage('⚠️ Check-in window expired. Booking was released.')
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
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-soft)] gap-3">
        <div className="w-5 h-5 border-2 border-[var(--color-ember)] border-t-transparent rounded-full animate-spin" />
        <span className="eyebrow">Loading reservations</span>
      </div>
    )
  }

  const activeBookings = bookings.filter((b) => ['confirmed', 'checked_in'].includes(b.status))
  const activeWaitlists = waitlists.filter((w) => ['waiting', 'offered'].includes(w.status))

  return (
    <div className="max-w-4xl mx-auto px-6 md:px-10 py-14">
      <div className="flex items-end justify-between mb-10">
        <div>
          <span className="eyebrow text-[var(--color-ember)]">My Reservations</span>
          <h2 className="font-[var(--font-display)] text-[40px] leading-tight text-[var(--color-ink)]">
            Your schedule
          </h2>
        </div>
        <button onClick={loadData} className="btn-ghost text-sm">
          Refresh
        </button>
      </div>

      {actionMessage && <p className="mb-6 text-sm text-[var(--color-status-open)]">{actionMessage}</p>}
      {error && <p className="mb-6 text-sm text-[var(--color-status-full)]">{error}</p>}

      {/* Active Waitlists */}
      <section className="mb-12">
        <h3 className="eyebrow text-[var(--color-ink-soft)] mb-4">
          Active waitlists ({activeWaitlists.length})
        </h3>

        <div>
          {activeWaitlists.map((w, i) => {
            const startFormat = formatDateTime(w.slot_start)
            const isOffered = w.status === 'offered'
            const fac = getFacilityInfo(w.facility_id)

            return (
              <div
                key={w.id}
                className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-4 ${
                  i !== activeWaitlists.length - 1 ? 'hair' : ''
                }`}
              >
                <div>
                  <div className="text-sm text-[var(--color-ink-soft)] capitalize mb-0.5">
                    {fac.name} · {fac.sport}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--color-ink)] font-medium">{startFormat.date}</span>
                    <span className="text-[var(--color-ember)]">{startFormat.time}</span>
                    <span className="text-sm text-[var(--color-ink-soft)]">· #{w.position} in line</span>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  <span
                    className="text-sm font-medium"
                    style={{ color: isOffered ? 'var(--color-ember)' : 'var(--color-status-filling)' }}
                  >
                    {isOffered ? 'Claim available' : `Waitlisted #${w.position}`}
                  </span>
                  <button
                    disabled={cancellingId === w.id}
                    onClick={() => handleCancelWaitlist(w.id)}
                    className="btn-ghost text-sm"
                  >
                    Leave queue
                  </button>
                </div>
              </div>
            )
          })}

          {activeWaitlists.length === 0 && (
            <p className="py-4 text-sm text-[var(--color-ink-soft)]">No active waitlist positions.</p>
          )}
        </div>
      </section>

      {/* Active Bookings */}
      <section>
        <h3 className="eyebrow text-[var(--color-ink-soft)] mb-4">
          Active bookings ({activeBookings.length})
        </h3>

        <div>
          {activeBookings.map((b, i) => {
            const startFormat = formatDateTime(b.slot_start)
            const endFormat = formatDateTime(b.slot_end)
            const isCheckedIn = b.status === 'checked_in'
            const fac = getFacilityInfo(b.facility_id)

            return (
              <div
                key={b.id}
                className={`flex flex-col sm:flex-row sm:items-center justify-between gap-3 py-4 ${
                  i !== activeBookings.length - 1 ? 'hair' : ''
                }`}
              >
                <div>
                  <div className="text-sm text-[var(--color-ink-soft)] capitalize mb-0.5">
                    {fac.name} · {fac.sport}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[var(--color-ink)] font-medium">{startFormat.date}</span>
                    <span className="text-[var(--color-ember)]">
                      {startFormat.time} – {endFormat.time}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-4">
                  {isCheckedIn ? (
                    <span className="text-sm font-medium text-[var(--color-status-open)]">✓ Checked in</span>
                  ) : (
                    <>
                      <button
                        onClick={() => setSelectedQrBooking(b)}
                        className="btn-primary text-sm px-3 py-1.5"
                      >
                        Show QR
                      </button>
                      <button
                        disabled={cancellingId === b.id}
                        onClick={() => handleCancelBooking(b.id)}
                        className="btn-ghost text-sm"
                      >
                        {cancellingId === b.id ? 'Cancelling…' : 'Cancel'}
                      </button>
                    </>
                  )}
                </div>
              </div>
            )
          })}

          {activeBookings.length === 0 && (
            <p className="py-4 text-sm text-[var(--color-ink-soft)]">No active court bookings.</p>
          )}
        </div>
      </section>

      {/* QR Code Modal */}
      {selectedQrBooking && (
        <div className="fixed inset-0 bg-[var(--color-forest-deep)]/85 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <div className="bg-[var(--color-paper)] max-w-sm w-full p-8 rounded-sm shadow-2xl text-center">
            <div className="flex justify-between items-center mb-6">
              <h3 className="font-[var(--font-display)] text-xl text-[var(--color-ink)]">Check-in credential</h3>
              <button
                onClick={() => setSelectedQrBooking(null)}
                className="text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] text-lg leading-none"
              >
                ✕
              </button>
            </div>

            <div className="flex flex-col items-center gap-4 mb-6">
              <div className="w-40 h-40 bg-white border-2 border-[var(--color-ember)] rounded-sm flex flex-col items-center justify-center p-3 text-center">
                <span className="eyebrow text-[var(--color-ember)]">Lockin QR</span>
                <span className="eyebrow text-[var(--color-ink-soft)] mt-1">Scannable access token</span>
              </div>

              <div className="text-sm text-[var(--color-ink-soft)] flex flex-col gap-1 w-full text-left">
                <div>
                  <span className="text-[var(--color-ink-soft)]">Facility: </span>
                  <span className="text-[var(--color-ink)] font-medium">
                    {getFacilityInfo(selectedQrBooking.facility_id).name}
                  </span>
                </div>
                <div>
                  <span className="text-[var(--color-ink-soft)]">Date: </span>
                  {formatDateTime(selectedQrBooking.slot_start).date}
                </div>
                <div>
                  <span className="text-[var(--color-ink-soft)]">Time: </span>
                  <span className="text-[var(--color-ember)]">
                    {formatDateTime(selectedQrBooking.slot_start).time} –{' '}
                    {formatDateTime(selectedQrBooking.slot_end).time}
                  </span>
                </div>
              </div>
            </div>

            <div className="flex gap-3">
              <button
                onClick={() => setSelectedQrBooking(null)}
                className="flex-1 btn-ghost text-sm py-2.5"
              >
                Close
              </button>
              <button
                disabled={checkinLoading}
                onClick={() => handleExecuteCheckin(selectedQrBooking)}
                className="flex-1 btn-primary text-sm py-2.5 flex items-center justify-center gap-2"
              >
                {checkinLoading ? (
                  <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
                ) : (
                  'Verify check-in'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
