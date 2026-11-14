-- Per-engineer Ramp step usefulness feedback.
-- Feedback is isolated by company, plan, step, and authenticated user.

BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.ramp_plans'::regclass
      AND conname = 'ramp_plans_id_company_id_key'
  ) THEN
    ALTER TABLE public.ramp_plans
      ADD CONSTRAINT ramp_plans_id_company_id_key UNIQUE (id, company_id);
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.ramp_step_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  plan_id UUID NOT NULL,
  company_id TEXT NOT NULL,
  step_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  rating TEXT NOT NULL CHECK (
    rating IN ('useful', 'partially_useful', 'not_useful')
  ),
  reason TEXT CHECK (reason IS NULL OR length(reason) <= 1000),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ramp_step_feedback_plan_company_fkey
    FOREIGN KEY (plan_id, company_id)
    REFERENCES public.ramp_plans(id, company_id) ON DELETE CASCADE,
  CONSTRAINT ramp_step_feedback_plan_step_user_key
    UNIQUE (plan_id, step_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_ramp_step_feedback_company_plan
  ON public.ramp_step_feedback (company_id, plan_id);

ALTER TABLE public.ramp_step_feedback ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ramp_step_feedback FROM anon, authenticated;
GRANT SELECT, INSERT, UPDATE ON TABLE public.ramp_step_feedback TO authenticated;
GRANT ALL ON TABLE public.ramp_step_feedback TO service_role;

CREATE POLICY "members read own Ramp feedback"
ON public.ramp_step_feedback
FOR SELECT TO authenticated
USING (
  user_id = auth.uid()::text
  AND public.is_company_member(company_id)
);

CREATE POLICY "members submit own Ramp feedback"
ON public.ramp_step_feedback
FOR INSERT TO authenticated
WITH CHECK (
  public.assert_real_company(company_id)
  AND user_id = auth.uid()::text
  AND public.is_company_member(company_id)
);

CREATE POLICY "members update own Ramp feedback"
ON public.ramp_step_feedback
FOR UPDATE TO authenticated
USING (
  user_id = auth.uid()::text
  AND public.is_company_member(company_id)
)
WITH CHECK (
  user_id = auth.uid()::text
  AND public.assert_real_company(company_id)
  AND public.is_company_member(company_id)
);

COMMIT;
