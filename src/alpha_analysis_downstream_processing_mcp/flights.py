"""Flight route scoring for EDU Ops team P1 Accountable assignment.

Uses SerpAPI Google Flights to check nonstop route availability and score
team members based on airline preference, nonstop availability, and flight
duration.
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import requests

logger = logging.getLogger("[flights]")

SERPAPI_BASE_URL = "https://serpapi.com/search.json"
SERPAPI_TIMEOUT_SECONDS = 30.0

# ---------------------------------------------------------------------------
# Team member model & configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TeamMember:
    """EDU Ops team member with flight preferences."""

    name: str
    home_airport: str  # IATA code
    wrike_contact_id: str
    required_airlines: frozenset[str]  # empty = no hard requirement
    preferred_airlines: frozenset[str]  # empty = no preference bonus
    prioritize_shortest: bool


TEAM_MEMBERS: dict[str, TeamMember] = {
    "andrea": TeamMember(
        name="Andrea Ewalefo",
        home_airport="MSY",
        wrike_contact_id="KUAWDEOX",
        required_airlines=frozenset({"UA", "DL"}),
        preferred_airlines=frozenset(),
        prioritize_shortest=False,
    ),
    "robbie": TeamMember(
        name="Robbie Forrest",
        home_airport="SAT",
        wrike_contact_id="KUAUVTLM",
        required_airlines=frozenset(),
        preferred_airlines=frozenset({"AA"}),
        prioritize_shortest=False,
    ),
    "devin": TeamMember(
        name="Devin Bates",
        home_airport="PHX",
        wrike_contact_id="KUAWS3KA",
        required_airlines=frozenset(),
        preferred_airlines=frozenset({"AA"}),
        prioritize_shortest=True,
    ),
    "brandon": TeamMember(
        name="Brandon Gee",
        home_airport="DTW",
        wrike_contact_id="KUAWKIGO",
        required_airlines=frozenset(),
        preferred_airlines=frozenset({"DL"}),
        prioritize_shortest=False,
    ),
}

# Reverse lookup: Wrike contact ID -> member key
CONTACT_ID_TO_MEMBER: dict[str, str] = {
    m.wrike_contact_id: key for key, m in TEAM_MEMBERS.items()
}

# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------

NONSTOP_EXISTS = 100
PREFERRED_AIRLINE_BONUS = 25
REQUIRED_AIRLINE_PENALTY = -200
SHORTEST_FLIGHT_FACTOR = 0.5
SHORTEST_FLIGHT_BASE_MINUTES = 360

# ---------------------------------------------------------------------------
# School location -> airport map
# ---------------------------------------------------------------------------

SCHOOL_LOCATION_MAP: dict[str, list[str]] = {
    "Austin, TX": ["AUS"],
    "Dallas, TX": ["DFW", "DAL"],
    "Houston, TX": ["IAH", "HOU"],
    "San Antonio, TX": ["SAT"],
    "Miami, FL": ["MIA", "FLL"],
    "Orlando, FL": ["MCO"],
    "Tampa, FL": ["TPA"],
    "Jacksonville, FL": ["JAX"],
    "Los Angeles, CA": ["LAX", "BUR", "SNA"],
    "San Francisco, CA": ["SFO", "OAK", "SJC"],
    "San Diego, CA": ["SAN"],
    "Sacramento, CA": ["SMF"],
    "Phoenix, AZ": ["PHX"],
    "Tucson, AZ": ["TUS"],
    "New York, NY": ["JFK", "LGA", "EWR"],
    "Charlotte, NC": ["CLT"],
    "Raleigh, NC": ["RDU"],
    "Richmond, VA": ["RIC"],
    "Norfolk, VA": ["ORF"],
    "Washington, DC": ["DCA", "IAD", "BWI"],
    "Boston, MA": ["BOS"],
}

# ---------------------------------------------------------------------------
# In-memory route cache
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS: float = 7 * 24 * 60 * 60  # 7 days


@dataclass
class _CacheEntry:
    routes: list[dict[str, Any]]
    timestamp: float


_route_cache: dict[str, _CacheEntry] = {}


class FlightScoringError(RuntimeError):
    """Flight scoring API or logic error."""


def _cache_key(origin: str, destination: str) -> str:
    return f"{origin.upper()}-{destination.upper()}"


def _get_cached(key: str) -> list[dict[str, Any]] | None:
    entry = _route_cache.get(key)
    if entry is None:
        return None
    if (time.time() - entry.timestamp) >= CACHE_TTL_SECONDS:
        del _route_cache[key]
        return None
    return entry.routes


def _set_cached(key: str, routes: list[dict[str, Any]]) -> None:
    _route_cache[key] = _CacheEntry(routes=routes, timestamp=time.time())


def get_cache_stats() -> dict[str, Any]:
    """Return cache statistics."""
    now = time.time()
    valid = sum(
        1
        for e in _route_cache.values()
        if (now - e.timestamp) < CACHE_TTL_SECONDS
    )
    pairs = list(_route_cache.keys())
    return {"total_entries": len(_route_cache), "valid_entries": valid, "route_pairs": pairs}


def clear_cache() -> int:
    """Clear all cached routes. Returns number of entries cleared."""
    count = len(_route_cache)
    _route_cache.clear()
    logger.info("Cleared %d cached route entries", count)
    return count


# ---------------------------------------------------------------------------
# SerpAPI Google Flights client
# ---------------------------------------------------------------------------


def _get_serpapi_key() -> str:
    key = os.getenv("SERPAPI_API_KEY", "")
    if not key:
        raise FlightScoringError(
            "SERPAPI_API_KEY not found in environment. "
            "Sign up at https://serpapi.com and add the key to your .env file."
        )
    return key


def _format_duration(minutes: int) -> str:
    """Format minutes as 'Xh Ym'."""
    h, m = divmod(minutes, 60)
    return f"{h}h {m}m"


def _parse_flights_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse SerpAPI Google Flights response into nonstop route dicts."""
    routes: list[dict[str, Any]] = []

    all_groups = data.get("best_flights", []) + data.get("other_flights", [])

    for group in all_groups:
        flights = group.get("flights", [])
        # Nonstop = exactly 1 flight segment
        if len(flights) != 1:
            continue

        segment = flights[0]
        flight_number = segment.get("flight_number", "")
        airline_iata = flight_number[:2] if len(flight_number) >= 2 else ""
        duration = segment.get("duration", 0)

        dep_airport = segment.get("departure_airport", {})
        arr_airport = segment.get("arrival_airport", {})

        routes.append({
            "origin": dep_airport.get("id", ""),
            "destination": arr_airport.get("id", ""),
            "airline": airline_iata,
            "airline_name": segment.get("airline", ""),
            "duration_minutes": duration,
            "duration_formatted": _format_duration(duration),
            "flight_number": flight_number,
            "departure_time": dep_airport.get("time", ""),
            "arrival_time": arr_airport.get("time", ""),
        })

    return routes


