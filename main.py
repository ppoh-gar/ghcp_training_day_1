"""FastAPI + NiceGUI application entry point for the ticketing system."""
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from nicegui import app as nicegui_app, ui
import uvicorn

from app.api import create_api_router
from app.database import TicketRepository
from app.ui import mount_ui


def create_app(database_path: str | None = None, seed: bool = True) -> FastAPI:
    """Build the FastAPI app: repository, REST API router, NiceGUI dashboard, and lifespan.

    Args:
        database_path: DuckDB file path, or `":memory:"`. Defaults to the
            `TICKET_DB_PATH` env var, then `"data/tickets.duckdb"`.
        seed: Whether to insert sample tickets if the database is empty.

    Returns:
        A configured `FastAPI` application with the ticket API mounted at
        `/api` and the NiceGUI dashboard mounted at `/`.
    """
    repository = TicketRepository(database_path or os.getenv("TICKET_DB_PATH", "data/tickets.duckdb"))
    if seed:
        repository.seed_defaults()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Close the repository's DuckDB connection when the app shuts down."""
        try:
            yield
        finally:
            repository.close()

    app = FastAPI(title="Ticketing System", version="0.1.0", lifespan=lifespan)
    app.include_router(create_api_router(repository))

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check endpoint used for monitoring."""
        return {"status": "ok"}

    mount_ui(repository)
    ui.run_with(app, title="Ticketing System", favicon="T", storage_secret=os.getenv("NICEGUI_SECRET", "dev-secret"))
    return app


app = create_app()


if __name__ in {"__main__", "__mp_main__"}:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
