import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { loginBackground } from '../assets/facilities'

type AuthMode = 'login' | 'signup' | 'forgot' | 'reset' | 'signup_success'

interface LoginViewProps {
  onClose?: () => void
  promptMessage?: string | null
  /** Full first-load screen gets the campus photo backdrop; the compact auth modal stays on the plain overlay it's already given. */
  fullPage?: boolean
}

export const LoginView: React.FC<LoginViewProps> = ({ onClose, promptMessage, fullPage = false }) => {
  const {
    signInWithPassword,
    signUp,
    resetPasswordForEmail,
    updatePassword,
    resendConfirmationEmail,
    loginDemoUser,
  } = useAuth()

  const [mode, setMode] = useState<AuthMode>('login')

  // Form states
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  // Status & Feedback states
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  // Check if hash includes reset-password route
  useEffect(() => {
    if (window.location.hash.includes('reset-password') || window.location.hash.includes('type=recovery')) {
      setMode('reset')
    }
  }, [])

  const resetForm = () => {
    setError(null)
    setSuccessMessage(null)
    setPassword('')
    setConfirmPassword('')
  }

  const switchMode = (newMode: AuthMode) => {
    resetForm()
    setMode(newMode)
  }

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setLoading(true)

    try {
      const res = await signInWithPassword(email, password)
      if (!res.success) {
        setError(res.error || 'Authentication failed.')
      } else if (onClose) {
        onClose()
      }
    } catch (err: any) {
      setError(err?.message || 'An unexpected error occurred during sign in.')
    } finally {
      setLoading(false)
    }
  }

  const handleDemoLogin = async (role: 'student' | 'sports_admin' = 'student') => {
    setError(null)
    setSuccessMessage(null)
    setLoading(true)
    try {
      await loginDemoUser(role)
      if (onClose) {
        onClose()
      }
    } catch (err: any) {
      setError(err?.message || 'Demo login failed.')
    } finally {
      setLoading(false)
    }
  }

  const handleSignUp = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)

    if (password.length < 6) {
      setError('Password must be at least 6 characters long.')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)

    try {
      const res = await signUp(email, password)
      if (!res.success) {
        setError(res.error || 'Account creation failed.')
      } else if (!res.requireConfirmation) {
        // Immediate login / session established (Email confirmation disabled for dev)
        if (onClose) {
          onClose()
        }
      } else {
        setMode('signup_success')
        setSuccessMessage(`Confirmation email sent to ${email.trim().toLowerCase()}. Please check your inbox and click the confirmation link to activate your account.`)
      }
    } catch (err: any) {
      setError(err?.message || 'An unexpected error occurred during account creation.')
    } finally {
      setLoading(false)
    }
  }

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)
    setLoading(true)

    try {
      const res = await resetPasswordForEmail(email)
      if (!res.success) {
        setError(res.error || 'Failed to send password reset email.')
      } else {
        setSuccessMessage(`Password reset link sent to ${email.trim().toLowerCase()}. Check your email inbox.`)
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to process password reset request.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetPassword = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSuccessMessage(null)

    if (password.length < 6) {
      setError('Password must be at least 6 characters long.')
      return
    }

    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)

    try {
      const res = await updatePassword(password)
      if (!res.success) {
        setError(res.error || 'Failed to update password.')
      } else {
        setSuccessMessage('Password updated successfully! You may now sign in with your new password.')
        setTimeout(() => switchMode('login'), 2000)
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to update password.')
    } finally {
      setLoading(false)
    }
  }

  const handleResendConfirmation = async () => {
    if (!email) return
    setError(null)
    setSuccessMessage(null)
    setLoading(true)

    try {
      const res = await resendConfirmationEmail(email)
      if (!res.success) {
        setError(res.error || 'Failed to resend confirmation email.')
      } else {
        setSuccessMessage(`Resent confirmation email to ${email.trim().toLowerCase()}.`)
      }
    } catch (err: any) {
      setError(err?.message || 'Failed to resend confirmation email.')
    } finally {
      setLoading(false)
    }
  }

  const inputCls = 'field-underline w-full text-[var(--color-ink)] text-sm'
  const labelCls = 'block text-sm text-[var(--color-ink-soft)] mb-1.5'

  return (
    <div
      className="min-h-[80vh] flex items-center justify-center p-4 bg-cover bg-center"
      style={fullPage ? { backgroundImage: `url(${loginBackground})` } : undefined}
    >
      <div className="bg-[var(--color-paper)] p-9 rounded-sm max-w-md w-full shadow-2xl relative">
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="absolute top-5 right-5 text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] text-lg leading-none"
            title="Continue as Guest"
          >
            ✕
          </button>
        )}

        <h2 className="font-[var(--font-display)] italic text-3xl text-[var(--color-ink)] mb-1">
          Lockin
        </h2>
        <span className="eyebrow text-[var(--color-ink-soft)]">Student portal</span>

        {promptMessage && (
          <p className="text-sm text-[var(--color-ember)] mt-5 mb-2 leading-relaxed">
            {promptMessage}
          </p>
        )}

        <p className="text-sm text-[var(--color-ink-soft)] mt-4 mb-6 leading-relaxed">
          {mode === 'login' && 'Sign in to access sports court availability and lock in bookings.'}
          {mode === 'signup' && 'Create your Lockin account using email and password.'}
          {mode === 'forgot' && 'Enter your account email to receive a password reset link.'}
          {mode === 'reset' && 'Enter your new account password.'}
          {mode === 'signup_success' && 'Email confirmation required before logging in.'}
        </p>

        {error && (
          <p className="text-sm text-[var(--color-status-full)] mb-5">{error}</p>
        )}

        {successMessage && (
          <p className="text-sm text-[var(--color-status-open)] mb-5">{successMessage}</p>
        )}

        {/* 1. LOGIN MODE */}
        {mode === 'login' && (
          <form onSubmit={handleSignIn} className="flex flex-col gap-5">
            <div>
              <label className={labelCls}>Email address</label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-1.5">
                <label className="text-sm text-[var(--color-ink-soft)]">Password</label>
                <button
                  type="button"
                  onClick={() => switchMode('forgot')}
                  className="text-sm text-[var(--color-ember)] hover:underline"
                >
                  Forgot password?
                </button>
              </div>
              <input
                type="password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary py-3 text-sm mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
              ) : (
                'Sign in'
              )}
            </button>

            <div className="text-center text-sm text-[var(--color-ink-soft)] mt-1">
              Don't have an account?{' '}
              <button
                type="button"
                onClick={() => switchMode('signup')}
                className="text-[var(--color-ember)] font-medium hover:underline"
              >
                Create account
              </button>
            </div>

            <div className="mt-4 pt-4 border-t border-[var(--color-paper-dim)] flex flex-col gap-2">
              <span className="eyebrow text-xs text-[var(--color-ink-soft)] text-center">Quick Demo Login (Instant Access)</span>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => handleDemoLogin('student')}
                  className="btn-ghost text-xs py-2 border border-[var(--color-ember)]/40 hover:border-[var(--color-ember)] text-[var(--color-ember)] font-medium"
                >
                  ⚡ Demo Student
                </button>
                <button
                  type="button"
                  disabled={loading}
                  onClick={() => handleDemoLogin('sports_admin')}
                  className="btn-ghost text-xs py-2 border border-[var(--color-ink-soft)]/40 hover:border-[var(--color-ink)] font-medium"
                >
                  ⚡ Demo Admin
                </button>
              </div>
            </div>
          </form>
        )}

        {/* 2. SIGN UP MODE */}
        {mode === 'signup' && (
          <form onSubmit={handleSignUp} className="flex flex-col gap-5">
            <div>
              <label className={labelCls}>Email address</label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label className={labelCls}>Password</label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="At least 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label className={labelCls}>Confirm password</label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="Re-enter password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary py-3 text-sm mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
              ) : (
                'Create account'
              )}
            </button>

            <div className="text-center text-sm text-[var(--color-ink-soft)] mt-1">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="text-[var(--color-ember)] font-medium hover:underline"
              >
                Sign in
              </button>
            </div>
          </form>
        )}

        {/* 3. SIGNUP SUCCESS MODE */}
        {mode === 'signup_success' && (
          <div className="flex flex-col gap-4">
            <p className="text-sm text-[var(--color-ink-soft)] leading-relaxed">
              Check your email inbox to confirm your Lockin account before signing in.
            </p>

            <button
              type="button"
              disabled={loading}
              onClick={handleResendConfirmation}
              className="btn-ghost text-sm py-2 text-left"
            >
              Resend confirmation email
            </button>

            <button
              type="button"
              onClick={() => switchMode('login')}
              className="btn-primary py-2.5 text-sm"
            >
              Back to login
            </button>
          </div>
        )}

        {/* 4. FORGOT PASSWORD MODE */}
        {mode === 'forgot' && (
          <form onSubmit={handleForgot} className="flex flex-col gap-5">
            <div>
              <label className={labelCls}>Account email address</label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className={inputCls}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary py-3 text-sm mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
              ) : (
                'Send reset link'
              )}
            </button>

            <div className="text-center text-sm mt-1">
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="btn-ghost text-sm"
              >
                Back to login
              </button>
            </div>
          </form>
        )}

        {/* 5. RESET PASSWORD MODE */}
        {mode === 'reset' && (
          <form onSubmit={handleResetPassword} className="flex flex-col gap-5">
            <div>
              <label className={labelCls}>New password</label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="At least 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <div>
              <label className={labelCls}>Confirm new password</label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="Re-enter new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className={inputCls}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary py-3 text-sm mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-current border-t-transparent rounded-full" />
              ) : (
                'Update password'
              )}
            </button>
          </form>
        )}

        {onClose && (
          <div className="mt-6 text-center">
            <button
              type="button"
              onClick={onClose}
              className="w-full btn-ghost py-2.5 text-sm text-[var(--color-ink)] border border-[var(--color-ink-soft)]/30 hover:bg-[var(--color-paper-dim)] transition-colors rounded-sm"
            >
              Browse Availability as Guest →
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
