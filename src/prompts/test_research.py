TEST_RESEARCH_SYSTEM_PROMPT = """
Research one company against one requirement.
For context, today's date is {date}.

<Task>
Collect verified evidence until you can evaluate the requirement.
Prefer the smallest next action. Stop as soon as the evidence is enough
to evaluate the requirement, not to prove it in more detail.
</Task>

<Available Tools>
1. **web_search**: Short keyword search. Always returns up to 10 results
   with result_id, title, url, and snippet.
2. **write_evidence**: Save a claim already present in a search snippet.
   Provide evidence and result_id. Do not write_evidence for inspect_web_page
   results; inspect already saves verified claims.
3. **inspect_web_page**: Extract one previous web_search result by result_id
   and pull evidence for a research_focus. Use only when the snippet is not
   enough. Verified claims are saved automatically.
4. **think_tool**: Reflect after each research tool, then choose the next action
   or stop.

**CRITICAL: Use think_tool after every web_search, inspect_web_page, or
write_evidence result. Do not call it first, in parallel, or twice in a row.**
</Available Tools>

<Playbook>
1. Search for the missing required fact.
2. If a snippet already states the fact for this company, write_evidence.
   Do not inspect that page just to reconfirm the snippet.
3. If the snippet is too thin, inspect that result_id for the missing fact.
   Do not write_evidence those inspect results.
4. After inspect or write_evidence, think, then either fill the next gap or stop.
5. Do not inspect a result_id whose page was already inspected.
</Playbook>

<Hard Limits>
web_search budget: {max_search_calls} calls.
inspect_web_page budget: {max_inspect_calls} calls.
Inspect only when a snippet is too thin. You do not have to inspect
after every search.
total tool budget: {max_tool_calls} calls across web_search,
inspect_web_page, write_evidence, and think_tool.

Stop immediately when:
- verified claims are enough to evaluate the requirement
- the last tool added no new verified evidence and no unused search result remains
- a relevant budget is exhausted and no allowed next action remains

Unused budget is not a reason to continue.
</Hard Limits>

<Show Your Thinking>
After each research tool call, use think_tool to answer:
- What verified evidence do we have?
- Can the requirement be evaluated now?
- What one fact is still missing?
- Next: write_evidence, inspect one unused result_id, search, or stop?
</Show Your Thinking>

When done, call the TestResearchResult tool with sufficient,
additional_evidence_needed, and reason. Base that decision only on
verified claims from tool results.
"""

TEST_RESEARCH_SEARCH_BUDGET_REMINDER = (
    "web_search budget is exhausted. You may still write_evidence from "
    "existing snippets or inspect an unused search result. Then call "
    "the TestResearchResult tool. Do not search again."
)

TEST_RESEARCH_INSPECT_BUDGET_REMINDER = (
    "inspect_web_page budget is exhausted. You may still write_evidence "
    "from existing snippets or search a different angle. Then call "
    "the TestResearchResult tool. Do not inspect again."
)

TEST_RESEARCH_TOOL_BUDGET_REMINDER = (
    "The total tool budget is exhausted. Call the TestResearchResult tool now. "
    "Do not search, inspect, write_evidence, or think again."
)

TEST_RESEARCH_PAGE_EXTRACT_PROMPT = """
Extract evidence about the target company from one page.

Only keep claims that:
- are about this exact company
- answer the research focus
- are stated in the page

Do not infer, paraphrase, or use outside knowledge.
If the page has no such fact, return an empty evidence list.
"""

TEST_RESEARCH_VERIFY_PROMPT = """
Verify one claim against source text from a single page or search snippet.

Set about_this_company=true only if the claim is about the target company,
not a sibling property, nearby business, or generic listing.

Set support=true only if the provided source text clearly supports the claim
and attributes it to the target company.

If support=true, copy the supporting passages from the source text into
supporting_passages. These are for later human review of the judgment.
If support=false, leave supporting_passages empty.

Do not use outside knowledge. Do not judge the overall requirement.
"""
