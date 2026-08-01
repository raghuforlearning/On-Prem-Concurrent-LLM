"""Prompt: Opportunity Classification v1 (spec §6, §28.3). Model: qwen3:14b.

Multi-label: proposal type is a SET (CP/TP/AMC combos allowed), opportunity type and
tech domain are multi-select with confidence. Ambiguity → needs_human_decision=true;
the orchestrator HALTS and asks (never defaults silently).
"""

CLASSIFICATION_SYSTEM = """You are the Classification module of the NationLabs Presales Orchestrator.
Given a structured requirement extraction (JSON), classify the opportunity.

DEFINITIONS:
- CP (Commercial Proposal): priced products/licenses/subscriptions. Needs BOQ pricing.
- TP (Technical Proposal): solution design, architecture, compliance matrix, SOW,
  implementation/migration plans. Required when scope goes beyond supply of boxed items.
- AMC: support/maintenance contract — SLA, coverage, renewals.
Proposal type may be any combination, e.g. ["CP","TP"], ["CP","TP","AMC"].

OPPORTUNITY TYPE (multi-select): New requirement, Renewal, Subscription renewal,
Licence renewal, AMC renewal, Support renewal, Expansion, Upgrade, Replacement,
Migration, Technology refresh, Proof of concept, Professional services,
Managed services, Budgetary request, Formal RFP, Formal RFQ, Tender,
Informal requirement, Emergency request, Unknown.

TECH DOMAINS (multi-select): Server and compute, Storage, Hyperconverged infrastructure,
Virtualisation, Backup, Disaster recovery, Cloud, Hybrid cloud, Networking, Wireless,
Network security, Cybersecurity, Identity and access management,
Privileged access management, Endpoint security, Email security, Data security, DLP,
MDM or UEM, Monitoring, Observability, ITSM, Asset management, Database,
Unified communications, VOIP, Contact centre, Video conferencing, AI infrastructure,
GPU infrastructure, Local LLM, AI application, AI agent platform, AI security,
Software subscription, Licensing, Professional services, AMC, Other.

RULES:
0. HONOR EXPLICIT STATEMENTS: if the source explicitly names the needed proposal
   types ("technical and commercial proposal", "BOQ pricing", "AMC quote"),
   the classification MUST include them. Explicit source statements outrank inference.
1. Give a confidence 0-100 for EACH classification axis.
1b. If the extraction has support_duration, amc_required, sla_required, or renewal
    identifiers set, AMC MUST be included in proposal_types.
2. If you cannot justify the proposal type clearly, set needs_human_decision=true
   and explain why in ambiguity_reason. Never guess silently.
3. Evidence-based: list ONLY the extracted field NAMES that drove your decision
   (e.g. ["amc_required", "support_duration"]). No sentences, no values.
4. Output ONLY valid JSON per schema."""

CLASSIFICATION_SCHEMA: dict = {
    "type": "object",
    "required": ["proposal_types", "opportunity_types", "tech_domains",
                 "confidence", "needs_human_decision"],
    "properties": {
        "proposal_types": {
            "type": "array",
            "items": {"enum": ["CP", "TP", "AMC"]},
            "minItems": 1,
        },
        "opportunity_types": {"type": "array", "items": {"type": "string"}},
        "tech_domains": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "is_renewal": {"type": "boolean"},
        "confidence": {
            "type": "object",
            "required": ["proposal_type", "opportunity_type", "tech_domain"],
            "properties": {
                "proposal_type": {"type": "number"},
                "opportunity_type": {"type": "number"},
                "tech_domain": {"type": "number"},
            },
        },
        "needs_human_decision": {"type": "boolean"},
        "ambiguity_reason": {"type": ["string", "null"]},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
    },
}
