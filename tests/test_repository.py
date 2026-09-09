from pathlib import Path

from app.database import TicketRepository
from app.models import TicketCreate, TicketFilters, TicketPriority, TicketStatus, TicketUpdate


def test_repository_reopens_seeded_database_without_duplicate_rows(temp_db_path: Path) -> None:
    repository = TicketRepository(temp_db_path)
    repository.seed_defaults()
    repository.seed_defaults()

    seeded = repository.list()
    assert [ticket.id for ticket in seeded] == [1, 2, 3]
    assert seeded[0].priority is TicketPriority.high
    assert seeded[0].status is TicketStatus.open

    created = repository.create(
        TicketCreate(
            title="  Printer issue  ",
            description="  Duplex jobs keep jamming.  ",
            requester="  Alex Doe  ",
            priority=TicketPriority.urgent,
        )
    )
    assert created.id == 4
    assert created.title == "Printer issue"
    assert created.description == "Duplex jobs keep jamming."
    assert created.requester == "Alex Doe"
    repository.close()

    reopened = TicketRepository(temp_db_path)
    reopened.seed_defaults()
    persisted = reopened.list()
    assert [ticket.id for ticket in persisted] == [1, 2, 3, 4]
    assert reopened.get(4).priority is TicketPriority.urgent
    reopened.close()


def test_repository_filters_and_partial_updates_use_exact_ticket_ids(temp_db_path: Path) -> None:
    repository = TicketRepository(temp_db_path)
    repository.seed_defaults()
    created = repository.create(
        TicketCreate(
            title="Case Sensitive Search",
            description="Need CASE search match",
            requester="Taylor Rae",
            priority=TicketPriority.urgent,
        )
    )

    assert [ticket.id for ticket in repository.list(TicketFilters(search="case"))] == [created.id]
    assert [ticket.id for ticket in repository.list(TicketFilters(search="Taylor"))] == [created.id]
    assert [ticket.id for ticket in repository.list(TicketFilters(priority=TicketPriority.urgent))] == [created.id]
    assert len(repository.list(TicketFilters(search="   "))) == 4

    updated = repository.update(created.id, TicketUpdate(status=TicketStatus.resolved))
    assert updated.id == created.id
    assert updated.status is TicketStatus.resolved
    assert updated.title == created.title
    repository.close()
