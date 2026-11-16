/**
 * 把二进制 Blob 交给浏览器下载。
 * 生成的 objectURL 延迟释放，避免部分浏览器在下载真正开始前就被回收。
 */
export function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename || 'download'
  link.rel = 'noopener'
  link.style.display = 'none'

  document.body.appendChild(link)
  link.click()
  link.remove()

  setTimeout(() => URL.revokeObjectURL(url), 1500)
}
