"""EDSM API client — bulk system metadata lookup (no API key required)."""

import logging
import httpx

log = logging.getLogger(__name__)

_ENDPOINT = "https://www.edsm.net/api-v1/systems"
_TIMEOUT   = httpx.Timeout(15.0)
_HEADERS   = {"User-Agent": "Elite-Scouterous/1.0 (github contact: marcoluzzaro99@gmail.com)"}


async def fetch_systems(client: httpx.AsyncClient, names: list[str]) -> list[dict]:
    """Fetch EDSM metadata for up to 100 systems in one request.

    Returns a list of system dicts. Systems EDSM doesn't know are simply absent.
    Each dict may contain: name, coords {x,y,z}, information {security, allegiance, population}.
    """
    params: list[tuple[str, str]] = [("systemName[]", n) for n in names]
    params += [("showInformation", "1"), ("showCoordinates", "1")]
    try:
        r = await client.get(_ENDPOINT, params=params, timeout=_TIMEOUT)
        if r.status_code == 429:
            raise httpx.HTTPStatusError("429 rate-limited", request=r.request, response=r)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else []
    except httpx.HTTPStatusError:
        raise  # caller handles backoff and logging
    except Exception as exc:
        log.warning("EDSM request error: %s", exc)
        raise  # propagate so caller can retry instead of marking systems as checked
