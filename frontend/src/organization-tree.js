// The search accepts either a display name or an exact organization id. Callers
// sometimes navigate with an id (for example from a scoped business record), so
// treating it as a name would silently filter the whole list away.
export function organizationMatches(org, query = "") {
  const term = String(query || "").trim();
  if (!term) return true;
  return org.name.includes(term) || String(org.id) === term;
}

export function organizationMemberCount(org, members = [], allowLocalFallback = true) {
  if (Number.isFinite(org?.member_count)) return org.member_count;
  if (!allowLocalFallback || !org?.id || !Array.isArray(members)) return null;
  return members.filter((member) => (member.orgId || member.org_unit_id) === org.id)
    .length;
}

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
    if (organizationMatches(node, term)) return node;
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
