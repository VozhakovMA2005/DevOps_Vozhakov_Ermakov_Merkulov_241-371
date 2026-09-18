"""Подразделения и их иерархия."""

from __future__ import annotations


class TestDepartments:
    def test_hierarchy(self, client, department):
        child = client.post(
            "/api/v1/departments",
            json={"code": "LAB-1", "name": "Лаборатория", "parent_id": department["id"]},
        )
        assert child.status_code == 201
        page = client.get(f"/api/v1/departments?parent_id={department['id']}").json()
        assert page["total"] == 1

    def test_self_parent_rejected(self, client, department):
        response = client.patch(
            f"/api/v1/departments/{department['id']}", json={"parent_id": department["id"]}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEPARTMENT_CYCLE"

    def test_long_cycle_rejected(self, client, department):
        """CHECK в схеме ловит только прямое самородительство, цикл длиннее — приложение."""
        child = client.post(
            "/api/v1/departments",
            json={"code": "B", "name": "Б", "parent_id": department["id"]},
        ).json()
        grandchild = client.post(
            "/api/v1/departments",
            json={"code": "C", "name": "В", "parent_id": child["id"]},
        ).json()
        response = client.patch(
            f"/api/v1/departments/{department['id']}", json={"parent_id": grandchild["id"]}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "DEPARTMENT_CYCLE"

    def test_unknown_parent(self, client, admin):
        response = client.post(
            "/api/v1/departments", json={"code": "X", "name": "Х", "parent_id": 99999}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "RELATED_NOT_FOUND"

    def test_department_with_children_is_not_deleted(self, client, department):
        client.post(
            "/api/v1/departments",
            json={"code": "B", "name": "Б", "parent_id": department["id"]},
        )
        response = client.delete(f"/api/v1/departments/{department['id']}")
        assert response.status_code == 409
        assert response.json()["error"]["details"]["children_count"] == 1


def test_section_requires_login(client):
    assert client.get("/api/v1/departments").status_code == 401
