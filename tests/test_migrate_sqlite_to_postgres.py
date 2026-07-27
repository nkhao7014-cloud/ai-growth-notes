import unittest

from scripts.migrate_sqlite_to_postgres import migrate_editions, migrate_items, migrate_notes


class Result:
    def __init__(self, one=None, all_rows=None):
        self.one, self.all_rows = one, all_rows or []
    def fetchone(self):
        return self.one
    def fetchall(self):
        return self.all_rows


class FakeConnection:
    def __init__(self, notes=None, item=None, editions=None):
        self.notes = notes or []
        self.item = item
        self.editions = editions or []
        self.writes = []
        self.next_id = 100
    def execute(self, sql, values=()):
        if sql.startswith("SELECT id,raw_text"):
            return Result(all_rows=self.notes)
        if sql.startswith("SELECT * FROM ai_daily_items"):
            return Result(one=self.item)
        if sql.startswith("SELECT edition_date"):
            return Result(all_rows=[{"edition_date": value} for value in self.editions])
        if sql.startswith(("INSERT", "UPDATE")):
            self.writes.append((sql, values))
            self.next_id += 1
            return Result(one={"id": self.next_id})
        raise AssertionError(sql)


def note(note_id=7):
    return {"id": note_id, "raw_text": "raw", "ai_summary": "summary",
            "created_at": "2026-01-02 03:04:05", "is_favorite": 1}


def item(item_id=8, saved_note_id=7, source_url="https://EXAMPLE.com/a/?utm_source=rss"):
    return {"id": item_id, "external_id": "ext", "fallback_key": "fallback", "title": "new title",
            "source_name": "source", "source_url": source_url, "normalized_url": "ignored",
            "published_at": None, "category": "AI", "summary": "summary", "why_it_matters": "why",
            "tags": "[]", "is_read": 0, "is_favorite": 0, "saved_note_id": saved_note_id,
            "fetched_at": "2026-01-02T00:00:00+00:00", "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-02T00:00:00+00:00"}


class MigrationTests(unittest.TestCase):
    def test_empty_target_uses_generated_ids_and_remaps_saved_note(self):
        connection = FakeConnection()
        note_map, note_stats = migrate_notes(connection, [note()], False)
        item_map, item_stats = migrate_items(connection, [item()], note_map, False)
        self.assertEqual(note_stats["inserted"], 1)
        self.assertEqual(item_stats["inserted"], 1)
        self.assertEqual(connection.writes[-1][1][13], note_map[7])
        self.assertNotEqual(item_map[8], 8)

    def test_existing_url_updates_body_without_user_state_or_created_at(self):
        target = {**item(99), "id": 99, "normalized_url": "https://example.com/a",
                  "is_read": True, "is_favorite": True, "saved_note_id": 55}
        connection = FakeConnection(item=target)
        mapping, stats = migrate_items(connection, [item()], {7: 101}, False)
        sql = connection.writes[0][0]
        self.assertEqual(mapping[8], 99)
        self.assertEqual(stats["updated"], 1)
        self.assertNotIn("is_read", sql)
        self.assertNotIn("is_favorite", sql)
        self.assertNotIn("saved_note_id", sql)
        self.assertNotIn("created_at", sql)

    def test_source_ids_never_drive_insert_ids(self):
        connection = FakeConnection()
        mapping, _ = migrate_items(connection, [item(item_id=100)], {7: 12}, False)
        self.assertNotIn("(id,", connection.writes[0][0])
        self.assertNotEqual(mapping[100], 100)

    def test_unmapped_saved_note_is_null_and_counted(self):
        connection = FakeConnection()
        _, stats = migrate_items(connection, [item(saved_note_id=999)], {}, False)
        self.assertEqual(stats["unmapped_foreign_keys"], 1)
        self.assertIsNone(connection.writes[0][1][13])

    def test_dry_run_performs_no_writes(self):
        connection = FakeConnection()
        note_map, _ = migrate_notes(connection, [note()], True)
        migrate_items(connection, [item()], note_map, True)
        migrate_editions(connection, [{"id": 1, "edition_date": "2026-01-01"}], True)
        self.assertEqual(connection.writes, [])

    def test_fallback_normalized_url_is_non_null(self):
        connection = FakeConnection()
        migrate_items(connection, [item(source_url="not-a-url")], {7: 12}, False)
        self.assertTrue(connection.writes[0][1][5].startswith("urn:ai-daily:fallback:"))

    def test_repeat_notes_and_editions_are_skipped(self):
        target_note = {**note(), "id": 44}
        connection = FakeConnection(notes=[target_note], editions=["2026-01-01"])
        mapping, note_stats = migrate_notes(connection, [note()], False)
        edition_stats = migrate_editions(connection, [{"id": 1, "edition_date": "2026-01-01"}], False)
        self.assertEqual(mapping[7], 44)
        self.assertEqual(note_stats["skipped"], 1)
        self.assertEqual(edition_stats["skipped"], 1)
        self.assertEqual(connection.writes, [])

    def test_item_failure_includes_source_context_for_transaction_rollback(self):
        class Broken(FakeConnection):
            def execute(self, sql, values=()):
                if sql.startswith("SELECT * FROM ai_daily_items"):
                    raise ValueError("forced failure")
                return super().execute(sql, values)
        with self.assertRaisesRegex(RuntimeError, "source_id=8.*normalized_url=https://example.com/a"):
            migrate_items(Broken(), [item()], {7: 12}, False)


if __name__ == "__main__":
    unittest.main()
