import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Facility } from '../api/client'
import { useAuth } from '../context/AuthContext'
import { getFacilityImages } from '../assets/facilities'

interface FacilitiesViewProps {
  onSelectFacility: (facilityId: string) => void
}

const statusColor: Record<string, string> = {
  open: 'var(--color-status-open)',
  maintenance: 'var(--color-status-filling)',
  closed: 'var(--color-status-full)',
}

export const FacilitiesView: React.FC<FacilitiesViewProps> = ({ onSelectFacility }) => {
  const { token } = useAuth()
  const [facilities, setFacilities] = useState<Facility[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sportFilter, setSportFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('all')

  useEffect(() => {
    let isMounted = true
    api
      .getFacilities(token)
      .then((data) => {
        if (isMounted) {
          setFacilities(data.facilities || [])
          setLoading(false)
        }
      })
      .catch(() => {
        if (isMounted) {
          setError('Failed to load sports facilities.')
          setLoading(false)
        }
      })
    return () => {
      isMounted = false
    }
  }, [token])

  const sports = Array.from(new Set(facilities.map((f) => f.sport_type)))

  const filtered = facilities.filter((f) => {
    const matchSport = sportFilter === 'all' || f.sport_type === sportFilter
    const matchStatus = statusFilter === 'all' || f.status === statusFilter
    return matchSport && matchStatus
  })

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-24 text-[var(--color-ink-soft)] gap-3">
        <div className="w-5 h-5 border-2 border-[var(--color-ember)] border-t-transparent rounded-full animate-spin" />
        <span className="eyebrow">Loading facilities</span>
      </div>
    )
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-16 px-6">
        <p className="text-[var(--color-status-full)]">{error}</p>
      </div>
    )
  }

  const heroImage = getFacilityImages(filtered[0]?.sport_type).hero

  return (
    <div>
      {/* Restrained full-bleed banner — one photo, quiet gradient, no stacked collage */}
      <div
        className="w-full h-[220px] md:h-[280px] bg-cover bg-center relative"
        style={{ backgroundImage: `url(${heroImage})` }}
      >
        <div className="absolute inset-0 bg-gradient-to-t from-[var(--color-forest-deep)]/80 via-[var(--color-forest-deep)]/10 to-transparent" />
        <div className="relative max-w-4xl mx-auto px-6 md:px-10 h-full flex flex-col justify-end pb-8">
          <span className="eyebrow text-[var(--color-ember)]">Discovery Board</span>
          <h2 className="font-[var(--font-display)] text-[42px] leading-[1.05] mt-1 text-[var(--color-cream)]">
            What's open right now
          </h2>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-6 md:px-10 py-10">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3 mb-10 pb-6 hair text-sm">
        <div className="flex items-center gap-2">
          <span className="text-[var(--color-ink-soft)]">Sport</span>
          <select
            value={sportFilter}
            onChange={(e) => setSportFilter(e.target.value)}
            className="field-underline text-[var(--color-ink)] cursor-pointer"
          >
            <option value="all">All sports</option>
            {sports.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-[var(--color-ink-soft)]">Status</span>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="field-underline text-[var(--color-ink)] cursor-pointer"
          >
            <option value="all">All statuses</option>
            <option value="open">Open</option>
            <option value="maintenance">Maintenance</option>
            <option value="closed">Closed</option>
          </select>
        </div>
      </div>

      {/* Editorial listing — hairline between rows, no boxed cards */}
      <div>
        {filtered.map((facility, i) => (
          <div
            key={facility.id}
            onClick={() => onSelectFacility(facility.id)}
            className={`group flex items-center justify-between gap-6 py-6 cursor-pointer transition-colors hover:bg-[var(--color-paper-dim)] -mx-4 px-4 ${
              i !== filtered.length - 1 ? 'hair' : ''
            }`}
          >
            <div className="flex items-center gap-5 min-w-0">
              <img
                src={getFacilityImages(facility.sport_type).thumb}
                alt=""
                className="w-16 h-12 md:w-20 md:h-14 object-cover rounded-[3px] shrink-0"
                loading="lazy"
              />
              <div className="min-w-0">
                <h3 className="font-[var(--font-display)] text-2xl text-[var(--color-ink)] group-hover:text-[var(--color-ember)] transition-colors truncate">
                  {facility.name}
                </h3>
                <span className="text-sm text-[var(--color-ink-soft)] capitalize">
                  {facility.sport_type} · {facility.slot_length_minutes} min slots
                </span>
              </div>
            </div>

            <div className="flex items-center gap-6 shrink-0">
              <div className="hidden sm:flex items-center gap-2">
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: statusColor[facility.status] }}
                />
                <span className="text-sm capitalize" style={{ color: statusColor[facility.status] }}>
                  {facility.status}
                </span>
              </div>
              <span className="text-[var(--color-ember)] opacity-0 group-hover:opacity-100 transition-opacity text-sm">
                View slots →
              </span>
            </div>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="py-16 text-center text-[var(--color-ink-soft)]">
          No facilities match the selected filters.
        </div>
      )}
      </div>
    </div>
  )
}
