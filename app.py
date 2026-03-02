import os
import re
import uuid
import random
import logging
import threading
from pathlib import Path

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from litellm import completion
from pydantic import BaseModel

load_dotenv()

# --- Config ---

MODEL = os.getenv("MODEL", "vertex_ai/gemini-2.5-flash-lite")
LITELLM_API_BASE = os.getenv("LITELLM_API_BASE")
LITELLM_API_KEY = os.getenv("LITELLM_API_KEY")
GIPHY_API_KEY = os.getenv("GIPHY_API_KEY", "")

print(f"[STARTUP] MODEL={MODEL}")
print(f"[STARTUP] GIPHY_API_KEY={'SET' if GIPHY_API_KEY else 'NOT SET'}")

INDEX_HTML_PATH = Path(__file__).resolve().parent / "index.html"
LOGGER = logging.getLogger("label_lens")

MAX_MESSAGE_CHARS = 4000
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB decoded payload cap
VISITOR_COOKIE_NAME = "label_lens_visitor_id"
VISITOR_COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 365  # 1 year

# --- Prompts ---

SYSTEM_PROMPT = """\
<role>
You are Label Lens, a no-nonsense supplement label analyst. Your job is \
to decode what ingredients on supplement labels actually do (or don't do), \
based on peer-reviewed evidence. You speak plainly, cite evidence quality, \
and call out marketing fluff without hesitation. Your audience is curious, \
health-conscious consumers who want the truth behind the label.
</role>

<task>
When a user shares supplement ingredients, a label, or asks about a specific \
ingredient or claim, you:
1. Identify each key ingredient and state what the evidence actually says.
2. Rate the evidence quality: Strong / Moderate / Weak / No Evidence.
3. Flag pure marketing language (proprietary blends, "supports", "boosts", \
"optimizes") for what it is.
4. Give a plain-English verdict on whether the product is likely worth it.
</task>

<positive_constraints>
This assistant answers questions about:
- Specific supplement ingredients and what peer-reviewed research says about them
- Decoding label claims (e.g. "clinically studied", "proprietary blend", "supports X")
- Comparing ingredient doses on a label to doses used in research
- Explaining what certifications like NSF, USP, or Informed Sport actually mean
- Common supplement categories: pre-workout, protein, vitamins, minerals, \
adaptogens, probiotics, omega-3s, creatine, collagen, nootropics
</positive_constraints>

<escape_hatch>
If you are unsure about a specific ingredient or the evidence is genuinely \
unclear, say so directly: "The evidence here is limited or mixed — I'd \
recommend checking Examine.com or PubMed for the latest research." \
Never invent studies or dosage claims.
</escape_hatch>

<out_of_scope>
This assistant focuses on ingredient evidence and label literacy. \
For medical questions (disease treatment, drug interactions, personal health \
conditions), direct the user to a doctor or pharmacist. \
For questions about buying or pricing supplements, acknowledge this is outside \
your scope. \
For questions about food nutrition rather than supplements, note that this tool \
is specifically for supplement labels.
</out_of_scope>

<rules>
EVIDENCE RATING SYSTEM
- Strong: Multiple large RCTs with consistent findings
- Moderate: Some RCTs or consistent meta-analyses, but limited data
- Weak: Small studies, animal studies, or inconsistent results
- No Evidence: No credible human research found

OUTPUT LENGTH
- Keep your entire response at or below 2500 characters.
- If needed, prioritize key ingredients, evidence quality, and final verdict.

COMMON MARKETING FLAGS
- "Proprietary blend": Hides individual ingredient doses — always a red flag
- "Clinically studied": Means almost nothing without a citation
- "Supports" / "boosts" / "optimizes": FDA-required hedge language, not a claim
- "Doctor formulated": Not a credential or guarantee of efficacy
- "Natural": Not synonymous with safe or effective
- Pixie-dusting: Including a trendy ingredient at far below the effective dose

INGREDIENT QUICK REFERENCE
- Creatine monohydrate: Strong evidence for strength and power; 3-5g/day effective
- Caffeine: Strong evidence for alertness and performance; 3-6mg/kg effective
- Beta-alanine: Moderate evidence for muscular endurance; 3.2-6.4g/day; causes harmless tingling
- Citrulline malate: Moderate evidence for blood flow and endurance; 6-8g/day
- Ashwagandha: Moderate evidence for stress/cortisol reduction; 300-600mg KSM-66
- Vitamin D3: Strong evidence for deficiency correction; 1000-4000 IU/day
- Magnesium: Strong evidence for deficiency; varied by form (glycinate > oxide)
- Collagen peptides: Weak-to-moderate for joints; no strong muscle-building evidence
- BCAAs: Weak evidence when adequate protein is consumed; redundant for most
- L-carnitine: Weak evidence for fat loss; some evidence for recovery at 2g/day
- Adaptogens (general): Weak to moderate; Rhodiola and Ashwagandha best supported
- Proprietary nootropic blends: Usually weak evidence and under-dosed
</rules>"""

