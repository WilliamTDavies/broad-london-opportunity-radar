import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.4";
export { normaliseEmail } from "./state.mjs";

export function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) throw new Error(`Missing required environment variable: ${name}`);
  return value;
}

export const allowedOrigin = requiredEnv("ALLOWED_ORIGIN");
export const supabase = createClient(
  requiredEnv("SUPABASE_URL"),
  requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
  { auth: { persistSession: false } },
);

export function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin": origin === allowedOrigin ? origin : allowedOrigin,
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Vary": "Origin",
    "Cache-Control": "no-store",
  };
}

export function originAllowed(request: Request): boolean {
  const origin = request.headers.get("origin");
  return !origin || origin === allowedOrigin;
}

export function json(request: Request, status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { ...corsHeaders(request), "Content-Type": "application/json; charset=utf-8" },
  });
}

export function html(request: Request, status: number, body: string): Response {
  return new Response(`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>London Opportunity Radar</title><body><main><h1>London Opportunity Radar</h1><p>${escapeHtml(body)}</p></main></body></html>`, {
    status,
    headers: { ...corsHeaders(request), "Content-Type": "text/html; charset=utf-8" },
  });
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, char => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char] ?? char));
}

export function randomToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

export async function tokenHash(token: string): Promise<string> {
  const secret = requiredEnv("TOKEN_SECRET");
  if (secret.length < 32) throw new Error("TOKEN_SECRET must contain at least 32 characters");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret), {name:"HMAC",hash:"SHA-256"}, false, ["sign"]);
  const digest = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(token));
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

export async function rateLimit(request: Request): Promise<boolean> {
  const address = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";
  const key = await tokenHash(`subscribe:${address}`);
  const { data, error } = await supabase.rpc("consume_rate_limit", {request_key_hash:key,maximum_requests:5,window_minutes:60});
  return !error && data === true;
}
