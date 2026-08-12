import test from "node:test";
import assert from "node:assert/strict";
import { confirmationDecision, normaliseEmail, unsubscribeDecision } from "../../supabase/functions/_shared/state.mjs";

test("email addresses are normalised without accepting malformed input", () => {
  assert.equal(normaliseEmail("  Reader@Example.COM "), "reader@example.com");
  assert.equal(normaliseEmail("not-an-email"), null);
  assert.equal(normaliseEmail("a".repeat(255) + "@example.com"), null);
});

test("confirmation is idempotent only while still subscribed", () => {
  const future = new Date(Date.now() + 60_000).toISOString();
  assert.equal(confirmationDecision("pending", future), "confirm");
  assert.equal(confirmationDecision("confirmed", future), "already_confirmed");
  assert.equal(confirmationDecision("unsubscribed", future), "invalid");
});

test("expired confirmation links cannot confirm", () => {
  const past = new Date(Date.now() - 60_000).toISOString();
  assert.equal(confirmationDecision("pending", past), "expired");
  assert.equal(confirmationDecision("pending", null), "expired");
});

test("unsubscribe is idempotent and does not disclose an unknown token", () => {
  assert.equal(unsubscribeDecision({ id: "1", status: "confirmed" }), "unsubscribe");
  assert.equal(unsubscribeDecision({ id: "1", status: "unsubscribed" }), "already_or_unknown");
  assert.equal(unsubscribeDecision(null), "already_or_unknown");
});
