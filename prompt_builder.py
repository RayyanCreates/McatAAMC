"""
prompt_builder.py — Constructs the AI prompt for MCAT question generation.

Takes the card data dict from card_reader.py and builds:
  1. A detailed system prompt defining the MCAT question-writing role.
  2. A user message containing the card content and generation instructions.

Nothing in this module touches Anki's collection.  It is pure data transformation.
"""

from __future__ import annotations

from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# System prompt — defines the AI's role and output format
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert MCAT question writer with deep knowledge of AAMC-style question \
construction across all MCAT sections: Biological and Biochemical Foundations (B/B), \
Chemical and Physical Foundations (C/P), and Psychological, Social, and Biological \
Foundations of Behavior (P/S).

CORE PRINCIPLES:
1. Generate questions that test APPLICATION and REASONING — never rote recall alone.
2. Make distractors plausible: they must reflect real student confusions, not nonsense.
3. Keep the stem concise and exam-like. Avoid unnecessary verbosity.
4. Ground every question firmly in the concept shown on the card.
5. If a concept is simple, elevate it into MCAT-level reasoning (consequence, mechanism, \
   scenario, discrimination between similar terms).
6. The question must be genuinely useful for test preparation — not filler.

OUTPUT FORMAT — Follow this EXACTLY. Use these exact headers. Do not add extra sections:

Based on Current Card:
[1–2 sentences naming the concept and what the card is testing]

Question:
[MCAT-style question stem — may include a brief clinical or scientific vignette when helpful]

A. [answer choice]
B. [answer choice]
C. [answer choice]
D. [answer choice]

Correct Answer: [single uppercase letter, e.g. "B"]

Why the Correct Answer Is Right:
[2–3 sentence explanation of why this answer is definitively correct]

Why the Other Answers Are Wrong:
A: [If A is correct write "This is the correct answer." Otherwise explain the specific flaw or \
why it is a tempting but incorrect choice]
B: [same pattern]
C: [same pattern]
D: [same pattern]

MCAT Topic / Category:
[Format: "Section: Specific Topic" — examples: "Psych/Soc: Identity and Social Interaction", \
"Biochemistry: Enzyme Kinetics", "Biology: Endocrine System", "Gen Chem: Acid-Base Equilibria", \
"Physics: Fluid Dynamics", "Orgo: Nucleophilic Substitution"]

High-Yield Takeaway:
[One focused, memorable sentence capturing what you MUST know about this concept for MCAT day]

