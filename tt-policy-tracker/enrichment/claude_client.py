"""One Claude call path and shared failure types for the enrichment stages.

Why this exists: until 2026-09 each stage caught `anthropic.APIError` and
returned a harmless-looking default. The classifier returned confidence 0.0,
so a dead key or a 429 made every doc look irrelevant, the doc was marked
classified, and it was never retried. The feed went quiet and every cron
stayed green.

The rule now:
  * EnrichmentAPIError  -- the call did not get an answer (auth, rate limit,
    connection, 5xx, empty key). The doc is NOT consumed; the next run
    retries it. Runs count these as `api_errors` and go red.
  * EnrichmentParseError -- the model answered, but not with parseable JSON,
    even after one retry. The doc IS consumed so one poisoned doc cannot
    retry forever; runs count these as `parse_errors` and list the ids.
"""

import json
import logging

import anthropic

from config import settings

logger = logging.getLogger(__name__)


class EnrichmentAPIError(Exception):
    """The Claude API gave no usable answer. Retry the doc on the next run.

    `kind` is one of: no_key, auth, permission, rate_limit, connection,
    server, status, sdk. `definitive` is True when retrying inside the same
    run is pointless (bad key, no permission, no key at all).
    """

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.definitive = kind in {"no_key", "auth", "permission"}


class EnrichmentParseError(Exception):
    """The model answered, but its output could not be parsed after a retry."""


def check_api_key() -> None:
    """Fail before any network call when the key is empty.

    With an empty key the SDK raises TypeError on the first call, which no
    `anthropic.APIError` handler catches. Never include the key in the message.
    """
    if not settings.anthropic_api_key:
        raise EnrichmentAPIError("no_key", "ANTHROPIC_API_KEY is not set")


async def create_message(**kwargs):
    """Call `messages.create`, turning every "no answer" failure into
    EnrichmentAPIError. Exceptions are caught most specific first.
    """
    check_api_key()
    client = anthropic.AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        timeout=settings.anthropic_timeout_seconds,
        max_retries=settings.anthropic_max_retries,
    )
    try:
        return await client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise EnrichmentAPIError("auth", "401 authentication failed") from e
    except anthropic.PermissionDeniedError as e:
        raise EnrichmentAPIError("permission", "403 permission denied") from e
    except anthropic.RateLimitError as e:
        raise EnrichmentAPIError("rate_limit", "429 rate limited") from e
    except anthropic.APIConnectionError as e:  # includes APITimeoutError
        raise EnrichmentAPIError("connection", type(e).__name__) from e
    except anthropic.InternalServerError as e:
        raise EnrichmentAPIError("server", f"HTTP {e.status_code}") from e
    except anthropic.APIStatusError as e:
        raise EnrichmentAPIError("status", f"HTTP {e.status_code}") from e
    except anthropic.APIError as e:
        raise EnrichmentAPIError("sdk", type(e).__name__) from e


# Stop reasons that mean the answer is missing or cut off.
FAILED_STOP_REASONS = {"max_tokens", "refusal"}


def response_text(response) -> str:
    """Text of a response, markdown fences stripped. Reads only text blocks."""
    raw = "".join(
        getattr(block, "text", "") for block in response.content
        if getattr(block, "type", "text") == "text"
    ).strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return raw


async def create_json(label: str, **kwargs) -> dict:
    """Call Claude and parse a JSON object from its text.

    Bad output is often a one-off, so an unparseable answer gets exactly one
    more call. A second failure raises EnrichmentParseError. API failures
    raise EnrichmentAPIError at once and are never retried here.
    """
    last_problem = ""
    for attempt in (1, 2):
        response = await create_message(**kwargs)
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in FAILED_STOP_REASONS:
            # A cut-off or declined answer is bad output, not an API outage:
            # retry once, then consume the doc and count a parse error.
            logger.warning(f"{label}: stop_reason={stop_reason} (attempt {attempt}/2)")
            last_problem = f"stop_reason={stop_reason}"
            continue
        raw = response_text(response)
        try:
            result = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning(f"{label}: unparseable model output (attempt {attempt}/2): {e}")
            last_problem = "unparseable JSON"
            continue
        if isinstance(result, dict):
            return result
        logger.warning(f"{label}: model output is not a JSON object (attempt {attempt}/2)")
        last_problem = "not a JSON object"
    raise EnrichmentParseError(f"{label}: no usable output after 2 attempts ({last_problem})")
