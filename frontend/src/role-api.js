import { request } from "./api.js";
const json = (method, body) => ({ method, body: JSON.stringify(body) });
const id = (value) => encodeURIComponent(value);
export const roleApi = {
  previewMaterial: (file, profile) => {
    const body = new FormData();
    body.append("file", file);
    return request(profile ? `/member-full/profiles/${id(profile)}/materials/preview` : "/member/self/materials/preview", { method: "POST", body });
  },
  archiveMaterial: (profile, { file, ...fields }) => {
    const body = new FormData();
    body.append("file", file);
    for (const [key, value] of Object.entries(fields))
      if (value != null) body.append(key, value);
    return request(`/member-full/profiles/${id(profile)}/materials/scan`, { method: "POST", body });
  },
  archive: () => request("/member/self/archive"),
  ownMaterials: (page = 1) =>
    request(`/member/self/materials?page=${page}&page_size=20`),
  submitMaterial: ({ file, title, category, description, submission_key }) => {
    const body = new FormData();
    for (const [key, value] of Object.entries({
      file,
      title,
      category,
      description,
      submission_key,
    }))
      body.append(key, value);
    return request("/member/self/materials", { method: "POST", body });
  },
  ownFile: (materialId) =>
    request(`/member/self/materials/${id(materialId)}/file`, {
      download: true,
    }),
  developmentFile: (material) => request(`/member-full/materials/${id(material)}/file`, { download: true }),
  receivedMaterials: (profile, page = 1) =>
    request(
      `/member/roster/${id(profile)}/materials?page=${page}&page_size=20`,
    ),
  receivedFile: (profile, material) =>
    request(`/member/roster/${id(profile)}/materials/${id(material)}/file`, {
      download: true,
    }),
  profile: (profile) => request(`/member-full/profiles/${id(profile)}`),
  linkAccount: (profile, username) =>
    request(`/member/roster/${id(profile)}/account`, json("PUT", { username })),
  addMaterial: (profile, body) =>
    request(
      `/member-full/profiles/${id(profile)}/materials`,
      json("POST", body),
    ),
  reviewMaterial: (material, body) =>
    request(
      `/member-full/materials/${id(material)}/review`,
      json("POST", body),
    ),
  transition: (profile, body) =>
    request(
      `/member-full/profiles/${id(profile)}/transition`,
      json("POST", body),
    ),
  cultivation: (profile, body) =>
    request(
      `/member-full/profiles/${id(profile)}/cultivation`,
      json("POST", body),
    ),
  checkArchive: (profile) =>
    request(
      "/member-full/archive-check",
      json("POST", { profile_id: profile, materials_note: {} }),
    ),
  reminders: () =>
    request("/member-full/reminders?status=open&page=1&page_size=100"),
  resolveReminder: (reminder, note) =>
    request(
      `/member-full/reminders/${id(reminder)}/resolve`,
      json("POST", { status: "closed", note }),
    ),
  meetingAction: (meeting, action, revision, reason, decision) =>
    request(
      `/meeting/records/${id(meeting)}/${action}`,
      json("POST", {
        expected_revision: revision,
        reason,
        ...(decision ? { decision } : {}),
      }),
    ),
  reviews: () => request("/admin/reviews?page=1&status=pending"),
  reviewDetail: (review) => request(`/admin/reviews/${id(review)}`),
  decideReview: (review, body) =>
    request(`/admin/reviews/${id(review)}/decision`, json("POST", body)),
  users: () => request("/admin/users"),
  accountOrgs: () => request("/admin/org-units"),
  memberCandidates: () => request("/admin/member-candidates"),
  createAccount: (body) => request("/admin/users", json("POST", body)),
  tenants: () => request("/admin/tenants"),
  createTenant: (body) => request("/admin/tenants", json("POST", body)),
  audit: (params = {}) =>
    request("/admin/audit-logs?" + new URLSearchParams(params)),
  exportAudit: (params = {}) =>
    request("/admin/audit-logs/export?" + new URLSearchParams(params), {
      download: true,
    }),
  operations: () => request("/admin/operations"),
};
