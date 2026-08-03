"""Tests for the pure slug helpers in core/slugs.py.

Deliberately DB-free, like test_habit_stats.py: `slugify` and `next_free_slug`
are pure functions and the numbering rule is easier to pin here than through
the API. The database-backed allocator (`allocate_slug`) and the
`/tasks/by-slug/{slug}` endpoint are covered in test_tasks.py::TestTaskSlugs.
"""

from habit_tracker.core.slugs import (
    FALLBACK_BASE,
    MAX_SLUG_LENGTH,
    next_free_slug,
    slugify,
)


class TestSlugify:
    """Tests for slugify()."""

    def test_lowercases_and_hyphenates(self):
        assert slugify("Setup Utilities") == "setup-utilities"

    def test_collapses_runs_of_separators(self):
        """Any run of non-alphanumerics becomes exactly one hyphen."""
        assert slugify("Fix   the  --  thing!!!") == "fix-the-thing"

    def test_strips_leading_and_trailing_separators(self):
        assert slugify("  ...Hello world?  ") == "hello-world"

    def test_folds_accents_to_ascii(self):
        assert slugify("Café renovation") == "cafe-renovation"

    def test_keeps_digits_inside_a_slug(self):
        """Digits are fine as long as the slug isn't *only* digits."""
        assert slugify("Pay 1099 forms") == "pay-1099-forms"

    def test_ampersand_and_punctuation_dropped(self):
        assert slugify("Completed & Closed") == "completed-closed"

    def test_all_digit_result_gets_the_fallback_prefix(self):
        """A slug of only digits would be ambiguous with the numeric id route,
        so the fallback prefix breaks the ambiguity while keeping the digits."""
        assert slugify("2841") == "task-2841"
        assert slugify("  2841  ") == "task-2841"
        # Already prefixed by the title itself, so no double prefix.
        assert slugify("Task #2841") == "task-2841"

    def test_digits_split_by_a_hyphen_are_a_valid_slug(self):
        """ "28-41" is not all-digits, so it is kept as-is. Consumers must
        therefore recognise the numeric-id form with a strict all-digits test:
        parsing the segment as an integer would read "28-41" as task 28."""
        assert slugify("28 41") == "28-41"

    def test_falls_back_when_nothing_survives_folding(self):
        assert slugify("???") == FALLBACK_BASE
        assert slugify("") == FALLBACK_BASE
        assert slugify("   ") == FALLBACK_BASE
        # Non-Latin scripts are dropped entirely by ASCII folding.
        assert slugify("日本語") == FALLBACK_BASE

    def test_mixed_script_keeps_the_latin_part(self):
        assert slugify("Ship 日本語 support") == "ship-support"

    def test_truncates_to_max_length_on_a_word_boundary(self):
        title = " ".join(["alpha"] * 40)
        slug = slugify(title)
        assert len(slug) <= MAX_SLUG_LENGTH
        # Trimmed between words, never mid-word, and never left dangling.
        assert not slug.endswith("-")
        assert all(part == "alpha" for part in slug.split("-"))

    def test_single_word_longer_than_max_length(self):
        """One unbroken word has no hyphen to trim on. It must still come back
        as a usable slug rather than an empty string."""
        slug = slugify("x" * (MAX_SLUG_LENGTH + 20))
        assert slug != ""
        assert set(slug) == {"x"}

    def test_trimming_cannot_produce_an_all_digit_slug(self):
        """Trimming runs BEFORE the all-digit check, because it can create one:
        this title is not all digits until its tail is cut off."""
        slug = slugify("2841 " + "supercalifragilistic" * 6)
        assert not slug.isdigit()
        assert len(slug) <= MAX_SLUG_LENGTH

    def test_never_returns_an_ambiguous_or_empty_slug(self):
        """The invariant the URL scheme rests on: no slug is ever empty or all
        digits, so an all-digits URL segment is unambiguously a task id.

        Asserted over every awkward title in this class at once, so a future
        change to the folding or trimming rules can't quietly break it for a
        shape that has no dedicated test.
        """
        titles = [
            "2841",
            "  2841  ",
            "28 41",
            "0",
            "007",
            "???",
            "",
            "   ",
            "日本語",
            "-",
            "---",
            "1" * (MAX_SLUG_LENGTH * 2),
            "2841 " + "supercalifragilistic" * 6,
            "x" * (MAX_SLUG_LENGTH + 20),
            "Setup Utilities",
        ]
        for title in titles:
            slug = slugify(title)
            assert slug, f"{title!r} produced an empty slug"
            assert not slug.isdigit(), f"{title!r} produced the all-digit {slug!r}"
            assert slug == slug.strip("-"), f"{title!r} produced dangling {slug!r}"


class TestNextFreeSlug:
    """Tests for next_free_slug(): the numbered-suffix rule."""

    def test_base_when_free(self):
        assert next_free_slug("follow-up", set()) == "follow-up"

    def test_second_gets_suffix_2(self):
        """Numbering starts at 2, so the first task keeps the clean slug."""
        assert next_free_slug("follow-up", {"follow-up"}) == "follow-up-2"

    def test_counts_up_past_consecutive_suffixes(self):
        taken = {"follow-up", "follow-up-2", "follow-up-3"}
        assert next_free_slug("follow-up", taken) == "follow-up-4"

    def test_fills_a_gap_left_by_a_deleted_task(self):
        """Slugs are stored, not renumbered, so deleting `follow-up-2` leaves a
        gap, and the next allocation reuses it rather than jumping to -4."""
        assert (
            next_free_slug("follow-up", {"follow-up", "follow-up-3"}) == "follow-up-2"
        )

    def test_unrelated_slugs_do_not_block(self):
        assert next_free_slug("follow-up", {"other", "follow-up-x"}) == "follow-up"
