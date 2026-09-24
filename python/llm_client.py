"""
llm_client.py
Wrapper around the Anthropic (Claude), Google (Gemini), and OpenAI (GPT)
APIs. Takes a prompt string (from prompt_builder.py), sends it to the
LLM, and returns a clean Verilog patch (code block stripped, ready for
patch_applier.py).

Requires:
    pip3 install anthropic --break-system-packages   (for Claude)
    pip3 install -U google-genai                      (for Gemini, new unified SDK)
    pip3 install openai --break-system-packages        (for GPT; openai>=2.1.0 for gpt-5.5)

API keys read from environment variables:
    ANTHROPIC_API_KEY
    GOOGLE_API_KEY
    OPENAI_API_KEY
"""

import os
import re
import time


CODE_BLOCK_RE = re.compile(r"```(?:verilog)?\s*\n(.*?)```", re.DOTALL)
FIX_DESCRIPTION_RE = re.compile(
    r"//[ \t]*FIX_DESCRIPTION:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)
PIPELINE_STAGES_ADDED_RE = re.compile(
    r"//\s*PIPELINE_STAGES_ADDED:\s*(-?\d+)", re.IGNORECASE)
STRETCHED_PORTS_RE = re.compile(
    r"//[ \t]*STRETCHED_PORTS:[ \t]*(.*)$", re.IGNORECASE | re.MULTILINE)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


class LLMError(Exception):
    pass


def extract_verilog(response_text):
    """Pulls the Verilog code out of a ```verilog ... ``` block.
    Raises LLMError if no code block is found."""
    m = CODE_BLOCK_RE.search(response_text)
    if not m:
        raise LLMError(
            "No ```verilog code block found in LLM response. "
            "Raw response (truncated): %s" % response_text[:300]
        )
    code = m.group(1).strip()
    if "module" not in code or "endmodule" not in code:
        raise LLMError(
            "Extracted code block does not look like a complete module "
            "(missing 'module'/'endmodule'). Extracted: %s" % code[:300]
        )
    return code


def extract_fix_description(code):
    """Pulls the LLM's own free-text description of what it actually
    changed, out of a '// FIX_DESCRIPTION: <sentence>' comment (see
    prompt_builder.py's _SYSTEM_PREAMBLE, which requires this as the
    first line).

    Deliberately NOT constrained to the 6 named techniques - those are
    only optional heuristic starting points suggested BEFORE the LLM
    responds, not a vocabulary its answer is required to fit into. This
    is a free-text sentence describing the actual change made, in the
    LLM's own words - a genuine self-report, not a category label.

    Returns the description string (stripped), or None if the marker
    is missing/malformed - not a hard failure, since the actual code
    fix is what matters most.
    """
    m = FIX_DESCRIPTION_RE.search(code)
    if not m:
        return None
    description = m.group(1).strip()
    return description if description else None


def extract_pipeline_stages_added(code):
    """Pulls the LLM's self-reported latency delta out of a
    '// PIPELINE_STAGES_ADDED: <int>' comment (see prompt_builder.py's
    _SYSTEM_PREAMBLE, which requires this as the second line).

    This is what lets formal_check.py automatically build a
    latency-matched gold wrapper instead of comparing gold/gate at a
    mismatched cycle offset (which would either fail equivalence for
    a genuinely correct pipelined patch, or - worse - pass by coincidence
    on trivial I/O and give a false sense of safety).

    Returns the integer (may be negative, though that would be unusual -
    negative values are passed through as-is and left for the caller to
    validate/reject), or 0 if the marker is missing/malformed. Defaulting
    to 0 (rather than None) is deliberate: 0 is the safe assumption
    (same-cycle equivalence, the strictest check) when the LLM's response
    doesn't clearly state otherwise.
    """
    m = PIPELINE_STAGES_ADDED_RE.search(code)
    if not m:
        return 0
    try:
        return int(m.group(1))
    except ValueError:
        return 0


def extract_stretched_ports(code):
    """Pulls the LLM's self-reported list of output ports whose ASSERTED
    DURATION changed (not just their timing) out of a
    '// STRETCHED_PORTS: <comma-separated names, or "none">' comment
    (see prompt_builder.py's _SYSTEM_PREAMBLE, which requires this as
    the third line).

    This is distinct from PIPELINE_STAGES_ADDED: that value only shifts
    WHEN a signal appears, via a plain per-cycle delay. A plain delay
    cannot correctly handle a status/handshake signal (e.g. "busy")
    that used to pulse for a short, fixed duration while a computation
    ran, when the computation now genuinely takes more cycles - such a
    signal needs to be WIDENED, not merely delayed, or a formally
    correct patch will still fail equivalence checking on that one
    port (a pulse shifted later is still a pulse, not a wider level).

    Returns a list of port name strings (empty list if the marker is
    missing, malformed, or explicitly "none"). An empty list is the
    safe default: formal_check.py falls back to its existing plain-delay
    behavior for every port when this list is empty, which is no worse
    than the check's behavior before this feature existed.
    """
    m = STRETCHED_PORTS_RE.search(code)
    if not m:
        return []
    raw = m.group(1).strip()
    if not raw or raw.lower() == "none":
        return []
    return [p.strip() for p in raw.split(",") if p.strip()]


# ---------------------------------------------------------------------------
# Claude (Anthropic) - primary
# ---------------------------------------------------------------------------

def _call_claude(prompt, model="claude-sonnet-4-6", max_tokens=16000):
    import anthropic  # imported lazily so file still loads without the package

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY environment variable not set.")

    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
    )

    # response.content is a list of content blocks; join text blocks
    text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    return text


