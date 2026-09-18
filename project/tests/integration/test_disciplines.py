"""Дисциплины и матрица допустимости (правило D1)."""

from __future__ import annotations


def test_matrix_is_editable(client, discipline, room_types):
    updated = client.patch(
        f"/api/v1/disciplines/{discipline['id']}",
        json={"allowed_room_type_ids": [room_types["LAB"]["id"], room_types["SEMINAR"]["id"]]},
    ).json()
    assert {row["code"] for row in updated["allowed_room_types"]} == {"LAB", "SEMINAR"}


def test_matrix_rejects_unknown_type(client, discipline):
    response = client.patch(
        f"/api/v1/disciplines/{discipline['id']}", json={"allowed_room_type_ids": [99999]}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RELATED_NOT_FOUND"


def test_disciplines_require_login(client):
    assert client.get("/api/v1/disciplines").status_code == 401
