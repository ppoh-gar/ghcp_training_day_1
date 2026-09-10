"""FastAPI router exposing REST CRUD endpoints for tickets under `/api/tickets`."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.database import TicketNotFoundError, TicketRepository
from app.models import Ticket, TicketCreate, TicketFilters, TicketPriority, TicketStatus, TicketUpdate


def _ticket_not_found_http_exception(error: TicketNotFoundError) -> HTTPException:
    """Wrap a `TicketNotFoundError` as a 404 `HTTPException` with the same message."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))


def create_api_router(repository: TicketRepository) -> APIRouter:
    """Build the `/api` router with CRUD routes bound to `repository`.

    Args:
        repository: The `TicketRepository` instance backing every route.

    Returns:
        An `APIRouter` ready to be included in a FastAPI app.
    """
    router = APIRouter(prefix="/api", tags=["tickets"])

    def get_repository() -> TicketRepository:
        """FastAPI dependency returning the router's bound `repository`."""
        return repository

    @router.get("/tickets", response_model=list[Ticket])
    def list_tickets(
        status_filter: TicketStatus | None = Query(default=None, alias="status"),
        priority: TicketPriority | None = None,
        search: str | None = None,
        tickets: TicketRepository = Depends(get_repository),
    ) -> list[Ticket]:
        """GET /api/tickets: list tickets, optionally filtered by status, priority, and search text.

        Args:
            status_filter: Optional status to filter by (query param `status`).
            priority: Optional priority to filter by.
            search: Optional case-insensitive substring matched against
                title, description, or requester.
            tickets: Injected repository dependency.
        """
        return tickets.list(TicketFilters(status=status_filter, priority=priority, search=search))

    @router.post("/tickets", response_model=Ticket, status_code=status.HTTP_201_CREATED)
    def create_ticket(ticket: TicketCreate, tickets: TicketRepository = Depends(get_repository)) -> Ticket:
        """POST /api/tickets: create a new ticket with status `open`.

        Args:
            ticket: Validated fields for the new ticket.
            tickets: Injected repository dependency.
        """
        return tickets.create(ticket)

    @router.get("/tickets/{ticket_id}", response_model=Ticket)
    def get_ticket(
        ticket_id: Annotated[int, Path(gt=0)],
        tickets: TicketRepository = Depends(get_repository),
    ) -> Ticket:
        """GET /api/tickets/{ticket_id}: fetch a single ticket by ID.

        Args:
            ticket_id: The ticket's primary key (must be > 0).
            tickets: Injected repository dependency.

        Raises:
            HTTPException: 404 if the ticket does not exist.
        """
        try:
            return tickets.get(ticket_id)
        except TicketNotFoundError as error:
            raise _ticket_not_found_http_exception(error) from error

    @router.patch("/tickets/{ticket_id}", response_model=Ticket)
    def update_ticket(
        ticket_id: Annotated[int, Path(gt=0)],
        update: TicketUpdate,
        tickets: TicketRepository = Depends(get_repository),
    ) -> Ticket:
        """PATCH /api/tickets/{ticket_id}: apply a partial update to a ticket.

        Args:
            ticket_id: The ticket's primary key (must be > 0).
            update: Fields to change; unset fields are left untouched.
            tickets: Injected repository dependency.

        Raises:
            HTTPException: 404 if the ticket does not exist.
        """
        try:
            return tickets.update(ticket_id, update)
        except TicketNotFoundError as error:
            raise _ticket_not_found_http_exception(error) from error

    @router.delete("/tickets/{ticket_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_ticket(
        ticket_id: Annotated[int, Path(gt=0)],
        tickets: TicketRepository = Depends(get_repository),
    ) -> Response:
        """DELETE /api/tickets/{ticket_id}: delete a ticket by ID.

        Args:
            ticket_id: The ticket's primary key (must be > 0).
            tickets: Injected repository dependency.

        Raises:
            HTTPException: 404 if the ticket does not exist.
        """
        try:
            tickets.delete(ticket_id)
        except TicketNotFoundError as error:
            raise _ticket_not_found_http_exception(error) from error
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
