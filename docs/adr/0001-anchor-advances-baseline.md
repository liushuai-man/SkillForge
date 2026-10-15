# Creating an anchor advances the baseline

When a user successfully creates any named anchor (`stable`, `tested`, or a custom name), SkillForge atomically selects the same Revision as the default Baseline while preserving the named anchor. The selected Baseline is stored as the reserved `baseline` reference; before any anchor exists, `base.rev=null` represents the empty pre-history state. Existing workspaces are not migrated by guessing from `stable`, `tested`, or the newest reference: they keep the empty Baseline until the user next creates an anchor. This keeps the default comparison zero-configuration without conflating the moving Working Revision with an explicitly approved comparison point or silently changing an old workspace's report meaning.


