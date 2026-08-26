const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export interface Facility {
  id: string
  name: string
  sport_type: string
  slot_length_minutes: number
  priority_policy: Record<string, any>
  status: 'open' | 'maintenance' | 'closed'
  created_at: string
}

export interface Slot {
  slot_id: string
  facility_id: string
  start_time: string
  end_time: string
  status: 'open' | 'full' | 'past' | 'maintenance'
  booking_id?: string | null
}

export interface Booking {
  id: string
  facility_id: string
  slot_start: string
  slot_end: string
  user_id: string
  status: 'confirmed' | 'cancelled' | 'checked_in' | 'no_show'
  idempotency_key: string
  checkin_token?: string | null
  checked_in_at?: string | null
  created_at: string
}

export interface WaitlistEntry {
  id: string
  facility_id: string
  slot_start: string
  slot_end: string
  user_id: string
  position: number
  status: 'waiting' | 'offered' | 'claimed' | 'expired' | 'cancelled'
  claim_started_at?: string | null
  claim_expires_at?: string | null
  created_at: string
}

export interface PriorityEligibility {
  id: string
  user_id: string
  priority_group: string
  facility_id?: string | null
  active: boolean
  valid_from: string
  valid_until?: string | null
}

export interface FacilityBlock {
  id: string
  facility_id: string
  start_time: string
  end_time: string
  reason: string
  block_type: 'maintenance' | 'event' | 'admin_hold'
  created_by: string
  active: boolean
  created_at: string
}

export interface AnalyticsData {
  ok: boolean
  from_date: string
  to_date: string
  total_bookings: number
  confirmed_count: number
  no_show_count: number
  cancelled_count: number
  waitlist_joins_count: number
  no_show_rate_percent: number
  cancellation_rate_percent: number
  peak_hour: string
  top_facility: string
  facility_demand: Record<string, number>
}

class ApiError extends Error {
  status: number
  data: any
  constructor(status: number, message: string, data?: any) {
    super(message)
    this.status = status
    this.data = data
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}, token?: string | null): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }

  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers,
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    const errorReason = data?.detail?.reason || data?.reason || 'request_failed'
    throw new ApiError(response.status, errorReason, data)
  }

  return data as T
}

