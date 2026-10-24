// Parent links are meaningful only when both organizations are authorized.
export function organizationForest(organizations, query = "") {
  const nodes = new Map(
    organizations.map((org) => [org.id, { ...org, children: [] }]),
  );
  const roots = [];
  for (const node of nodes.values()) {
    const parent = nodes.get(node.parent_id);
    const visited = new Set([node.id]);
    let ancestor = parent;
    let cyclic = false;
    while (ancestor) {
      if (visited.has(ancestor.id)) {
        cyclic = true;
        break;
      }
      visited.add(ancestor.id);
      ancestor = nodes.get(ancestor.parent_id);
    }
    if (parent && !cyclic) parent.children.push(node);
    else roots.push(node);
  }

  const term = query.trim();
  if (!term) return roots;
  function matching(node) {
    // Keep a matching parent's full subtree and a matching child's ancestors.
    if (node.name.includes(term)) return node;
    const children = node.children.map(matching).filter(Boolean);
    return children.length ? { ...node, children } : null;
  }
  return roots.map(matching).filter(Boolean);
}

export function organizationType(org) {
  return {
    school: "学校党委",
    department: "二级党组织",
    branch: "党支部",
  }[org.org_type] || org.type || "未登记";
}
