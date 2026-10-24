# Count each semantic change once

> 已退出当前产品（2026-10-24）：仅保留为旧语义实现的历史决策。当前只做文件/行级比较，不再用本ADR验收产品。

Each Semantic Unit has one primary kind and belongs to at most one Cluster. Exact content relocated between source spans is a `move`; content and location changing together is a `modify` whose before and after spans may use different paths; uncertain correspondence remains separate add/delete evidence in `needs_review`. Secondary effects such as security or compatibility are risk labels rather than duplicate units. This keeps accuracy, risk, clustering, and report totals deterministic and prevents one edit from being counted several times.
