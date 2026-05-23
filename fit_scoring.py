from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from web_scraper import scrape_hotel_website_summary

from prompts import (
    HOTEL_MEDSPA_WELLNESS_EVAL_SYSTEM_PROMPT,
    build_hotel_eval_user_prompt,
)
from schemas import EvalResult

load_dotenv()

llm = ChatOpenAI(model = "gpt-4o-mini", temperature = 0)


def llm_score_with_evidence(
    about_text: str,
    meetings_and_events_content: str,
    amenities_content: str,
    location_content: str,
) -> EvalResult:
    user_prompt = build_hotel_eval_user_prompt(
        about_text=about_text,
        meetings_and_events_content=meetings_and_events_content,
        amenities_content=amenities_content,
        location_content=location_content,
    )
    structured_llm = llm.with_structured_output(EvalResult)
    result: EvalResult = structured_llm.invoke(
        [
            SystemMessage(content = HOTEL_MEDSPA_WELLNESS_EVAL_SYSTEM_PROMPT),
            HumanMessage(content = user_prompt)
        ]
    )
    return result

def filter_matches(matches):
    qualified = []
    # for email composer to use
    qualified_summary = []
    for m in matches:
        website = m.get("website", "")
        score = m.get("totalScore", 0)
        closed = m.get("permanentlyClosed", False)
        reviews = m.get("reviewsCount", 0)
        stars = m.get("hotelStars")  
        if not website or score < 3.5 or closed or reviews < 100:
            continue

        desc = m["description"] 
        hotel_desc = m["hotelDescription"]

        summary = scrape_hotel_website_summary(website)
        status = summary["status"]
        if status == "ok":
            about = summary["about"]
            events_meetings = summary["events_meetings"]
            promotion_news = summary["promotion_news"]
            facility_amenity = summary["facility_amenity"]
            full_content = summary["full_content"]

            eval_result = llm_score_with_evidence(
                about,
                events_meetings,
                facility_amenity,
                location_content = ""
            ) 
            total_score = eval_result.total_score
            # if total_score > sth:
                # qualified.append(m)
                # also add summary, pass to emal_composer
                # store detailed score and recommandation, evidence inside google doc for review
            # else:
                # store filtered out candidates in another doc, for review
    return qualified, qualified_summary