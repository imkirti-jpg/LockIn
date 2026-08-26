import React, { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'

type AuthMode = 'login' | 'signup' | 'forgot' | 'reset' | 'signup_success'

interface LoginViewProps {
  onClose?: () => void
  promptMessage?: string | null
}

export const LoginView: React.FC<LoginViewProps> = ({ onClose, promptMessage }) => {
  const {
    signInWithPassword,
    signUp,
    resetPasswordForEmail,
    updatePassword,
    resendConfirmationEmail,
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

  return (
    <div className="min-h-[80vh] flex items-center justify-center p-4">
      <div className="bg-[#1A2024] border border-[#2D373E] p-8 rounded-md max-w-md w-full shadow-2xl font-mono relative">
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="absolute top-4 right-4 text-gray-400 hover:text-white text-lg font-bold w-8 h-8 flex items-center justify-center rounded hover:bg-[#2D373E] transition-colors"
            title="Continue as Guest"
          >
            ✕
          </button>
        )}

        <div className="flex items-center gap-3 mb-4">
          <div className="w-3.5 h-3.5 bg-[#C97A2B] rounded-sm animate-pulse" />
          <h2 className="text-xl font-bold text-white tracking-wider uppercase">
            Lockin <span className="text-[#C97A2B] text-xs font-normal">Student Portal</span>
          </h2>
        </div>

        {promptMessage && (
          <div className="bg-[#C97A2B]/10 border border-[#C97A2B]/40 text-[#C97A2B] p-3 rounded text-xs mb-4 font-sans font-semibold flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#C97A2B] animate-ping" />
            {promptMessage}
          </div>
        )}

        <p className="text-xs text-gray-400 font-sans mb-4 leading-relaxed">
          {mode === 'login' && 'Sign in to access sports court availability and lock in bookings.'}
          {mode === 'signup' && 'Create your Lockin account using email and password.'}
          {mode === 'forgot' && 'Enter your account email to receive a password reset link.'}
          {mode === 'reset' && 'Enter your new account password.'}
          {mode === 'signup_success' && 'Email confirmation required before logging in.'}
        </p>

        {error && (
          <div className="bg-red-950/50 border border-red-800 text-red-300 p-3 rounded text-xs mb-4 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-500 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {successMessage && (
          <div className="bg-[#16372E] border border-[#1F4B3F] text-emerald-300 p-3 rounded text-xs mb-4">
            {successMessage}
          </div>
        )}

        {/* 1. LOGIN MODE */}
        {mode === 'login' && (
          <form onSubmit={handleSignIn} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Email Address
              </label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in or user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-2">
                <label className="text-xs text-gray-400 uppercase tracking-wider">
                  Password
                </label>
                <button
                  type="button"
                  onClick={() => switchMode('forgot')}
                  className="text-[11px] text-[#C97A2B] hover:underline"
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
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-3 rounded transition-colors tracking-wider border border-[#2A6354] mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              ) : (
                'SIGN IN'
              )}
            </button>

            <div className="text-center text-xs text-gray-400 mt-2">
              Don't have an account?{' '}
              <button
                type="button"
                onClick={() => switchMode('signup')}
                className="text-[#C97A2B] font-bold hover:underline"
              >
                Create account
              </button>
            </div>
          </form>
        )}

        {/* 2. SIGN UP MODE */}
        {mode === 'signup' && (
          <form onSubmit={handleSignUp} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Email Address
              </label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in or user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Password
              </label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="At least 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Confirm Password
              </label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="Re-enter password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-3 rounded transition-colors tracking-wider border border-[#2A6354] mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              ) : (
                'CREATE ACCOUNT'
              )}
            </button>

            <div className="text-center text-xs text-gray-400 mt-2">
              Already have an account?{' '}
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="text-[#C97A2B] font-bold hover:underline"
              >
                Sign in
              </button>
            </div>
          </form>
        )}

        {/* 3. SIGNUP SUCCESS MODE */}
        {mode === 'signup_success' && (
          <div className="flex flex-col gap-4 text-center">
            <div className="p-4 bg-[#121619] border border-[#2D373E] rounded text-xs text-gray-300 leading-relaxed">
              Check your email inbox to confirm your Lockin account before signing in.
            </div>

            <button
              type="button"
              disabled={loading}
              onClick={handleResendConfirmation}
              className="w-full bg-[#121619] hover:bg-[#1A2024] border border-[#2D373E] text-gray-300 hover:text-white font-bold uppercase text-xs py-2.5 rounded transition-colors"
            >
              Resend Confirmation Email
            </button>

            <button
              type="button"
              onClick={() => switchMode('login')}
              className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-2.5 rounded transition-colors border border-[#2A6354]"
            >
              Back to Login
            </button>
          </div>
        )}

        {/* 4. FORGOT PASSWORD MODE */}
        {mode === 'forgot' && (
          <form onSubmit={handleForgot} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Account Email Address
              </label>
              <input
                type="email"
                required
                placeholder="student@iitg.ac.in or user@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-3 rounded transition-colors tracking-wider border border-[#2A6354] mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              ) : (
                'SEND RESET LINK'
              )}
            </button>

            <div className="text-center text-xs text-gray-400 mt-2">
              <button
                type="button"
                onClick={() => switchMode('login')}
                className="text-gray-400 hover:text-white underline"
              >
                Back to Login
              </button>
            </div>
          </form>
        )}

        {/* 5. RESET PASSWORD MODE */}
        {mode === 'reset' && (
          <form onSubmit={handleResetPassword} className="flex flex-col gap-4">
            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                New Password
              </label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="At least 6 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <div>
              <label className="block text-xs text-gray-400 uppercase tracking-wider mb-2">
                Confirm New Password
              </label>
              <input
                type="password"
                required
                minLength={6}
                placeholder="Re-enter new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full bg-[#121619] border border-[#2D373E] text-white px-4 py-2.5 rounded focus:outline-none focus:border-[#1F4B3F] text-sm"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#1F4B3F] hover:bg-[#2A6354] text-white font-bold uppercase text-xs py-3 rounded transition-colors tracking-wider border border-[#2A6354] mt-2 flex items-center justify-center gap-2"
            >
              {loading ? (
                <span className="animate-spin w-4 h-4 border-2 border-white border-t-transparent rounded-full" />
              ) : (
                'UPDATE PASSWORD'
              )}
            </button>
          </form>
        )}

        {onClose && (
          <div className="mt-4 text-center border-t border-[#2D373E] pt-3">
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-gray-400 hover:text-white underline font-sans"
            >
              Continue as Guest
            </button>
          </div>
        )}

        <div className="mt-4 border-t border-[#2D373E] pt-3 text-center text-[11px] text-gray-500">
          IIT Guwahati Sports Board • Authoritative Supabase Auth
        </div>
      </div>
    </div>
  )
}
