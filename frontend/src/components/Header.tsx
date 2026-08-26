import React from 'react'
import { useAuth } from '../context/AuthContext'

interface HeaderProps {
  currentTab: 'facilities' | 'bookings' | 'admin' | 'detail'
  onNavigate: (tab: 'facilities' | 'bookings' | 'admin') => void
  onRequestAuth?: (prompt?: string) => void
}

export const Header: React.FC<HeaderProps> = ({ currentTab, onNavigate, onRequestAuth }) => {
  const { user, logout, isAuthenticated, isAdmin } = useAuth()

  return (
    <header className="border-b border-[#2D373E] bg-[#121619] px-6 py-4 flex items-center justify-between sticky top-0 z-50">
      <div className="flex items-center gap-4 cursor-pointer" onClick={() => onNavigate('facilities')}>
        <div className="w-3.5 h-3.5 bg-[#C97A2B] rounded-sm animate-pulse" />
        <h1 className="text-xl font-bold tracking-tight text-[#F3F4F6] uppercase font-mono flex items-center gap-2">
          LOCKIN
          <span className="text-[#C97A2B] text-xs font-normal uppercase tracking-widest bg-[#1F4B3F]/40 px-2 py-0.5 border border-[#1F4B3F] rounded">
            IIT GUWAHATI
          </span>
        </h1>
      </div>

      <div className="flex items-center gap-6 font-mono text-xs">
        <nav className="flex items-center gap-2 bg-[#1A2024] p-1 border border-[#2D373E] rounded">
          <button
            onClick={() => onNavigate('facilities')}
            className={`px-3 py-1.5 rounded uppercase font-semibold transition-colors ${
              currentTab === 'facilities' || currentTab === 'detail'
                ? 'bg-[#1F4B3F] text-white'
                : 'text-gray-400 hover:text-white'
            }`}
          >
            Facilities
          </button>
          <button
            onClick={() => {
              if (isAuthenticated) {
                onNavigate('bookings')
              } else if (onRequestAuth) {
                onRequestAuth('Sign in to view your court reservations.')
              }
            }}
            className={`px-3 py-1.5 rounded uppercase font-semibold transition-colors ${
              currentTab === 'bookings' ? 'bg-[#1F4B3F] text-white' : 'text-gray-400 hover:text-white'
            }`}
          >
            My Bookings
          </button>
          {isAuthenticated && isAdmin && (
            <button
              onClick={() => onNavigate('admin')}
              className={`px-3 py-1.5 rounded uppercase font-semibold transition-colors ${
                currentTab === 'admin' ? 'bg-[#C97A2B] text-black font-bold' : 'text-gray-400 hover:text-white'
              }`}
            >
              Admin Ops
            </button>
          )}
        </nav>

        {isAuthenticated ? (
          <div className="flex items-center gap-3 text-gray-400 border-l border-[#2D373E] pl-4">
            <span className="text-[#10B981] font-semibold">{user?.email}</span>
            <button
              onClick={logout}
              className="text-gray-500 hover:text-red-400 underline transition-colors"
            >
              Sign Out
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-3 border-l border-[#2D373E] pl-4">
            <button
              onClick={() => onRequestAuth && onRequestAuth()}
              className="bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase px-3 py-1.5 rounded transition-colors border border-[#2A6354]"
            >
              Sign In / Register
            </button>
          </div>
        )}
      </div>
    </header>
  )
}
