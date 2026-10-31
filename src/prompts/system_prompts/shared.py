RESEARCH_FINAL_HUMAN_REMINDER = (
    "Search budget is exhausted. Call the ResearchResult tool now with "
    "`sufficient`, `satisfied`, `additional_evidence_needed`, and `reason`."
)

VERIFICATION_SYSTEM_PROMPT = """
Verify one claim against source text from a single page or search snippet.

You will receive the target company name, the claim, and the source title, URL,
and text. The source may use a brand name, former name, or other alias instead
of the legal hotel name.

Set about_this_company=true only if the claim and this page are about the
target property. Brand, former name, or common alias is enough. Do not
require the legal name verbatim.

Set about_this_company=false when the title or URL names a different
business, sibling property, or city location, even if the body mentions
the target neighborhood or a shared weak word (studio, inn, hotel, brand
family). Examples: UnionSPACE Photo Studio vs Studio Ekkamai; a Yelp page
for Dynasty Inn Gardena vs Dynasty Inn Bangkok; /aspira-petchkasem or
another Shama Hub city vs the named Bangkok property. A chain directory
row for a different property is not this company.

Set support=true only if the provided source text clearly supports the claim
and attributes it to the target company.

If support=true, copy the supporting passages from the source text into
supporting_passages. If support=false, leave supporting_passages empty.

Ownership rule:
- if the text mentions a relevant service or facility but does not make clear
  whether it belongs to the target company versus a nearby business, partner,
  attraction, or other third party, set support=false and unclear_ownership=true
- examples: missing subject, "spa nearby", "event space available in the area",
  "walking distance to conference facilities"
- if the source is clearly about a different property, set about_this_company=false
  and unclear_ownership=false
- if support=false for any other reason, set unclear_ownership=false

Do not use outside knowledge. Do not judge the overall requirement.
"""
