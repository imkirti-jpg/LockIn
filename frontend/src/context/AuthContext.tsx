import React, { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { createClient } from '@supabase/supabase-js'
import { api } from '../api/client'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://yuwawjbqwpsxutxvovai.supabase.co'
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl1d2F3amJxd3BzeHV0eHZvdmFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc2NzIyMjAsImV4cCI6MjEwMzI0ODIyMH0.uhOIrQ1TDBpYpqPjXar0bNBvJr5kvRqRHflm1myfQx4'

export const supabaseAuth = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

export interface User {
  id: string
  email: string
  role: 'student' | 'facility_manager' | 'sports_admin'
  isAdmin: boolean
}

interface AuthContextType {
  user: User | null
  token: string | null
  signUp: (email: string, password: string) => Promise<{ success: boolean; error?: string; requireConfirmation?: boolean }>
  signInWithPassword: (email: string, password: string) => Promise<{ success: boolean; error?: string }>
  resetPasswordForEmail: (email: string) => Promise<{ success: boolean; error?: string }>
  updatePassword: (newPassword: string) => Promise<{ success: boolean; error?: string }>
  resendConfirmationEmail: (email: string) => Promise<{ success: boolean; error?: string }>
  logout: () => Promise<void>
  isAuthenticated: boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  const fetchRolesAndSetUser = useCallback(async (uId: string, emailStr: string, tokStr: string) => {
    let resolvedRole: 'student' | 'facility_manager' | 'sports_admin' = 'student'

    try {
      const roleRes = await api.getMyRoles(tokStr)
      if (roleRes.roles && roleRes.roles.length > 0) {
        const hasSportsAdmin = roleRes.roles.some((r) => r.role === 'sports_admin')
        const hasManager = roleRes.roles.some((r) => r.role === 'facility_manager')
        if (hasSportsAdmin) {
          resolvedRole = 'sports_admin'
        } else if (hasManager) {
          resolvedRole = 'facility_manager'
        }
      }
    } catch (err) {
      console.warn('Could not fetch user roles from backend user_roles table:', err)
    }

    const updatedUser: User = {
      id: uId,
      email: emailStr,
      role: resolvedRole,
      isAdmin: resolvedRole === 'sports_admin' || resolvedRole === 'facility_manager',
    }

    setUser(updatedUser)
    localStorage.setItem('lockin_user', JSON.stringify(updatedUser))
  }, [])

  useEffect(() => {
    // 1. Get current active session from Supabase Auth
    supabaseAuth.auth.getSession().then(({ data: { session } }) => {
      if (session?.user && session.access_token) {
        const uId = session.user.id
        const email = session.user.email || ''
        setToken(session.access_token)
        localStorage.setItem('lockin_token', session.access_token)
        fetchRolesAndSetUser(uId, email, session.access_token)
        return
      }

      const savedUserStr = localStorage.getItem('lockin_user')
      const savedToken = localStorage.getItem('lockin_token')
      if (savedUserStr && savedToken) {
        try {
          const parsed = JSON.parse(savedUserStr)
          setToken(savedToken)
          fetchRolesAndSetUser(parsed.id, parsed.email, savedToken)
        } catch {
          // Ignore
        }
      }
    })

    // 2. Listen to Supabase Auth state changes
    const { data: { subscription } } = supabaseAuth.auth.onAuthStateChange((event, session) => {
      if (session?.user && session.access_token) {
        const uId = session.user.id
        const email = session.user.email || ''
        setToken(session.access_token)
        localStorage.setItem('lockin_token', session.access_token)
        fetchRolesAndSetUser(uId, email, session.access_token)
      } else if (event === 'SIGNED_OUT') {
        setUser(null)
        setToken(null)
        localStorage.removeItem('lockin_user')
        localStorage.removeItem('lockin_token')
      }
    })

    return () => {
      subscription.unsubscribe()
    }
  }, [fetchRolesAndSetUser])

  const validateDomain = (email: string): { allowed: boolean; error?: string } => {
    const cleanEmail = email.trim().toLowerCase()
    const allowedDomain = import.meta.env.VITE_AUTH_ALLOWED_EMAIL_DOMAIN || (import.meta.env.VITE_ENFORCE_IITG_DOMAIN === 'true' ? 'iitg.ac.in' : '')

    if (allowedDomain && !cleanEmail.endsWith('@' + allowedDomain)) {
      return {
        allowed: false,
        error: `Production requirement: Only @${allowedDomain} email addresses are permitted.`,
      }
    }
    return { allowed: true }
  }

  const signUp = async (email: string, password: string) => {
    const cleanEmail = email.trim().toLowerCase()
    const domainCheck = validateDomain(cleanEmail)
    if (!domainCheck.allowed) {
      return { success: false, error: domainCheck.error }
    }

    try {
      const { data, error } = await supabaseAuth.auth.signUp({
        email: cleanEmail,
        password: password,
        options: {
          emailRedirectTo: window.location.origin,
        },
      })

      if (error) {
        console.error('[Supabase Auth] signUp error:', error)
        let friendlyMsg = error.message
        if (error.message.toLowerCase().includes('user already registered') || error.message.toLowerCase().includes('already exists')) {
          friendlyMsg = 'An account with this email already exists. Try signing in instead.'
        } else if (error.message.toLowerCase().includes('rate limit') || error.status === 429) {
          friendlyMsg = error.message || 'Too many signup attempts. Please wait 60 seconds before trying again.'
        } else if (error.message.toLowerCase().includes('disabled')) {
          friendlyMsg = 'Email signups are currently disabled in your Supabase Auth project configuration.'
        }
        return { success: false, error: friendlyMsg }
      }

      if (data?.user) {
        if (data.session && data.session.access_token) {
          const uId = data.user.id
          const tok = data.session.access_token
          setToken(tok)
          localStorage.setItem('lockin_token', tok)
          await fetchRolesAndSetUser(uId, cleanEmail, tok)
          return { success: true, requireConfirmation: false }
        }

        const isConfirmed = !!data.user.confirmed_at
        return {
          success: true,
          requireConfirmation: !isConfirmed,
        }
      }

      return { success: false, error: 'Sign up failed. Please check your network connection.' }
    } catch (err: any) {
      console.error('[Supabase Auth] signUp exception:', err)
      return { success: false, error: err?.message || 'Sign up request failed due to a network error.' }
    }
  }

  const signInWithPassword = async (email: string, password: string) => {
    const cleanEmail = email.trim().toLowerCase()
    const domainCheck = validateDomain(cleanEmail)
    if (!domainCheck.allowed) {
      return { success: false, error: domainCheck.error }
    }

    try {
      const { data, error } = await supabaseAuth.auth.signInWithPassword({
        email: cleanEmail,
        password: password,
      })

      if (error) {
        console.error('[Supabase Auth] signInWithPassword error:', error)
        if (error.message.toLowerCase().includes('email not confirmed')) {
          return { success: false, error: 'Email not confirmed. Please check your inbox and click the confirmation link.' }
        }
        if (error.message.toLowerCase().includes('invalid login credentials')) {
          return { success: false, error: 'Invalid email or password. Please verify your credentials or create an account.' }
        }
        return { success: false, error: error.message || 'Invalid email or password.' }
      }

      if (data?.session && data.user) {
        const uId = data.user.id
        const tok = data.session.access_token
        setToken(tok)
        localStorage.setItem('lockin_token', tok)
        await fetchRolesAndSetUser(uId, cleanEmail, tok)
        return { success: true }
      }

      return { success: false, error: 'Authentication failed.' }
    } catch (err: any) {
      console.error('[Supabase Auth] signInWithPassword exception:', err)
      return { success: false, error: err?.message || 'Sign in request failed.' }
    }
  }

  const resetPasswordForEmail = async (email: string) => {
    const cleanEmail = email.trim().toLowerCase()
    const domainCheck = validateDomain(cleanEmail)
    if (!domainCheck.allowed) {
      return { success: false, error: domainCheck.error }
    }

    try {
      const { error } = await supabaseAuth.auth.resetPasswordForEmail(cleanEmail, {
        redirectTo: `${window.location.origin}/#reset-password`,
      })
      if (error) {
        console.error('[Supabase Auth] resetPasswordForEmail error:', error)
        return { success: false, error: error.message }
      }
      return { success: true }
    } catch (err: any) {
      console.error('[Supabase Auth] resetPasswordForEmail exception:', err)
      return { success: false, error: 'Password reset request failed.' }
    }
  }

  const updatePassword = async (newPassword: string) => {
    try {
      const { error } = await supabaseAuth.auth.updateUser({
        password: newPassword,
      })
      if (error) {
        console.error('[Supabase Auth] updateUser error:', error)
        return { success: false, error: error.message }
      }
      return { success: true }
    } catch (err: any) {
      console.error('[Supabase Auth] updateUser exception:', err)
      return { success: false, error: 'Failed to update password.' }
    }
  }

  const resendConfirmationEmail = async (email: string) => {
    const cleanEmail = email.trim().toLowerCase()
    try {
      const { error } = await supabaseAuth.auth.resend({
        type: 'signup',
        email: cleanEmail,
        options: {
          emailRedirectTo: window.location.origin,
        },
      })
      if (error) {
        console.error('[Supabase Auth] resend error:', error)
        return { success: false, error: error.message }
      }
      return { success: true }
    } catch (err: any) {
      console.error('[Supabase Auth] resend exception:', err)
      return { success: false, error: 'Failed to resend confirmation email.' }
    }
  }

  const logout = async () => {
    try {
      await supabaseAuth.auth.signOut()
    } catch {
      // Ignore
    }
    setUser(null)
    setToken(null)
    localStorage.removeItem('lockin_user')
    localStorage.removeItem('lockin_token')
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        signUp,
        signInWithPassword,
        resetPasswordForEmail,
        updatePassword,
        resendConfirmationEmail,
        logout,
        isAuthenticated: !!user,
        isAdmin: !!user?.isAdmin,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
