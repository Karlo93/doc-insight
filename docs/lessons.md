# Lessons

Keep lessons as one-line observations grounded in a defect, test or implementation result.
Each should explain a constraint that the next change can reuse. Milestone narratives belong
in the engineering journal; decisions with alternatives belong in ADRs.

- A transaction must include metadata as well as children: otherwise a failed replacement can label old vectors with a new model version.
- Tenant filters protect reads; composite foreign keys also prevent a write from assigning a child to another tenant's document.

- FORCE RLS does not constrain superusers or BYPASSRLS roles. Exercise contracts through a restricted login, and use transaction-local tenant settings so pooled sessions do not retain tenant identity.

- Resetting a custom Postgres setting can leave an empty string instead of NULL. Normalize it in the policy so missing context cannot authorize rows with an empty tenant id.
