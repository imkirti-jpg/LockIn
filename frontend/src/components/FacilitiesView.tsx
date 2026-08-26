import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Facility } from '../api/client'
import { useAuth } from '../context/AuthContext'

interface FacilitiesViewProps {
  onSelectFacility: (facilityId: string) => void
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
      <div className="flex flex-col items-center justify-center p-12 text-gray-400 font-mono gap-3">
        <div className="w-6 h-6 border-2 border-[#C97A2B] border-t-transparent rounded-full animate-spin" />
        Loading IIT Guwahati Facilities...
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6 bg-red-950/40 border border-red-800 rounded font-mono text-red-300 text-sm max-w-2xl mx-auto mt-8">
        {error}
      </div>
    )
  }

  return (
    <div className="max-w-5xl mx-auto p-6 flex flex-col gap-6">
      {/* Scoreboard Control & Filters */}
      <div className="bg-[#1A2024] border border-[#2D373E] p-4 rounded flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <span className="text-xs font-mono uppercase tracking-widest text-[#C97A2B]">DISCOVERY BOARD</span>
          <h2 className="text-lg font-bold text-white font-mono">IIT Guwahati Sports Facilities</h2>
        </div>

        <div className="flex flex-wrap items-center gap-3 font-mono text-xs">
          <div>
            <label className="text-gray-500 mr-2 uppercase">Sport:</label>
            <select
              value={sportFilter}
              onChange={(e) => setSportFilter(e.target.value)}
              className="bg-[#121619] border border-[#2D373E] text-white px-3 py-1.5 rounded focus:outline-none focus:border-[#1F4B3F]"
            >
              <option value="all">ALL SPORTS</option>
              {sports.map((s) => (
                <option key={s} value={s}>
                  {s.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-gray-500 mr-2 uppercase">Status:</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="bg-[#121619] border border-[#2D373E] text-white px-3 py-1.5 rounded focus:outline-none focus:border-[#1F4B3F]"
            >
              <option value="all">ALL STATUSES</option>
              <option value="open">OPEN</option>
              <option value="maintenance">MAINTENANCE</option>
              <option value="closed">CLOSED</option>
            </select>
          </div>
        </div>
      </div>

      {/* Facilities Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filtered.map((facility) => (
          <div
            key={facility.id}
            onClick={() => onSelectFacility(facility.id)}
            className="bg-[#1A2024] border border-[#2D373E] hover:border-[#1F4B3F] p-5 rounded cursor-pointer transition-all duration-200 flex flex-col justify-between group shadow-lg"
          >
            <div>
              <div className="flex items-center justify-between mb-3">
                <span className="text-[11px] font-mono uppercase px-2 py-0.5 bg-[#121619] text-[#C97A2B] border border-[#2D373E] rounded">
                  {facility.sport_type}
                </span>
                <div className="flex items-center gap-1.5 text-[11px] font-mono uppercase">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      facility.status === 'open'
                        ? 'bg-emerald-500'
                        : facility.status === 'maintenance'
                        ? 'bg-amber-500'
                        : 'bg-red-500'
                    }`}
                  />
                  <span
                    className={
                      facility.status === 'open'
                        ? 'text-emerald-400 font-semibold'
                        : facility.status === 'maintenance'
                        ? 'text-amber-400'
                        : 'text-red-400'
                    }
                  >
                    {facility.status}
                  </span>
                </div>
              </div>

              <h3 className="text-lg font-bold text-white group-hover:text-[#C97A2B] transition-colors font-mono mb-2">
                {facility.name}
              </h3>
            </div>

            <div className="border-t border-[#2D373E] pt-3 mt-4 flex items-center justify-between text-xs font-mono text-gray-400">
              <span>{facility.slot_length_minutes} MIN SLOTS</span>
              <span className="text-[#C97A2B] group-hover:translate-x-1 transition-transform">View Slots →</span>
            </div>
          </div>
        ))}
      </div>

      {filtered.length === 0 && (
        <div className="bg-[#1A2024] border border-[#2D373E] p-8 text-center font-mono text-gray-400 rounded">
          No facilities match the selected filters.
        </div>
      )}
    </div>
  )
}