Common Trap:
[One sentence describing the most common mistake students make regarding this concept]
"""


# ---------------------------------------------------------------------------
# Subject-specific generation guidance
# ---------------------------------------------------------------------------

_SUBJECT_GUIDANCE: Dict[str, str] = {
    "psych": (
        "This is a Psych/Soc concept. MCAT P/S style:\n"
        "- Prefer scenarios: describe a person's behavior or social interaction, then ask which "
        "concept best explains it.\n"
        "- Test the student's ability to APPLY the term to a concrete situation, not define it.\n"
        "- Common confusions to exploit as distractors: similar sociological terms "
        "(e.g., assimilation vs. accommodation, prejudice vs. discrimination, "
        "operant vs. classical conditioning, self-efficacy vs. self-esteem).\n"
        "- Often appears as: 'Which concept BEST explains...', 'A researcher observes...'"
    ),
    "bio": (
        "This is a Biology concept. MCAT B/B style:\n"
        "- Prefer PHYSIOLOGICAL CONSEQUENCE questions: what happens downstream when X changes?\n"
        "- Test cause-effect reasoning, structure-function logic, system-level integration.\n"
        "- Common confusions: similar structures with different functions, mixing up cause and "
        "effect, confusing sympathetic vs. parasympathetic effects.\n"
        "- Often appears as clinical vignettes with lab values, or 'What would MOST LIKELY "
        "result from...'"
    ),
    "biochem": (
        "This is a Biochemistry concept. MCAT B/B style:\n"
        "- Prefer MECHANISTIC questions: enzyme kinetics, metabolic pathway logic, "
        "regulation points, molecular mechanisms.\n"
        "- Test understanding of Km/Vmax effects, inhibition types, pathway block consequences, "
        "fed vs. fasted state, energy accounting.\n"
        "- Common confusions: competitive vs. noncompetitive inhibition, allosteric vs. "
        "covalent regulation, glycolysis vs. gluconeogenesis fed/fasted direction.\n"
        "- Often appears as graph interpretation, pathway block consequences, "
        "or 'An enzyme exhibits... which type of inhibition?'"
    ),
    "chem": (
        "This is a General Chemistry concept. MCAT C/P style:\n"
        "- Prefer TREND REASONING and conceptual application: Le Chatelier, Hess's law, "
        "acid-base equilibria, electrochemistry, colligative properties.\n"
        "- Test 'what happens when X changes' rather than pure calculation.\n"
        "- Common confusions: Ka/Kb vs. strength vs. concentration, endothermic/exothermic "
        "vs. spontaneity, anode/cathode conventions in galvanic vs. electrolytic cells.\n"
        "- Often appears as: 'Which statement is TRUE...', 'If X doubles, Y will...'"
    ),
    "physics": (
        "This is a Physics concept. MCAT C/P style:\n"
        "- Prefer PROPORTIONAL REASONING and conceptual variable relationships.\n"
        "- Test understanding of equations as relationships, not just calculation.\n"
        "- Common confusions: direction of current vs. electron flow, sign conventions, "
        "forgetting all contributing forces, Bernoulli vs. common sense.\n"
        "- Often appears as: 'If X doubles, what happens to Y?', experimental diagram "
        "interpretation, or conceptual ranking."
    ),
    "ochem": (
        "This is an Organic Chemistry concept. MCAT C/P style:\n"
        "- Prefer MECHANISM REASONING and functional group behavior.\n"
        "- Test prediction of reaction outcomes, stereochemistry consequences, "
        "spectroscopy clues (NMR, IR), or mechanism identification.\n"
        "- Common confusions: SN1 vs. SN2 conditions, enantiomers vs. diastereomers, "
        "E1 vs. E2 selectivity, nucleophile vs. electrophile identification.\n"
        "- Often appears as reaction prediction, 'Which mechanism...', or spectroscopy data."
    ),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_prompt(card_data: Dict[str, Any], config: Dict[str, Any]) -> str:
    """
    Build the user-turn message for MCAT question generation.

    Args:
        card_data: Output of card_reader.get_current_card_data().
        config:    Validated config dict from config_manager.load_config().

    Returns:
        A string to be sent as the user message to the AI model.

    Raises:
        ValueError: If card_data is None or has no readable content.
    """
    if not card_data:
        raise ValueError("card_data is empty or None — cannot build prompt")

    note_type_name = card_data.get("note_type_name", "Unknown")
    deck_name = card_data.get("deck_name", "Unknown")
    tags = card_data.get("tags", [])
    fields: Dict[str, Dict[str, str]] = card_data.get("fields", {})
    template_name = card_data.get("template_name", "Unknown")

    # ------------------------------------------------------------------
    # Build field content string
    # ------------------------------------------------------------------
    preferred_fields: List[str] = config.get("preferred_fields", [])
    field_lines: List[str] = []

    if preferred_fields:
        for fname in preferred_fields:
            if fname in fields:
                text = fields[fname].get("text", "").strip()
                if text:
                    field_lines.append(f"  {fname}: {text}")

    # Always fall back to all fields if preferred gave nothing
    if not field_lines:
        for fname, fdata in fields.items():
            text = fdata.get("text", "").strip()
            if text:
                field_lines.append(f"  {fname}: {text}")

    if not field_lines:
        raise ValueError(
            "All card fields are empty after HTML stripping — nothing to generate from"
        )

    fields_block = "\n".join(field_lines)

    # ------------------------------------------------------------------
    # Tags — filter out internal Anki tags
    # ------------------------------------------------------------------
    skip_prefixes = ("marked", "leech", "is:")
    meaningful_tags = [
        t for t in tags
        if not any(t.lower().startswith(p) for p in skip_prefixes)
    ]
    tags_str = ", ".join(meaningful_tags) if meaningful_tags else "None"

    # ------------------------------------------------------------------
    # Subject detection and guidance
    # ------------------------------------------------------------------
    all_text = " ".join([
        deck_name,
        " ".join(meaningful_tags),
        fields_block,
        note_type_name,
    ]).lower()
    subject_key = _detect_subject(all_text)
    subject_guidance = _SUBJECT_GUIDANCE.get(subject_key, "")

    # ------------------------------------------------------------------
    # Style and verbosity instructions
    # ------------------------------------------------------------------
    style = config.get("question_style", "auto")
    if style == "discrete":
        style_instr = (
            "Generate a DIRECT DISCRETE question — no scenario or vignette, "
            "just a clear conceptual or application question."
        )
    elif style == "scenario":
        style_instr = (
            "Generate a SCENARIO-BASED question — include a brief clinical or scientific "
            "vignette (2–4 sentences) before the question stem."
        )
    else:  # auto
        style_instr = (
            "Choose the most effective format: use a brief scenario/vignette if it "
            "makes the concept clearer or more MCAT-like; otherwise ask a direct "
            "application question."
        )

    verbosity = config.get("explanation_verbosity", "standard")
    if verbosity == "brief":
        verbosity_instr = "Keep all explanations SHORT: 1–2 sentences each."
    elif verbosity == "detailed":
        verbosity_instr = (
            "Provide DETAILED explanations: 3–4 sentences each, covering mechanism, "
            "reasoning, and how to distinguish the right from the wrong answer."
        )
    else:
        verbosity_instr = "Keep explanations FOCUSED: 2–3 sentences each."

    # ------------------------------------------------------------------
    # Optional section suppression
    # ------------------------------------------------------------------
    suppress_lines: List[str] = []
    if not config.get("show_topic_category", True):
        suppress_lines.append('- Omit the "MCAT Topic / Category" section.')
    if not config.get("show_high_yield_takeaway", True):
        suppress_lines.append('- Omit the "High-Yield Takeaway" section.')
    if not config.get("show_common_trap", True):
        suppress_lines.append('- Omit the "Common Trap" section.')
    suppress_block = (
        "\nSECTION SUPPRESSION:\n" + "\n".join(suppress_lines)
        if suppress_lines else ""
    )

    # ------------------------------------------------------------------
    # Final user message
    # ------------------------------------------------------------------
    user_message = f"""\
