"""Bounded iterative inheritance proof; unknown ancestors cannot be cancelled."""

from ._models import TableStyleDefinition, TableStyleIssue, budget


def resolve(definitions, all_styles, limits, inherited_issues):
    results, depths = {}, {}
    issue_count, chain_links = inherited_issues, 0
    budget(issue_count, limits.max_issues)

    def finish(key, depth, code=None, parent=None):
        nonlocal issue_count, chain_links
        budget(depth, limits.max_chain_depth)
        own = definitions[key]
        record = own.record
        chain, issues = (), ()
        if code:
            issue_count += 1
            budget(issue_count, limits.max_issues)
            issues = (TableStyleIssue(code, record.anchor, key),)
        else:
            chain_links += depth
            budget(chain_links, limits.max_chain_links)
            chain = (record.anchor,) + (parent.chain if parent else ())
        results[key] = TableStyleDefinition(
            key,
            record.anchor,
            own.parent,
            record.is_default,
            "blocked" if code else "neutral",
            own.regions,
            own.metadata,
            chain,
            issues,
        )
        depths[key] = depth

    for key, own in definitions.items():
        if own.code:
            finish(key, 1, own.code)
    for start in definitions:
        if start in results:
            continue
        path, positions, key = [], {}, start
        while key not in results:
            if key in positions:
                position = positions[key]
                cycle = path[position:]
                for member in cycle:
                    finish(member, len(cycle), "style_cycle")
                path = path[:position]
                break
            positions[key] = len(path)
            path.append(key)
            budget(len(path), limits.max_chain_depth)
            parent = definitions[key].parent
            if parent is None:
                finish(key, 1)
                path.pop()
                break
            if parent not in all_styles:
                finish(key, 1, "missing_base_style")
                path.pop()
                break
            if all_styles[parent].style_type != "table":
                finish(key, 1, "base_style_type_mismatch")
                path.pop()
                break
            key = parent
        for key in reversed(path):
            parent = results[definitions[key].parent]
            code = None
            if parent.status != "neutral":
                code = (
                    "style_cycle"
                    if parent.issues[0].code == "style_cycle"
                    else "unresolved_base_style"
                )
            finish(key, depths[definitions[key].parent] + 1, code, parent)
    return tuple(results[key] for key in sorted(results))
