export function normaliseEmail(value) {
  if (typeof value !== "string") return null;
  const email = value.trim().toLowerCase();
  if (email.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return null;
  return email;
}

export function confirmationDecision(status, expiry, now = Date.now()) {
  if (status === "confirmed") return "already_confirmed";
  if (status !== "pending") return "invalid";
  if (!expiry || new Date(expiry).getTime() < now) return "expired";
  return "confirm";
}

export function unsubscribeDecision(record) {
  if (!record?.id) return "already_or_unknown";
  if (record.status === "unsubscribed") return "already_or_unknown";
  return "unsubscribe";
}
