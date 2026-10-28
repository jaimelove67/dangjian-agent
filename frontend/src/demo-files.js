const NAME = "dangjian-demo-files-v1";
function open() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(NAME, 1);
    req.onupgradeneeded = () =>
      req.result.createObjectStore("files", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () =>
      reject(new Error("无法打开浏览器文件存储，请检查隐私模式或存储权限。"));
  });
}
export async function saveDemoFile(id, ownerId, file) {
  const db = await open();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      tx.objectStore("files").put({ id, ownerId, file });
      tx.oncomplete = resolve;
      tx.onerror = () =>
        reject(new Error("文件未能保存，请检查浏览器存储空间后重试。"));
      tx.onabort = () => reject(new Error("文件保存被中止，请重试。"));
    });
  } finally {
    db.close();
  }
}
export async function getDemoFile(id, ownerId) {
  const db = await open();
  try {
    return await new Promise((resolve, reject) => {
      const req = db.transaction("files").objectStore("files").get(id);
      req.onsuccess = () =>
        req.result?.ownerId === ownerId
          ? resolve(req.result.file)
          : reject(new Error("原件不存在或不在当前授权范围内。"));
      req.onerror = () => reject(new Error("原件读取失败，请重试。"));
    });
  } finally {
    db.close();
  }
}
export async function deleteDemoFile(id, ownerId) {
  const db = await open();
  try {
    await new Promise((resolve, reject) => {
      const tx = db.transaction("files", "readwrite");
      const store = tx.objectStore("files");
      const req = store.get(id);
      req.onsuccess = () => {
        if (req.result?.ownerId === ownerId) store.delete(id);
      };
      tx.oncomplete = resolve;
      tx.onerror = () => reject(new Error("文件未能删除，请重试。"));
      tx.onabort = () => reject(new Error("文件删除被中止，请重试。"));
    });
  } finally {
    db.close();
  }
}
