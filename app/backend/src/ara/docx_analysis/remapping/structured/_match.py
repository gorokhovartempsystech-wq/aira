"""Unique noncrossing groups, complete note-parent proof, then literal positions."""

from collections import Counter, defaultdict

from ._groups import context


def neighbors(groups):
    stories, result = defaultdict(list), {}
    for g in groups:
        stories[g.story].append(g)
    for rows in stories.values():
        for i, g in enumerate(rows):
            result[g.identity] = (
                ("previous", rows[i - 1].neighbor) if i else ("start",),
                ("next", rows[i + 1].neighbor) if i + 1 < len(rows) else ("end",),
            )
    return result


def candidates(left, right):
    a_count = Counter((g.identity[0], g.texts) for g in left)
    b_count = Counter((g.identity[0], g.texts) for g in right)
    index = {
        g.key: j
        for j, g in enumerate(right)
        if any(t.strip() for t in g.texts) and b_count[g.identity[0], g.texts] == 1
    }
    pairs = [
        (i, index[g.key])
        for i, g in enumerate(left)
        if g.fragments and a_count[g.identity[0], g.texts] == 1 and g.key in index
    ]
    suffix = [len(right)] * (len(pairs) + 1)
    for k in range(len(pairs) - 1, -1, -1):
        suffix[k] = min(suffix[k + 1], pairs[k][1])
    a_neighbors, b_neighbors = neighbors(left), neighbors(right)
    output, prefix = [], -1
    for k, (i, j) in enumerate(pairs):
        monotone = prefix < j < suffix[k + 1]
        prefix = max(prefix, j)
        if monotone and a_neighbors[left[i].identity] == b_neighbors[right[j].identity]:
            output.append((left[i], right[j]))
    return output


def note_dependence(left, right, pairs):
    parents = {a.identity: b.identity for a, b in pairs if a.kind == b.kind == "body"}
    verdicts = {}
    for target, links in left.incoming.items():
        mapped = set()
        complete = True
        for parent, path, kind in links:
            if parent not in parents:
                complete = False
            else:
                mapped.add((parents[parent], path, kind))
        verdicts[target] = complete and bool(mapped) and mapped == right.incoming.get(target, set())
    return verdicts


def fragment_matches(old_source, old_snapshot, new_source, new_snapshot):
    left, right = context(old_source, old_snapshot), context(new_source, new_snapshot)
    if (
        not left.original.transferable
        or not right.original.transferable
        or left.original.seal != right.original.seal
    ):
        return {}
    pairs = candidates(left.groups, right.groups)
    dependence = note_dependence(left, right, pairs)
    result = {}
    for a, b in pairs:
        if a.kind in ("footnote", "endnote") and not dependence.get(a.story, False):
            continue
        result.update(zip(a.fragments, b.fragments, strict=True))
    return result
