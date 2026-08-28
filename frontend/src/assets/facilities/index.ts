// Curated, colour-graded facility photography.
// Mapped by sport_type so any facility the API returns gets a sensible photo
// even without a dedicated photo_url field on the backend.

import thumbCricket from './thumb_cricket.jpg'
import thumbBasketball from './thumb_basketball.jpg'
import thumbBadminton from './thumb_badminton.jpg'
import thumbTennis from './thumb_tennis.jpg'
import thumbFootball from './thumb_football.jpg'
import thumbGym from './thumb_gym.jpg'
import thumbTableTennis from './thumb_tabletennis.jpg'
import thumbTrack from './thumb_track.jpg'
import thumbCampus from './thumb_campus.jpg'

import heroCricket from './hero_cricket.jpg'
import heroBasketball from './hero_basketball.jpg'
import heroBadminton from './hero_badminton.jpg'
import heroTennis from './hero_tennis.jpg'
import heroFootball from './hero_football.jpg'
import heroGym from './hero_gym.jpg'
import heroTableTennis from './hero_tabletennis.jpg'
import heroTrack from './hero_track.jpg'
import heroCampus from './hero_campus.jpg'

export { default as loginBackground } from './loginbg_track.jpg'

interface FacilityImageSet {
  thumb: string
  hero: string
}

const bySport: Record<string, FacilityImageSet> = {
  cricket: { thumb: thumbCricket, hero: heroCricket },
  basketball: { thumb: thumbBasketball, hero: heroBasketball },
  badminton: { thumb: thumbBadminton, hero: heroBadminton },
  tennis: { thumb: thumbTennis, hero: heroTennis },
  football: { thumb: thumbFootball, hero: heroFootball },
  soccer: { thumb: thumbFootball, hero: heroFootball },
  gym: { thumb: thumbGym, hero: heroGym },
  gymnasium: { thumb: thumbGym, hero: heroGym },
  fitness: { thumb: thumbGym, hero: heroGym },
  table_tennis: { thumb: thumbTableTennis, hero: heroTableTennis },
  'table tennis': { thumb: thumbTableTennis, hero: heroTableTennis },
  ping_pong: { thumb: thumbTableTennis, hero: heroTableTennis },
  athletics: { thumb: thumbTrack, hero: heroTrack },
  track: { thumb: thumbTrack, hero: heroTrack },
  running: { thumb: thumbTrack, hero: heroTrack },
}

const fallback: FacilityImageSet = { thumb: thumbCampus, hero: heroCampus }

export function getFacilityImages(sportType: string | undefined | null): FacilityImageSet {
  if (!sportType) return fallback
  const normalized = sportType.toLowerCase().trim()
  if (bySport[normalized]) return bySport[normalized]
  for (const [key, value] of Object.entries(bySport)) {
    if (normalized.includes(key) || key.includes(normalized)) return value
  }
  return fallback
}
