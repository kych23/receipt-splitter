"""Write the API's OpenAPI schema to web/src/lib/api/openapi.json for frontend type generation.

Usage (from api/): ``uv run python -m app.scripts.export_openapi``
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "web" / "src" / "lib" / "api" / "openapi.json"


def main() -> None:
    # The engine is lazy, so a placeholder URL is enough to build the schema without a database.
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://localhost/unused")
    os.environ.setdefault("ENVIRONMENT", "local")
    from app.main import create_app

    schema = create_app().openapi()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n")
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
