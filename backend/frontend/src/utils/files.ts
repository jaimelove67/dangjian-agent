/** 本地日历日期；避免 UTC 跨日导致实际日期与界面不一致。 */
export function todayISO(): string {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}

export function downloadBlob(content: Blob, fileName: string): void {
  const url = URL.createObjectURL(content)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName.replace(/[\\/:*?"<>|]/g, '_')
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
