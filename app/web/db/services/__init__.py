"""DB service layer: queries and persistence only, no business rules.

Everything here takes an AsyncSession and returns ORM objects or plain values.
No function in this package inspects a role or raises HTTPException.

    codegraph explore "user_service instrument_service onboarding_service"
"""
