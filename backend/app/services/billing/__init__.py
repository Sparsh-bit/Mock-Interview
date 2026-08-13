"""
Plans, entitlement and payment — services/billing/

`plans.py`    what each tier includes and costs; the single source of truth.
`credits.py`  checking and consuming an allowance, with the concurrency guarantee.
`razorpay.py` turning a payment into a plan change, and verifying it really was one.
"""
