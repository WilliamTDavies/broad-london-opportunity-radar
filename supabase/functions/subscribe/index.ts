import { corsHeaders, json, normaliseEmail, originAllowed, randomToken, rateLimit, requiredEnv, supabase, tokenHash } from "../_shared/security.ts";

Deno.serve(async (request: Request) => {
  if (request.method === "OPTIONS") return new Response(null, {status:204,headers:corsHeaders(request)});
  if (request.method !== "POST" || !originAllowed(request)) return json(request, 403, {message:"Request not allowed"});
  if (!(await rateLimit(request))) return json(request, 429, {message:"Please wait before trying again"});
  let body: Record<string, unknown>;
  try { body = await request.json(); } catch { return json(request, 400, {message:"Invalid request"}); }
  const generic = {message:"If this address can be subscribed, a confirmation email will arrive shortly."};
  if (body.website) return json(request, 202, generic);
  const email = normaliseEmail(body.email);
  if (!email) return json(request, 202, generic);
  const token = randomToken();
  const hash = await tokenHash(token);
  const expiry = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
  const { data: shouldSend, error } = await supabase.rpc("begin_subscription", {subscriber_email:email,new_confirmation_hash:hash,new_confirmation_expiry:expiry});
  if (error || shouldSend !== true) return json(request, 202, generic);
  const confirmUrl = `${requiredEnv("SUPABASE_URL")}/functions/v1/confirm?token=${encodeURIComponent(token)}`;
  const delivery = await fetch("https://api.resend.com/emails", {method:"POST",headers:{"Authorization":`Bearer ${requiredEnv("RESEND_API_KEY")}`,"Content-Type":"application/json","Idempotency-Key":`confirm-${hash}`},body:JSON.stringify({from:requiredEnv("RESEND_FROM_EMAIL"),to:[email],subject:"Confirm your London Opportunity Radar subscription",html:`<p>Confirm your daily opportunity alerts:</p><p><a href="${confirmUrl}">Confirm subscription</a></p><p>This link expires in 24 hours.</p>`,text:`Confirm your subscription: ${confirmUrl}\nThis link expires in 24 hours.`})});
  if (!delivery.ok) await supabase.from("subscribers").update({delivery_failure_status:"confirmation_delivery_failed"}).eq("email", email);
  return json(request, 202, generic);
});