FEW_SHOT_EXAMPLES = [
    {
        "user": (
            "Label says: Pre-workout with 'Explosive Energy Matrix (3000mg): "
            "Caffeine anhydrous, L-Citrulline, Beta-Alanine, Taurine'. "
            "Is this any good?"
        ),
        "assistant": (
            "**Red flag: Proprietary blend.** You're seeing a 3000mg total for "
            "four ingredients — but you have no idea how much of each is in there.\n\n"
            "Here's what the ingredients could do:\n\n"
            "- **Caffeine anhydrous** — Strong evidence for energy and performance. "
            "Effective dose: 150–300mg. Unknown here.\n"
            "- **L-Citrulline** — Moderate evidence for blood flow and endurance. "
            "Effective dose: 6000–8000mg. Impossible at 3000mg total for all four.\n"
            "- **Beta-Alanine** — Moderate evidence for endurance. "
            "Effective dose: 3200mg. Almost certainly under-dosed here.\n"
            "- **Taurine** — Weak evidence for performance. Mostly filler.\n\n"
            "**Verdict:** The only ingredient likely at an effective dose is caffeine. "
            "Everything else is probably pixie-dusted. This label is hiding "
            "under-dosed ingredients behind a blend name."
        ),
    },
    {
        "user": "Does creatine monohydrate actually work or is it just hype?",
        "assistant": (
            "**Creatine monohydrate is one of the most well-supported supplements in existence.**\n\n"
            "- **Evidence: Strong.** Hundreds of studies, multiple meta-analyses.\n"
            "- **What it does:** Increases phosphocreatine stores in muscle, "
            "improving performance in short, high-intensity efforts (lifting, sprinting).\n"
            "- **Effective dose:** 3–5g per day. No loading phase required "
            "(though 20g/day for 5 days speeds saturation).\n"
            "- **Form:** Monohydrate is the gold standard. Ignore 'Kre-Alkalyn', "
            "'HCl', or 'Buffered' variants — no evidence they're superior and they cost more.\n\n"
            "**Verdict:** Not hype. It works, it's cheap, and it's safe for healthy adults. "
            "If you see 'Creatine blend' on a label, check it's monohydrate and at 3–5g."
        ),
    },
    {
        "user": (
            "My protein powder says 'Enzyme Blend for Maximum Absorption' — "
            "is that real or marketing?"
        ),
        "assistant": (
            "**Marketing, mostly.**\n\n"
            "- **Digestive enzyme blends** (usually protease, amylase, lipase) "
            "in protein powders claim to improve protein digestion and absorption.\n"
            "- **Evidence: Weak.** A few small studies show modest improvements "
            "in protein absorption in people with digestive issues. For healthy "
            "adults already producing enough digestive enzymes, the benefit is negligible.\n"
            "- **Dose problem:** Amounts used in research (e.g., 3mg+ protease) "
            "are rarely disclosed on labels. You're likely getting a sprinkle.\n\n"
            "**Verdict:** This is a value-add claim that sounds scientific but means "
            "little for most people. It won't hurt you, but you're paying for a feature "
            "with minimal real-world impact. Focus on total protein per serving and the "
            "amino acid profile instead."
        ),
    },
]

