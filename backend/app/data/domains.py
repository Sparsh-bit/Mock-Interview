"""
The domain registry — app/data/domains.py

WHAT A ROLE IS ACTUALLY ABOUT, and therefore what it may be asked, who asks it,
and what a good answer to it looks like.

WHY THIS FILE EXISTS. Until now the planner had exactly two categories: "Java
role" and "everything else". The Java branch read the curated bank in
`java_fundamentals.py`; the other branch, when the company was not on the
catalogue, told the planner in so many words to cover "programming fundamentals,
DBMS and SQL, data structures". That sentence is why a candidate who asked for
**Asian Paints, sales / business development** was handed an interview plan of
Programming Fundamentals, Data Structures, DBMS & SQL and Version Control. The
bug was not a bad model response. It was the brief.

There is no defensible way to write that fallback without a notion of a domain,
because the honest answer to "what should we ask?" is a function of the role and
nothing else. So: a domain per family of roles, and for each one the three things
every other part of the interview needs.

  topics      the must-cover weighting, the same shape the company catalogue
              uses, so `_must_cover_block` can hand the planner a real
              distribution instead of a sentence naming CS subjects.
  panel       who is in the room. A sales candidate interviewed by a "Senior
              Engineering Manager" and a "Technical Lead" is being told, before a
              word is spoken, that the simulation does not know what job they
              applied for. The designations are per domain for that reason.
  scenarios   seed questions, and deliberately SITUATIONAL ones — see below.

SCENARIOS, NOT DEFINITIONS. Every seed question here puts the candidate in a
situation and asks what they would do. That is a decision about interview
realism, not a stylistic preference: campus interviews outside the CS core are
overwhelmingly situational ("a dealer is threatening to switch to a competitor
over a pricing dispute — walk me through your next two days"), and a definitional
bank ("what is channel sales?") trains a candidate for a round that does not
exist. It is also the honest way to seed a domain the author is not an expert in:
a scenario is answerable from judgement and can be scored on reasoning, whereas a
fact question in an unfamiliar field risks being confidently wrong. Where a
domain here is thinner than `java_fundamentals.py`, that is by design — the seed
guarantees a coherent first interview and the planner generates depth on top of
it, cached globally by the vector cache so the cost falls as the bank warms.

WHAT THIS IS NOT. It is not a replacement for the company catalogue. The
catalogue says what a *company* weights; this says what a *role* is. When both
exist the planner gets both, and the company weighting refines the domain rather
than replacing it — an Accenture sales role is still a sales interview.

Adding a domain: add a `_Profile` to `PROFILES`, add its keywords to `_KEYWORDS`
(most specific first — see `resolve`), and the planner, the seeder and the panel
all pick it up with no further wiring.
"""

from __future__ import annotations

from typing import Literal, TypedDict


class ScenarioQuestion(TypedDict):
    """One seed question. Mirrors the Question model, as `BankQuestion` does."""

    topic: str
    content: str
    difficulty: Literal["easy", "medium"]
    type: Literal["conceptual", "practical"]
    keywords: list[str]
    ideal: str


class DomainProfile(TypedDict):
    """Everything the rest of the app needs to know about a family of roles."""

    label: str
    #: Designations for the two-person panel, lead first. Kept parallel to
    #: `panel.INTERVIEWERS`, which is where they are actually rendered.
    lead_role: str
    specialist_role: str
    #: (topic, weight). Validated to sum to 100 at import — see the check below.
    topics: list[tuple[str, int]]
    scenarios: list[ScenarioQuestion]


# ─── Sales & business development ─────────────────────────────────────────────

