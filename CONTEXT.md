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

**File Comparison**:
A comparison between immutable Revisions that shows changed paths and Git-style line patches. Web uses complete historical text in CodeMirror MergeView to align unchanged content. No semantic, intent, risk, or behavior analysis participates in the current product.
