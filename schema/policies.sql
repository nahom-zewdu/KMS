
-- Tenant-scoped access policies.
-- These rules intentionally prevent self-service membership creation or role escalation.

ALTER TABLE public.companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.company_integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ramp_step_progress ENABLE ROW LEVEL SECURITY;

-- Companies: members can read their own companies and authenticated users may create a company.
CREATE POLICY "Members can read their companies"
ON public.companies
FOR SELECT
USING (
  id IN (
    SELECT company_id FROM public.company_members WHERE user_id = auth.uid()
  )
);

CREATE POLICY "Authenticated users can create companies"
ON public.companies
FOR INSERT
WITH CHECK (
  auth.uid() IS NOT NULL
  AND id IS NOT NULL
  AND lower(btrim(id)) <> 'default'
);

-- Membership: users may read only their own membership or admin-managed membership records.
CREATE POLICY "Users can read their memberships"
ON public.company_members
FOR SELECT
USING (
  user_id = auth.uid()
  OR company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
  )
);

CREATE POLICY "Admins can invite or add members"
ON public.company_members
FOR INSERT
WITH CHECK (
  company_id IS NOT NULL
  AND lower(btrim(company_id)) <> 'default'
  AND EXISTS (
    SELECT 1
    FROM public.company_members as cm
    WHERE cm.user_id = auth.uid()
      AND cm.company_id = company_members.company_id
      AND cm.role IN ('admin', 'manager')
  )
  AND NOT (user_id = auth.uid() AND role IN ('admin', 'manager'))
);

CREATE POLICY "Admins can update member roles"
ON public.company_members
FOR UPDATE
USING (
  company_id IN (
    SELECT company_id
    FROM public.company_members
    WHERE user_id = auth.uid() AND role IN ('admin', 'manager')
  )
)
WITH CHECK (
  company_id IS NOT NULL
  AND lower(btrim(company_id)) <> 'default'
  AND EXISTS (
    SELECT 1
    FROM public.company_members as cm
    WHERE cm.user_id = auth.uid()
      AND cm.company_id = company_members.company_id
      AND cm.role IN ('admin', 'manager')
  )
  AND NOT (user_id = auth.uid() AND role IN ('admin', 'manager'))
);

CREATE POLICY "Admins can remove members"
ON public.company_members
FOR DELETE
USING (
  EXISTS (
    SELECT 1
    FROM public.company_members as cm
    WHERE cm.user_id = auth.uid()
      AND cm.company_id = company_members.company_id
      AND cm.role IN ('admin', 'manager')
  )
  AND user_id <> auth.uid()
);

-- Company integrations: members can read, admins manage.
CREATE POLICY "Members can view integrations"
ON public.company_integrations
FOR SELECT
USING (
  company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid()
  )
);

-- Admins can insert/update/delete
CREATE POLICY "Admins manage integrations"
ON public.company_integrations
FOR ALL
USING (
  company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role = 'admin'
  )
)
WITH CHECK (
  company_id IS NOT NULL
  AND lower(btrim(company_id)) <> 'default'
  AND company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role = 'admin'
  )
);

-- Ramp plans: company members can read, admins manage.
CREATE POLICY "Members can read ramp plans"
ON public.ramp_plans
FOR SELECT
USING (
  company_id IN (
    SELECT company_id FROM public.company_members WHERE user_id = auth.uid()
  )
);

CREATE POLICY "Admins can manage ramp plans"
ON public.ramp_plans
FOR ALL
USING (
  company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role = 'admin'
  )
)
WITH CHECK (
  company_id IS NOT NULL
  AND lower(btrim(company_id)) <> 'default'
  AND company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role = 'admin'
  )
);

-- Ramp step progress: members can read their own progress and admins manage company entries.
CREATE POLICY "Members can read company ramp progress"
ON public.ramp_step_progress
FOR SELECT
USING (
  company_id IN (
    SELECT company_id FROM public.company_members WHERE user_id = auth.uid()
  )
);

-- Ramp step progress policies
create policy "Members can manage company ramp progress"
on public.ramp_step_progress
for all
using (
  company_id in (
    select company_id from public.company_members
    where user_id = auth.uid()
  )
)
with check (
  company_id in (
    select company_id from public.company_members
    where user_id = auth.uid()
  )
);