"""DuckDB-backed persistence layer for tickets (`TicketRepository`)."""
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import duckdb

from app.models import Ticket, TicketCreate, TicketFilters, TicketPriority, TicketStatus, TicketUpdate


class TicketNotFoundError(LookupError):
    """Raised when a ticket ID does not exist in the `tickets` table."""

    pass


class TicketRepository:
    """Thread-safe DuckDB access layer for creating, querying, and mutating tickets.

    A single connection is shared across calls and guarded by a lock, since
    DuckDB connections are not safe for concurrent use from multiple threads.
    """

    _ticket_column_names = ("id", "title", "description", "requester", "priority", "status", "created_at", "updated_at")
    _ticket_columns = "id, title, description, requester, priority, status, created_at, updated_at"

    def __init__(self, database_path: str | Path = "data/tickets.duckdb") -> None:
        """Open (or create) the DuckDB file at `database_path` and ensure the schema exists.

        Args:
            database_path: Filesystem path to the DuckDB database file, or
                `":memory:"` for an ephemeral in-memory database. Parent
                directories are created automatically for file-based paths.
        """
        self.database_path = str(database_path)
        path = Path(self.database_path)
        if self.database_path != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = duckdb.connect(self.database_path)
        self._lock = Lock()
        self._initialize()

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.execute(
                """
                CREATE SEQUENCE IF NOT EXISTS ticket_id_seq START 1;
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY DEFAULT nextval('ticket_id_seq'),
                    title VARCHAR NOT NULL,
                    description VARCHAR NOT NULL,
                    requester VARCHAR NOT NULL,
                    priority VARCHAR NOT NULL,
                    status VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ticket_audit (
                    ticket_id INTEGER NOT NULL,
                    message VARCHAR NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )

    def seed_defaults(self) -> None:
        """Insert three sample tickets if the `tickets` table is currently empty.

        No-op when the table already has at least one row, so it is safe to
        call on every application startup.
        """
        with self._lock:
            count = self._connection.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        if count > 0:
            return

        samples = [
            TicketCreate(
                title="Laptop cannot connect to VPN",
                description="Requester is blocked from accessing internal systems while traveling.",
                requester="Avery Stone",
                priority=TicketPriority.high,
            ),
            TicketCreate(
                title="New finance dashboard access",
                description="Grant read-only dashboard access for monthly reporting.",
                requester="Mina Patel",
                priority=TicketPriority.medium,
            ),
            TicketCreate(
                title="Broken conference room display",
                description="Display in room Cedar does not wake when connected over HDMI.",
                requester="Jon Bell",
                priority=TicketPriority.low,
            ),
        ]
        for ticket in samples:
            self.create(ticket)

    def create(self, ticket: TicketCreate) -> Ticket:
        """Insert a new ticket with status `open` and return the persisted `Ticket`.

        Args:
            ticket: Validated fields for the new ticket.

        Returns:
            The newly created ticket, including its generated `id` and timestamps.
        """
        now = self._now()
        with self._lock:
            row = self._connection.execute(
                """
                INSERT INTO tickets (title, description, requester, priority, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id, title, description, requester, priority, status, created_at, updated_at
                """,
                [
                    ticket.title,
                    ticket.description,
                    ticket.requester,
                    ticket.priority.value,
                    TicketStatus.open.value,
                    now,
                    now,
                ],
            ).fetchone()
        return self._row_to_ticket(row)

    def list(self, filters: TicketFilters | None = None) -> list[Ticket]:
        """Return tickets matching `filters`, ordered by `created_at` then `id` (ascending).

        Args:
            filters: Optional status/priority/search criteria. When omitted,
                all tickets are returned.

        Returns:
            The matching tickets in creation order.
        """
        query, parameters = self._build_list_query(filters or TicketFilters())
        with self._lock:
            rows = self._connection.execute(query, parameters).fetchall()
        return [self._row_to_ticket(row) for row in rows]

    def get(self, ticket_id: int) -> Ticket:
        """Fetch a single ticket by ID.

        Args:
            ticket_id: The ticket's primary key.

        Returns:
            The matching `Ticket`.

        Raises:
            TicketNotFoundError: If no ticket with `ticket_id` exists.
        """
        with self._lock:
            row = self._connection.execute(
                f"SELECT {self._ticket_columns} FROM tickets WHERE id = ?",
                [ticket_id],
            ).fetchone()
        if row is None:
            raise TicketNotFoundError(f"Ticket {ticket_id} was not found")
        return self._row_to_ticket(row)

    def update(self, ticket_id: int, update: TicketUpdate) -> Ticket:
        """Apply a partial update to a ticket and refresh its `updated_at` timestamp.

        Only fields explicitly set on `update` are changed; unset fields are
        left untouched. If `update` has no set fields, the ticket is returned
        unchanged (still validating that it exists).

        Args:
            ticket_id: The ticket's primary key.
            update: Partial field values to apply.

        Returns:
            The ticket after the update is applied.

        Raises:
            TicketNotFoundError: If no ticket with `ticket_id` exists.
        """
        changes = update.model_dump(exclude_unset=True)
        if not changes:
            return self.get(ticket_id)

        assignments, parameters = self._build_update_assignments(changes)
        assignments.append("updated_at = ?")
        parameters.append(self._now())
        parameters.append(ticket_id)

        with self._lock:
            row = self._connection.execute(
                f"UPDATE tickets SET {', '.join(assignments)} WHERE id = ? "
                f"RETURNING {self._ticket_columns}",
                parameters,
            ).fetchone()
        return self._require_ticket(row, ticket_id)

    def delete(self, ticket_id: int) -> None:
        """Delete a ticket by ID.

        Args:
            ticket_id: The ticket's primary key.

        Raises:
            TicketNotFoundError: If no ticket with `ticket_id` exists.
        """
        with self._lock:
            deleted = self._connection.execute(
                "DELETE FROM tickets WHERE id = ? RETURNING id",
                [ticket_id],
            ).fetchone()
        if deleted is None:
            self._raise_not_found(ticket_id)

    @staticmethod
    def _now() -> datetime:
        """Current UTC time, stored naive (no tzinfo) to match the DuckDB TIMESTAMP column."""
        return datetime.now(UTC).replace(tzinfo=None)

    @staticmethod
    def _row_to_ticket(row: Iterable[object]) -> Ticket:
        """Convert a raw DuckDB row (in `_ticket_column_names` order) into a `Ticket`."""
        return Ticket.model_validate(dict(zip(TicketRepository._ticket_column_names, row, strict=True)))

    def _build_list_query(self, filters: TicketFilters) -> tuple[str, "list[str]"]:
        """Build a parameterized SELECT for `list`.

        Filter order is status, then priority, then a case-insensitive search
        across title/description/requester; results are always ordered by
        `created_at ASC, id ASC`.
        """
        where_parts: list[str] = []
        parameters: list[str] = []

        if filters.status:
            where_parts.append("status = ?")
            parameters.append(filters.status.value)
        if filters.priority:
            where_parts.append("priority = ?")
            parameters.append(filters.priority.value)
        if filters.search:
            where_parts.append("(title ILIKE ? OR description ILIKE ? OR requester ILIKE ?)")
            search = f"%{filters.search}%"
            parameters.extend([search, search, search])

        query = f"SELECT {self._ticket_columns} FROM tickets"
        if where_parts:
            query += " WHERE " + " AND ".join(where_parts)
        query += " ORDER BY created_at ASC, id ASC"
        return query, parameters

    @staticmethod
    def _build_update_assignments(changes: dict[str, object]) -> tuple["list[str]", "list[object]"]:
        """Turn `changes` (from `TicketUpdate.model_dump(exclude_unset=True)`) into SQL
        `field = ?` assignments and their parameter values, converting enums to strings.
        """
        assignments: list[str] = []
        parameters: list[object] = []
        for field, value in changes.items():
            assignments.append(f"{field} = ?")
            parameters.append(value.value if hasattr(value, "value") else value)
        return assignments, parameters

    def _require_ticket(self, row: Iterable[object] | None, ticket_id: int) -> Ticket:
        """Convert `row` to a `Ticket`, or raise `TicketNotFoundError` if `row` is `None`."""
        if row is None:
            self._raise_not_found(ticket_id)
        return self._row_to_ticket(row)

    @staticmethod
    def _raise_not_found(ticket_id: int) -> None:
        """Raise `TicketNotFoundError` with the standard "Ticket {id} was not found" message."""
        raise TicketNotFoundError(f"Ticket {ticket_id} was not found")
