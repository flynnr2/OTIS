# OTIS Coding Conventions

This document defines the initial coding conventions for OTIS firmware, host software,
telemetry schemas, and documentation.

The conventions are intended to support:

- readability;
- deterministic reasoning;
- maintainability;
- explicit semantics;
- low-friction review;
- long-term consistency.

These conventions may evolve, but changes should be deliberate and documented.

---

# General Principles

OTIS code should be:

- explicit rather than clever;
- engineered enough, but not over-engineered;
- easy to inspect during debugging;
- clear about clock domains, timing paths, and provenance;
- conservative around timing-critical code.

Avoid:

- hidden side effects;
- ambiguous naming;
- speculative abstraction;
- duplicated protocol/schema definitions;
- mixing conceptual and implementation names carelessly.

---

# C / C++ Firmware Style

Firmware conventions apply to RP2040/RP2350, embedded C/C++, and future low-level
timing-fabric support code unless a platform-specific reason requires otherwise.

## Naming

| Item                 | Convention          | Example                         |
|----------------------|---------------------|---------------------------------|
| variables            | `snake_case`        | `event_seq`                     |
| functions            | `snake_case()`      | `capture_record_is_valid()`     |
| structs/classes      | `PascalCase`        | `CaptureRecord`                 |
| enums                | `PascalCase`        | `DisciplineState`               |
| enum values          | `UPPER_SNAKE_CASE`  | `DISCIPLINE_STATE_LOCKED`       |
| macros               | `UPPER_SNAKE_CASE`  | `OTIS_ENABLE_TELEMETRY`         |
| compile-time flags   | `UPPER_SNAKE_CASE`  | `OTIS_ENABLE_PROFILING`         |
| file-scope constants | `kPascalCase`       | `kPpsTimeoutMs`                 |

## Braces

Use same-line opening braces and cuddled `else`.

```cpp
if (is_locked) {
    update_discipline_loop();
} else {
    enter_acquire_state();
}
```

Always use braces, even for single-line bodies.

Preferred:

```cpp
if (record_valid) {
    emit_capture_record(record);
}
```

Avoid:

```cpp
if (record_valid)
    emit_capture_record(record);
```

## Function Structure

Functions should generally be:

- small enough to inspect;
- named for what they do;
- explicit about state transitions;
- conservative in timing-critical paths.

Timing-critical functions should avoid:

- allocation;
- logging;
- blocking calls;
- hidden global mutation;
- complex branching unless justified.

## Comments

Comments should explain:

- timing assumptions;
- hardware assumptions;
- clock-domain assumptions;
- non-obvious ordering constraints;
- provenance implications.

Comments should not simply restate the code.

## Timing-Critical Code

Timing-critical paths should clearly distinguish:

- hardware capture time;
- firmware service time;
- telemetry emission time.

The CPU should never be treated as the source of timing truth.

---

# Python Host / Analysis Style

Python code should generally follow standard modern Python conventions.

## Naming

| Item       | Convention      | Example                    |
|------------|-----------------|----------------------------|
| variables  | `snake_case`    | `capture_domain`           |
| functions  | `snake_case()`  | `load_capture_records()`   |
| classes    | `PascalCase`    | `CaptureDataset`           |
| constants  | `UPPER_SNAKE`   | `DEFAULT_SCHEMA_VERSION`   |
| modules    | `snake_case.py` | `telemetry_parser.py`      |

## Formatting

Preferred tools:

- Black for formatting;
- Ruff for linting;
- type hints where useful;
- pytest for tests.

Python tools should preserve replayability and make preprocessing assumptions explicit.

---

# Telemetry Field Naming

Telemetry fields should use `snake_case`.

Examples:

```text
event_seq
ref_ticks
capture_domain
discipline_state
dac_code
schema_version
```

Telemetry names should be:

- stable;
- explicit;
- machine-readable;
- easy to inspect in CSV/JSONL form.

Avoid:

- abbreviations that are not domain-standard;
- overloaded field names;
- mixed naming styles;
- fields whose clock domain is ambiguous.

---

# Schema and Protocol Naming

Schema names and protocol identifiers should be versioned explicitly.

Examples:

```text
otis_capture_v1
otis_discipline_v1
otis_environment_v1
```

Protocol/schema changes should document:

- compatibility impact;
- field additions/removals;
- semantic changes;
- replay implications.

---

# Markdown and Documentation Style

Documentation should use clear, serious, readable scientific-engineering prose.

## Filenames

For major conceptual documents, use the existing uppercase underscore style:

```text
OTIS_VISION.md
TIMESTAMPING_MODEL.md
MVP_HARDWARE_REFERENCE.md
```

For generated artifacts or implementation-specific files, `snake_case` or `kebab-case`
may be appropriate if tooling conventions require it.

## Tables

Markdown tables should be aligned for readability in source form.

Preferred:

```markdown
| Item                 | Convention         | Example                     |
|----------------------|--------------------|-----------------------------|
| variables            | `snake_case`       | `event_seq`                 |
| functions            | `snake_case()`     | `capture_record_is_valid()` |
```

Avoid ragged tables when practical.

---

# Repository Naming

Prefer descriptive names that preserve conceptual clarity.

General guidance:

| Item                 | Convention                         |
|----------------------|------------------------------------|
| top-level docs       | uppercase underscore markdown      |
| source directories   | lowercase descriptive names        |
| Python modules       | `snake_case.py`                    |
| firmware modules     | descriptive C/C++ names            |
| telemetry fields     | `snake_case`                       |

---

# Explicitness Around Units

Names should include units where ambiguity is likely.

Preferred:

```text
pps_timeout_ms
phase_error_ticks
ref_frequency_hz
dac_update_interval_s
```

Avoid:

```text
timeout
error
frequency
interval
```

unless context makes the unit unambiguous.

---

# Review Guidance

Reviewers should flag:

- duplicated logic;
- unclear clock-domain semantics;
- implicit timing assumptions;
- hidden state changes;
- telemetry fields without provenance;
- cleverness that reduces auditability;
- abstractions that obscure instrumentation behavior.

Style exists to support engineering clarity, not to create bureaucracy.
