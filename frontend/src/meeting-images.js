// 三会一课现场图片的浏览器端边界校验；服务端仍会按真实图片格式复核。
export const MEETING_IMAGE_ACCEPT = "image/jpeg,image/png,image/webp";
export const MEETING_IMAGE_LIMIT = 9;
export const MEETING_IMAGE_MAX_BYTES = 10 * 1024 * 1024;
const TYPES = new Set(["image/jpeg", "image/jpg", "image/png", "image/webp"]);
const EXTENSIONS = new Set(["jpg", "jpeg", "png", "webp"]);

function extension(name) {
  const value = String(name || "").toLowerCase();
  const index = value.lastIndexOf(".");
  return index >= 0 ? value.slice(index + 1) : "";
}

export function meetingImageError(file) {
  if (!file) return "请选择现场图片。";
  if (!TYPES.has(String(file.type || "").toLowerCase()) && !EXTENSIONS.has(extension(file.name)))
    return "仅支持 JPG、PNG 或 WebP 格式的现场图片。";
  if (!file.size) return "图片不能为空，请重新选择。";
  if (file.size > MEETING_IMAGE_MAX_BYTES)
    return "单张现场图片不能超过 10 MB，请压缩后重试。";
  return null;
}

export function meetingImageSelectionError(files, existingCount = 0) {
  const list = Array.from(files || []);
  if (!list.length) return "请选择现场图片。";
  if (existingCount + list.length > MEETING_IMAGE_LIMIT)
    return `每场会议最多上传 ${MEETING_IMAGE_LIMIT} 张现场图片。`;
  for (const file of list) {
    const error = meetingImageError(file);
    if (error) return error;
  }
  return null;
}
