from __future__ import annotations

import uvicorn

from .config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        reload_dirs=["app", "devtools"] if settings.reload else None,
    )
