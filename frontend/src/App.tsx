import { useEffect, useState } from 'react'
import { AdminDashboardView } from './components/AdminDashboardView'
import { FacilitiesView } from './components/FacilitiesView'
import { FacilityDetailView } from './components/FacilityDetailView'
import { Header } from './components/Header'
import { LoginView } from './components/LoginView'
import { MyBookingsView } from './components/MyBookingsView'
import { useAuth } from './context/AuthContext'

export function App() {
  const { isAuthenticated, isAdmin } = useAuth()
  const [currentTab, setCurrentTab] = useState<'facilities' | 'bookings' | 'admin' | 'detail'>('facilities')
  const [selectedFacilityId, setSelectedFacilityId] = useState<string | null>(null)

  // Guest Mode and Auth Modal State
  const [isGuestMode, setIsGuestMode] = useState<boolean>(false)
  const [showAuthModal, setShowAuthModal] = useState<boolean>(false)
  const [authPromptMessage, setAuthPromptMessage] = useState<string | null>(null)

  // Security Protection: Redirect non-admin users attempting to open admin view
  useEffect(() => {
    if (currentTab === 'admin' && !isAdmin) {
      setCurrentTab('facilities')
    }
  }, [currentTab, isAdmin])

  // Automatically close modal when user successfully authenticates
  useEffect(() => {
    if (isAuthenticated) {
      setShowAuthModal(false)
      setAuthPromptMessage(null)
    }
  }, [isAuthenticated])

  const handleSelectFacility = (facilityId: string) => {
    setSelectedFacilityId(facilityId)
    setCurrentTab('detail')
  }

  const handleNavigate = (tab: 'facilities' | 'bookings' | 'admin') => {
    if (tab === 'admin' && !isAdmin) {
      if (!isAuthenticated) {
        handleRequestAuth('Sign in with admin credentials to access Admin Ops.')
      } else {
        setCurrentTab('facilities')
      }
      return
    }
    if (tab === 'bookings' && !isAuthenticated) {
      handleRequestAuth('Sign in to view your court reservations.')
      return
    }
    setCurrentTab(tab)
    if (tab === 'facilities') {
      setSelectedFacilityId(null)
    }
  }

  const handleRequestAuth = (prompt?: string) => {
    setAuthPromptMessage(prompt || null)
    setShowAuthModal(true)
  }

  const handleCloseAuthModal = () => {
    setShowAuthModal(false)
    setAuthPromptMessage(null)
    setIsGuestMode(true)
  }

  return (
    <div className="min-h-screen bg-[var(--color-paper)] text-[var(--color-ink)] flex flex-col relative">
      <Header
        currentTab={currentTab}
        onNavigate={handleNavigate}
        onRequestAuth={(prompt) => handleRequestAuth(prompt)}
      />

      <main className="flex-grow">
        {/* Initial login prompt screen for unauthenticated users if not yet in guest mode and modal is closed */}
        {!isAuthenticated && !isGuestMode && !showAuthModal ? (
          <LoginView
            onClose={() => setIsGuestMode(true)}
            promptMessage="Sign in or continue as guest to browse facility availability."
            fullPage
          />
        ) : (
          <>
            {(currentTab === 'facilities' || (currentTab === 'detail' && !selectedFacilityId)) && (
              <FacilitiesView onSelectFacility={handleSelectFacility} />
            )}

            {currentTab === 'detail' && selectedFacilityId && (
              <FacilityDetailView
                facilityId={selectedFacilityId}
                onBack={() => handleNavigate('facilities')}
                onBookingSuccess={() => handleNavigate('bookings')}
                onRequestAuth={(prompt) => handleRequestAuth(prompt)}
              />
            )}

            {currentTab === 'bookings' && isAuthenticated && <MyBookingsView />}

            {currentTab === 'admin' && isAuthenticated && isAdmin && <AdminDashboardView />}
          </>
        )}
      </main>

      {/* Action-Triggered Auth Modal */}
      {showAuthModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--color-forest-deep)]/85 backdrop-blur-sm p-4">
          <div className="w-full max-w-md">
            <LoginView
              onClose={handleCloseAuthModal}
              promptMessage={authPromptMessage}
            />
          </div>
        </div>
      )}

      <footer className="bg-[var(--color-forest)] px-6 md:px-10 py-6 mt-auto">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <span className="eyebrow text-[var(--color-cream-soft)]">Lockin — IIT Guwahati Sports Board</span>
          <span className="eyebrow text-[var(--color-cream-soft)]/70">Core booking &amp; ops</span>
        </div>
      </footer>
    </div>
  )
}

export default App