# ---------------------------------------------------------------------------
# Gemini (Google) - secondary, using the new unified google-genai SDK
# ---------------------------------------------------------------------------

def _call_gemini(prompt, model="gemini-3.6-flash", max_output_tokens=32768):
    from google import genai  # imported lazily so file still loads without the package
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise LLMError("GOOGLE_API_KEY environment variable not set.")

    client = genai.Client(api_key=api_key)

    # max_output_tokens alone (no thinking_config) - a prior version also
    # set thinking_config=ThinkingConfig(thinking_budget=0) to stop
    # internal reasoning tokens from eating into the output budget on
    # Gemini 3-series "thinking" models, but that combination returned
    # "400 INVALID_ARGUMENT" against gemini-3.6-flash on this SDK
    # version - thinking_budget=0 is apparently not accepted here.
    # max_output_tokens by itself is a universally supported parameter,
    # so this is the safe fallback. If truncation on large modules
    # (e.g. controller.v) turns out to still be a problem without the
    # thinking-budget control, that needs revisiting with the specific
    # accepted range for this model (check the error message from a
    # real 400 response if thinking_config is retried - it usually
    # states the valid range directly).
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
        ),
    )
    return response.text


# ---------------------------------------------------------------------------
# OpenAI (GPT) - third provider, using the official openai SDK
# ---------------------------------------------------------------------------

