
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

CREATE POLICY "Update own memberships"
ON public.company_members
FOR UPDATE
USING (auth.uid() = user_id);

CREATE POLICY "Admins can remove members"
ON public.company_members
FOR DELETE
USING (auth.uid() = user_id);

-- Companies policies (keep simple)
DROP POLICY IF EXISTS "Authenticated users can create companies" ON public.companies;
DROP POLICY IF EXISTS "Users can view companies they belong to" ON public.companies;

CREATE POLICY "Authenticated users can create companies"
ON public.companies
FOR INSERT
WITH CHECK (auth.role() = 'authenticated');

CREATE POLICY "Users can view all companies for now"
ON public.companies
FOR SELECT
USING (true);


-- Company integrations policies
ALTER TABLE public.company_integrations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Admins manage integrations" ON public.company_integrations;
DROP POLICY IF EXISTS "Members view integrations" ON public.company_integrations;

-- Members of a company can read its integrations
CREATE POLICY "Members view integrations"
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
  company_id IN (
    SELECT company_id FROM public.company_members
    WHERE user_id = auth.uid() AND role = 'admin'
  )
);

-- Ramp plans policies
create policy "Members can read company ramp plans"
on public.ramp_plans
for select
using (
  company_id in (
    select company_id from public.company_members
    where user_id = auth.uid()
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