def fetch_nonstop_routes(
    origin: str,
    destination: str,
    *,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Fetch nonstop flight routes between two airports via SerpAPI.

    Args:
        origin: Origin IATA airport code (e.g. "MSY")
        destination: Destination IATA airport code (e.g. "CLT")
        force_refresh: Bypass cache and fetch fresh data

    Returns:
        List of nonstop route dicts with airline, duration, flight_number, etc.

    Raises:
        FlightScoringError: If API key is missing or API call fails
    """
    origin = origin.upper().strip()
    destination = destination.upper().strip()
    key = _cache_key(origin, destination)

    if not force_refresh:
        cached = _get_cached(key)
        if cached is not None:
            logger.info("Cache hit for %s -> %s (%d routes)", origin, destination, len(cached))
            return cached

    api_key = _get_serpapi_key()
    outbound_date = (date.today() + timedelta(days=14)).isoformat()

    params = {
        "engine": "google_flights",
        "api_key": api_key,
        "departure_id": origin,
        "arrival_id": destination,
        "outbound_date": outbound_date,
        "type": "2",  # one-way
        "stops": "1",  # nonstop only
        "currency": "USD",
        "hl": "en",
        "gl": "us",
    }

    logger.info("Fetching nonstop routes: %s -> %s (date=%s)", origin, destination, outbound_date)

    try:
        resp = requests.get(
            SERPAPI_BASE_URL,
            params=params,
            timeout=SERPAPI_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise FlightScoringError(f"SerpAPI request failed: {e}") from e

    if not resp.ok:
        raise FlightScoringError(
            f"SerpAPI returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()

    if "error" in data:
        logger.warning("SerpAPI error for %s->%s: %s", origin, destination, data["error"])
        routes: list[dict[str, Any]] = []
    else:
        routes = _parse_flights_response(data)

    logger.info("Found %d nonstop routes: %s -> %s", len(routes), origin, destination)
    _set_cached(key, routes)
    return routes


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


def score_member_for_destination(
    member: TeamMember,
    destination: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Score a team member for a destination airport.

    Returns dict with: member_name, home_airport, destination, score,
    eligible, reasoning, available_airlines, shortest_duration_minutes.
    """
    routes = fetch_nonstop_routes(member.home_airport, destination, force_refresh=force_refresh)
    available_airlines = sorted({r["airline"] for r in routes if r["airline"]})

    if not routes:
        return {
            "member_name": member.name,
            "home_airport": member.home_airport,
            "destination": destination,
            "score": 0,
            "eligible": False,
            "reasoning": f"No nonstop routes from {member.home_airport} to {destination}",
            "available_airlines": [],
            "shortest_duration_minutes": None,
            "score_breakdown": {},
        }

    score: float = NONSTOP_EXISTS
    breakdown: dict[str, int | float] = {"nonstop_exists": NONSTOP_EXISTS}
    reasons: list[str] = [f"Nonstop available from {member.home_airport} to {destination}"]
    eligible = True

    # Required airline check
    if member.required_airlines:
        has_required = bool(member.required_airlines & set(available_airlines))
        if has_required:
            score += PREFERRED_AIRLINE_BONUS
            breakdown["required_airline_match"] = PREFERRED_AIRLINE_BONUS
            matched = member.required_airlines & set(available_airlines)
            reasons.append(f"Required airline available: {', '.join(sorted(matched))}")
        else:
            score += REQUIRED_AIRLINE_PENALTY
            breakdown["required_airline_missing"] = REQUIRED_AIRLINE_PENALTY
            reasons.append(
                f"Required airline ({', '.join(sorted(member.required_airlines))}) "
                f"not available; only: {', '.join(available_airlines)}"
            )
            eligible = False

    # Preferred airline check (only if no required_airlines constraint)
    if not member.required_airlines and member.preferred_airlines:
        has_preferred = bool(member.preferred_airlines & set(available_airlines))
        if has_preferred:
            score += PREFERRED_AIRLINE_BONUS
            breakdown["preferred_airline_bonus"] = PREFERRED_AIRLINE_BONUS
            matched = member.preferred_airlines & set(available_airlines)
            reasons.append(f"Preferred airline bonus: {', '.join(sorted(matched))}")

    # Shortest flight bonus
    shortest = min((r["duration_minutes"] for r in routes if r["duration_minutes"] > 0), default=0)
    if member.prioritize_shortest and shortest > 0:
        bonus = max(0.0, (SHORTEST_FLIGHT_BASE_MINUTES - shortest) * SHORTEST_FLIGHT_FACTOR)
        score += bonus
        breakdown["shortest_flight_bonus"] = bonus
        reasons.append(
            f"Shortest flight: {_format_duration(shortest)} "
            f"(+{bonus:.0f} pts)"
        )

    if score <= 0:
        eligible = False

    return {
        "member_name": member.name,
        "home_airport": member.home_airport,
        "destination": destination,
        "score": round(score, 1),
        "eligible": eligible,
        "reasoning": "; ".join(reasons),
        "available_airlines": available_airlines,
        "shortest_duration_minutes": shortest if shortest > 0 else None,
        "score_breakdown": breakdown,
    }


def score_destination_for_all_members(
    destination: str,
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Score a destination airport for all team members.

    Returns dict with: destination, best_fit, member_scores (sorted descending).
    """
    scores = []
    for member in TEAM_MEMBERS.values():
        result = score_member_for_destination(member, destination, force_refresh=force_refresh)
        scores.append(result)

    scores.sort(key=lambda s: s["score"], reverse=True)

    best = next((s for s in scores if s["eligible"]), None)
    best_fit = best["member_name"] if best else "UNASSIGNED"

    return {
        "destination": destination,
        "best_fit": best_fit,
        "member_scores": scores,
    }


def assign_locations_to_members(
    locations: list[dict[str, str]],
    *,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Batch-assign destination airports to best-fit team members.

    Args:
        locations: List of dicts with "airport" key and optional "city" key
        force_refresh: Bypass cache

    Returns:
        Dict with per-person summary and detailed assignments.
    """
    assignments: list[dict[str, Any]] = []
    person_summary: dict[str, list[str]] = {m.name: [] for m in TEAM_MEMBERS.values()}
    unassigned: list[str] = []

    for loc in locations:
        airport = loc.get("airport", "").upper().strip()
        city = loc.get("city", "")

        if not airport:
            continue

        result = score_destination_for_all_members(airport, force_refresh=force_refresh)
        assigned_to = result["best_fit"]

        assignment = {
            "destination_airport": airport,
            "destination_city": city,
            "assigned_to": assigned_to,
            "score": result["member_scores"][0]["score"] if result["member_scores"] else 0,
            "reasoning": result["member_scores"][0]["reasoning"] if result["member_scores"] else "",
            "all_scores": result["member_scores"],
        }
        assignments.append(assignment)

        if assigned_to == "UNASSIGNED":
            unassigned.append(airport)
        else:
            person_summary[assigned_to].append(f"{airport} ({city})" if city else airport)

    return {
        "assignments": assignments,
        "summary_by_person": {
            name: locs for name, locs in person_summary.items() if locs
        },
        "unassigned": unassigned,
        "total_locations": len(assignments),
    }


# ---------------------------------------------------------------------------
# Location resolution
# ---------------------------------------------------------------------------


def resolve_location_to_airports(location: str) -> dict[str, Any]:
    """Map a city/location string to IATA airport codes.

    Supports exact match, case-insensitive match, and partial string match.

    Returns dict with: query, matched_location, airports, all_locations (on no match).
    """
    query = location.strip()
    query_lower = query.lower()

    # Exact match (case-insensitive)
    for loc, airports in SCHOOL_LOCATION_MAP.items():
        if loc.lower() == query_lower:
            return {
                "query": query,
                "matched_location": loc,
                "airports": airports,
                "match_type": "exact",
            }

    # Partial match (query is substring of location or vice versa)
    matches: list[tuple[str, list[str]]] = []
    for loc, airports in SCHOOL_LOCATION_MAP.items():
        if query_lower in loc.lower() or loc.lower() in query_lower:
            matches.append((loc, airports))

    if len(matches) == 1:
        loc, airports = matches[0]
        return {
            "query": query,
            "matched_location": loc,
            "airports": airports,
            "match_type": "partial",
        }

    if len(matches) > 1:
        return {
            "query": query,
            "multiple_matches": [
                {"location": loc, "airports": airports} for loc, airports in matches
            ],
            "match_type": "ambiguous",
            "message": f"Multiple matches for '{query}'. Please be more specific.",
        }

    return {
        "query": query,
        "matched_location": None,
        "airports": [],
        "match_type": "none",
        "all_locations": sorted(SCHOOL_LOCATION_MAP.keys()),
        "message": f"No match for '{query}'. See all_locations for known cities.",
    }


# ---------------------------------------------------------------------------
# P1 assignment integration
# ---------------------------------------------------------------------------


def rank_contacts_by_flight_score(
    destination_airports: list[str],
    eligible_contact_ids: set[str],
    *,
    force_refresh: bool = False,
) -> list[tuple[str, float]]:
    """Rank eligible Wrike contacts by flight score to destination airports.

    Only scores contacts that exist in CONTACT_ID_TO_MEMBER. Contacts not in
    the flight system are silently skipped (allows mixed pools with Growth/Flagship).

    Args:
        destination_airports: IATA codes for the destination city
        eligible_contact_ids: Set of Wrike contact IDs to consider
        force_refresh: Bypass cache

    Returns:
        List of (contact_id, best_score) sorted descending by score.
        Only includes contacts with score > 0 (eligible).
    """
    results: list[tuple[str, float]] = []

    for contact_id in eligible_contact_ids:
        member_key = CONTACT_ID_TO_MEMBER.get(contact_id)
        if member_key is None:
            continue
        member = TEAM_MEMBERS[member_key]

        # Score against all airports for the city, take the best
        best_score = 0.0
        for airport in destination_airports:
            score_result = score_member_for_destination(
                member, airport, force_refresh=force_refresh
            )
            if score_result["eligible"] and score_result["score"] > best_score:
                best_score = score_result["score"]

        if best_score > 0:
            results.append((contact_id, best_score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results
