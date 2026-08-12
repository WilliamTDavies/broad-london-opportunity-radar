import { corsHeaders, html, json, supabase, tokenHash } from "../_shared/security.ts";
import { unsubscribeDecision } from "../_shared/state.mjs";

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response(null, {status:204,headers:corsHeaders(request)});
  if (!["GET","POST"].includes(request.method)) return json(request, 405, {message:"Method not allowed"});
  let token = new URL(request.url).searchParams.get("token");
  if (!token && request.method === "POST") { try { token = (await request.json()).token; } catch { token = null; } }
  if (!token || token.length > 200) return request.method === "GET" ? html(request, 400, "This unsubscribe link is invalid.") : json(request, 400, {message:"Invalid request"});
  const hash = await tokenHash(token);
  const { data, error: lookupError } = await supabase.from("subscribers").select("id,status").contains("unsubscribe_token_hashes", [hash]).maybeSingle();
  if (lookupError) return request.method === "GET" ? html(request, 503, "Unsubscribe is temporarily unavailable.") : json(request, 503, {message:"Temporarily unavailable"});
  if (unsubscribeDecision(data) === "unsubscribe") {
    const { error } = await supabase.from("subscribers").update({status:"unsubscribed",unsubscribed_at:new Date().toISOString()}).eq("id", data.id);
    if (error) return request.method === "GET" ? html(request, 503, "Unsubscribe is temporarily unavailable.") : json(request, 503, {message:"Temporarily unavailable"});
  }
  return request.method === "GET" ? html(request, 200, "You have been unsubscribed. If this link was already used, no further action was needed.") : json(request, 200, {message:"Unsubscribed"});
});
