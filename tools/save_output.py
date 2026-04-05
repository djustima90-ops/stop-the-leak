"""Save a rendered HTML report to the Supabase reports table."""

from tools.supabase_client import get_supabase


def save_output(
    html: str,
    business_name: str,
    url: str = "",
    grade: str = "",
) -> str:
    """Insert the rendered report into Supabase and return its uuid.

    Args:
        html: Rendered HTML report string.
        business_name: Business display name for this report.
        url: URL that was audited.
        grade: Letter grade (A/B/C/D/F) assigned to the report.

    Returns:
        The uuid (as a string) of the inserted report row.
    """
    client = get_supabase()
    response = (
        client.table("reports")
        .insert({
            "business_name": business_name,
            "url": url,
            "grade": grade,
            "html": html,
        })
        .execute()
    )
    rows = response.data or []
    if not rows:
        raise RuntimeError("Supabase reports insert returned no rows.")
    return rows[0]["id"]
