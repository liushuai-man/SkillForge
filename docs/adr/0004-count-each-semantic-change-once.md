# Count each semantic change once

Each Semantic Unit has one primary kind and belongs to at most one Cluster. Exact content relocated between source spans is a `move`; content and location changing together is a `modify` whose before and after spans may use different paths; uncertain correspondence remains separate add/delete evidence in `needs_review`. Secondary effects such as security or compatibility are risk labels rather than duplicate units. This keeps accuracy, risk, clustering, and report totals deterministic and prevents one edit from being counted several times.
