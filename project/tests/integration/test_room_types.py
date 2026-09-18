"""Справочник типов помещений."""

from __future__ import annotations


class TestRoomTypes:
    def test_reference_data_comes_with_migrations(self, client, admin):
        """Без справочника типов нельзя завести ни одного помещения."""
        codes = {row["code"] for row in client.get("/api/v1/room-types").json()}
        assert {"LECTURE", "SEMINAR", "LAB", "COMPUTER", "OFFICE"} <= codes

    def test_norm_returned_as_string(self, client, room_types):
        assert room_types["SEMINAR"]["area_norm"] == "2.50"
        assert room_types["OFFICE"]["area_norm"] is None


def test_section_requires_login(client):
    assert client.get("/api/v1/room-types").status_code == 401
