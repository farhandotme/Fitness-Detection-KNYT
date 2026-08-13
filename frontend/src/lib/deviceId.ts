const DEVICE_ID_KEY = "fitness_device_id";

/**
 * A random id generated once per browser and persisted in localStorage.
 * Sent with every competition join so the backend can recognize "this is
 * the same person trying to join again" without requiring login, and
 * reattach them to their existing seat instead of handing out a second one
 * (see competition-backend's competitionService.joinEvent). Best-effort by
 * design: clearing storage or using a different browser resets it, the same
 * way clearing the per-competition participant identity would.
 */
export function getDeviceId(): string {
  let id = localStorage.getItem(DEVICE_ID_KEY);
  if (!id) {
    id =
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `dev_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(DEVICE_ID_KEY, id);
  }
  return id;
}