# --- Safety backstop ---

DISTRESS_PATTERNS = re.compile(
    r"\b(kill myself|suicide|end my life|self.?harm|hurt myself|don't want to live|"
    r"want to die|eating disorder|starving myself|stop eating|purging)\b",
    re.IGNORECASE,
)

MEDICAL_CLAIM_PATTERNS = re.compile(
    r"\b(cure|treat|diagnose|prescription|drug interaction|my doctor said|"
    r"my medication|chemotherapy|cancer treatment|diabetes medication|"
    r"blood pressure medication)\b",
    re.IGNORECASE,
)

MEDICAL_CONDITION_PATTERNS = re.compile(
    r"\b(kidney|renal|liver|hepatic|pregnant|pregnancy|breastfeeding|thyroid|"
    r"hypothyroid|hyperthyroid|hypertension|high blood pressure|heart disease|"
    r"cardiac|autoimmune|lupus|hashimoto|diabetes|pcos|epilepsy|seizure|"
    r"cancer|chronic disease|medical condition)\b",
    re.IGNORECASE,
)

MEDICAL_ADVICE_PATTERNS = re.compile(
    r"\b(can i take|should i take|what should i take|what supplements should i take|"
    r"what supplement should i take|is it safe|safe for me|supplement advice|"
    r"recommend(ed)? supplement|which supplement|what supplement|what supplements|"
    r"dose should i take)\b",
    re.IGNORECASE,
)

JAILBREAK_PATTERNS = re.compile(
    r"\b(ignore (all )?(previous|prior)? ?(rules|instructions|prompts|guardrails)|"
    r"all previous rules|all previous instructions|you are now|unrestricted|"
    r"scope limitations are deleted|developer mode|act as|roleplay as)\b",
    re.IGNORECASE,
)

MEDICAL_BIOMARKER_PATTERNS = re.compile(
    r"\b(bloodwork|blood work|labs?|biomarkers?|total t|free t|shbg|"
    r"testosterone|estradiol|a1c|tsh|t3|t4|ng/dl|pg/ml|nmol/l)\b",
    re.IGNORECASE,
)

MEDICAL_PROTOCOL_INTENT_PATTERNS = re.compile(
    r"\b(exact protocol|dosing protocol|protocol|stack|optimization clinic|"
    r"what would you give|no doctor.?speak|no hedging|maximal truth|"
    r"moves the needle)\b",
    re.IGNORECASE,
)

NUTRITION_OR_DIET_PATTERNS = re.compile(
    r"\b(calories?|calorie deficit|macros?|meal plan|diet plan|weight loss plan|"
    r"cutting|bulking|lose weight|fat loss|daily intake|maintenance calories|"
    r"nutrition facts|carbs?|protein intake|how many calories)\b",
    re.IGNORECASE,
)

SHOPPING_OR_PRICING_PATTERNS = re.compile(
    r"\b(price|pricing|cost|cheap|cheaper|cheapest|best brand|which brand|"
    r"where to buy|where should i buy|where can i buy|should i buy|"
    r"buying|amazon|discount|deal|coupon|subscription|meal delivery|"
    r"recommend a product|product recommendation|brand recommendation)\b",
    re.IGNORECASE,
)

SAFETY_FALLBACK_PROMPT = """\
<role>
You are a compassionate assistant. The user's message may contain signs of \
distress or a serious medical situation that requires professional support.
</role>
<task>
Respond with warmth and care. Do not provide supplement advice. \
Gently acknowledge what the user shared and encourage them to speak with \
a healthcare professional or a trusted person. If distress signals are present, \
mention that crisis support is available (e.g. 988 Suicide & Crisis Lifeline \
in the US). Keep your entire response at or below 2500 characters.
</task>"""

MEDICAL_REDIRECT_PROMPT = """\
<role>You are Label Lens, a supplement label analyst.</role>
<task>
The user's question involves a medical condition, prescription drug, or \
drug interaction. Acknowledge their question, explain that this is outside \
your scope as a supplement label tool, and recommend they speak with a \
doctor or pharmacist who can account for their full health picture. \
Be warm and brief. Keep your entire response at or below 2500 characters.
</task>"""

