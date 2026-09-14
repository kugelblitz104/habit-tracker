"""Tests for the Obsidian journal importer: the parser and the endpoint.

The parser half is pure - no session, no fixtures, no zip - and every
fixture here is synthetic text shaped like the real vault rather than a
copy of it. The endpoint half covers the zip walking, the skip rules and
the guards.
"""

import io
import zipfile
from datetime import date

import pytest
from sqlalchemy import select

from habit_tracker.constants import DayQuality
from habit_tracker.schemas.db_models import JournalEntry
from habit_tracker.services.journal_import import parse_journal_file
from tests.factories import JournalEntryFactory, UserFactory

DATAVIEW_TAIL = """#### Tasks completed today:
```dataview
task
where completed
and completion =
date(this.file.name)
```

## Notes:
#### Notes created today:
```dataview
list from ""
where file.cday = date("2025-06-10")
sort file.ctime asc
```
"""


def templated(quality_line: str = "[day_quality::good]") -> str:
    """A templated daily note, shaped like the post-2025-03-25 vault era."""
    return (
        "**How did today go?**\n"
        f"{quality_line}\n"
        "played some games after a workout\n"
        "\n"
        "**Something you're grateful for?**\n"
        "sydney for making dinner\n"
        f"{DATAVIEW_TAIL}"
    )


