"""Framework primitives for a "router" orchestrator: an agent with zero
tools of its own whose only job is transferring a question to the right
domain specialist(s) among its sub_agents and combining their answers.

This is the pattern nl2sql_orchestrator (scripts/seed_nl2sql_orchestrator.py)
already used for exactly two specialists (credit_facility_analyst,
revenue_returns_analyst), generalized here so it scales to any number of
specialists without new "first/second"-style hardcoded wording, and made
reusable so any future router orchestrator (a new one, or an existing
single-transfer one like market_intelligence_orchestrator, if it's ever
upgraded to this richer behavior) wires up the exact same two functions
rather than hand-rolling its own version of this prompt.

The actual coordination happens entirely through Google ADK's built-in
transfer_to_agent tool call and the orchestrator/specialist instructions
below — no new orchestrator agent, no extra planning step, no scratchpad
state for the plan itself. The specialists bouncing back to their parent
with a note on what's still outstanding *is* the plan; the orchestrator's
own conversation history *is* the coordination state. The one piece of
actual runtime infrastructure this pattern relies on is the transfer-hop
safety net in agent_runtime.builder._build_before_tool_callback, which caps
how many times transfer_to_agent can fire in a single turn so a model that
ignores the "never transfer to the same specialist twice" rule below can't
loop forever — that cap applies to every agent this platform builds, not
just router orchestrators, so it costs nothing to rely on it here too.
"""

import re

_PEER_CLAUSE_START = "\n\n<!-- router-peer-clause:start -->"
_PEER_CLAUSE_END = "<!-- router-peer-clause:end -->"


def build_router_instruction(domain_summary: str, specialists: dict[str, str]) -> str:
    """`domain_summary` is a short noun phrase for what this orchestrator
    routes ("structured-data domain", "market intelligence", ...).
    `specialists` maps each sub-agent's exact published name to a one-line
    description of its domain, in the order they should appear in the
    directory. Adding, removing, or reordering a specialist is the only
    thing that ever needs to change here — the routing algorithm itself
    already handles one specialist or all of them the same way."""
    directory = "\n".join(f"- {name}: {desc}" for name, desc in specialists.items())
    return f"""You are the {domain_summary} orchestrator. You never answer a data
question yourself — you always transfer to the right specialist(s). Each specialist
writes its own real logic against its own domain and enforces its own access rules —
you don't need to know any of that, only which specialist(s) own which topic.

Specialists currently onboarded:
{directory}

Routing algorithm — follow this every time, whether the question needs exactly one
specialist or several:
1. Identify EVERY specialist domain the question touches — it might be just one, or
   more than one.
2. Transfer to ONE relevant specialist you haven't already used for this question.
3. That specialist answers what it can. If the question also needs data outside its
   own domain, it will silently transfer back to you (never sideways to another
   specialist directly) with a note on exactly what's still outstanding — you'll see
   its partial answer already in the conversation when that happens.
4. Repeat step 2 for whatever's still outstanding, picking the next relevant
   specialist you haven't used yet — this works the same whether that's the 2nd,
   3rd, or Nth specialist a given question ends up needing.
5. Never transfer to the same specialist twice for one question. If every relevant
   specialist has already been tried and something is still outstanding, stop and
   say so plainly rather than transferring again.
6. Once nothing is left outstanding (or every relevant specialist has already
   answered), stop transferring and present ONE combined final answer that clearly
   attributes each figure to the specialist/domain it came from — never just
   concatenate separate replies, and never silently drop a part you already
   collected.
7. If the request doesn't clearly belong to any onboarded specialist's domain, say so
   plainly and list what you can currently help with — don't guess or transfer to a
   specialist that isn't a good fit.
8. Never fabricate figures yourself — you have no data tools of your own by design,
   only transfer targets.

When a new specialist is onboarded, it gets a new bullet in the directory above and a
new sub-agent attachment — nothing else about this instruction needs to change, no
matter how many specialists a single question ends up needing."""


def build_peer_clause() -> str:
    """Appended to every specialist attached to a router orchestrator built
    with build_router_instruction() above. Deliberately generic and free of
    any domain names — a specialist only ever needs one fact ("go back to
    my parent for anything outside my domain"), never the full roster of
    every other onboarded specialist. That's what keeps onboarding a new
    specialist a change to the orchestrator + its directory alone; no
    existing specialist's own instruction has to be rewritten when a
    further domain shows up later.

    Wrapped in a marker comment (not matched by exact wording) so a reseed
    script can find and strip/replace it safely even after this wording
    changes — see scripts/seed_nl2sql_orchestrator.py's original version of
    this same idea for why that matters in practice."""
    body = (
        "If the user's question ALSO needs data outside your own domain, do not "
        "decline or guess and do not narrate what you're about to do — first answer "
        "the part you can, then silently call transfer_to_agent to transfer back to "
        "your parent orchestrator with a brief note on what still needs answering, so "
        "it can route the rest to the right specialist (there may be more than one "
        "still outstanding). Never silently drop the out-of-domain part, and never "
        "tell the user you're transferring — just do it.\n\n"
        "This also applies to meta-questions about the assistant itself — 'what can "
        "you do', 'what are your capabilities', 'who are you', 'what can I ask you' — "
        "these are NOT about your domain specifically, even though you could technically "
        "answer with just your own scope. A conversation can resume directly on you "
        "(skipping your parent) if you answered the last message, so you may be the "
        "first agent to see a meta-question like this even though it was never meant for "
        "you alone. Silently transfer back to your parent orchestrator for these instead "
        "of self-describing — it knows the full roster and can give a complete answer; "
        "you only know your own domain."
    )
    return f"{_PEER_CLAUSE_START}\n{body}\n{_PEER_CLAUSE_END}"


def strip_peer_clause(instruction: str) -> str:
    return re.sub(
        re.escape(_PEER_CLAUSE_START) + r".*?" + re.escape(_PEER_CLAUSE_END),
        "",
        instruction,
        flags=re.DOTALL,
    )
