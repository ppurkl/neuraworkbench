import os
import re
import base64
import time
import openai
from pathlib import Path
from typing import Literal, Dict, Optional, Tuple, Any, List, Iterable
from openai import OpenAI, AsyncOpenAI
from tenacity import retry, wait_random_exponential, stop_after_attempt, retry_if_exception, retry_if_exception_type

from langchain.chat_models import init_chat_model
from langchain_core.messages import HumanMessage, SystemMessage, BaseMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.rate_limiters import InMemoryRateLimiter

#####################################################
#                      API Keys                     #
#####################################################
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent  # Expects the keys to be on the same level as neuraworkbench

os.environ["OPENAI_API_KEY"] = (PROJECT_ROOT / "openai_key.txt").read_text().strip()
os.environ["GOOGLE_API_KEY"] = (PROJECT_ROOT / "google_key.txt").read_text().strip()
os.environ["ANTHROPIC_API_KEY"] = (PROJECT_ROOT / "anthropic_key.txt").read_text().strip()

#####################################################
#                 Model Providers                   #
#####################################################
Provider = Literal["openai", "anthropic", "google", "unknown"]

# Compile once; anchor at the beginning so "claude-opus-4.1" doesn't trip "o4".
OPENAI_RE = re.compile(r'^(?:openai[:/])?(?:gpt|o[134])(?:$|[-:/])', re.I)
ANTHROPIC_RE = re.compile(r'^(?:anthropic[:/])?claude(?:$|[-:/])', re.I)
GOOGLE_RE = re.compile(r'^(?:google[:/]|vertex(?:-ai)?[:/])?(?:gemini|learnlm)(?:$|[-:/])', re.I)

#####################################################
#                   Rate Limits                     #
#####################################################
DEFAULT_RPM: Dict[Provider, int] = {
    "openai": 3000,
    "anthropic": 50,
    "google": 1000,
}


def detect_provider(model_name: str) -> Provider:
    """
    Guess the model's provider from its name.

    Rules:
      - OpenAI: names starting with 'gpt-' or 'o1/o3/o4' (e.g., 'gpt-4o', 'o3-mini').
      - Anthropic: names starting with 'claude' (e.g., 'claude-3.7-sonnet-latest').
      - Google: names starting with 'gemini' or 'learnlm' (e.g., 'gemini-2.5-pro').
      - Optional prefixes like 'openai:', 'anthropic/', 'google:' are handled.
    """
    m = model_name.strip()
    if OPENAI_RE.match(m):
        return "openai"
    if ANTHROPIC_RE.match(m):
        return "anthropic"
    if GOOGLE_RE.match(m):
        return "google"
    return "unknown"


def build_chat_model(
        model_name: str,
        provider: Optional[Provider] = None,
        rpm_overrides: Optional[Dict[Provider, int]] = None,
        **kwargs: Any,
):
    """
    Create a LangChain chat model with a per-provider RPM rate limiter.

    Args:
        model_name: The provider model id (e.g., "gpt-4o-mini", "claude-3-5-sonnet-20240620", "gemini-1.5-pro").
        provider: Force a provider ("openai" | "anthropic" | "google"). If None, detect from model_name.
        rpm_overrides: Dict to override DEFAULT_RPM for any provider.
        **kwargs: Passed through to the underlying model class. Examples:
            - OpenAI/Anthropic: max_tokens=512, temperature=0.2
            - Google: max_output_tokens=512, temperature=0.2

    Returns:
        (model, provider) tuple.
    """
    prov: Provider = provider if provider is not None else detect_provider(model_name)
    rpm_cfg = {**DEFAULT_RPM, **(rpm_overrides or {})}
    rpm = rpm_cfg[prov]
    rps = rpm / 60.0  # convert RPM → RPS

    rl = InMemoryRateLimiter(requests_per_second=rps)

    if prov == "openai":
        model = ChatOpenAI(model=model_name, rate_limiter=rl, **kwargs)
    elif prov == "anthropic":
        model = ChatAnthropic(model=model_name, rate_limiter=rl, **kwargs)
    elif prov == "google":
        model = ChatGoogleGenerativeAI(model=model_name, rate_limiter=rl, **kwargs)
    else:
        raise ValueError(f"Unsupported provider: {prov}")

    return model, prov


