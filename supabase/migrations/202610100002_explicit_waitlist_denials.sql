create policy waitlist_signup_browser_deny
  on public.opend_dispatch_waitlist_signups
  for all
  to anon, authenticated
  using (false)
  with check (false);

create policy waitlist_rate_limit_browser_deny
  on public.opend_dispatch_waitlist_rate_limits
  for all
  to anon, authenticated
  using (false)
  with check (false);