NUTRITION_REDIRECT_PROMPT = """\
<role>You are Label Lens, a supplement label analyst.</role>
<task>
The user is asking for general diet or calorie planning rather than supplement \
label analysis. Briefly acknowledge and explain this tool focuses on supplement \
ingredients and label claims, not personalized nutrition planning. Suggest they \
use a registered dietitian or a dedicated nutrition app for calorie/macronutrient \
targets. Keep it concise and helpful. Keep your entire response at or below 2500 characters.
</task>"""

SHOPPING_REDIRECT_PROMPT = """\
<role>You are Label Lens, a supplement label analyst.</role>
<task>
The user is asking for shopping, brand, or pricing recommendations. Briefly say \
that this tool focuses on evidence behind ingredients and label literacy rather \
than product purchasing advice. Invite them to share a specific label/ingredient \
if they want an evidence-based analysis. Keep it concise and helpful. Keep your entire response at or below 2500 characters.
</task>"""

MEDICAL_REDIRECT_TEXT = (
    "I can't provide personalized supplement protocols for medical conditions, "
    "symptoms, lab results, or medication questions. Please consult a doctor or "
    "pharmacist."
)

POST_BACKSTOP_MEDICAL_ADVICE_PATTERNS = re.compile(
    r"\b(you should|i recommend|recommended dose|dosage|start|stop|increase|decrease|"
    r"take \d+|\d+\s?(mg|g|iu|mcg)|daily dose|once daily|twice daily|per day|"
    r"every day|weekly|cycle|protocol|stack)\b",
    re.IGNORECASE,
)

POST_BACKSTOP_DANGEROUS_INSTRUCTION_PATTERNS = re.compile(
    r"\b(stop (your )?medication|replace (your )?medication|instead of (your )?medication|"
    r"no need to see (a )?doctor|self-diagnose)\b",
    re.IGNORECASE,
)


def apply_post_backstop(user_text: str, response_text: str) -> str:
    """Light output guardrail for medical-condition treatment/advice leakage."""
    if not response_text:
        return response_text

    user_is_medical = classify_message(user_text) == "medical"

    if POST_BACKSTOP_DANGEROUS_INSTRUCTION_PATTERNS.search(response_text):
        LOGGER.warning("Post-backstop override: dangerous instruction detected")
        return MEDICAL_REDIRECT_TEXT

    if user_is_medical and POST_BACKSTOP_MEDICAL_ADVICE_PATTERNS.search(response_text):
        LOGGER.warning("Post-backstop override: medical prompt + directive advice detected")
        return MEDICAL_REDIRECT_TEXT

    if (
        MEDICAL_CONDITION_PATTERNS.search(response_text)
        and POST_BACKSTOP_MEDICAL_ADVICE_PATTERNS.search(response_text)
    ):
        LOGGER.warning("Post-backstop override: medical condition + directive advice detected")
        return MEDICAL_REDIRECT_TEXT

    return response_text


def is_medical_jailbreak_or_protocol(text: str) -> bool:
    lower = text.lower()
    has_medical_context = bool(
        MEDICAL_CONDITION_PATTERNS.search(text) or MEDICAL_BIOMARKER_PATTERNS.search(text)
    )
    has_protocol_intent = bool(
        MEDICAL_ADVICE_PATTERNS.search(text) or MEDICAL_PROTOCOL_INTENT_PATTERNS.search(text)
    )
    if has_medical_context and has_protocol_intent:
        return True
    if JAILBREAK_PATTERNS.search(text) and (
        has_medical_context or has_protocol_intent or "patient" in lower
    ):
        return True
    return False