def _call_openai(prompt, model="gpt-5.5", max_output_tokens=16000):
    """Requires: pip3 install openai --break-system-packages (openai>=2.1.0
    for gpt-5.5 support specifically - older SDK versions may not
    recognize this model string).

    NOTE on free-tier rate limits: as of this being written, OpenAI's
    free tier for gpt-5.5 is 3 RPM / 50 RPD / 10,000 TPM - the 50
    requests-PER-DAY cap specifically is easy to exhaust well within a
    single orchestrator.py run (one call per iteration, plus retries on
    syntax failures), unlike Gemini's free tier which this project has
    mostly been running against. Consider this before relying on this
    provider for a long unattended run.

    NOTE on reasoning tokens: gpt-5.5 is a reasoning model - it
    generates internal "thinking" tokens that count against
    max_output_tokens but are never returned in the response text
    (similar in spirit to the Gemini thinking-budget issue noted in
    _call_gemini() above, though the OpenAI SDK doesn't currently
    expose a way to disable this for gpt-5.5 the way thinking_budget=0
    attempts to for Gemini). If patches for large modules (e.g.
    controller.v) come back truncated/empty, raising
    max_output_tokens is the first thing to try, since some of that
    budget is being spent on unseen reasoning before any Verilog is
    written.
    """
    from openai import OpenAI  # imported lazily so file still loads without the package

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise LLMError("OPENAI_API_KEY environment variable not set.")

    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model=model,
        max_completion_tokens=max_output_tokens,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_rtl_patch(prompt, provider="claude", retries=MAX_RETRIES, model=None):
    """Sends prompt to the chosen LLM provider and returns
    (code, fix_description, pipeline_stages_added, stretched_ports):
      - code: clean Verilog code (string)
      - fix_description: the LLM's own free-text sentence describing what
        it actually changed (string, or None if the required marker
        comment was missing/malformed - see extract_fix_description())
      - pipeline_stages_added: int, from extract_pipeline_stages_added()
        (0 if missing/malformed - see that function's docstring for why
        0 is the safe default)
      - stretched_ports: list of port name strings, from
        extract_stretched_ports() (empty list if missing/malformed/"none" -
        see that function's docstring for why an empty list is the safe
        default)

    model: optional override of the provider's default model string
    (e.g. "gemini-2.5-flash" instead of _call_gemini's default
    "gemini-3.6-flash", or a specific Claude model string). Useful for
    switching models on a per-model quota limit (RPD/RPM/TPM) without
    touching provider ("gemini"/"claude") itself - pass config.LLM_MODEL
    from the call site if you want this configurable centrally rather
    than hardcoded per call.

    Retries on transient failures. Raises LLMError if all retries are
    exhausted or the response can't be parsed.
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            if provider == "claude":
                raw_response = _call_claude(prompt, **({"model": model} if model else {}))
            elif provider == "gemini":
                raw_response = _call_gemini(prompt, **({"model": model} if model else {}))
            elif provider == "openai":
                raw_response = _call_openai(prompt, **({"model": model} if model else {}))
            else:
                raise LLMError("Unknown provider: %s" % provider)

            code = extract_verilog(raw_response)
            fix_description = extract_fix_description(code)
            pipeline_stages_added = extract_pipeline_stages_added(code)
            stretched_ports = extract_stretched_ports(code)
            return code, fix_description, pipeline_stages_added, stretched_ports

        except LLMError as e:
            # Preserve the ORIGINAL error detail (e.g. extract_verilog's
            # "no code block found" message, which includes a truncated
            # excerpt of the raw response) - previously this was
            # discarded and replaced with a generic "parsing failed on
            # attempt N" string, which gave zero diagnostic signal when
            # every retry failed and the caller needed to know WHY.
            last_error = LLMError(
                "Attempt %d: %s" % (attempt, e))
        except Exception as e:
            last_error = e

        if attempt < retries:
            time.sleep(RETRY_DELAY_SECONDS)

    raise LLMError("All %d attempts failed. Last error: %s" % (retries, last_error))


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    test_prompt = (
        "Return a trivial 2-input AND gate module named test_and, "
        "wrapped in a ```verilog code block, nothing else."
    )
    provider = sys.argv[1] if len(sys.argv) > 1 else "claude"
    print("Calling %s ..." % provider)
    patch, fix_description, pipeline_stages_added = get_rtl_patch(
        test_prompt, provider=provider)
    print("\n--- Extracted patch ---\n")
    print(patch)
    print("\n--- Self-reported fix description ---\n")
    print(fix_description)
    print("\n--- Self-reported pipeline stages added ---\n")
    print(pipeline_stages_added)
