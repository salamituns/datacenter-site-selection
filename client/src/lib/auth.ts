"use client";

/**
 * Session — magic-link identity for recording decisions, and nothing
 * else. The public map stays anonymous: every read surface is readable
 * by anon, so signing in changes what a visitor can record, never what
 * they can see. The auth surface is deliberately small — an email, a
 * link, a session — because that is all a decision's authorship needs.
 *
 * Uses the same Supabase client as the read path (supabase-js persists
 * the session in localStorage and picks tokens out of the magic-link
 * redirect automatically), so there is exactly one client and one
 * session store in the browser.
 */

import { useEffect, useState } from "react";
import { Session } from "@supabase/supabase-js";
import { supabase } from "@/lib/supabase";

export interface SessionState {
  /** null while restoring, then the session or null once known. */
  ready: boolean;
  userId: string | null;
  email: string | null;
}

/**
 * Subscribes to the session. One subscription per consumer is fine (the
 * client deduplicates its own auth state), and each consumer sees the
 * same session.
 */
export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({
    ready: false,
    userId: null,
    email: null,
  });

  useEffect(() => {
    if (!supabase) {
      setState({ ready: true, userId: null, email: null });
      return;
    }
    // getSession first: onAuthStateChange alone misses the initial
    // state on a page load that restored a session from storage.
    supabase.auth
      .getSession()
      .then(({ data }: { data: { session: Session | null } }) => {
        setState({
          ready: true,
          userId: data.session?.user?.id ?? null,
          email: data.session?.user?.email ?? null,
        });
      })
      .catch(() => setState({ ready: true, userId: null, email: null }));

    const { data: sub } = supabase.auth.onAuthStateChange(
      (_event: string, session: Session | null) => {
        setState({
          ready: true,
          userId: session?.user?.id ?? null,
          email: session?.user?.email ?? null,
        });
      }
    );
    return () => sub.subscription.unsubscribe();
  }, []);

  return state;
}

export type SendLinkResult =
  | { ok: true }
  | { ok: false; error: string };

/**
 * Sends a magic link. The redirect targets the origin the page is
 * actually served from, so the link lands back on this site (localhost
 * in development, the production domain once it is on the project's
 * redirect allowlist).
 */
export async function sendMagicLink(email: string): Promise<SendLinkResult> {
  if (!supabase) return { ok: false, error: "Supabase is not configured." };
  try {
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: {
        emailRedirectTo:
          typeof window !== "undefined" ? window.location.origin : undefined,
      },
    });
    if (error) return { ok: false, error: error.message };
    return { ok: true };
  } catch (err) {
    return {
      ok: false,
      error: err instanceof Error ? err.message : "Could not send the link.",
    };
  }
}

export async function signOut(): Promise<void> {
  await supabase?.auth.signOut();
}
