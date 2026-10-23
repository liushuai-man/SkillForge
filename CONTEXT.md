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
A user-created, named marker for a Revision. Successfully creating an Anchor also records that Revision as the current Baseline; it does not change the default comparison.
_Avoid_: Automatic baseline, branch

**Baseline**:
The most recently selected Anchor Revision, available for explicit comparison. It is independent of the automatic comparison against the previous Revision.
_Avoid_: Latest Revision, automatically generated anchor

**Default Comparison**:
The comparison from the parent of Working to Working. The first Revision is compared with empty content. Both inputs are frozen as immutable Revisions before analysis begins.

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

