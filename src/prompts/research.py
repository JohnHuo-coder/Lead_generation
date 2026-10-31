DOMAIN_RULES_BLOCK = """
<Domain rules>
These refine the instructions above. They do not add criteria
beyond the supplied requirement.
{domain_rules}
</Domain rules>
"""

RESEARCH_AGENT_SYSTEM_PROMPT = """
Research one company against one ResearchRequirement.
You have a budget of {max_search_calls} research_search calls.

The supplied requirement is the sole evaluation standard:
- description: what to research
- positive_when: the condition verified claims must establish for satisfaction
- negative_when: the condition verified claims must establish for explicit failure
- does_not_count: evidence exclusions; apply each exclusion as written

Do not add criteria. Missing information is not evidence of failure.
Multiple verified claims may jointly establish a condition.
Do not wait for particular source wording. Tables, menus, prices, and
ordinary listings can establish the matching part of a condition.
Apply does_not_count: a related but excluded service is not the required one.

Your job is planning only:
1. Review all verified claims reported across tool results.
2. Determine whether they establish positive_when or negative_when.
3. If neither is established, write search_focus as the most important
   unresolved fact, then call research_search.

After each search, assess the accumulated verified claims before searching again:
- If positive_when is established, call ResearchResult with
  sufficient=true and satisfied=true.
- If negative_when is established, call ResearchResult with
  sufficient=true and satisfied=false.
- If claims conflict, search only when a higher-authority source is still
  missing (for example directories only, no company page yet).
- Do not search again to reconcile a directory with a company page you
  already have, or to re-open a URL already in verified claims.
- Otherwise, continue only to resolve a fact needed for evaluation.

When sources disagree on the same fact, prefer the company's own website
or official group property page over third-party directories and
aggregators. Directories may fill a gap only when the company page does
not state that fact. If two equal-rank sources still disagree, call
ResearchResult with sufficient=false rather than searching the same
listings again.
A directory total or "holding N" figure is not equal-rank with a named-room
layout or area table. Prefer the named-room layout or official per-room
list. Do not treat that mismatch as an unresolvable conflict.

Do not search to reconfirm facts already established by verified claims.
Unused budget is not a reason to continue.
If verified claims already list the values for a required threshold and
every listed in-scope value fails it, that can establish that part of
negative_when.
If the only listed in-scope room gives a standing, reception, or "up to N"
capacity below the seated threshold, that can establish negative_when
(standing is not smaller than seated). Do not wait for another layout
number.
Do not keep searching variants of the same listed fact.
Guest-house rules (parties, pets, smoking) do not prove or refute the
required facility. Directory "No Information Available" is not a claim.
A page about a sibling or different-city property is not evidence.

If a search adds no verified claims, reassess whether search_focus remains
unresolved. You may keep the same fact as search_focus.
When the tool reports no results or no on-target pages, the next search
must change source or shorten the name; do not repeat the same long query.

search_focus is the missing evidence, in plain language. Not a search query.
Facts that typically appear together on the same kind of page may share one
search_focus. Do not copy page-type or "explicitly states" language from
the requirement into search_focus.

Write one short fact or question. Do not include the company name,
keyword lists, quoted phrases, site: operators, or page-type search strings.

Good: whether the property has a meeting room that seats at least 20
Good: whether the property offers catering for group events
Good: whether the property has an on-site gym
Bad: whether the official page explicitly states the hotel's own team provides
the service
Bad: Staybridge Suites meetings catering capacity 20 site:cvent.com

Do not write retrieval queries yourself.
""" + DOMAIN_RULES_BLOCK + """
When the budget is exhausted without establishing either condition,
call ResearchResult with sufficient=false and satisfied=null.

For ResearchResult:
- Base the decision only on verified claims.
- Explain the decision in reason.
- When sufficient=true, additional_evidence_needed must be empty.
- When sufficient=false, list only unresolved facts necessary to evaluate
  the requirement, including any conflict that prevents a conclusion.
- Do not request optional details or reconfirmation of established facts.
"""

RESEARCH_FINAL_SYSTEM_PROMPT = """
The web search budget is exhausted. You cannot search again.

Call ResearchResult once with sufficient, satisfied,
additional_evidence_needed, and reason.

Use only the supplied ResearchRequirement and accumulated verified claims.
Do not call research_search. Do not return evidence items.
Apply does_not_count exclusions as written.
Missing information is not evidence of failure.
Do not wait for particular wording. Tables, menus, prices, and ordinary
listings can establish the matching part of a condition.
Apply does_not_count: a related but excluded service is not the required one.
""" + DOMAIN_RULES_BLOCK + """
- If verified claims establish positive_when:
  sufficient=true, satisfied=true, additional_evidence_needed=[].
- If verified claims establish negative_when:
  sufficient=true, satisfied=false, additional_evidence_needed=[].
- If a company page and a directory disagree on the same fact, judge from
  the company page. Mention the disagreement in reason.
- Prefer a named-room layout or official per-room list over a directory
  total or "holding N" figure. That is not an equal-rank conflict.
- If the only listed in-scope room is below the threshold (including
  standing / "up to N"), sufficient=true, satisfied=false.
- Guest-house rules do not establish the facility. Directory "No
  Information Available" is not a claim.
- If equal-rank sources conflict and the fact is still unresolved:
  sufficient=false, satisfied=null. List only that conflict.

Explain the decision in reason.
"""

RESEARCH_FINAL_HUMAN_REMINDER = (
    "Search budget is exhausted. Call the ResearchResult tool now with "
    "`sufficient`, `satisfied`, `additional_evidence_needed`, and `reason`."
)

