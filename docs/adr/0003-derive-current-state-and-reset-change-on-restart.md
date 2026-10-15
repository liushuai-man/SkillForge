# Derive current state and reset the active Change on restart

Current Revision is derived from the highest committed workspace sequence, Current Op from the latest committed operation, and the active Change remains process-local. A service restart starts a new Change instead of reconstructing the previous editing interval. This avoids a second mutable source of truth and schema expansion while making the restart boundary explicit and reproducible.
