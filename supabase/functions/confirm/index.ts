import { html, supabase, tokenHash } from "../_shared/security.ts";
import { confirmationDecision } from "../_shared/state.mjs";

Deno.serve(async (request: Request) => {
  if (request.method !== "GET") return html(request, 405, "Method not allowed.");
  const token = new URL(request.url).searchParams.get("token");
  if (!token || token.length > 200) return html(request, 400, "This confirmation link is invalid or expired.");
  const hash = await tokenHash(token);
  const { data, error: lookupError } = await supabase.from("subscribers").select("id,status,confirmation_expires_at").eq("confirmation_token_hash", hash).maybeSingle();
  if (lookupError) return html(request, 503, "Confirmation is temporarily unavailable.");
  if (!data) return html(request, 400, "This confirmation link is invalid or expired.");
  const decision = confirmationDecision(data.status, data.confirmation_expires_at);
  if (decision === "already_confirmed") return html(request, 200, "Your subscription is already confirmed.");
  if (decision !== "confirm") return html(request, 400, "This confirmation link is invalid or expired.");
  const { error } = await supabase.from("subscribers").update({status:"confirmed",confirmed_at:new Date().toISOString(),unsubscribed_at:null,delivery_failure_status:null}).eq("id", data.id).eq("status", "pending");
  return error ? html(request, 500, "Confirmation is temporarily unavailable.") : html(request, 200, "Your subscription is confirmed.");
});
