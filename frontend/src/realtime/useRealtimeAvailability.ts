import { useEffect, useState } from 'react'
import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://yuwawjbqwpsxutxvovai.supabase.co'
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inl1d2F3amJxd3BzeHV0eHZvdmFpIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODc2NzIyMjAsImV4cCI6MjEwMzI0ODIyMH0.uhOIrQ1TDBpYpqPjXar0bNBvJr5kvRqRHflm1myfQx4'

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)

export type RealtimeStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

export function useRealtimeAvailability(onBookingChanged: () => void) {
  const [status, setStatus] = useState<RealtimeStatus>('connecting')

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null

    // Subscribe to logical replication CDC on bookings table
    const channel = supabase
      .channel('public:bookings_availability')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'bookings',
        },
        () => {
          // Debounce refetch to avoid rapid consecutive requests
          if (timer) clearTimeout(timer)
          timer = setTimeout(() => {
            onBookingChanged()
          }, 150)
        }
      )
      .subscribe((resStatus: string) => {
        if (resStatus === 'SUBSCRIBED') {
          setStatus('connected')
        } else if (resStatus === 'TIMED_OUT' || resStatus === 'CLOSED') {
          setStatus('disconnected')
        } else if (resStatus === 'CHANNEL_ERROR') {
          setStatus('reconnecting')
        }
      })

    return () => {
      if (timer) clearTimeout(timer)
      supabase.removeChannel(channel)
    }
  }, [onBookingChanged])

  return { status }
}
