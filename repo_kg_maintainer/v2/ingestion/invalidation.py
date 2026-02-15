from __future__ import annotations

from collections import defaultdict, deque
from typing import Iterable, Set

from v2.models import GraphSnapshot


class DependencyInvalidationPlanner:
    def compute_impacted_files(self, snapshot: GraphSnapshot, changed_files: Iterable[str]) -> set[str]:
        changed = set(changed_files)
        if not changed:
            return set()

        file_by_node = {node.id: node.file_path for node in snapshot.nodes}
        reverse_dependencies = defaultdict(set)

        for edge in snapshot.edges:
            source_file = file_by_node.get(edge.source_id)
            target_file = file_by_node.get(edge.target_id)
            if not source_file or not target_file:
                continue
            if source_file == target_file:
                continue
            reverse_dependencies[target_file].add(source_file)

        impacted = set(changed)
        queue = deque(changed)
        while queue:
            current = queue.popleft()
            for dependent in sorted(reverse_dependencies.get(current, set())):
                if dependent in impacted:
                    continue
                impacted.add(dependent)
                queue.append(dependent)

        has_reverse_edges = any(reverse_dependencies.get(path) for path in changed)
        if not has_reverse_edges:
            all_files = {node.file_path for node in snapshot.nodes}
            impacted |= all_files

        return impacted
