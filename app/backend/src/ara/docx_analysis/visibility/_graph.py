"""Linear functional-graph resolution with bounded iterative walks."""

from ._models import ResolvedStyle, StyleIssue, VisibilityProperties, budget


def resolve(definitions, limits):
    results, depths = {}, {}
    issue_count = 0

    def finish(key, depth, code=None, properties=None):
        nonlocal issue_count
        budget(depth, limits.max_chain_depth)
        d = definitions[key]
        if code:
            issue_count += 1
            budget(issue_count, limits.max_issues)
        results[key] = ResolvedStyle(
            key,
            d.kind,
            d.anchor,
            d.parent,
            d.default,
            "opaque" if code == "opaque_style_type" else "blocked" if code else "resolved",
            None if code else properties or d.properties,
            (StyleIssue(code, d.anchor, key),) if code else (),
        )
        depths[key] = depth

    for key, d in definitions.items():
        if d.code:
            finish(key, 1, d.code)

    for start in definitions:
        if start in results:
            continue
        path, positions = [], {}
        key = start
        while key not in results:
            if key in positions:
                index = positions[key]
                cycle = path[index:]
                for member in cycle:
                    finish(member, len(cycle), "style_cycle")
                path = path[:index]
                break
            positions[key] = len(path)
            path.append(key)
            budget(len(path), limits.max_chain_depth)
            d = definitions[key]
            if d.parent is None:
                finish(key, 1)
                path.pop()
                break
            if d.parent not in definitions:
                finish(key, 1, "missing_base_style")
                path.pop()
                break
            if definitions[d.parent].kind != d.kind:
                finish(key, 1, "base_style_type_mismatch")
                path.pop()
                break
            key = d.parent
        for key in reversed(path):
            d = definitions[key]
            parent = results[d.parent]
            depth = depths[d.parent] + 1
            if parent.status != "resolved":
                code = (
                    "style_cycle"
                    if parent.issues[0].code == "style_cycle"
                    else "unresolved_base_style"
                )
                finish(key, depth, code)
            else:
                values = []
                for name in ("vanish", "spec_vanish", "web_hidden"):
                    own = getattr(d.properties, name)
                    values.append(
                        own if own.value is not None else getattr(parent.properties, name)
                    )
                finish(key, depth, properties=VisibilityProperties(*values))
    return tuple(results[key] for key in sorted(results))
