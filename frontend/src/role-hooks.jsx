import { useEffect, useState } from "react";
import { useApp } from "./app-context";
import { useStore } from "./store";
import { backend, IS_LIVE } from "./api";
import { roleApi } from "./role-api";
import { normalizeMember } from "./contracts";
import {
  hasPermission,
  scopedMembers,
  scopedMeetings,
  scopedOrganizations,
  isSelfService,
} from "./roles";

export function useManagedWorkspace() {
  const { session } = useApp();
  const { data, update } = useStore();
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const [orgs, setOrgs] = useState([]);
  const [meetings, setMeetings] = useState([]);
  useEffect(() => {
    if (!IS_LIVE || !hasPermission(session, "member.query")) return;
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([
      backend.members(),
      backend.organizations(),
      hasPermission(session, "meeting.query")
        ? backend.meetings()
        : { items: [] },
    ])
      .then(([members, organizations, records]) => {
        if (active) {
          update("members", (members.items || []).map(normalizeMember));
          setOrgs(organizations);
          setMeetings(
            (records.items || []).map((m) => ({
              ...m,
              date: m.scheduled_on,
              status: m.archived_at
                ? "已归档"
                : m.review_status === "pending"
                  ? "待审核"
                  : m.review_status === "approved"
                    ? "已完成"
                    : m.review_status === "rejected"
                      ? "已退回"
                      : "待召开",
              orgId: m.org_unit_id,
            })),
          );
        }
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [session.user.id, tick, update]);
  return {
    members: scopedMembers(data, session, IS_LIVE),
    meetings: IS_LIVE ? meetings : scopedMeetings(data, session),
    orgs: IS_LIVE ? orgs : scopedOrganizations(session),
    error,
    loading,
    reload: () => setTick((t) => t + 1),
  };
}
export function useOwnWorkspace() {
  const { session } = useApp();
  const { data, update } = useStore();
  const [profile, setProfile] = useState(null);
  const [materials, setMaterials] = useState([]);
  const [maxSize, setMaxSize] = useState(20 * 1024 * 1024);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!IS_LIVE || !isSelfService(session.user)) return;
    let active = true;
    setLoading(true);
    setError(null);
    Promise.all([roleApi.archive(), roleApi.ownMaterials(page)])
      .then(([archive, records]) => {
        if (!active) return;
        setProfile(archive.profile ? normalizeMember(archive.profile) : null);
        setMaxSize(archive.max_upload_size || 20 * 1024 * 1024);
        setMaterials(records.items || []);
        setTotal(records.total || 0);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [session.user.id, page, tick]);
  const own = IS_LIVE
    ? profile
    : data.members.find((m) => m.id === session.user.profile_id) || null;
  const items = IS_LIVE
    ? materials
    : data.personalMaterials.filter((m) => m.owner_id === session.user.id);
  return {
    profile: own,
    materials: items,
    total: IS_LIVE ? total : items.length,
    maxSize: IS_LIVE
      ? maxSize
      : (data.platform?.config?.uploads?.max_file_mb || 20) * 1024 * 1024,
    allowedExtensions: IS_LIVE
      ? undefined
      : data.platform?.config?.uploads?.allowed_extensions,
    error,
    loading,
    page,
    setPage,
    reload: () => setTick((t) => t + 1),
    append: (material) =>
      IS_LIVE
        ? setTick((t) => t + 1)
        : update("personalMaterials", (prev) => [material, ...prev]),
  };
}