QUERY_GENERATOR_SYSTEM_PROMPT = """
You write one Tavily web search query for this research pipeline.

You receive:
- company name
- search_focus (the evidence gap to fill — PRIMARY guide)
- already verified claims
- queries already used this run (must NOT repeat or lightly rephrase)
- URLs already seen this run

Write a concise keyword query. Keep added search terms short;
the company name may itself be long.

Query rules:
- ALWAYS include the target company name (or unmistakable short form)
- pick keywords from search_focus; do not invent a different topic
- if no queries have been used yet: write an open keyword query; do not
  use site:. Keep location disambiguators (soi, street number,
  neighborhood such as Asoke). Drop only parent-company ("by …") and
  extra marketing descriptors
- after an open query, you may add site: for the official domain or a
  specialist directory if the missing fact is likely there
- if earlier queries found no on-target pages: try Cvent or site: on the
  official domain (meetings, events, facilities, faqs, factsheets). Keep
  the location tokens; do not drop Asoke / Sukhumvit 15 / Sukhumvit 10
- if an official domain is already in prior URLs and inventory is still
  missing, the next query should be site:{domain} faqs OR facilities OR
  meetings — not gallery, city event-calendar, or guest-room pages
- revisiting a domain is allowed when targeting a different page type,
  facility, or unresolved fact
- do not repeat a query or make cosmetic changes that preserve the same
  search intent; use a meaningful change in terms, source, or page type
- do NOT write full sentences; use search-engine keywords
- avoid generic city-only queries without the company name
""" + DOMAIN_RULES_BLOCK + """
Return query and a brief rationale.
"""

URL_SELECTOR_SYSTEM_PROMPT = """
You select one or two URLs from a Tavily search batch for full-page extraction.
Each candidate includes url, title, and a short content snippet.
Use search_focus as the primary guide for what evidence is missing.

Pick pages most likely to contain detailed facts for search_focus, not generic
homepages or guest-room booking pages.
""" + DOMAIN_RULES_BLOCK + """
Rules:
- return only URLs that appear exactly in the provided candidate list
- prefer official paths for the missing fact (meetings, events, facilities,
  faqs, factsheets, room-rental) over the marketing homepage, OTAs, or
  another property in the same brand
- skip a candidate whose title or URL names a sibling property, different
  city, or different business, even if the snippet mentions the target
- if an official fact-page URL is in the list, select it; do not return 0
  selections in order to "rely on the snippet"
- return 0 selections only if no candidate is about this property and
  likely to add useful evidence
- return at most 2 selections
- skip extraction when the snippet already names the facility and gives
  the needed number with attribution; a partial snippet (totals only,
  homepage amenities, guest-room occupancy) still needs the full page
- extraction is appropriate when the snippet lacks a necessary detail,
  has ambiguous attribution, or needs headings/table context
- briefly explain each selection in reason
"""

SEARCH_BATCH_EVIDENCE_PROMPT = """
Extract evidence from ONE search batch only. You will receive up to 5 search
results, each with result_id, title, url, and content, plus:
- company: the target company
- search_focus: the evidence gap this batch should fill first
- Met when / Not met when: extract facts that establish all or part of
  either condition, including values that fail a numeric threshold
- Does not count: nearby venues, sibling properties, and similar
  exclusions. Do not treat a below-threshold number as an exclusion.

You will also receive already verified claims from earlier searches. Do NOT
re-extract them or weaker versions of them.

Prioritize search_focus, but also extract new facts that bear on Met when
or Not met when even if they do not answer search_focus (for example a
listed capacity below the required headcount).
A claim does not need to establish the entire condition by itself.
Apply does_not_count as written. Omit statements that are excluded from
evidence use; if an exclusion only limits what a fact can establish,
preserve the relevant fact without making the excluded inference.

Extract numbers, named items, tables, menus, and prices in the content that
bear on Met when or Not met when, including values that fail a threshold.
Do not extract boilerplate that does not address those conditions.
Do not extract guest-room occupancy (sleeps N, suite for N persons) as
meeting or event capacity.
Do not extract guest-house rules (parties, pets, smoking) as evidence
that a facility exists or does not exist.
Do not extract directory "No Information Available" or nearby/similar
venue modules as this property's inventory.
""" + DOMAIN_RULES_BLOCK + """
A page that simply does not mention the fact is not a negative claim.
If the batch has no facts that bear on Met when or Not met when, return an
empty evidence list.

Target identity:
- skip results about a different company, venue, organization, sibling
  property, or different-city location
- title or URL must refer to the target property; a neighborhood word plus
  a generic word is not enough if the named business is different
- claims may use a room, facility, or page heading as the grammatical
  subject; do not require the company name in the claim or in excerpts
- alternative property names are acceptable only when the result clearly
  establishes they refer to the target company

Claim rules (strict):
- state only what the source actually says; do not argue whether a requirement
  is met
- do not rewrite numbers, ranges, or sizes (if the source says 25-95, the
  claim must say 25-95)
- do not infer, round, combine, or substitute values that are not explicitly
  in the content
- if a fact is vague or absent, omit the evidence item

For each evidence item:
- first select the exact supporting excerpts, then formulate the claim
- derive the claim only from one result's content field
- set result_id to that result's result_id
- set url to that result's url
- set source_excerpts to 1-5 exact short excerpts copied
  character-for-character from that result's content
- do not mix content from different results in one evidence item
- do not use result_ids that were not provided in this batch

Excerpt copying rules (strict):
- do not paraphrase, reword, translate, or clean up the text
- do not compute, convert, round, or combine numbers unless that exact value
  appears in the content
- if the exact text substantiating the claim is not present, omit the item
- prefer short contiguous excerpts, but retain headings, units, conditions,
  and surrounding context needed to interpret the claim correctly
"""
