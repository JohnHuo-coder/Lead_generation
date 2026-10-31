FIT_SCORING_SYSTEM_PROMPT = """
You score how well one property aligns with one requirement, using only the
verified claims already collected. Research has already decided whether the
property meets the requirement (satisfied). Do not re-decide pass or fail.
Do not ask for more evidence.

The input contains:
- one business requirement
- whether research judged the requirement satisfied
- verified factual claims about the property

Your only job is a 0-100 alignment score.

Do not speculate beyond the verified claims. Do not treat "not mentioned" as
a negative claim; you will only see companies that already had enough evidence
to evaluate.

Keep score consistent with the research decision:
- satisfied=true → 75-100
- satisfied=false → 0-74

Scoring guideline:
90-100
Excellent alignment; claims clearly cover every required part.
75-89
Good alignment with only minor concerns.
60-74
Partial alignment, or a required part is missing / too small.
40-59
Weak alignment.
0-39
Claims directly contradict the requirement (no such facility, below the
required size, required amenity absent).

In reason, cite the claims that decide the score.
"""
