import React from 'react'
import { useAuth } from '../context/AuthContext'

interface HeaderProps {
  currentTab: 'facilities' | 'bookings' | 'admin' | 'detail'
  onNavigate: (tab: 'facilities' | 'bookings' | 'admin') => void
  onRequestAuth?: (prompt?: string) => void
}

export const Header: React.FC<HeaderProps> = ({ currentTab, onNavigate, onRequestAuth }) => {
  const { user, logout, isAuthenticated, isAdmin } = useAuth()

  const NavLink: React.FC<{ active: boolean; onClick: () => void; children: React.ReactNode }> = ({
    active,
    onClick,
    children,
  }) => (
    <button
      onClick={onClick}
      className={`relative pb-0.5 text-[15px] transition-colors ${
        active ? 'text-[var(--color-cream)]' : 'text-[var(--color-cream-soft)] hover:text-[var(--color-cream)]'
      }`}
    >
      {children}
      {active && <span className="absolute left-0 right-0 -bottom-1 h-[2px] bg-[var(--color-ember)] rounded-full" />}
    </button>
  )

  return (
    <header className="bg-[var(--color-forest)] sticky top-0 z-50">
      <div className="max-w-6xl mx-auto px-6 md:px-10 py-5 flex items-center justify-between gap-6">
        <div
          className="flex items-baseline gap-3 cursor-pointer shrink-0"
          onClick={() => onNavigate('facilities')}
        >
          <h1 className="font-[var(--font-display)] italic text-[26px] leading-none text-[var(--color-cream)]">
            Lockin
          </h1>
          <span className="eyebrow text-[var(--color-cream-soft)] hidden sm:inline">IIT Guwahati</span>
        </div>

        <nav className="flex items-center gap-7">
          <NavLink active={currentTab === 'facilities' || currentTab === 'detail'} onClick={() => onNavigate('facilities')}>
            Facilities
          </NavLink>
          <NavLink
            active={currentTab === 'bookings'}
            onClick={() => {
              if (isAuthenticated) {
                onNavigate('bookings')
              } else if (onRequestAuth) {
                onRequestAuth('Sign in to view your court reservations.')
              }
            }}
          >
            My Bookings
          </NavLink>
          {isAuthenticated && isAdmin && (
            <NavLink active={currentTab === 'admin'} onClick={() => onNavigate('admin')}>
              Ops Console
            </NavLink>
          )}
        </nav>

        {isAuthenticated ? (
          <div className="flex items-center gap-4 shrink-0">
            <span className="hidden md:inline text-sm text-[var(--color-cream-soft)]">{user?.email}</span>
            <button
              onClick={logout}
              className="eyebrow text-[var(--color-cream-soft)] hover:text-[var(--color-ember)] transition-colors"
            >
              Sign out
            </button>
          </div>
        ) : (
          <button
            onClick={() => onRequestAuth && onRequestAuth()}
            className="btn-primary text-sm px-4 py-2 shrink-0"
          >
            Sign in
          </button>
        )}
      </div>
    </header>
  )
}