def _is_rate_limit_error(e: Exception) -> bool:
    # OpenAI: RateLimitError or APIError(429)
    try:
        from openai import RateLimitError as OpenAIRateLimitError
        if isinstance(e, OpenAIRateLimitError):
            return True
    except Exception:
        pass
    # Anthropic: APIStatusError with status_code=429
    try:
        from anthropic import APIStatusError as AnthropicAPIStatusError
        if isinstance(e, AnthropicAPIStatusError) and getattr(e, "status_code", None) == 429:
            return True
    except Exception:
        pass
    # Google (Gemini): google.api_core.exceptions.ResourceExhausted / TooManyRequests
    try:
        from google.api_core.exceptions import ResourceExhausted, TooManyRequests
        if isinstance(e, (ResourceExhausted, TooManyRequests)):
            return True
    except Exception:
        pass
    # Generic 429 on any exception with .status / .status_code
    sc = getattr(e, "status_code", None) or getattr(e, "status", None)
    if sc == 429:
        return True
    # String fallback
    msg = str(e).lower()
    return "rate limit" in msg or "too many requests" in msg or "http 429" in msg


def _sleep_retry_after(exc: Exception) -> bool:
    """Sleep according to Retry-After if the provider sent it. Return True if we slept."""
    for attr in ("response",):
        resp = getattr(exc, attr, None)
        headers = getattr(resp, "headers", None) if resp else None
        if headers:
            ra = headers.get("Retry-After") or headers.get("retry-after")
            try:
                if ra:
                    time.sleep(float(ra))
                    return True
            except Exception:
                pass
    return False


def _before_sleep(retry_state):
    e = retry_state.outcome.exception() if retry_state and retry_state.outcome else None
    if e:
        # If server gave a precise wait, honor it in addition to exponential backoff.
        if _sleep_retry_after(e):
            return


# --- build LangChain messages from inputs ---
def _make_messages(
        user: Optional[str] = None,
        system: Optional[str | Iterable[str]] = None,
        messages: Optional[List[BaseMessage]] = None,
) -> List[BaseMessage]:
    if messages:
        return messages
    out: List[BaseMessage] = []
    if system:
        if isinstance(system, str):
            out.append(SystemMessage(content=system))
        else:
            out.extend(SystemMessage(content=s) for s in system)
    if user:
        out.append(HumanMessage(content=user))
    if not out:
        raise ValueError("Provide either messages=..., or user=... (optionally with system=...).")
    return out


# --- the core invoke-with-backoff ---
def _retry_predicate(e: Exception) -> bool:
    # Only retry on rate limit-ish errors; let other exceptions surface immediately.
    return _is_rate_limit_error(e)


def _make_retry_decorator(min_wait=1, max_wait=60, attempts=6):
    return retry(
        wait=wait_random_exponential(min=min_wait, max=max_wait),
        stop=stop_after_attempt(attempts),
        retry=retry_if_exception(_retry_predicate),
        before_sleep=_before_sleep,
        reraise=True,
    )


