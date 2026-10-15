# SkillForge Version Manager

SkillForge Version Manager records the evolution of one managed Skill and explains the difference between immutable revisions without requiring manual version operations.

## Language

**Skill**:
The managed collection of instruction, configuration, example, and resource files whose evolution is recorded as one unit.

**Snapshot**:
The act of capturing a stable Skill state after file changes settle. A successful Snapshot produces a Revision; an unchanged state produces no new Revision.

**Revision**:
An immutable, addressable record of one successfully captured Skill state.
_Avoid_: Version, Working copy

**Working**:
The latest committed Revision used as the head of the default comparison. Disk edits still waiting for a Snapshot are pending changes, not Working.
_Avoid_: Live files, working tree

**Pending Changes**:
Disk content observed after Working but not yet committed as a Revision. Pending Changes are never silently treated as part of Working.

**Change**:
A process-local grouping of consecutive Revisions produced during one editing interval. A service restart always begins a new Change rather than reviving the previous group.
_Avoid_: Branch, persistent session

**Anchor**:
A user-created, named marker for a Revision. Successfully creating an Anchor also selects that Revision as the current Baseline.
_Avoid_: Automatic baseline, branch

**Baseline**:
The currently selected Anchor Revision used as the base of the default comparison. Before the first Anchor, the comparison uses the empty pre-history state.
_Avoid_: Latest Revision, automatically generated anchor

**Default Comparison**:
The comparison from Baseline to Working. It freezes both inputs as immutable Revisions before analysis begins.

**Semantic Unit**:
One evidence-backed piece of Skill meaning with exactly one primary kind. A Semantic Unit is counted once even when it has several effects.

**Cluster**:
A deterministic grouping that presents related Semantic Units as one user-facing intent. Each Semantic Unit belongs to at most one Cluster.

**Needs Review**:
A report item whose evidence is insufficient for a definite semantic conclusion. It is shown to the user instead of being guessed or hidden. In the MVP it is an uncertainty marker, not an approval task or a user-managed resolved state.
_Avoid_: Approval, Todo, Resolved Review

**Risk**:
An advisory, evidence-backed severity attached during semantic report generation. Risk never blocks saving, anchoring, comparison, restoration, or undo.
_Avoid_: Approval gate, confidence score

