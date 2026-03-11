# patch_community_civic.py
# Fixes NULL community_civic scores for Cleveland, Hartford, and New Haven
# caused by missing voter turnout data during ingestion.
#
# Strategy: set community_civic to the national median (0.5) for these
# three cities so they score neutrally on this dimension rather than
# propagating NaN through the scoring engine.
#
# Run once on the server:
#   python patch_community_civic.py

import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

AFFECTED_METROS = ["Cleveland, OH", "Hartford, CT", "New Haven, CT"]
NEUTRAL_SCORE = 0.5  # national median percentile

def get_engine():
    url = (
        f"postgresql+psycopg2://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


def patch():
    engine = get_engine()
    with engine.begin() as conn:

        # Fix composite_index.community_civic
        result = conn.execute(text("""
            UPDATE composite_index ci
            SET community_civic = :score
            FROM metros m
            WHERE ci.geo_id = m.cbsa_code
            AND m.name = ANY(:metros)
            AND ci.community_civic IS NULL
            AND ci.geo_level = 'metro'
            RETURNING m.name
        """), {"score": NEUTRAL_SCORE, "metros": AFFECTED_METROS})
        patched = [row[0] for row in result]
        print(f"composite_index patched: {patched}")

        # Fix community_civic table voter_turnout_rate
        result2 = conn.execute(text("""
            UPDATE community_civic cc
            SET voter_turnout_rate = :score,
                voter_participation_rate = :score
            FROM metros m
            WHERE cc.geo_id = m.cbsa_code
            AND m.name = ANY(:metros)
            AND cc.voter_turnout_rate IS NULL
            AND cc.geo_level = 'metro'
            RETURNING m.name
        """), {"score": NEUTRAL_SCORE, "metros": AFFECTED_METROS})
        patched2 = [row[0] for row in result2]
        print(f"community_civic table patched: {patched2}")

    # Verify
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT m.name, ci.community_civic
            FROM composite_index ci
            JOIN metros m ON ci.geo_id = m.cbsa_code
            WHERE m.name = ANY(:metros)
            AND ci.geo_level = 'metro'
        """), {"metros": AFFECTED_METROS}).fetchall()
        print("\nVerification:")
        for row in rows:
            print(f"  {row[0]}: community_civic = {row[1]}")


if __name__ == "__main__":
    patch()
