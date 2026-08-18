import { z } from "zod";

// Query params arrive as strings over HTTP - z.coerce converts them, and
// the refine below makes sure the caller picked one real search mode
// ("Nearby": lat+lng, or "Choose a region": country [+ optional city]).
export const discoverRoomsQuerySchema = z
  .object({
    lat: z.coerce.number().min(-90).max(90).optional(),
    lng: z.coerce.number().min(-180).max(180).optional(),
    radiusKm: z.coerce.number().min(1).max(500).optional(),
    country: z.string().trim().min(1).max(60).optional(),
    city: z.string().trim().min(1).max(80).optional(),
    // Optional - scopes the search to rooms under a single event. Used by
    // the per-event rooms lobby's "Near you" filter (RoomsLobbyPage) so it
    // never has to fetch or leak location results from other events.
    // Validated as a Mongo ObjectId shape so a malformed value fails fast
    // with a 400 here instead of surfacing as an unhandled CastError (500)
    // once it reaches the database query.
    eventId: z
      .string()
      .trim()
      .regex(/^[a-f\d]{24}$/i, "Invalid eventId")
      .optional(),
  })
  .refine((q) => (q.lat !== undefined && q.lng !== undefined) || !!q.country, {
    message:
      "Provide either lat & lng (nearby search) or a country (region search)",
  });

export type DiscoverRoomsQuery = z.infer<typeof discoverRoomsQuerySchema>;
