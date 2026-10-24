import unittest

from services.recommendation_service import _is_duplicate_listing


def listing(
    *,
    source_name="Greenhouse",
    title="Regional Sales Director - France",
    company="GitLab",
    location="Remote, France",
    source_url="https://jobs.example.com/role/1",
    description=(
        "Lead regional sales strategy for France, coach account executives, "
        "and deliver quarterly revenue goals."
    ),
):
    return {
        "source_name": source_name,
        "title": title,
        "company": company,
        "location": location,
        "source_url": source_url,
        "description": description,
    }


class RecommendationDeduplicationTests(unittest.TestCase):
    def test_near_duplicate_from_another_provider_is_suppressed(self):
        first = listing()
        near_duplicate = listing(
            source_name="Arbeitnow",
            title=" Regional Sales Director – France ",
            company="GITLAB",
            location="Remote",
            source_url="https://www.example.org/job/another-id",
            description=(
                "Lead regional sales strategy for France, coach account "
                "executives, and deliver quarterly revenue targets."
            ),
        )

        self.assertTrue(_is_duplicate_listing(first, near_duplicate))

    def test_original_url_match_supports_title_company_match(self):
        first = listing(
            location="New York",
            source_url="https://jobs.example.com/role/1?utm_source=one",
            description="Original announcement content.",
        )
        same_posting = listing(
            source_name="Lever",
            location="San Francisco",
            source_url="https://www.jobs.example.com/role/1?utm_source=two",
            description="Updated announcement content.",
        )

        self.assertTrue(_is_duplicate_listing(first, same_posting))

    def test_description_similarity_alone_does_not_suppress_distinct_company(self):
        first = listing()
        other_company = listing(
            source_name="Arbeitnow",
            company="Different Employer",
        )

        self.assertFalse(_is_duplicate_listing(first, other_company))

    def test_same_employer_and_similar_description_but_different_title_is_distinct(self):
        first = listing()
        other_role = listing(
            source_name="Arbeitnow",
            title="Regional Sales Manager - France",
        )

        self.assertFalse(_is_duplicate_listing(first, other_role))

    def test_incompatible_locations_prevent_description_only_match(self):
        first = listing(location="New York, NY")
        other_location = listing(
            source_name="Arbeitnow",
            location="London, UK",
            source_url="https://jobs.example.org/role/other",
        )

        self.assertFalse(_is_duplicate_listing(first, other_location))

    def test_distinct_job_descriptions_are_not_suppressed(self):
        first = listing()
        other_posting = listing(
            source_name="Arbeitnow",
            source_url="https://jobs.example.org/role/2",
            description=(
                "Own global partner operations, build channel programs, "
                "and negotiate reseller agreements."
            ),
        )

        self.assertFalse(_is_duplicate_listing(first, other_posting))

    def test_same_provider_rows_are_not_cross_provider_deduplicated(self):
        first = listing()
        same_source = listing(
            source_url="https://jobs.example.com/role/other",
        )

        self.assertFalse(_is_duplicate_listing(first, same_source))


if __name__ == "__main__":
    unittest.main()