def zip_bytes(files: dict[str, str]) -> bytes:
    """Build an in-memory zip of name -> text."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return buffer.getvalue()


def upload(content: bytes, filename: str = "daily.zip") -> dict:
    return {"file": (filename, content, "application/zip")}


class TestParseJournalFile:
    """Pure parsing of one (filename, text) pair."""

    def test_templated_entry(self):
        parsed = parse_journal_file("2025-06-10.md", templated())
        assert parsed is not None
        assert parsed.entry_date == date(2025, 6, 10)
        assert parsed.body == "played some games after a workout"
        assert parsed.gratitude == "sydney for making dinner"
        assert parsed.day_quality == "good"
        assert parsed.warnings == []

    def test_dataview_scaffolding_is_dropped(self):
        parsed = parse_journal_file("2025-06-10.md", templated())
        assert parsed is not None
        assert "dataview" not in (parsed.body or "")
        assert "dataview" not in (parsed.gratitude or "")
        assert "Tasks completed today" not in (parsed.gratitude or "")

    def test_quality_at_the_end_of_a_prose_line(self):
        """509 of 519 sit alone on a line; the rest trail a sentence."""
        text = (
            "**How did today go?**\n"
            "hung out with sydney, lexi, and zingus. [day_quality::great]\n"
            "\n"
            "**Something you're grateful for?**\n"
            "zingus comin over\n"
            f"{DATAVIEW_TAIL}"
        )
        parsed = parse_journal_file("2025-04-05.md", text)
        assert parsed is not None
        assert parsed.day_quality == "great"
        assert parsed.body == "hung out with sydney, lexi, and zingus."

    def test_double_bracket_wikilink_form(self):
        parsed = parse_journal_file(
            "2025-06-01.md", templated("[[day_quality::great]]")
        )
        assert parsed is not None
        assert parsed.day_quality == "great"
        assert parsed.body == "played some games after a workout"

    def test_transposed_field_name(self):
        """2025-04-16.md spells the field day_guality."""
        parsed = parse_journal_file("2025-04-16.md", templated("[day_guality::good]"))
        assert parsed is not None
        assert parsed.day_quality == "good"

    def test_single_colon_form(self):
        """2025-03-30.md writes the separator as one colon."""
        parsed = parse_journal_file("2025-03-30.md", templated("[day_quality:meh]"))
        assert parsed is not None
        assert parsed.day_quality == "good"
        assert parsed.body == "played some games after a workout"

    def test_whitespace_inside_the_field(self):
        parsed = parse_journal_file("2025-06-10.md", templated("[day_quality:: Good ]"))
        assert parsed is not None
        assert parsed.day_quality == "good"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("good", "good"),
            ("great", "great"),
            ("meh", "good"),
            ("bad", "rough"),
            ("stressful", "stressful"),
            ("poor", "rough"),
            ("mid", "good"),
            ("blech", "draining"),
        ],
    )
    def test_value_mapping(self, raw, expected):
        parsed = parse_journal_file("2025-06-10.md", templated(f"[day_quality::{raw}]"))
        assert parsed is not None
        assert parsed.day_quality == expected
        assert parsed.warnings == []

    def test_every_valid_quality_passes_through(self):
        for quality in DayQuality:
            parsed = parse_journal_file(
                "2025-06-10.md", templated(f"[day_quality::{quality.value}]")
            )
            assert parsed is not None
            assert parsed.day_quality == quality.value

    def test_unknown_value_warns_and_imports_without_a_quality(self):
        parsed = parse_journal_file("2025-06-10.md", templated("[day_quality::sleepy]"))
        assert parsed is not None
        assert parsed.day_quality is None
        assert parsed.body == "played some games after a workout"
        assert len(parsed.warnings) == 1
        assert "sleepy" in parsed.warnings[0]
        assert "2025-06-10.md" in parsed.warnings[0]

    def test_untemplated_file_is_body_verbatim(self):
        text = (
            "work was mostly good, worked on validation for most of the day\n"
            "\n"
            "[[ADHD Notes - Synthesized]]\n"
            "medication did not make any difference"
        )
        parsed = parse_journal_file("2024-09-18.md", text)
        assert parsed is not None
        assert parsed.body == text
        assert parsed.gratitude is None
        assert parsed.day_quality is None
        assert parsed.warnings == []

    def test_gratitude_without_the_how_prompt(self):
        """23 files carry the gratitude prompt and no How prompt."""
        text = (
            "good day today! had a great time with the gang\n"
            "I love sydney but they're super stressed\n"
            "\n"
            "**Something you're grateful for?**\n"
            "lin bringing snacks to the hang today!\n"
        )
        parsed = parse_journal_file("2024-11-10.md", text)
        assert parsed is not None
        assert parsed.body == (
            "good day today! had a great time with the gang\n"
            "I love sydney but they're super stressed"
        )
        assert parsed.gratitude == "lin bringing snacks to the hang today!"
        assert parsed.day_quality is None

    def test_empty_prompts_give_null_prose(self):
        text = (
            "**How did today go?**\n"
            "**Something you're grateful for?**\n"
            "\n"
            "#### Notes:\n"
            "0:45\n"
        )
        parsed = parse_journal_file("2025-03-13.md", text)
        assert parsed is not None
        assert parsed.body is None
        assert parsed.gratitude is None
        assert parsed.day_quality is None

    def test_multiline_body_keeps_its_line_breaks(self):
        text = (
            "**How did today go?**\n"
            "[day_quality::good]\n"
            "first line\n"
            "second line\n"
            "\n"
            "**Something you're grateful for?**\n"
            "thanks\n"
        )
        parsed = parse_journal_file("2025-06-10.md", text)
        assert parsed is not None
        assert parsed.body == "first line\nsecond line"

    def test_bolder_prompt_variant(self):
        """One file wraps the prompt in three asterisks."""
        text = (
            "***How did today go?***\n"
            "[day_quality::good]\n"
            "a fine day\n"
            "\n"
            "**Something you're grateful for?**\n"
            "coffee\n"
        )
        parsed = parse_journal_file("2025-05-02.md", text)
        assert parsed is not None
        assert parsed.body == "a fine day"
        assert parsed.gratitude == "coffee"

    @pytest.mark.parametrize(
        "filename",
        ["daily.md", "space/2025-06-10.md", "notes.md", "2025-13-99.md", "README"],
    )
    def test_files_that_are_not_daily_notes(self, filename):
        assert parse_journal_file(filename, templated()) is None


class TestImportJournalEndpoint:
    """POST /import/journal."""

    async def test_imports_a_folder_of_notes(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        profile = user.profiles[0]

        content = zip_bytes(
            {
                "2025-06-10.md": templated(),
                "2025-06-11.md": templated("[day_quality::meh]"),
                "daily.md": "**How did today go?**\n",
            }
        )
        response = await client.post(
            "/import/journal",
            params={"profile_id": profile.id},
            files=upload(content),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entries_imported"] == 2
        assert data["entries_skipped"] == 0
        assert data["files_failed"] == 0
        assert data["warnings"] == []

        rows = (
            (
                await db_session.execute(
                    select(JournalEntry)
                    .where(JournalEntry.profile_id == profile.id)
                    .order_by(JournalEntry.entry_date)
                )
            )
            .scalars()
            .all()
        )
        assert [r.entry_date for r in rows] == [date(2025, 6, 10), date(2025, 6, 11)]
        assert [r.day_quality for r in rows] == ["good", "good"]
        assert rows[0].body == "played some games after a workout"
        assert rows[0].gratitude == "sydney for making dinner"

    async def test_existing_days_are_skipped_not_overwritten(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        profile = user.profiles[0]
        JournalEntryFactory(
            profile=profile, entry_date=date(2025, 6, 10), body="mine already"
        )
        await db_session.commit()
        await login_as(user)

        profile_id = profile.id
        content = zip_bytes({"2025-06-10.md": templated()})
        response = await client.post(
            "/import/journal",
            params={"profile_id": profile_id},
            files=upload(content),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entries_imported"] == 0
        assert data["entries_skipped"] == 1
        assert any("2025-06-10.md" in w for w in data["warnings"])

        db_session.expire_all()
        rows = (
            (
                await db_session.execute(
                    select(JournalEntry).where(JournalEntry.profile_id == profile_id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].body == "mine already"

    async def test_subdirectories_and_bad_names_do_not_abort_the_run(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        profile = user.profiles[0]

        content = zip_bytes(
            {
                "space/2025-06-01.md": templated(),
                "not-a-date.md": templated(),
                "2025-06-10.md": templated(),
            }
        )
        response = await client.post(
            "/import/journal",
            params={"profile_id": profile.id},
            files=upload(content),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entries_imported"] == 1
        assert any("not-a-date.md" in w for w in data["warnings"])
        # A note inside a subdirectory is not a daily note and is not imported
        assert not any("space/" in w for w in data["warnings"])

        rows = (
            (
                await db_session.execute(
                    select(JournalEntry).where(JournalEntry.profile_id == profile.id)
                )
            )
            .scalars()
            .all()
        )
        assert [r.entry_date for r in rows] == [date(2025, 6, 10)]

    async def test_unknown_quality_imports_the_entry_and_warns(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        profile = user.profiles[0]

        content = zip_bytes({"2025-06-10.md": templated("[day_quality::sleepy]")})
        response = await client.post(
            "/import/journal",
            params={"profile_id": profile.id},
            files=upload(content),
        )
        assert response.status_code == 201
        data = response.json()
        assert data["entries_imported"] == 1
        assert any("sleepy" in w for w in data["warnings"])

        row = (
            (
                await db_session.execute(
                    select(JournalEntry).where(JournalEntry.profile_id == profile.id)
                )
            )
            .scalars()
            .one()
        )
        assert row.day_quality is None
        assert row.body == "played some games after a workout"

    async def test_rejects_a_file_that_is_not_a_zip(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        response = await client.post(
            "/import/journal",
            params={"profile_id": user.profiles[0].id},
            files=upload(b"not a zip at all", filename="vault.zip"),
        )
        assert response.status_code == 400

    async def test_rejects_an_archive_with_too_many_members(
        self, client, db_session, login_as
    ):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        content = zip_bytes({f"file-{n}.md": "x" for n in range(2001)})
        response = await client.post(
            "/import/journal",
            params={"profile_id": user.profiles[0].id},
            files=upload(content),
        )
        assert response.status_code == 400

    async def test_rejects_another_users_profile(self, client, db_session, login_as):
        user = UserFactory()
        other = UserFactory()
        await db_session.commit()
        await login_as(user)

        content = zip_bytes({"2025-06-10.md": templated()})
        response = await client.post(
            "/import/journal",
            params={"profile_id": other.profiles[0].id},
            files=upload(content),
        )
        assert response.status_code == 403

    async def test_rejects_a_missing_profile(self, client, db_session, login_as):
        user = UserFactory()
        await db_session.commit()
        await login_as(user)

        content = zip_bytes({"2025-06-10.md": templated()})
        response = await client.post(
            "/import/journal",
            params={"profile_id": 999999},
            files=upload(content),
        )
        assert response.status_code == 404

    async def test_requires_authentication(self, client):
        content = zip_bytes({"2025-06-10.md": templated()})
        response = await client.post(
            "/import/journal", params={"profile_id": 1}, files=upload(content)
        )
        assert response.status_code == 401

    async def test_an_entry_with_no_prose_at_all_still_imports(
        self, client, db_session, login_as
    ):
        """A profile can hold an empty day; the importer does not invent prose."""
        user = UserFactory()
        await db_session.commit()
        await login_as(user)
        profile = user.profiles[0]

        content = zip_bytes({"2025-03-13.md": "**How did today go?**\n"})
        response = await client.post(
            "/import/journal",
            params={"profile_id": profile.id},
            files=upload(content),
        )
        assert response.status_code == 201
        assert response.json()["entries_imported"] == 1

        row = (
            (
                await db_session.execute(
                    select(JournalEntry).where(JournalEntry.profile_id == profile.id)
                )
            )
            .scalars()
            .one()
        )
        assert row.body is None
        assert row.gratitude is None
        assert row.day_quality is None
