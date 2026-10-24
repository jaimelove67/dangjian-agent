const allowedExtensions = new Set([
  "pdf",
  "docx",
  "txt",
  "md",
  "png",
  "jpg",
  "jpeg",
]);
export function validateMaterialFile(file, maxSize, configuredExtensions) {
  if (!file || !file.size) throw new Error("请选择非空文件。");
  if (
    !file.name ||
    file.name.length > 255 ||
    /[\\/:\u0000-\u001f\u007f]/.test(file.name)
  )
    throw new Error("文件名无效，请重命名后上传。");
  if (!allowedExtensions.has(file.name.split(".").at(-1).toLowerCase()))
    throw new Error("支持 PDF、DOCX、TXT、MD、PNG 和 JPG 文件。");
  if (
    configuredExtensions &&
    !configuredExtensions.includes(file.name.split(".").at(-1).toLowerCase())
  )
    throw new Error("当前平台未允许此文件格式，请按平台上传要求准备材料。");
  if (file.size > maxSize)
    throw new Error(
      `文件超过 ${(maxSize / 1024 / 1024).toFixed(0)} MB，请压缩后重试。`,
    );
}
