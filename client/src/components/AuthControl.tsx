"use client";

/**
 * The sign-in control — the one surface where an account exists.
 *
 * Compact by design: it sits in the desktop header beside the sync
 * button, shows who is signed in (decisions are attributed), and offers
 * a magic-link sign-in otherwise. Nothing here gates any read surface —
 * the map, dossier and comparison are exactly the same signed out —
 * which is why the control is small and quiet rather than prominent.
 */

import React, { useEffect, useRef, useState } from "react";
import { UserRound, LogOut, Mail } from "lucide-react";
import { useSession, sendMagicLink, signOut } from "@/lib/auth";

export function AuthControl({ compact = false }: { compact?: boolean }) {
  const session = useSession();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<
    { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string }
  >({ kind: "idle" });
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Close the popover on any click outside it — the map behind it is
  // live, so a click there should reach the map, not just dismiss.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || status.kind === "sending") return;
    setStatus({ kind: "sending" });
    const result = await sendMagicLink(email);
    if (result.ok) {
      setStatus({ kind: "sent" });
    } else {
      setStatus({ kind: "error", message: result.error });
    }
  };

  if (!session.ready) {
    // Placeholder keeps the header height stable while the session
    // restores from storage.
    return <div className={compact ? "h-10 w-10" : "h-8 w-8"} aria-hidden="true" />;
  }

  // Compact (mobile masthead): an icon that opens the same popover —
  // the bar has no room for an email address, but "who is signed in"
  // should still be one tap away wherever decisions can be recorded.
  if (compact) {
    return (
      <div className="relative shrink-0" ref={panelRef}>
        <button
          onClick={() => {
            setOpen((v) => !v);
            setStatus({ kind: "idle" });
          }}
          aria-expanded={open}
          aria-label={session.email ? `Signed in as ${session.email}` : "Sign in to record decisions"}
          title={session.email ? `Signed in as ${session.email} — decisions you record are attributed to this address` : "Sign in to record decisions"}
          className={`flex h-10 w-10 items-center justify-center rounded-[3px] bg-surface/95 shadow-plate backdrop-blur transition-colors ${
            session.email ? "text-foreground" : "text-muted"
          }`}
        >
          <UserRound className="h-4 w-4" />
          {session.email && (
            <span className="absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full bg-success dark:bg-success-night" aria-hidden="true" />
          )}
        </button>
        {open && (
          <div className="absolute right-0 top-11 z-[1200] w-72 rounded-[3px] border border-border-strong bg-surface p-4 shadow-overlay">
            {session.email ? (
              <>
                <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted">
                  Signed in
                </p>
                <p className="mt-1.5 break-all font-mono text-[11px] text-foreground">
                  {session.email}
                </p>
                <p className="mt-2 font-sans text-[11px] leading-[1.5] text-muted">
                  Decisions you record are attributed to this address.
                </p>
                <button
                  onClick={() => {
                    void signOut();
                  }}
                  className="mt-3 flex h-8 items-center gap-2 rounded-[2px] border border-border-strong px-3 font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:text-foreground"
                >
                  <LogOut className="h-3 w-3" /> Sign out
                </button>
              </>
            ) : (
              <>
                <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted">
                  Sign in to record decisions
                </p>
                <p className="mt-2 font-sans text-[11.5px] leading-[1.55] text-muted">
                  The survey needs no account — screening, qualification and
                  comparison stay anonymous. Signing in adds one ability:
                  attributing a decision to your email.
                </p>
                <form onSubmit={submit} className="mt-3 flex gap-2">
                  <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    aria-label="Email address"
                    className="h-8 min-w-0 flex-1 rounded-[2px] border border-border-strong bg-background px-2 font-mono text-[11px] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
                  />
                  <button
                    type="submit"
                    disabled={status.kind === "sending"}
                    className="flex h-8 shrink-0 items-center gap-1.5 rounded-[2px] bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.12em] text-background transition-opacity hover:opacity-80 disabled:opacity-60"
                  >
                    <Mail className="h-3 w-3" />
                    {status.kind === "sending" ? "Sending…" : "Send link"}
                  </button>
                </form>
                {status.kind === "sent" && (
                  <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-success dark:text-success-night">
                    Link sent. Check your email — the session opens when you click
                    it.
                  </p>
                )}
                {status.kind === "error" && (
                  <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-danger dark:text-danger-night">
                    {status.message}
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </div>
    );
  }

  if (session.email) {
    return (
      <div
        className="flex h-8 items-center gap-2 rounded-[2px] border border-border-strong bg-surface px-2.5"
        title={`Signed in as ${session.email} — decisions you record are attributed to this address`}
      >
        <UserRound className="h-3 w-3 shrink-0 text-muted" />
        <span className="max-w-[11rem] truncate font-mono text-[10px] tracking-wide text-foreground">
          {session.email}
        </span>
        <button
          onClick={() => {
            void signOut();
          }}
          aria-label="Sign out"
          title="Sign out"
          className="text-muted transition-colors hover:text-foreground"
        >
          <LogOut className="h-3 w-3" />
        </button>
      </div>
    );
  }

  return (
    <div className="relative" ref={panelRef}>
      <button
        onClick={() => {
          setOpen((v) => !v);
          setStatus({ kind: "idle" });
        }}
        aria-expanded={open}
        className="flex h-8 items-center gap-2 rounded-[2px] border border-border-strong bg-surface px-2.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted transition-colors hover:border-foreground/60 hover:text-foreground"
      >
        <UserRound className="h-3 w-3" />
        Sign in
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-[1200] w-72 rounded-[3px] border border-border-strong bg-surface p-4 shadow-overlay">
          <p className="font-mono text-[9px] uppercase tracking-[0.18em] text-muted">
            Sign in to record decisions
          </p>
          <p className="mt-2 font-sans text-[11.5px] leading-[1.55] text-muted">
            The survey needs no account — screening, qualification and
            comparison stay anonymous. Signing in adds one ability:
            attributing a decision to your email.
          </p>
          <form onSubmit={submit} className="mt-3 flex gap-2">
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              aria-label="Email address"
              className="h-8 min-w-0 flex-1 rounded-[2px] border border-border-strong bg-background px-2 font-mono text-[11px] text-foreground placeholder:text-muted focus:border-accent-600 focus:outline-none"
            />
            <button
              type="submit"
              disabled={status.kind === "sending"}
              className="flex h-8 shrink-0 items-center gap-1.5 rounded-[2px] bg-foreground px-3 font-mono text-[10px] uppercase tracking-[0.12em] text-background transition-opacity hover:opacity-80 disabled:opacity-60"
            >
              <Mail className="h-3 w-3" />
              {status.kind === "sending" ? "Sending…" : "Send link"}
            </button>
          </form>
          {status.kind === "sent" && (
            <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-success dark:text-success-night">
              Link sent. Check your email — the session opens when you click
              it.
            </p>
          )}
          {status.kind === "error" && (
            <p className="mt-3 font-sans text-[11.5px] leading-[1.55] text-danger dark:text-danger-night">
              {status.message}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
