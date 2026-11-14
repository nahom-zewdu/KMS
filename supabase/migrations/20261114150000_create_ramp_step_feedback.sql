BEGIN;

CREATE TABLE IF NOT EXISTS public.ramp_step_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id uuid NOT NULL REFERENCES public.ramp_plans(id) ON DELETE CASCADE,
  company_id text NOT NULL,
  step_id text NOT NULL,
  user_id text NOT NULL,
  rating text NOT NULL CHECK (rating IN ('useful', 'partially_useful', 'not_useful')),
  reason text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ramp_step_feedback_reason_length
    CHECK (reason IS NULL OR char_length(reason) <= 1000),
  CONSTRAINT ramp_step_feedback_plan_step_user_key
    UNIQUE (plan_id, step_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_ramp_step_feedback_plan_step
  ON public.ramp_step_feedback (plan_id, step_id);

CREATE INDEX IF NOT EXISTS idx_ramp_step_feedback_company_plan
  ON public.ramp_step_feedback (company_id, plan_id);

ALTER TABLE public.ramp_step_feedback ENABLE ROW LEVEL SECURITY;

-- Feedback is accessed only by the authenticated NLP backend using service_role.
-- User-facing routes verify identity and company membership before reaching this store.
REVOKE ALL ON TABLE public.ramp_step_feedback FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ramp_step_feedback TO service_role;

COMMENT ON TABLE public.ramp_step_feedback IS
  'Tenant-scoped per-engineer usefulness ratings for Ramp onboarding steps. Backend-only access; API enforces membership and user scoping.';

COMMIT;
