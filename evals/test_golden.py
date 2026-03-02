"""Golden-example evals: judge the bot's output against reference answers.

10 in-domain cases covering the core supplement label literacy domain.
Each response is judged against a reference answer by a judge model (MaaJ).
Pass threshold: >= 6/10.
"""

from conftest import get_response, judge_with_golden

GOLDEN_EXAMPLES = [
    {
        "name": "creatine_monohydrate",
        "input": "Does creatine monohydrate actually work?",
        "reference": (
            "Yes. Creatine monohydrate has strong evidence — hundreds of RCTs and "
            "meta-analyses confirm it improves strength and power output. Effective "
            "dose is 3–5g per day. Monohydrate is the best-supported form; fancier "
            "variants like Kre-Alkalyn or HCl have no evidence of superiority."
        ),
    },
    {
        "name": "proprietary_blend_flag",
        "input": (
            "Pre-workout label says 'Pump Matrix (4000mg): L-Citrulline, "
            "Arginine, Beet Root Extract'. Is this good?"
        ),
        "reference": (
            "Red flag: proprietary blend. You cannot tell how much of each "
            "ingredient is in there. L-Citrulline needs 6000–8000mg alone to be "
            "effective — impossible at 4000mg total for three ingredients. "
            "This is likely pixie-dusted. Avoid proprietary blends when possible."
        ),
    },
    {
        "name": "bcaa_verdict",
        "input": "Are BCAAs worth taking if I already eat enough protein?",
        "reference": (
            "No, for most people. BCAAs (leucine, isoleucine, valine) are already "
            "present in dietary protein. If you hit your protein targets, additional "
            "BCAA supplements show weak evidence of benefit. They are redundant and "
            "overpriced compared to just eating protein. Evidence rating: Weak."
        ),
    },
    {
        "name": "clinically_studied_claim",
        "input": "What does 'clinically studied ingredients' mean on a supplement label?",
        "reference": (
            "Almost nothing on its own. Any ingredient can be 'clinically studied' "
            "by even a single small, industry-funded study. It does not mean the "
            "evidence is strong, the dose on the label matches what was studied, "
            "or that the results were meaningful. Always ask: studied by whom, at "
            "what dose, with what result?"
        ),
    },
    {
        "name": "vitamin_d_evidence",
        "input": "Should I take Vitamin D3?",
        "reference": (
            "Possibly, depending on your levels. Vitamin D3 has strong evidence for "
            "correcting deficiency, which is very common especially in people with "
            "limited sun exposure. A standard supplemental dose is 1000–4000 IU/day. "
            "Getting your levels tested first is ideal. D3 is better absorbed than D2."
        ),
    },
    {
        "name": "ashwagandha_evidence",
        "input": "Is ashwagandha legit or just a trendy herb?",
        "reference": (
            "Moderate evidence for stress and cortisol reduction. The KSM-66 "
            "and Sensoril extracts have the most research behind them. Effective "
            "dose around 300–600mg of a standardized extract. Evidence for other "
            "claimed benefits (testosterone, sleep) is weaker. Not pure hype, "
            "but not a miracle either."
        ),
    },
    {
        "name": "magnesium_forms",
        "input": "What's the difference between magnesium glycinate and magnesium oxide?",
        "reference": (
            "Magnesium glycinate has much better absorption (bioavailability) than "
            "magnesium oxide. Oxide is the cheapest form but poorly absorbed and "
            "mostly acts as a laxative. Glycinate is preferred for sleep, anxiety, "
            "and general supplementation. Citrate is a middle ground — decent "
            "absorption, cheaper than glycinate."
        ),
    },
    {
        "name": "collagen_muscle_claim",
        "input": "My protein powder has collagen peptides in it. Does that help build muscle?",
        "reference": (
            "No, not effectively. Collagen is low in leucine, the key amino acid "
            "that triggers muscle protein synthesis. It is not a substitute for "
            "whey, casein, or plant proteins for muscle building. There is "
            "weak-to-moderate evidence for collagen helping joints and tendons, "
            "but for muscle growth it is the wrong tool."
        ),
    },
    {
        "name": "nsf_certification",
        "input": "What does NSF Certified for Sport mean?",
        "reference": (
            "NSF Certified for Sport is one of the most credible third-party "
            "certifications. It means the product has been independently tested "
            "to verify the label is accurate and that it contains no banned "
            "substances prohibited by major sports organizations. It is meaningful "
            "and worth looking for, especially for competitive athletes."
        ),
    },
    {
        "name": "beta_alanine_dose",
        "input": "My pre-workout has 1.6g of beta-alanine. Is that enough?",
        "reference": (
            "No, it is under-dosed. The evidence-backed range for beta-alanine "
            "is 3.2–6.4g per day. At 1.6g, you are getting half the minimum "
            "effective dose. You might notice some tingling (paresthesia), "
            "but the endurance benefit will be minimal. This is a common "
            "example of pixie-dusting — just enough to put it on the label."
        ),
    },
]


def test_golden_examples():
    """Each bot response should score >= 6/10 against its golden reference."""
    print()
    ratings = []
    for example in GOLDEN_EXAMPLES:
        response = get_response(example["input"])
        rating = judge_with_golden(
            prompt=example["input"],
            reference=example["reference"],
            response=response,
        )
        ratings.append(rating)
        status = "PASS" if rating >= 6 else "FAIL"
        print(f"  [{status}] {example['name']}: {rating}/10")
        assert rating >= 6, (
            f"[{example['name']}] Rating {rating}/10 — response: {response[:200]}"
        )
    print(f"  average: {sum(ratings) / len(ratings):.1f}/10")
    print(f"  pass rate: {sum(1 for r in ratings if r >= 6)}/{len(ratings)}")
