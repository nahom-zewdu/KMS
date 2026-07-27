
-- Simple, non-recursive policies for companies table
CREATE POLICY "Insert own membership"
ON public.company_members
FOR INSERT
WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Select own memberships"
ON public.company_members
FOR SELECT
USING (auth.uid() = user_id);

CREATE POLICY "Update own memberships"
ON public.company_members
FOR UPDATE
USING (auth.uid() = user_id);

CREATE POLICY "Delete own memberships"
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