export const api = {
  getFacilities: (token?: string | null) =>
    request<{ ok: boolean; count: number; facilities: Facility[] }>('/facilities', {}, token),

  getFacility: (id: string, token?: string | null) =>
    request<{ ok: boolean; facility: Facility }>(`/facilities/${id}`, {}, token),

  getFacilitySlots: (id: string, date: string, token?: string | null) =>
    request<{
      ok: boolean
      facility_id: string
      date: string
      slot_length_minutes: number
      slots: Slot[]
    }>(`/facilities/${id}/slots?date=${date}`, {}, token),

  createBooking: (
    facilityId: string,
    slotStart: string,
    slotEnd: string,
    idempotencyKey: string,
    token?: string | null
  ) =>
    request<{
      ok: boolean
      reason: string
      booking_id: string
      booking: Booking
    }>(
      '/bookings',
      {
        method: 'POST',
        body: JSON.stringify({
          facility_id: facilityId,
          slot_start: slotStart,
          slot_end: slotEnd,
          idempotency_key: idempotencyKey,
        }),
      },
      token
    ),

  getMyBookings: (token?: string | null) =>
    request<{ ok: boolean; count: number; user_id: string; bookings: Booking[] }>('/bookings/me', {}, token),

  cancelBooking: (bookingId: string, token?: string | null) =>
    request<{ ok: boolean; reason: string; booking_id: string }>(
      `/bookings/${bookingId}`,
      { method: 'DELETE' },
      token
    ),

  getMyPriorityEligibility: (token?: string | null) =>
    request<{ ok: boolean; user_id: string; is_priority_eligible: boolean; eligibilities: PriorityEligibility[] }>(
      '/bookings/priority/eligibility/me',
      {},
      token
    ),

  // Waitlist endpoints (Phase 5.1)
  joinWaitlist: (facilityId: string, slotStart: string, slotEnd: string, token?: string | null) =>
    request<{
      ok: boolean
      reason: string
      waitlist_entry: WaitlistEntry
    }>(
      `/waitlist/${facilityId}`,
      {
        method: 'POST',
        body: JSON.stringify({
          slot_start: slotStart,
          slot_end: slotEnd,
        }),
      },
      token
    ),

  getMyWaitlists: (token?: string | null) =>
    request<{ ok: boolean; count: number; user_id: string; waitlist_entries: WaitlistEntry[] }>(
      '/waitlist/me',
      {},
      token
    ),

  getWaitlistEntry: (entryId: string, token?: string | null) =>
    request<{ ok: boolean; waitlist_entry: WaitlistEntry }>(`/waitlist/${entryId}`, {}, token),

  cancelWaitlistEntry: (entryId: string, token?: string | null) =>
    request<{ ok: boolean; reason: string; entry_id: string }>(
      `/waitlist/${entryId}`,
      { method: 'DELETE' },
      token
    ),

  claimWaitlistSlot: (entryId: string, idempotencyKey: string, token?: string | null) =>
    request<{
      ok: boolean
      reason: string
      booking_id: string
      booking: Booking
    }>(
      `/waitlist/${entryId}/claim`,
      {
        method: 'POST',
        body: JSON.stringify({
          idempotency_key: idempotencyKey,
        }),
      },
      token
    ),

  // QR Check-in endpoints (Phase 5.2)
  getCheckinInfo: (bookingId: string, token?: string | null) =>
    request<{ ok: boolean; booking: Booking }>(`/bookings/${bookingId}/checkin`, {}, token),

  executeCheckin: (bookingId: string, checkinToken: string, token?: string | null) =>
    request<{ ok: boolean; reason: string; booking_id: string; checked_in_at: string }>(
      `/bookings/${bookingId}/checkin`,
      {
        method: 'POST',
        body: JSON.stringify({
          checkin_token: checkinToken,
        }),
      },
      token
    ),

  // Admin Ops & Analytics Endpoints (Phase 6)
  getMyRoles: (token?: string | null) =>
    request<{ ok: boolean; user_id: string; roles: Array<{ role: string; facility_id?: string | null }> }>(
      '/admin/me/roles',
      {},
      token
    ),

  getAdminFacilities: (token?: string | null) =>
    request<{ ok: boolean; count: number; admin_role: string; facilities: Facility[]; active_blocks: FacilityBlock[] }>(
      '/admin/facilities',
      {},
      token
    ),

  updateFacilityStatus: (facilityId: string, statusStr: string, token?: string | null) =>
    request<{ ok: boolean; facility_id: string; status: string }>(
      `/admin/facilities/${facilityId}/status`,
      {
        method: 'PATCH',
        body: JSON.stringify({ status: statusStr }),
      },
      token
    ),

  getFacilityBlocks: (facilityId: string, token?: string | null) =>
    request<{ ok: boolean; facility_id: string; blocks: FacilityBlock[] }>(
      `/admin/facilities/${facilityId}/blocks`,
      {},
      token
    ),

  createFacilityBlock: (
    facilityId: string,
    startTime: string,
    endTime: string,
    reason: string,
    blockType: string = 'maintenance',
    token?: string | null
  ) =>
    request<{ ok: boolean; reason: string; block_id: string; affected_bookings_count: number; block: FacilityBlock }>(
      `/admin/facilities/${facilityId}/blocks`,
      {
        method: 'POST',
        body: JSON.stringify({
          start_time: startTime,
          end_time: endTime,
          reason,
          block_type: blockType,
        }),
      },
      token
    ),

  deleteFacilityBlock: (blockId: string, token?: string | null) =>
    request<{ ok: boolean; reason: string; block_id: string }>(
      `/admin/blocks/${blockId}`,
      { method: 'DELETE' },
      token
    ),

  getAdminAnalytics: (fromDate?: string, toDate?: string, token?: string | null) => {
    let url = '/admin/analytics'
    const params: string[] = []
    if (fromDate) params.push(`from=${fromDate}`)
    if (toDate) params.push(`to=${toDate}`)
    if (params.length > 0) url += `?${params.join('&')}`
    return request<AnalyticsData>(url, {}, token)
  },
}
