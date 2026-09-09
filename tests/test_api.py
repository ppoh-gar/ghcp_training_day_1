def test_ticket_api_crud_returns_exact_ticket_and_expected_status_codes(client) -> None:
    initial = client.get("/api/tickets")
    assert initial.status_code == 200
    assert [ticket["id"] for ticket in initial.json()] == [1, 2, 3]

    created = client.post(
        "/api/tickets",
        json={
            "title": "  Printer jam on floor 3  ",
            "description": "  Printer repeatedly jams on duplex jobs.  ",
            "requester": "  Alicia Keys  ",
            "priority": "urgent",
        },
    )
    assert created.status_code == 201
    created_ticket = created.json()
    assert created_ticket["id"] == 4
    assert created_ticket["title"] == "Printer jam on floor 3"
    assert created_ticket["description"] == "Printer repeatedly jams on duplex jobs."
    assert created_ticket["requester"] == "Alicia Keys"

    fetched = client.get(f"/api/tickets/{created_ticket['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created_ticket

    updated = client.patch(f"/api/tickets/{created_ticket['id']}", json={"status": "resolved"})
    assert updated.status_code == 200
    assert updated.json()["id"] == created_ticket["id"]
    assert updated.json()["status"] == "resolved"
    assert updated.json()["title"] == created_ticket["title"]

    missing_patch = client.patch("/api/tickets/9999", json={"status": "closed"})
    assert missing_patch.status_code == 404

    deleted = client.delete(f"/api/tickets/{created_ticket['id']}")
    assert deleted.status_code == 204
    assert deleted.content == b""

    missing = client.get(f"/api/tickets/{created_ticket['id']}")
    assert missing.status_code == 404


def test_ticket_api_rejects_invalid_null_blank_and_out_of_range_inputs(client) -> None:
    assert client.patch("/api/tickets/1", json={"title": None}).status_code == 422
    assert client.patch("/api/tickets/1", json={"status": None}).status_code == 422

    blank_create = client.post(
        "/api/tickets",
        json={"title": "   ", "description": "  bad  ", "requester": "  ", "priority": "low"},
    )
    assert blank_create.status_code == 422

    whitespace_search = client.get("/api/tickets", params={"search": "   "})
    assert whitespace_search.status_code == 200
    assert [ticket["id"] for ticket in whitespace_search.json()] == [1, 2, 3]

    for ticket_id in (0, -1):
        response = client.get(f"/api/tickets/{ticket_id}")
        assert response.status_code == 422