def chat_with_backoff_and_fallback(
        *,
        model_name: str,
        provider: Optional[str] = None,
        messages: Optional[List[BaseMessage]] = None,
        user_prompt: Optional[str] = None,
        system_prompt: Optional[str | Iterable[str]] = None,
        # primary model build options
        build_kwargs: Optional[Dict[str, Any]] = None,
        # list of (model_name, provider, build_kwargs) fallbacks in priority order
        fallbacks: Optional[List[Tuple[str, Optional[str], Optional[Dict[str, Any]]]]] = None,
        # retry config
        retry_min_s: int = 1,
        retry_max_s: int = 60,
        retry_attempts: int = 6,
) -> Any:
    """
    Try primary model with backoff; on persistent rate limits, try fallbacks in order.
    Returns the model's `.invoke(...)` result (an AIMessage or similar).
    """
    build_kwargs = build_kwargs or {}
    all_specs = [(model_name, provider, build_kwargs)] + (fallbacks or [])

    last_err: Optional[Exception] = None

    for idx, (m_name, m_provider, m_kwargs) in enumerate(all_specs):
        # Build model via your existing factory
        model, prov = build_chat_model(
            m_name,
            provider=m_provider,  # may be None -> auto-detect
            **(m_kwargs or {}),
        )
        msgs = _make_messages(user=user_prompt, system=system_prompt, messages=messages)

        @_make_retry_decorator(min_wait=retry_min_s, max_wait=retry_max_s, attempts=retry_attempts)
        def _invoke_once():
            # You can pass callbacks here if you use a TPM gate, logging, etc.
            return model.invoke(msgs)

        try:
            return _invoke_once()
        except Exception as e:
            last_err = e
            # If it wasn't rate-limit related, don't try further fallbacks—surface immediately
            if not _is_rate_limit_error(e):
                raise
            # If it was rate-limit related and we have more models to try, continue loop
            if idx < len(all_specs) - 1:
                continue
            # No more fallbacks—raise the last error
            raise

    # Should never reach here; loop either returned or raised
    if last_err:
        raise last_err


def single_prompt_sync(prompt, model="gpt-4o"):
    client = OpenAI()

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )
    return completion.choices[0].message.content


def single_prompt_sync_v2(prompt, model_name="claude-sonnet-4-20250514", max_tokens=None):
    model = init_chat_model(model_name, max_tokens=max_tokens).with_retry(stop_after_attempt=6)
    messages = [
        HumanMessage(content=prompt),
    ]
    return model.invoke(messages).content


async def single_prompt_async(prompt, model="gpt-4o"):
    client = AsyncOpenAI()

    completion = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )
    return completion.choices[0].message.content


@retry(
    wait=wait_random_exponential(min=1, max=60),
    stop=stop_after_attempt(6),
    retry=retry_if_exception_type((openai.RateLimitError, openai.APIError, openai.APIConnectionError))
)
async def completion_with_backoff(system_prompt, user_prompt, model='gpt-5'):
    """
    Call OpenAI chat completions with backoff.

    Args:
        system_prompt: Instructions for the assistant.
        user_prompt: The article/text to analyze.
        model: OpenAI model name.

    Returns:
        The response from the OpenAI chat completion.
    """
    client = AsyncOpenAI()

    completion = await client.beta.chat.completions.parse(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    )

    return completion.choices[0].message.content


def transcribe_audio_sync(audio_path, model="whisper-1"):
    client = OpenAI()

    with open(audio_path, "rb") as f:
        transcript = client.audio.transcriptions.create(
            model=model,  # or "gpt-4o-mini-transcribe"
            file=f
        )

    return transcript.text


def generate_speech_sync(
        text: str,
        output_path: str | Path,
        model: str = "gpt-4o-mini-tts",
        voice: str = "nova",
        instructions: Optional[str] = None,
):
    client = OpenAI()
    speech_file_path = Path(output_path)
    speech_file_path.parent.mkdir(parents=True, exist_ok=True)

    with client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        instructions=instructions,
    ) as response:
        response.stream_to_file(speech_file_path)

    return speech_file_path


# create image encode function
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')


def image_prompt_sync(image_path, system_prompt, user_prompt, model="gpt-5"):
    base64_image = encode_image(image_path)

    client = OpenAI()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": user_prompt
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
                    },
                ],
            }
        ]
    )

    return response.choices[0].message.content


if __name__ == "__main__":
    # model = init_chat_model("gemini-2.5-pro", model_provider="google_genai")
    # model = init_chat_model("claude-sonnet-4-20250514", model_provider="anthropic")
    response = chat_with_backoff_and_fallback(model_name="gemini-2.5-flash",
                                              user_prompt="Hi there, whats your name?",
                                              system_prompt=["Answer like a pirate", "Check if the user has gold"])

    print(response.content)
