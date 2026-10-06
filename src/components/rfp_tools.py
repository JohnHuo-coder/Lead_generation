from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.types import Command

from components.state import RfpAgentState


@tool(parse_docstring=True)
def think_tool(reflection: str) -> str:
    """Reflect on research progress before using another research tool or finishing.

    Use this tool after receiving results from tavily_search, tavily_extract,
    or tavily_crawl.

    Do not call this tool before receiving a research result.
    Do not call it in parallel with a Tavily tool.
    Do not call it twice consecutively.

    The reflection should determine:

    1. What useful information was found?
    2. Does it refer to the exact target hotel?
    3. Is there a verified, actionable meeting/event inquiry channel?
    4. What specific uncertainty remains?
    5. Should the next action be:
       - search for a different page or source
       - extract an already-known candidate page
       - crawl a known site to locate a hidden inquiry entry
       - stop because a reliable route was found
       - stop because the research budget is exhausted

    An official meetings page counts only if extract or crawl text shows a
    quote / RFP / enquiry form or button. A failed extract, a search snippet,
    or "this brand usually has a button" is not enough. Return null instead.
    Do not keep searching for the button's hidden href.

    An official email found on a meetings page is optional fallback only.
    Do not treat missing email as remaining uncertainty.

    Do not recommend extracting or crawling a URL that already failed
    or was already extracted.

    Prefer the smallest next action that resolves the remaining uncertainty.
    Stop researching once a high-confidence actionable route is verified.

    This tool records reasoning only. The reflection is not evidence;
    factual conclusions must come from Tavily tool results.

    Args:
        reflection: Concise analysis of findings, remaining uncertainty,
            and the best next action.

    Returns:
        Confirmation that the reflection was recorded.
    """

    return "Reflection recorded."


@tool
def save_contact_email(
    email: str,
    runtime: ToolRuntime[None, RfpAgentState],
) -> Command:
    """Save the best hotel contact email as a fallback.

    Use only after extracting an official meetings or events page, if that
    page already shows an email that belongs to the target hotel and is
    appropriate for event, group, sales, or general inquiries.

    Do not search, extract, or crawl in order to find an email.
    Do not save reservation-only emails, OTA emails, vendor emails, or emails
    belonging to another property.

    Saving an email does not complete the task. Continue looking for an
    actionable RFP or event inquiry route.
    """

    email = email.strip().lower()

    return Command(
        update={
            "fallback_email": email,
            "messages": [
                ToolMessage(
                    content=(
                        f"Saved {email} as the fallback contact email. "
                        "Continue looking for an actionable RFP route."
                    ),
                    tool_call_id=runtime.tool_call_id,
                )
            ],
        }
    )
