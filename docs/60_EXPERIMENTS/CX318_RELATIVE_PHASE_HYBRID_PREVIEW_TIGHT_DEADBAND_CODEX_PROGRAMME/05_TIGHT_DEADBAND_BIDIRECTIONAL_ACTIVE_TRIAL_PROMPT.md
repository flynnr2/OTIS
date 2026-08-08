# Stage 5 Prompt: Tight-Deadband Bidirectional Active Trial

Execute Stage 5 only after Stage 4 passes and the active frequency path plus all
CX317 safety gates revalidate. This stage grants bounded frequency-only
authority. Phase and hybrid preview remain non-actionable.

## Goal

Falsify or validate the tighter hysteretic frequency band quickly from both
sides of the operating point while collecting simultaneous relative-phase and
hybrid-preview evidence.

## Preflight and freeze

Before any write:

- freeze a new versioned tight-deadband policy implementing the master's integer
  count semantics and `REQUALIFY_OUTSIDE` initial state;
- retain the original V2 and symmetric tight policies as zero-authority shadows;
- replay Campaign A, Campaign B, Stage 7 and all active fault fixtures;
- prove unchanged transaction, abort, range, cadence, budget, model,
  qualification and fail-static gates;
- prove phase/hybrid data cannot influence the active delta or eligibility;
- bind exact run/build/profile/estimator/model/policy/response hashes;
- query or otherwise reconfirm the physical last-applied code without writing;
- verify independent host and bounded device abort paths.

## Finite legs

Run two new, separately sealed legs:

| Leg | Exact setup stimulus | Required learning | Maximum qualified duration |
|---|---:|---|---:|
| A: below operating point | `0xA808` | positive automatic correction direction and tight entry | 4 h after qualification |
| B: above operating point | `0xA848` | negative automatic correction direction and tight entry | 4 h after qualification |

Each leg has:

- one exact setup transaction opening a new DAC epoch;
- qualification deadline of 90 min;
- at most 4 automatic corrections;
- at most 21 codes per automatic correction;
- at most 84 codes of total absolute automatic movement;
- no automatic correction faster than 1800 s;
- 900 s exclusion plus 600 s fresh support after every write;
- one request outstanding;
- no retry, restoration or reboot recovery;
- hard range `0xA800..0xAB00`;
- continuous zero-authority hybrid preview and shadow deadband comparison.

The setup transaction is not evidence of controller direction. Each passing leg
must contain at least one complete automatic request/accepted/applied/response
transaction in the expected direction.

## Tight state semantics

- Begin and rearm in `REQUALIFY_OUTSIDE`.
- Enter tight residence only after two consecutive fresh 600 s estimates with
  absolute accumulated edge error at most two counts.
- While inside, three counts retains the inside state.
- Release only after two consecutive fresh estimates with at least four counts
  absolute error.
- While outside, three counts does not qualify tight entry and remains eligible
  for the frozen controller policy.
- Reset pending counters on opposite evidence, invalidity, DAC epoch or session
  transition as declared in the frozen contract.

## Success and failure

A leg passes when:

- the required automatic direction is observed and healthy;
- the controller reaches two-estimate tight entry;
- no alternation/dither, clamp, budget or transaction fault occurs;
- terminal state is disarmed/evidence-clear;
- host replay exactly explains active and shadow decisions.

If the finite endpoint arrives without tight entry, terminate the leg as the
predeclared bounded non-pass outcome and preserve it as useful diagnostic
evidence. The overall Stage 5 gate requires both legs to pass. Do not extend a
leg or change a threshold to manufacture entry. A wrong-sign response, repeated
alternation, unexplained growth, authority contamination or failed transaction
stops fail-static and prevents the next leg.

## Required analysis

Compare V2, tight hysteretic and symmetric tight policies for:

- time/corrections/path to entry;
- median and RMS frequency error;
- boundary churn and alternation;
- response gain and settling by direction;
- relative-phase movement before and after tight entry;
- hybrid-preview requests and sensitivity to actual DAC epochs;
- agreement with Stage 7 counterfactual predictions.

## Deliverables and exit gate

Deliver both sealed legs, exact transaction capsules, replay, tight/shadow
comparison, phase/preview context, full verification and Stage 5 report.

Pass only when both directions are demonstrated within limits and the tighter
policy remains bounded. Passing Stage 5 authorizes only its use in the Stage 6
frequency-only run; it does not authorize hybrid actuation.