Generate one high-quality MCAT-style practice question based on the Anki card below.

=== CARD DATA ===
Note Type:     {note_type_name}
Deck:          {deck_name}
Card Template: {template_name}
Tags:          {tags_str}

Fields:
{fields_block}
=== END CARD DATA ===

QUESTION FORMAT: {style_instr}
EXPLANATION STYLE: {verbosity_instr}{suppress_block}

SUBJECT-SPECIFIC GUIDANCE:
{subject_guidance if subject_guidance else "Apply MCAT question-writing principles appropriate to the subject of this card."}

QUALITY REMINDERS:
- Do NOT ask "What is [term]?" or any question that only tests definition recall.
- Distractors must reflect actual MCAT-tested confusions, not arbitrary wrong facts.
- If the concept is simple on the card, elevate it — test a consequence, a mechanism, \
a scenario, or a discrimination between confusable terms.
- Every part of the output must fit the exact format specified in your system instructions.
"""
    return user_message


# ---------------------------------------------------------------------------
# Subject detection
# ---------------------------------------------------------------------------

def _detect_subject(combined_text: str) -> str:
    """
    Heuristically identify the MCAT subject from combined card text.

    Returns one of: 'psych', 'bio', 'biochem', 'chem', 'physics', 'ochem', or ''
    The order of checks matters: more specific subjects are checked first.
    """
    # Psych / Sociology
    if _any(combined_text, [
        "psych", "sociolog", "social learning", "behaviorism", "cognit",
        "perception", "identity", "personality", "attitude", "prejudice",
        "discriminat", "culture", "social group", "self-concept", "self-esteem",
        "self-efficacy", "motivation", "emotion", "memory", "learning theory",
        "freud", "piaget", "erikson", "vygotsky", "kohlberg", "bandura",
        "operant", "classical condition", "reinforcement", "habituation",
        "conformity", "obedience", "ethnocent", "socialization",
        "looking-glass", "impression management", "stigma", "deviance",
        "social stratification", "social mobility", "relative deprivation",
        "attribution", "cognitive dissonance", "heuristic", "bias",
        "stress response", "coping", "psychological disorder",
    ]):
        return "psych"

    # Organic Chemistry (check before general chem)
    if _any(combined_text, [
        "organic chem", "ochem", "o chem",
        "reaction mechanism", "functional group", "nucleophil", "electrophil",
        "alkene", "alkyne", "aldehyde", "ketone", "carboxylic", "ester",
        "amide", "amine", "aromatic", "benzene", "phenyl",
        "stereochem", "enantiomer", "diastereomer", "chiral",
        "sn1", "sn2", "e1", "e2", "elimination reaction", "addition reaction",
        "nmr", "ir spectrum", "infrared", "mass spec",
        "grignard", "oxidation state organic", "reduction organic",
        "saponification", "acyl", "carbonyl",
    ]):
        return "ochem"

    # Biochemistry (check before broad biology)
    if _any(combined_text, [
        "biochem", "enzyme kinetic", "metabol", "glycolysis", "gluconeogen",
        "krebs cycle", "citric acid", "tca cycle", "electron transport",
        "oxidative phosphorylation", "atp synthase", "beta oxidation",
        "fatty acid synthesis", "amino acid catabolism", "urea cycle",
        "purine", "pyrimidine", "nucleotide synthesis",
        "competitive inhibit", "noncompetitive inhibit", "uncompetitive",
        "allosteric", "km", "vmax", "michaelis",
        "dna replication", "transcription", "translation", "codon",
        "post-translational", "protein folding", "chaperone",
        "signal transduction", "second messenger", "phosphorylation cascade",
        "nad+", "nadh", "fadh2", "coenzyme", "cofactor",
        "fed state", "fasted state", "insulin signaling", "glucagon",
        "photosynthesis", "calvin cycle", "light reaction",
    ]):
        return "biochem"

    # Physics
    if _any(combined_text, [
        "physics", "newtonian", "kinematics", "force", "torque", "momentum",
        "elastic collision", "inelastic collision", "centripetal",
        "work-energy", "potential energy", "kinetic energy",
        "wave", "frequency", "wavelength", "amplitude", "interference",
        "optics", "refraction", "reflection", "lens", "mirror",
        "electric field", "magnetic field", "electromagnetic",
        "circuit", "resistor", "capacitor", "inductor", "ohm",
        "fluid dynamics", "bernoulli", "poiseuille", "viscosity",
        "buoyancy", "archimedes", "pressure fluid",
        "nuclear decay", "radioactiv", "half-life", "alpha decay",
        "sound wave", "doppler effect",
        "thermodynamics physics", "heat transfer", "specific heat",
    ]):
        return "physics"

    # General Chemistry
    if _any(combined_text, [
        "general chem", "gen chem", "inorganic chem",
        "equilibrium", "le chatelier", "hess law",
        "acid-base", "acid base", "ph ", " ph", "pka", "pkb",
        "buffer", "henderson-hasselbalch", "titration",
        "electrochemistry", "galvanic cell", "electrolytic",
        "oxidation state", "reduction potential", "nernst",
        "periodic trend", "atomic radius", "ionization energy",
        "electronegativity", "electron configuration",
        "molecular orbital", "hybridization", "vsepr",
        "colligative", "molarity", "molality", "osmosis",
        "reaction rate", "rate law", "activation energy",
        "enthalpy", "entropy", "gibbs free energy",
        "gas law", "ideal gas", "van der waals",
        "solubility product", "ksp", "common ion",
    ]):
        return "chem"

    # Biology (broad — checked last so it catches remaining bio concepts)
    if _any(combined_text, [
        "biology", "cell biology", "anatomy", "physiology",
        "organ system", "tissue", "histology",
        "hormone", "endocrin", "insulin", "glucagon", "cortisol",
        "aldosterone", "epinephrine", "thyroid", "parathyroid",
        "neuron", "synapse", "action potential", "neurotransmitter",
        "muscle contraction", "sarcomere", "actin", "myosin",
        "heart", "cardiac", "cardiovascular", "blood pressure",
        "kidney", "nephron", "glomerulus", "renal",
        "lung", "respiration", "ventilation", "gas exchange",
        "immune system", "antibody", "antigen", "t cell", "b cell",
        "genetics", "chromosome", "allele", "dominant", "recessive",
        "mutation", "dna damage", "cell cycle", "mitosis", "meiosis",
        "evolution", "natural selection", "speciation",
        "reproductive", "embryology", "development",
        "digestive", "liver", "pancreas", "absorption",
    ]):
        return "bio"

    return ""  # Unknown — generic guidance will be applied


def _any(text: str, keywords: List[str]) -> bool:
    """Return True if any keyword appears in text (case-insensitive, already lowercased text)."""
    return any(kw in text for kw in keywords)