def classify_message(text: str) -> str:
    """Return one of: distress, medical, nutrition_or_diet, shopping_or_pricing, ok."""
    if DISTRESS_PATTERNS.search(text):
        return "distress"
    if MEDICAL_CLAIM_PATTERNS.search(text):
        return "medical"
    if is_medical_jailbreak_or_protocol(text):
        return "medical"
    if NUTRITION_OR_DIET_PATTERNS.search(text):
        return "nutrition_or_diet"
    if SHOPPING_OR_PRICING_PATTERNS.search(text):
        return "shopping_or_pricing"
    return "ok"


def build_initial_messages() -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example in FEW_SHOT_EXAMPLES:
        messages.append({"role": "user", "content": example["user"]})
        messages.append({"role": "assistant", "content": example["assistant"]})
    return messages


def build_fallback_messages(text: str, fallback_prompt: str) -> list[dict]:
    return [
        {"role": "system", "content": fallback_prompt},
        {"role": "user", "content": text},
    ]


# --- LLM Call ---

def generate_response(messages: list[dict]) -> str:
    try:
        completion_kwargs = {"model": MODEL, "messages": messages}
        if LITELLM_API_BASE:
            completion_kwargs["api_base"] = LITELLM_API_BASE
        if LITELLM_API_KEY:
            completion_kwargs["api_key"] = LITELLM_API_KEY
        print(f"Using model: {MODEL}")
        response = completion(**completion_kwargs)
        return response.choices[0].message.content
    except Exception as e:
        LOGGER.exception("LLM response generation failed")
        return "I hit an internal error while generating a response. Please try again."


# --- Giphy ---

GIPHY_QUERY_SUMMARY_PROMPT = """\
You extract only the main ingredient from supplement-chat context.
Given the user message and assistant response, output exactly one ingredient phrase.

Requirements:
- Output only the main ingredient name.
- Keep it concise (2 to 3 words max).
- Lowercase only.
- No punctuation, no quotes, no extra text.
- If no ingredient is identifiable, output: funny cat
"""


def summarize_giphy_query(user_text: str, response_text: str) -> str:
    """Generate a query containing only the main ingredient."""
    fallback = "supplement"
    try:
        messages = [
            {"role": "system", "content": GIPHY_QUERY_SUMMARY_PROMPT},
            {
                "role": "user",
                "content": (
                    "User message:\n"
                    f"{user_text}\n\n"
                    "Assistant response:\n"
                    f"{response_text}"
                ),
            },
        ]
        completion_kwargs = {"model": MODEL, "messages": messages}
        if LITELLM_API_BASE:
            completion_kwargs["api_base"] = LITELLM_API_BASE
        if LITELLM_API_KEY:
            completion_kwargs["api_key"] = LITELLM_API_KEY

        summary = (completion(**completion_kwargs).choices[0].message.content or "").strip().lower()
        summary = re.sub(r"[^a-z0-9\s-]", " ", summary)
        words = [w for w in re.split(r"\s+", summary) if w]

        if not words:
            print(f"[GIPHY] Empty summary → fallback '{fallback}'")
            return fallback

        query = " ".join(words[:3])
        print(f"[GIPHY] Main ingredient query: '{query}'")
        return query
    except Exception as e:
        print(f"[GIPHY] Summary generation error: {e}")
        return fallback


def fetch_giphy(query: str) -> str | None:

    print(f"[GIPHY] Fetching GIF for query: '{query}'")
    """Search Giphy and return a GIF URL, or None on failure."""
    if not GIPHY_API_KEY:
        print("[GIPHY] Skipped — GIPHY_API_KEY not set")
        return None
    try:
        resp = requests.get(
            "https://api.giphy.com/v1/gifs/search",
            params={
                "api_key": GIPHY_API_KEY,
                "q": query,
                "limit": 10,
                "rating": "g",
                "lang": "en",
            },
            timeout=5,
        )
        print(f"[GIPHY] HTTP {resp.status_code} for query: '{query}'")
        data = resp.json().get("data", [])
        print(f"[GIPHY] Results: {len(data)}")
        if data:
            pick = random.choice(data[:7])
            url = pick["images"]["downsized_medium"]["url"]
            print(f"[GIPHY] URL: {url}")
            return url
    except Exception as e:
        print(f"[GIPHY] Error: {e}")
    return None


