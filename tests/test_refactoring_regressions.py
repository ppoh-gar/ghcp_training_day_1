import pytest

from database import TicketRepository
from models import TicketCreate, TicketFilters, TicketPriority, TicketStatus, TicketUpdate
from ui import _build_ticket_create, _build_ticket_filters, _ticket_filters_or_none


def test_repository_build_list_query_keeps_values_parameterized_and_in_filter_order() -> None:
    repository = TicketRepository(":memory:")

    query, parameters = repository._build_list_query(
        TicketFilters(status=TicketStatus.open, priority=TicketPriority.high, search="100%")
    )

    assert query == (
        "SELECT id, title, description, requester, priority, status, created_at, updated_at FROM tickets "
        "WHERE status = ? AND priority = ? AND (title ILIKE ? OR description ILIKE ? OR requester ILIKE ?) "
        "ORDER BY created_at ASC, id ASC"
    )
    assert "100%" not in query
    assert parameters == ["open", "high", "%100%%", "%100%%", "%100%%"]
    repository.close()


def test_repository_build_update_assignments_preserves_model_field_order_and_enum_values() -> None:
    changes = TicketUpdate(title="Renamed title", priority=TicketPriority.urgent, status=TicketStatus.closed).model_dump(
        exclude_unset=True
    )

    assignments, parameters = TicketRepository._build_update_assignments(changes)

    assert assignments == ["title = ?", "priority = ?", "status = ?"]
    assert parameters == ["Renamed title", "urgent", "closed"]


def test_repository_empty_update_returns_existing_ticket_without_changing_timestamp(temp_db_path) -> None:
    repository = TicketRepository(temp_db_path)
    created = repository.create(
        TicketCreate(
            title="Monitor issue",
            description="Primary monitor flickers after sleep.",
            requester="Dana Lee",
            priority=TicketPriority.medium,
        )
    )

    unchanged = repository.update(created.id, TicketUpdate())

    assert unchanged == created
    assert unchanged.updated_at == created.updated_at
    repository.close()


def test_ticket_api_missing_ticket_messages_remain_unchanged(client) -> None:
    expected = {"detail": "Ticket 9999 was not found"}

    assert client.get("/api/tickets/9999").json() == expected
    assert client.patch("/api/tickets/9999", json={"status": "closed"}).json() == expected
    assert client.delete("/api/tickets/9999").json() == expected


def test_ui_helpers_preserve_filter_mapping_and_ticket_create_validation() -> None:
    filters = _build_ticket_filters("all", "all", "   ")
    assert filters.status is None
    assert filters.priority is None
    assert filters.search is None
    assert _ticket_filters_or_none("all", "all", "   ") is None

    specific = _ticket_filters_or_none("open", "high", "  Avery  ")
    assert specific == TicketFilters(status=TicketStatus.open, priority=TicketPriority.high, search="Avery")

    created = _build_ticket_create("  Broken badge reader  ", "  Lobby reader is offline.  ", "  Sam Wu  ", "low")
    assert created == TicketCreate(
        title="Broken badge reader",
        description="Lobby reader is offline.",
        requester="Sam Wu",
        priority=TicketPriority.low,
    )

    with pytest.raises(ValueError, match="title cannot be blank"):
        _build_ticket_create("   ", "valid description", "Taylor", "medium")