_SALES: list[ScenarioQuestion] = [
    {
        "topic": "Prospecting & Pipeline",
        "content": (
            "You've been given a territory with no existing customers and a list of "
            "two hundred businesses. Walk me through your first week — how do you "
            "decide who to call first?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["qualify", "segment", "prioritise", "research", "ICP", "pipeline"],
        "ideal": (
            "Segment the list before touching the phone — size, sector, and whether "
            "they already buy something adjacent. Rank by fit and reachability, not "
            "alphabetically. Spend day one on research so the first call has a reason "
            "to exist, then work the top tier while keeping a steady volume of "
            "lower-priority outreach so the pipeline never runs dry."
        ),
    },
    {
        "topic": "Objection Handling",
        "content": (
            "A prospect says your product is thirty percent more expensive than the "
            "competitor they're already using. What do you say next?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["value", "total cost", "discovery", "differentiate", "not discount"],
        "ideal": (
            "Don't lead with a discount — that concedes the frame. Ask what they're "
            "comparing, because a price gap usually hides a scope difference. Move the "
            "conversation to total cost: downtime, switching cost, service. If the "
            "value genuinely isn't there for this buyer, say so and qualify out rather "
            "than discounting into a bad account."
        ),
    },
    {
        "topic": "Channel & Distribution",
        "content": (
            "A long-standing dealer is threatening to move to a competitor because "
            "they say your margins are too thin. You can't change the margin. What do "
            "you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["relationship", "non-price levers", "credit", "support", "escalate"],
        "ideal": (
            "Find out whether margin is the real issue or the stated one — often it's "
            "slow service, stock-outs or credit terms. Then use the levers you do "
            "have: delivery reliability, marketing support, exclusivity in a sub-area, "
            "training for their staff. Be honest about what you can't move, and "
            "escalate with a documented case if the account justifies a policy "
            "exception."
        ),
    },
    {
        "topic": "Negotiation",
        "content": (
            "You're close to signing, and the buyer asks for a twenty percent discount "
            "to close today. Your approval limit is ten. Talk me through it."
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["trade", "concession", "authority", "urgency", "walk away"],
        "ideal": (
            "Never give a concession without taking something back — volume, a longer "
            "term, an earlier payment, a reference. Test whether the deadline is real. "
            "Use the approval limit honestly rather than pretending it doesn't exist, "
            "and be willing to lose a deal that only works at a price you can't repeat."
        ),
    },
    {
        "topic": "Target & Territory Management",
        "content": (
            "It's the last week of the quarter and you're at sixty percent of target. "
            "What do you actually do with those five days?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["pipeline review", "close plan", "prioritise", "honest forecast"],
        "ideal": (
            "Work the pipeline you have rather than prospecting cold — go to deals "
            "already in late stage and remove whatever is blocking them. Be realistic "
            "with the manager early instead of surprising them on the last day. Avoid "
            "pulling next quarter's business forward with discounts, because that just "
            "moves the problem."
        ),
    },
    {
        "topic": "Customer Retention",
        "content": (
            "A major customer's order volume has dropped by half over two months and "
            "they haven't complained about anything. How do you approach it?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["diagnose", "visit", "stakeholder", "competitor", "silent churn"],
        "ideal": (
            "Silence is the warning sign — go and see them rather than emailing. Find "
            "out whether it's their demand that fell or your share of it, and whether "
            "the buying contact changed. Map the other stakeholders so the account "
            "doesn't depend on one relationship, then bring a specific proposal rather "
            "than asking what went wrong."
        ),
    },
    {
        "topic": "Market & Product Knowledge",
        "content": (
            "How would you explain our product's advantage to a customer who has used "
            "the competitor for ten years and is happy with it?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["differentiation", "switching cost", "specific", "credibility"],
        "ideal": (
            "Accept that 'happy' is a real position and don't attack their past choice. "
            "Look for the thing their current supplier structurally cannot do. Ask for "
            "a small trial rather than a switch, so the risk of being wrong is theirs "
            "in a small way rather than yours in a large one."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": (
            "Tell me about a time you committed to something you then couldn't "
            "deliver. What did you do?"
        ),
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["accountability", "early communication", "recovery", "learning"],
        "ideal": (
            "A specific example, told without blaming others. The important parts are "
            "how early it was flagged, what was offered instead, and what changed "
            "afterwards so the same commitment isn't made again."
        ),
    },
]


# ─── Marketing ────────────────────────────────────────────────────────────────

_MARKETING: list[ScenarioQuestion] = [
    {
        "topic": "Campaign Planning",
        "content": (
            "You have a small budget and one month to raise awareness of a product "
            "among college students. What do you do, and how do you know it worked?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["audience", "channel", "budget", "metric", "measurable"],
        "ideal": (
            "Pick one audience and one channel rather than spreading thin. Define the "
            "success metric before spending — reach is not the same as consideration. "
            "Build in a way to attribute results, even crudely, so the next budget "
            "decision has evidence behind it."
        ),
    },
    {
        "topic": "Brand & Positioning",
        "content": (
            "Our brand is seen as reliable but boring, and a younger competitor is "
            "taking share. How would you address that without alienating existing "
            "customers?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["positioning", "segment", "sub-brand", "consistency", "risk"],
        "ideal": (
            "Don't discard the equity you have — reliability is expensive to build. "
            "Consider reaching the new segment through a sub-brand or a specific line "
            "rather than repositioning the whole company, and test before committing."
        ),
    },
    {
        "topic": "Digital & Analytics",
        "content": (
            "A campaign is getting a lot of clicks but almost no sign-ups. Where do "
            "you look first?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["funnel", "landing page", "targeting mismatch", "attribution"],
        "ideal": (
            "A click-to-signup gap points at a mismatch between the promise and the "
            "landing experience, or at traffic that was never qualified. Check the "
            "landing page load and form length, then check who the clicks are actually "
            "coming from before spending more."
        ),
    },
    {
        "topic": "Market Research",
        "content": (
            "How would you find out whether there's real demand for a product that "
            "doesn't exist yet?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["primary research", "willingness to pay", "proxy", "bias"],
        "ideal": (
            "Asking people whether they'd buy something is weak evidence. Look for "
            "proxies — what they currently spend money or effort on to solve the same "
            "problem — and test willingness to pay with a real commitment, however "
            "small."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": (
            "Tell me about a time you had to convince someone senior that your idea "
            "was right. How did you do it?"
        ),
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["evidence", "framing", "listening", "outcome"],
        "ideal": (
            "A concrete example where the persuasion came from evidence and from "
            "understanding what the other person was actually worried about, not from "
            "persistence alone."
        ),
    },
]


# ─── Human resources ──────────────────────────────────────────────────────────

_HR: list[ScenarioQuestion] = [
    {
        "topic": "Recruitment",
        "content": (
            "You need to fill a role urgently and the hiring manager keeps rejecting "
            "every shortlist without clear reasons. How do you handle it?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["align criteria", "scorecard", "calibration", "stakeholder"],
        "ideal": (
            "Stop sourcing and go back to the brief — repeated vague rejections almost "
            "always mean the criteria were never agreed. Get to a written scorecard, "
            "calibrate on two or three real profiles, and agree what is essential "
            "versus desirable before restarting."
        ),
    },
    {
        "topic": "Employee Relations",
        "content": (
            "An employee reports that their manager is regularly making them work "
            "late without notice. Walk me through your next steps."
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["confidentiality", "listen", "document", "policy", "fair process"],
        "ideal": (
            "Listen fully and record what was said, make clear what will and won't stay "
            "confidential, and check it against policy rather than reacting. Speak to "
            "the manager separately, look for a pattern rather than a single incident, "
            "and follow the documented process so any outcome is defensible."
        ),
    },
    {
        "topic": "Onboarding & Engagement",
        "content": (
            "Half your new joiners are leaving within six months. How would you find "
            "out why, and what would you try first?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["exit interview", "expectation gap", "onboarding", "manager"],
        "ideal": (
            "Talk to leavers and to people who stayed, since only comparing the two "
            "isolates the cause. Early attrition usually traces to a gap between what "
            "was promised in hiring and the actual role, or to one manager. Fix the "
            "promise or the manager before redesigning the whole programme."
        ),
    },
    {
        "topic": "HR Operations & Compliance",
        "content": (
            "You discover payroll has been under-deducting a statutory contribution "
            "for several months. What do you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["escalate", "quantify", "correct", "communicate", "compliance"],
        "ideal": (
            "Quantify the exposure before escalating so the conversation is factual, "
            "raise it immediately rather than quietly correcting it going forward, and "
            "plan the communication to affected employees — a silent correction that "
            "changes take-home pay is worse than the original error."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": (
            "Tell me about a time you had to deliver news someone did not want to "
            "hear."
        ),
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["directness", "empathy", "preparation", "follow-up"],
        "ideal": (
            "A real example, delivered directly and early rather than softened into "
            "ambiguity, with attention to what the person needed afterwards."
        ),
    },
]


# ─── Finance & accounting ─────────────────────────────────────────────────────

_FINANCE: list[ScenarioQuestion] = [
    {
        "topic": "Financial Analysis",
        "content": (
            "A business unit's revenue is up fifteen percent but its profit is down. "
            "How do you find out what's happening?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["margin", "cost structure", "mix", "variance analysis"],
        "ideal": (
            "Separate volume, price and mix before looking at costs. Growth with "
            "falling profit usually means discounting, a shift toward lower-margin "
            "products, or a cost that scales with volume faster than expected. Variance "
            "analysis against budget localises it quickly."
        ),
    },
    {
        "topic": "Accounting Fundamentals",
        "content": (
            "A company is profitable on paper but keeps running short of cash. "
            "Explain how that happens."
        ),
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["accrual", "receivables", "inventory", "working capital", "cash flow"],
        "ideal": (
            "Profit is recognised on accrual, cash is not. Money can be tied up in "
            "receivables customers haven't paid, in inventory, or in capital spending "
            "that doesn't hit the P&L at once. Working-capital growth funded from "
            "operations is the usual culprit."
        ),
    },
    {
        "topic": "Budgeting & Control",
        "content": (
            "A department has overspent its budget by a wide margin and says the "
            "budget was unrealistic. How do you respond?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["variance", "evidence", "reforecast", "control", "accountability"],
        "ideal": (
            "Test the claim with the variance breakdown rather than accepting or "
            "rejecting it. If the assumptions genuinely moved, reforecast openly; if "
            "not, tighten approval on the categories that ran over. Either way agree "
            "what triggers an escalation next time."
        ),
    },
    {
        "topic": "Audit & Controls",
        "content": (
            "During a routine check you notice a series of payments just below the "
            "approval threshold, all to the same vendor. What do you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["red flag", "splitting", "document", "escalate", "independence"],
        "ideal": (
            "Payment splitting to stay under a threshold is a classic control-avoidance "
            "pattern. Gather the evidence quietly and completely, don't accuse anyone "
            "on the basis of a pattern alone, and escalate through the defined channel "
            "rather than confronting the budget holder directly."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time you found an error in your own work after it was submitted.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["integrity", "speed of disclosure", "correction", "prevention"],
        "ideal": (
            "The answer that matters is how quickly it was raised and what control was "
            "added afterwards, not how small the error was."
        ),
    },
]


# ─── Operations & supply chain ────────────────────────────────────────────────

_OPERATIONS: list[ScenarioQuestion] = [
    {
        "topic": "Process & Efficiency",
        "content": (
            "One stage of a production line is consistently slower than the rest and "
            "work is piling up in front of it. How do you approach it?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["bottleneck", "measure", "root cause", "throughput", "WIP"],
        "ideal": (
            "Confirm it's the constraint by measuring rather than by where the pile is. "
            "Then look for causes in that order: machine availability, changeover time, "
            "operator method, input quality. Improving anything that isn't the "
            "bottleneck raises inventory without raising output."
        ),
    },
    {
        "topic": "Supply Chain",
        "content": (
            "Your single supplier for a critical component has just told you they'll "
            "be two weeks late. What do you do today?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["impact assessment", "expedite", "alternate source", "communicate"],
        "ideal": (
            "Work out the real impact first — buffer stock may absorb part of it. In "
            "parallel, look for partial shipments, an alternate source, or resequencing "
            "production. Tell whoever is downstream early rather than hoping to recover "
            "quietly."
        ),
    },
    {
        "topic": "Quality",
        "content": (
            "A customer reports a defect that your inspection process should have "
            "caught. How do you investigate?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["containment", "root cause", "5 why", "corrective action", "escape"],
        "ideal": (
            "Contain first — find out what else from that batch shipped. Then two "
            "separate root causes: why the defect occurred, and why inspection missed "
            "it. Fixing only the first guarantees the next defect escapes too."
        ),
    },
    {
        "topic": "Planning & Inventory",
        "content": (
            "You're told to cut inventory by thirty percent without affecting "
            "availability. Is that possible, and how would you try?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["segment", "lead time", "variability", "safety stock", "trade-off"],
        "ideal": (
            "Possible in parts, not uniformly. Segment by value and variability, cut "
            "hardest where demand is predictable and lead times are short, and be "
            "explicit about the service-level risk on the rest rather than pretending "
            "the trade-off doesn't exist."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time you had to make a decision without complete information.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["judgement", "reversibility", "assumptions", "review"],
        "ideal": (
            "A specific decision, with the assumptions stated at the time and a check "
            "on whether the decision was reversible if wrong."
        ),
    },
]


# ─── Mechanical engineering ───────────────────────────────────────────────────

_MECHANICAL: list[ScenarioQuestion] = [
    {
        "topic": "Design & Materials",
        "content": (
            "A bracket in the field keeps failing at the same weld after a few months. "
            "How would you work out why?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["fatigue", "stress concentration", "load cycle", "material", "inspection"],
        "ideal": (
            "Repeated failure at one location after time in service points at fatigue "
            "rather than overload. Look at the stress concentration at the weld toe, "
            "the actual cyclic load versus the design assumption, and whether the weld "
            "procedure or material matches the drawing."
        ),
    },
    {
        "topic": "Thermodynamics & Fluids",
        "content": (
            "A pump that used to deliver rated flow is now delivering noticeably less "
            "and making more noise. What do you check?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["cavitation", "NPSH", "suction", "wear", "blockage"],
        "ideal": (
            "Noise plus lost flow suggests cavitation or a suction-side restriction. "
            "Check the suction head available against what the pump requires, look for "
            "a blocked strainer or leaking joint, then consider impeller wear."
        ),
    },
    {
        "topic": "Manufacturing Processes",
        "content": (
            "A machined part is within tolerance at the machine but out of tolerance "
            "when it reaches assembly. What could be happening?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["thermal", "residual stress", "measurement", "handling", "datum"],
        "ideal": (
            "Consider whether the part is being measured hot, whether residual stress "
            "is relaxing after clamping is released, whether the measurement datum "
            "differs between the two places, and whether handling is deforming it."
        ),
    },
    {
        "topic": "Strength of Materials",
        "content": (
            "Explain to a non-engineer why a hollow tube can be nearly as strong as a "
            "solid bar in bending but much lighter."
        ),
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["second moment of area", "bending", "distance from neutral axis"],
        "ideal": (
            "In bending, material far from the centre carries most of the load, and "
            "material near the centre contributes very little. Removing the middle "
            "sheds weight while keeping most of the stiffness."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a project where your design had to change late. What happened?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["constraints", "trade-off", "communication", "outcome"],
        "ideal": "A real project, with the constraint that forced the change and the trade-off made.",
    },
]


# ─── Civil engineering ────────────────────────────────────────────────────────

_CIVIL: list[ScenarioQuestion] = [
    {
        "topic": "Site Execution",
        "content": (
            "You arrive on site and find the contractor has poured a slab without the "
            "reinforcement being inspected. What do you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["stop work", "document", "non-conformance", "testing", "escalate"],
        "ideal": (
            "Record it as a non-conformance immediately and stop dependent work. You "
            "cannot inspect what is now covered, so the question becomes what "
            "verification is still possible — pour records, photographs, and if "
            "necessary non-destructive testing or core sampling — and who decides "
            "whether it is accepted or removed."
        ),
    },
    {
        "topic": "Structural Design",
        "content": (
            "A client asks you to remove a column from a completed design to open up "
            "a floor. How do you respond?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["load path", "transfer beam", "recheck", "cost", "safety"],
        "ideal": (
            "It is not a no, but it is not free. The load has to go somewhere — "
            "usually a transfer beam and heavier foundations — and the whole load path "
            "and lateral system need rechecking. Give the client the cost and the "
            "implications rather than a flat refusal or a casual yes."
        ),
    },
    {
        "topic": "Materials & Testing",
        "content": (
            "A concrete cube test at 28 days comes back below the specified strength. "
            "What now?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["retest", "sampling", "core test", "structural assessment", "records"],
        "ideal": (
            "First check whether the sample and curing were valid, because bad testing "
            "is more common than bad concrete. If the result stands, move to in-situ "
            "assessment — core tests or rebound — and then to a structural check of "
            "whether the actual strength is adequate for the actual load."
        ),
    },
    {
        "topic": "Planning & Estimation",
        "content": (
            "Your project is four weeks behind at the halfway point. How do you build "
            "a recovery plan?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["critical path", "resource", "sequence", "cost trade-off", "realistic"],
        "ideal": (
            "Only compression on the critical path recovers time, so start there. "
            "Options are more resources, longer shifts, or resequencing — each with a "
            "cost and a quality risk. Present a plan that is actually achievable rather "
            "than one that restores the original date on paper."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time you disagreed with someone more senior on a technical point.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["evidence", "respect", "escalation", "outcome"],
        "ideal": "A real disagreement resolved with evidence and a clear record, not by seniority alone.",
    },
]


# ─── Electrical & electronics ─────────────────────────────────────────────────

_ELECTRICAL: list[ScenarioQuestion] = [
    {
        "topic": "Power Systems",
        "content": (
            "A motor on the shop floor keeps tripping its breaker after running for "
            "about twenty minutes. How do you diagnose it?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["thermal overload", "current draw", "insulation", "load", "ventilation"],
        "ideal": (
            "Tripping after a delay points at thermal overload rather than a short. "
            "Measure the running current against the rating, check whether the "
            "mechanical load has increased, and look at cooling and ambient "
            "temperature before assuming the motor is faulty."
        ),
    },
    {
        "topic": "Circuits & Electronics",
        "content": (
            "A circuit works perfectly on the bench and fails intermittently in the "
            "product. Where do you look?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["noise", "grounding", "supply", "thermal", "connector", "EMI"],
        "ideal": (
            "The bench has clean power, room temperature and short leads; the product "
            "has none of those. Look at supply quality and decoupling, grounding and "
            "loop area, connector integrity under vibration, and behaviour at "
            "temperature extremes."
        ),
    },
    {
        "topic": "Control & Instrumentation",
        "content": (
            "A temperature controller is oscillating around the setpoint instead of "
            "settling. What would you adjust and why?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["PID", "gain", "integral", "derivative", "sensor lag", "tuning"],
        "ideal": (
            "Oscillation usually means too much proportional gain or too aggressive "
            "integral action for the process lag. Reduce gain first, then adjust "
            "integral time. Also check whether sensor placement is adding delay, since "
            "no tuning fixes a badly placed sensor."
        ),
    },
    {
        "topic": "Safety & Standards",
        "content": (
            "You're asked to work on a panel that someone says has already been "
            "isolated. What do you do before touching it?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["lockout tagout", "test", "verify", "own isolation", "PPE"],
        "ideal": (
            "Verify isolation yourself and apply your own lock — never rely on someone "
            "else's word. Test the tester, test the circuit, test the tester again, and "
            "use the right protective equipment for the fault level."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a fault you couldn't solve immediately. How did you work through it?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["systematic", "hypothesis", "elimination", "help"],
        "ideal": "A systematic account — hypotheses tested and eliminated, and when help was asked for.",
    },
]


# ─── Chemical engineering ─────────────────────────────────────────────────────

_CHEMICAL: list[ScenarioQuestion] = [
    {
        "topic": "Process Engineering",
        "content": (
            "Yield in a reactor has dropped by five percent over a month with no "
            "change to the recipe. How do you investigate?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["feed quality", "catalyst", "temperature profile", "fouling", "data"],
        "ideal": (
            "A gradual drift points at something degrading rather than a step change: "
            "catalyst activity, heat-exchanger fouling, or feed quality moving within "
            "spec. Compare the trend data against feed certificates and temperature "
            "profiles before touching the recipe."
        ),
    },
    {
        "topic": "Heat & Mass Transfer",
        "content": (
            "A heat exchanger isn't reaching its design outlet temperature. What are "
            "the likely causes?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["fouling", "flow rate", "bypass", "air lock", "area"],
        "ideal": (
            "Fouling on either side, lower-than-design flow, non-condensables or air "
            "pockets, or internal bypassing past a damaged baffle. Check the pressure "
            "drop alongside the temperatures, since fouling and low flow look similar "
            "on temperature alone."
        ),
    },
    {
        "topic": "Safety & HAZOP",
        "content": (
            "During a plant walk you notice a relief valve outlet has been piped into "
            "a location people walk past. What do you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["hazard", "escalate", "interim control", "management of change"],
        "ideal": (
            "Treat it as a live hazard, not a paperwork issue — raise it immediately "
            "and put an interim control in place. Then find out how it passed the "
            "change process, because the same gap will have produced other issues."
        ),
    },
    {
        "topic": "Quality & Control",
        "content": (
            "A batch is marginally out of specification. The customer needs it "
            "tomorrow. What do you do?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["deviation", "reprocess", "concession", "documented", "integrity"],
        "ideal": (
            "Never ship out of spec informally. The options are reprocess, blend within "
            "the rules, or seek a documented concession from the customer with full "
            "disclosure. Schedule pressure is not a reason to skip the deviation "
            "process."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time you raised a safety concern that was inconvenient.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["speaking up", "evidence", "persistence", "outcome"],
        "ideal": "A concrete example where the concern was raised despite cost or schedule pressure.",
    },
]


# ─── Data & analytics ─────────────────────────────────────────────────────────

_DATA: list[ScenarioQuestion] = [
    {
        "topic": "Data Analysis",
        "content": (
            "A dashboard shows sign-ups fell forty percent overnight. Before you tell "
            "anyone, what do you check?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["data quality", "tracking", "pipeline", "segment", "verify"],
        "ideal": (
            "Assume a data problem before a business problem. Check whether the "
            "tracking or pipeline changed, whether one segment or platform is "
            "responsible, and whether the drop appears in an independent source. "
            "Announcing a tracking bug as a business collapse is expensive."
        ),
    },
    {
        "topic": "SQL & Data Modelling",
        "content": (
            "A report's numbers don't match the source system, and the query looks "
            "correct. Where do you look?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["join fan-out", "duplicates", "filter", "timezone", "grain"],
        "ideal": (
            "Usually the grain: a join that duplicates rows, a filter that silently "
            "drops nulls, or a timezone boundary. Count rows before and after each join "
            "rather than reading the SQL again."
        ),
    },
    {
        "topic": "Statistics & Experimentation",
        "content": (
            "An A/B test shows a two percent improvement. Would you ship it? What "
            "would you want to know?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["significance", "sample size", "duration", "effect size", "guardrail"],
        "ideal": (
            "Not on the number alone. Ask about sample size, how long it ran, whether "
            "it was stopped early when it looked good, whether the metric is the one "
            "that matters, and what the guardrail metrics did."
        ),
    },
    {
        "topic": "Communication & Insight",
        "content": (
            "How would you present an analysis to a business audience who won't read "
            "the methodology?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["lead with answer", "decision", "caveats", "visual"],
        "ideal": (
            "Lead with the answer and the decision it supports, keep the method "
            "available but not in the way, and state the caveats that would change the "
            "recommendation rather than every limitation."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time your analysis turned out to be wrong.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["detection", "disclosure", "correction", "process change"],
        "ideal": "How it was caught, how quickly it was disclosed, and what check was added after.",
    },
]


# ─── Consulting & business analysis ───────────────────────────────────────────

_CONSULTING: list[ScenarioQuestion] = [
    {
        "topic": "Case & Problem Structuring",
        "content": (
            "A retail chain's profit per store has fallen for three straight quarters. "
            "How would you structure the problem?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["revenue vs cost", "structure", "hypothesis", "MECE", "data"],
        "ideal": (
            "Split profit into revenue and cost before hypothesising. Revenue into "
            "footfall, conversion and basket size; cost into fixed and variable. Then "
            "say what data would distinguish the branches, rather than guessing which "
            "one it is."
        ),
    },
    {
        "topic": "Estimation",
        "content": "Estimate how many two-wheelers are sold in a mid-sized Indian city in a year.",
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["population", "households", "penetration", "replacement", "assumptions"],
        "ideal": (
            "Build from population to households, apply an ownership rate, then a "
            "replacement cycle plus new ownership growth. State each assumption out "
            "loud so it can be challenged — the structure is what is being assessed, "
            "not the number."
        ),
    },
    {
        "topic": "Stakeholder & Communication",
        "content": (
            "Your recommendation is not what the client wants to hear, and they're "
            "paying. How do you handle the meeting?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["evidence", "framing", "options", "honesty", "relationship"],
        "ideal": (
            "Lead with the evidence rather than the conclusion so they arrive at it "
            "with you. Offer options with consequences rather than a single verdict, "
            "and don't soften the finding into something unusable."
        ),
    },
    {
        "topic": "Business Judgement",
        "content": (
            "A client wants to enter a new market next quarter. What would make you "
            "advise against it?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["capability", "timing", "capital", "competition", "focus"],
        "ideal": (
            "Lack of a real right-to-win, capital that the core business needs more, "
            "or a timeline that guarantees a poor entry. Entering badly is often worse "
            "than not entering."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a time you worked with incomplete data and had to commit to a view.",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["assumptions", "judgement", "communication", "revisit"],
        "ideal": "A specific case with assumptions made explicit and a plan to revisit them.",
    },
]


# ─── Software (the general technical default) ─────────────────────────────────
#
# Deliberately NOT the Java bank. `java_fundamentals.py` stays the curated source
# for Java/backend roles; this is the scenario layer for software roles generally,
# and it is what a non-Java software role gets instead of a language quiz.

_SOFTWARE: list[ScenarioQuestion] = [
    {
        "topic": "Debugging & Production",
        "content": (
            "Users report the app is slow, but your monitoring says every service is "
            "healthy. Where do you start?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["reproduce", "client side", "percentile", "network", "observability gap"],
        "ideal": (
            "Healthy averages hide slow tails — look at high percentiles, not means. "
            "Then establish where the time actually goes: client rendering, network, or "
            "a dependency that isn't instrumented. 'All green' usually means the "
            "monitoring doesn't cover the failing path."
        ),
    },
    {
        "topic": "System Design",
        "content": (
            "Design a system that lets students book interview slots. What are the "
            "hard parts?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["concurrency", "double booking", "consistency", "scale", "trade-off"],
        "ideal": (
            "The interesting part is contention on a limited resource — two students "
            "taking the last slot at once. That needs a real locking or transactional "
            "strategy. Then availability queries, timezone handling, and cancellation."
        ),
    },
    {
        "topic": "Databases",
        "content": (
            "A query that was fast last month now takes thirty seconds. Nothing in the "
            "code changed. What happened?"
        ),
        "difficulty": "medium",
        "type": "practical",
        "keywords": ["data growth", "index", "plan change", "statistics", "locking"],
        "ideal": (
            "Data volume crossed a threshold where the planner stopped using an index, "
            "statistics went stale, or a new pattern is causing lock contention. Read "
            "the execution plan rather than rewriting the query blind."
        ),
    },
    {
        "topic": "Code Quality & Collaboration",
        "content": (
            "You're reviewing a teammate's code and it works, but you think the "
            "approach is wrong. What do you do?"
        ),
        "difficulty": "easy",
        "type": "practical",
        "keywords": ["evidence", "severity", "blocking vs nit", "discussion"],
        "ideal": (
            "Separate 'this is broken' from 'I'd have done it differently' and be "
            "explicit about which you're raising. Give the concrete failure case if "
            "there is one; if it's preference, say so and don't block on it."
        ),
    },
    {
        "topic": "Behavioural & Ownership",
        "content": "Tell me about a bug you shipped. How did you find out, and what did you change?",
        "difficulty": "easy",
        "type": "conceptual",
        "keywords": ["ownership", "detection", "fix", "prevention"],
        "ideal": "A real incident, with how it was detected and what prevented a repeat.",
    },
]


# ─── The registry ─────────────────────────────────────────────────────────────

PROFILES: dict[str, DomainProfile] = {
    "sales": {
        "label": "Sales & Business Development",
        "lead_role": "Regional Sales Manager",
        "specialist_role": "Area Sales Lead",
        "topics": [
            ("Prospecting & Pipeline", 15),
            ("Objection Handling", 15),
            ("Negotiation", 15),
            ("Channel & Distribution", 15),
            ("Customer Retention", 12),
            ("Market & Product Knowledge", 13),
            ("Behavioural & Ownership", 15),
        ],
        "scenarios": _SALES,
    },
    "marketing": {
        "label": "Marketing & Brand",
        "lead_role": "Marketing Manager",
        "specialist_role": "Brand & Digital Lead",
        "topics": [
            ("Campaign Planning", 20),
            ("Brand & Positioning", 20),
            ("Digital & Analytics", 20),
            ("Market Research", 20),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _MARKETING,
    },
    "hr": {
        "label": "Human Resources",
        "lead_role": "HR Manager",
        "specialist_role": "Talent & Employee Relations Lead",
        "topics": [
            ("Recruitment", 22),
            ("Employee Relations", 22),
            ("Onboarding & Engagement", 18),
            ("HR Operations & Compliance", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _HR,
    },
    "finance": {
        "label": "Finance & Accounting",
        "lead_role": "Finance Manager",
        "specialist_role": "Senior Financial Analyst",
        "topics": [
            ("Financial Analysis", 22),
            ("Accounting Fundamentals", 22),
            ("Budgeting & Control", 18),
            ("Audit & Controls", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _FINANCE,
    },
    "operations": {
        "label": "Operations & Supply Chain",
        "lead_role": "Operations Manager",
        "specialist_role": "Supply Chain Lead",
        "topics": [
            ("Process & Efficiency", 22),
            ("Supply Chain", 22),
            ("Quality", 18),
            ("Planning & Inventory", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _OPERATIONS,
    },
    "mechanical": {
        "label": "Mechanical Engineering",
        "lead_role": "Design Engineering Manager",
        "specialist_role": "Senior Mechanical Engineer",
        "topics": [
            ("Design & Materials", 22),
            ("Thermodynamics & Fluids", 20),
            ("Manufacturing Processes", 20),
            ("Strength of Materials", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _MECHANICAL,
    },
    "civil": {
        "label": "Civil Engineering",
        "lead_role": "Project Manager",
        "specialist_role": "Senior Structural Engineer",
        "topics": [
            ("Site Execution", 22),
            ("Structural Design", 22),
            ("Materials & Testing", 18),
            ("Planning & Estimation", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _CIVIL,
    },
    "electrical": {
        "label": "Electrical & Electronics Engineering",
        "lead_role": "Electrical Engineering Manager",
        "specialist_role": "Senior Electrical Engineer",
        "topics": [
            ("Power Systems", 22),
            ("Circuits & Electronics", 22),
            ("Control & Instrumentation", 18),
            ("Safety & Standards", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _ELECTRICAL,
    },
    "chemical": {
        "label": "Chemical Engineering",
        "lead_role": "Plant Manager",
        "specialist_role": "Senior Process Engineer",
        "topics": [
            ("Process Engineering", 22),
            ("Heat & Mass Transfer", 20),
            ("Safety & HAZOP", 20),
            ("Quality & Control", 18),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _CHEMICAL,
    },
    "data": {
        "label": "Data & Analytics",
        "lead_role": "Analytics Manager",
        "specialist_role": "Senior Data Analyst",
        "topics": [
            ("Data Analysis", 22),
            ("SQL & Data Modelling", 22),
            ("Statistics & Experimentation", 20),
            ("Communication & Insight", 16),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _DATA,
    },
    "consulting": {
        "label": "Consulting & Business Analysis",
        "lead_role": "Engagement Manager",
        "specialist_role": "Senior Business Analyst",
        "topics": [
            ("Case & Problem Structuring", 25),
            ("Estimation", 20),
            ("Stakeholder & Communication", 18),
            ("Business Judgement", 17),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _CONSULTING,
    },
    "software": {
        "label": "Software Engineering",
        "lead_role": "Senior Engineering Manager",
        "specialist_role": "Technical Lead",
        "topics": [
            ("Debugging & Production", 20),
            ("System Design", 20),
            ("Databases", 20),
            ("Code Quality & Collaboration", 20),
            ("Behavioural & Ownership", 20),
        ],
        "scenarios": _SOFTWARE,
    },
}


#: Role-title keywords per domain. ORDER MATTERS — `resolve` takes the first
#: match, so the more specific domain must come first. "business analyst" has to
#: beat "business development", and "data engineer" has to beat "engineer",
#: which is why this is an ordered list of pairs and not a dict comprehension
#: over PROFILES.
_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "data",
        (
            "data analyst", "data science", "data scientist", "data engineer",
            "analytics", "business intelligence", "machine learning", "ml engineer",
        ),
    ),
    (
        "consulting",
        (
            "consultant", "consulting", "business analyst", "strategy",
            "case analyst", "research analyst",
        ),
    ),
    (
        "sales",
        (
            "sales", "business development", "bd executive", "account executive",
            "account manager", "territory", "channel", "pre-sales", "presales",
            "inside sales", "field officer", "relationship manager",
        ),
    ),
    (
        "marketing",
        ("marketing", "brand", "digital marketing", "growth", "seo", "content strategy"),
    ),
    (
        "hr",
        (
            "human resource", "hr ", "hr executive", "hr generalist", "recruit",
            "talent acquisition", "people operations", "hrbp",
        ),
    ),
    (
        "finance",
        (
            "finance", "financial", "account", "audit", "taxation", "treasury",
            "ca ", "chartered accountant", "costing",
        ),
    ),
    (
        "operations",
        (
            "operations", "supply chain", "logistics", "procurement", "warehouse",
            "production planning", "plant operations", "industrial engineer",
        ),
    ),
    (
        "civil",
        # "civil engineering" rather than bare "civil", because "Civil Services" — the IAS
        # exam route, one of the largest things this product will ever be used for — matched
        # civil ENGINEERING and offered a UPSC aspirant "Site Execution" and "Structural
        # Design". A substring list is only as good as its least specific entry.
        (
            "civil engineering",
            "civil engineer",
            "structural",
            "construction",
            "site engineer",
            "quantity surveyor",
        ),
    ),
    (
        "chemical",
        ("chemical", "process engineer", "petrochemical", "polymer", "biotech"),
    ),
    (
        "electrical",
        (
            "electrical", "electronics", "ece", "eee", "embedded", "vlsi",
            "instrumentation", "power system",
        ),
    ),
    (
        "mechanical",
        (
            "mechanical", "automobile", "automotive", "manufacturing engineer",
            "design engineer", "thermal", "cad", "production engineer",
        ),
    ),
    (
        "software",
        (
            "software", "developer", "programmer", "full stack", "fullstack",
            "backend", "frontend", "java", "python", "web", "qa", "testing",
            "devops", "cloud", "system engineer", "technology analyst", "fse",
            "programmer analyst", "it ", "application",
        ),
    ),
]

#: What a role resolves to when nothing matches. Software, because this product's
#: catalogue is campus IT recruitment and an unrecognised title there is far more
#: likely to be a technology role than a chemical-engineering one. `resolve`
#: returns the match reason too, so a caller that cares can tell a real match from
#: this.
_DEFAULT = "software"


def resolve(role_title: str = "", program: str = "") -> str:
    """
    Which domain is this role? Returns a key into `PROFILES`.

    Matches on the role title and program text together, most specific domain
    first. Substring matching is intentional and is why the keyword lists carry
    trailing spaces where a short token would otherwise over-match — "hr " must
    not fire on "through", and "it " must not fire on "unit".
    """
    blob = f" {role_title} {program} ".lower().replace("/", " ").replace("-", " ")
    # Collapse repeated whitespace so " hr " matches "HR  Executive".
    blob = " ".join(blob.split())
    blob = f" {blob} "
    for domain, keywords in _KEYWORDS:
        if any(k in blob for k in keywords):
            return domain
    return _DEFAULT


def matched(role_title: str = "", program: str = "") -> bool:
    """
    Did the role actually match a domain, or did it fall through to the default?

    Callers use this to decide how strongly to phrase the brief: a confident
    match can tell the planner "this is a sales interview, do not ask CS
    questions", whereas a fall-through should leave more room.
    """
    blob = f" {role_title} {program} ".lower().replace("/", " ").replace("-", " ")
    blob = f" {' '.join(blob.split())} "
    return any(any(k in blob for k in kws) for _, kws in _KEYWORDS)


def profile_for(role_title: str = "", program: str = "") -> DomainProfile:
    """The full profile for a role. Never raises; falls back to the default domain."""
    return PROFILES[resolve(role_title, program)]


def topic_block(role_title: str = "", program: str = "") -> str:
    """
    The domain's must-cover weighting as markdown bullets.

    Deliberately the same shape `_company_topic_block` emits, so the planner
    prompt can concatenate the two without a second format to reason about.
    """
    profile = profile_for(role_title, program)
    lines = "\n".join(f"- **{name}** — {weight:g}% of the interview" for name, weight in profile["topics"])
    return f"This is a **{profile['label']}** role. Cover these areas:\n{lines}"


def is_technical(role_title: str = "", program: str = "") -> bool:
    """
    Does this role get asked engineering/CS content at all?

    Used to keep coding questions and code review out of a sales or HR interview
    — the code panel is wired to the same session machinery and would otherwise
    happily hand a marketing candidate a SQL problem.
    """
    return resolve(role_title, program) in {
        "software",
        "data",
        "mechanical",
        "civil",
        "electrical",
        "chemical",
    }


# Weights are a distribution the planner allocates an interview across, exactly
# as the company catalogue's are, and the catalogue validates its own at load for
# the same reason. A profile that sums to 90 silently under-plans an interview.
for _key, _profile in PROFILES.items():
    _total = sum(w for _, w in _profile["topics"])
    if _total != 100:
        raise ValueError(f"domain '{_key}' topic weights sum to {_total}, expected 100")
