-- ============================================================================
-- Migration: release31b_cadastre_queue_security_invoker
-- Description: make v_cadastre_queue read as its caller, and deny anon.
--
--   release30 created v_cadastre_queue without security_invoker, so it ran
--   as its owner and bypassed cadastre_sources' RLS — and Supabase's
--   default privileges had granted anon every privilege on it. The census
--   was readable anonymously over REST, against release30's own "anon has
--   no rows". The view now executes with the caller's RLS, like every
--   other view in this schema, and only authenticated may select it.

ALTER VIEW public.v_cadastre_queue SET (security_invoker = true);
REVOKE ALL ON public.v_cadastre_queue FROM anon;
REVOKE ALL ON public.v_cadastre_queue FROM authenticated;
GRANT SELECT ON public.v_cadastre_queue TO authenticated;
