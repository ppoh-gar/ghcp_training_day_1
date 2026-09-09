def test_dashboard_page_renders_header_form_and_filters(client) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["x-nicegui-content"] == "page"
    page = response.text
    for snippet in ("Ticket Desk", "New ticket", "Create ticket", "Filters", "Search"):
        assert snippet in page
