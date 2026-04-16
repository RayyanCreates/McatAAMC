# MCAT Question Generator — Configuration

## api_provider
Which AI service to use for generation.
- `"anthropic"` — Use the Claude API (recommended)
- `"openai"` — Use the OpenAI API (GPT-4)

## api_key
Your API key for the selected provider.
- Anthropic: Get from https://console.anthropic.com/
- OpenAI: Get from https://platform.openai.com/api-keys
- **This is required.** Generation will fail with an error if this is empty.

## model
The specific model to use.
- Anthropic options: `"claude-sonnet-4-6"` (default), `"claude-opus-4-6"`, `"claude-haiku-4-5-20251001"`
- OpenAI options: `"gpt-4o"`, `"gpt-4o-mini"`

## hotkey
Keyboard shortcut to trigger the MCAT question generator while reviewing.
- Default: `"Ctrl+M"`
- Format uses Qt key notation: `"Ctrl+M"`, `"Alt+Q"`, `"Ctrl+Shift+M"`, etc.

## button_label
Text shown on the floating reviewer button.
- Default: `"MCAT Q"`

## show_button_in_reviewer
Whether to show a floating button in the reviewer.
- `true` — Show button (default)
- `false` — Hotkey only

## question_style
How the generated question should be framed.
- `"auto"` — Let the AI decide based on the concept (recommended)
- `"discrete"` — Direct question, no scenario
- `"scenario"` — Always use a clinical/scientific vignette

## explanation_verbosity
How detailed the answer explanations should be.
- `"brief"` — 1-2 sentences per explanation
- `"standard"` — 2-3 sentences (default)
- `"detailed"` — 3-4 sentences with fuller reasoning

## show_topic_category
Whether to include the "MCAT Topic / Category" section.
- `true` (default) or `false`

## show_high_yield_takeaway
Whether to include the "High-Yield Takeaway" section.
- `true` (default) or `false`

## show_common_trap
Whether to include the "Common Trap" section.
- `true` (default) or `false`

## preferred_fields
List of note field names to prioritize when extracting card content.
- Default: `[]` (empty = use all fields)
- Example: `["Front", "Back"]` or `["Term", "Definition"]`
- If a preferred field is not present, all fields are used as fallback.

## timeout_seconds
How long to wait for the API response before giving up.
- Default: `45` seconds

## max_tokens
Maximum number of tokens in the generated response.
- Default: `1800`
- Reduce if you want shorter outputs; increase for more detailed explanations.

## quiz_interval_count
How many answered/reviewed cards trigger an automatic pop quiz.
- Default: `10`

## quiz_size
How many questions to include in each pop quiz batch.
- Default: `10`

## scramble_question_order
Shuffle generated questions locally before showing quiz.
- Default: `true`

## scramble_answer_choices
Shuffle A/B/C/D answer order locally per question.
- Default: `true`

## quiz_max_tokens
Token limit for a batched quiz generation request.
- Default: `3200`

## cache_enabled
Enable local non-collection cache for reused/similar source concepts.
- Default: `true`

## generation_mode
Cost/quality profile for quiz generation prompts.
- `"cheap"` (default), `"balanced"`, `"rich"`

## include_wrong_answer_rationales
If true, asks model to include concise wrong-answer rationales per choice.
- Default: `false` (more token-efficient)