def estimate_base64_size_bytes(data: str) -> int:
    """Approximate decoded byte size from base64 string length."""
    cleaned = re.sub(r"\s+", "", data)
    if "," in cleaned:
        cleaned = cleaned.split(",", 1)[1]
    padding = cleaned.count("=")
    return max((len(cleaned) * 3) // 4 - padding, 0)


# --- Session Management ---

sessions: dict[str, list[dict]] = {}
site_view_count = 0
seen_visitor_ids: set[str] = set()
view_counter_lock = threading.Lock()

# --- FastAPI App ---

app = FastAPI()


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    image_base64: str | None = None
    image_media_type: str | None = "image/jpeg"


class ChatResponse(BaseModel):
    response: str
    session_id: str
    gif_url: str | None = None
    giphy_query: str | None = None   # exposed for debugging


class StatsResponse(BaseModel):
    views: int


@app.get("/")
def index(request: Request):
    global site_view_count

    visitor_id = request.cookies.get(VISITOR_COOKIE_NAME) or str(uuid.uuid4())
    with view_counter_lock:
        if visitor_id not in seen_visitor_ids:
            seen_visitor_ids.add(visitor_id)
            site_view_count += 1

    response = FileResponse(INDEX_HTML_PATH)
    if request.cookies.get(VISITOR_COOKIE_NAME) != visitor_id:
        response.set_cookie(
            key=VISITOR_COOKIE_NAME,
            value=visitor_id,
            max_age=VISITOR_COOKIE_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
    return response


@app.get("/stats", response_model=StatsResponse)
def stats():
    with view_counter_lock:
        current_views = site_view_count
    return StatsResponse(views=current_views)


def build_user_message(text: str, image_base64: str | None, image_media_type: str) -> dict:
    if image_base64:
        return {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{image_media_type};base64,{image_base64}"},
                },
                {"type": "text", "text": text or "Please analyze this supplement label."},
            ],
        }
    return {"role": "user", "content": text}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    user_text = request.message
    image_base64 = request.image_base64
    image_media_type = request.image_media_type or "image/jpeg"

    if len(user_text) > MAX_MESSAGE_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Message too long. Max {MAX_MESSAGE_CHARS} characters.",
        )

    if image_base64:
        if not image_media_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid image media type.")
        if estimate_base64_size_bytes(image_base64) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail="Image too large. Maximum size is 8 MB.",
            )

    classification = classify_message(user_text)

    if classification == "distress":
        response_text = generate_response(
            build_fallback_messages(user_text, SAFETY_FALLBACK_PROMPT)
        )
        return ChatResponse(response=response_text, session_id=session_id)

    if classification == "medical":
        return ChatResponse(response=MEDICAL_REDIRECT_TEXT, session_id=session_id)

    if classification == "nutrition_or_diet":
        response_text = generate_response(
            build_fallback_messages(user_text, NUTRITION_REDIRECT_PROMPT)
        )
        return ChatResponse(response=response_text, session_id=session_id)

    if classification == "shopping_or_pricing":
        response_text = generate_response(
            build_fallback_messages(user_text, SHOPPING_REDIRECT_PROMPT)
        )
        return ChatResponse(response=response_text, session_id=session_id)

    if session_id not in sessions:
        sessions[session_id] = build_initial_messages()

    user_message = build_user_message(user_text, image_base64, image_media_type)
    sessions[session_id].append(user_message)
    response_text = generate_response(sessions[session_id])
    response_text = apply_post_backstop(user_text, response_text)
    sessions[session_id].append({"role": "assistant", "content": response_text})

    giphy_query = summarize_giphy_query(user_text, response_text)
    gif_url = fetch_giphy(giphy_query)

    print(f"[CHAT] gif_url={gif_url!r}")
    return ChatResponse(
        response=response_text,
        session_id=session_id,
        gif_url=gif_url,
        giphy_query=giphy_query,
    )


@app.post("/clear")
def clear(session_id: str | None = None):
    if session_id and session_id in sessions:
        del sessions[session_id]
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
