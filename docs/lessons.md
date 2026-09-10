# Lessons

- A transaction must include metadata as well as children: otherwise a failed replacement can label old vectors with a new model version.
- Tenant filters protect reads; composite foreign keys also prevent a write from assigning a child to another tenant's document.
