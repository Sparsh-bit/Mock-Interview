"""
Account-security services — services/security/

`sharing.py` lived here and detected one account being used from two networks at once,
suspending it. It has been removed along with the rest of that feature: the population it
actually caught was candidates on phones moving between college wi-fi and mobile data, and its
strike counter incremented per REQUEST rather than per overlap, so a single network handover
mid-interview suspended the account and took `/complete` with it. See the note in
core/security.py for the full reasoning.

`models/security.py` and the `user_plans` ban columns are intentionally still present and are
now inert — no migration, no data loss, and nothing gates on them.
"""
