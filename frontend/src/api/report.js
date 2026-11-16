import { readToken } from '@/utils/authStorage'

import { ApiError, http, refreshAccessToken } from './http'

/**
 * 体检报告 PDF：POST /api/get_pdf（见 API.md §16）。
 *
 * 返回二进制且必须带 Authorization，所以不能用 window.open / <a href>，
 * 只能用 fetch 取 blob 再交给前端触发下载。
 */

const PDF_PATH = '/get_pdf'

function pdfUrl() {
  const base = String(http.defaults.baseURL ?? '/api').replace(/\/$/, '')
  return `${base}${PDF_PATH}`
}

async function safeJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

/** 从 Content-Disposition 里取文件名，兼容 filename*=utf-8'' 与普通 filename。 */
function parseFilename(disposition) {
  if (!disposition) return ''

  const utf8 = /filename\*=utf-8''([^;]+)/i.exec(disposition)
  if (utf8) {
    try {
      return decodeURIComponent(utf8[1].trim())
    } catch {
      /* 落在下面的普通 filename 分支 */
    }
  }

  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1].trim() : ''
}

async function requestPdf(payload, signal, retried) {
  const token = readToken()
  const headers = {
    'Content-Type': 'application/json; charset=utf-8',
    Accept: 'application/pdf',
  }
  if (token) headers.Authorization = `Bearer ${token}`

  let response
  try {
    response = await fetch(pdfUrl(), {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiError('无法连接后端服务，请确认后端已启动（默认 http://127.0.0.1:8000）。', {
      code: 'network_error',
    })
  }

  if (response.status === 401) {
    const data = await safeJson(response)
    const code = data?.code ?? ''

    if (code === 'token_expired' && !retried) {
      await refreshAccessToken()
      return requestPdf(payload, signal, true)
    }

    throw new ApiError(data?.detail ?? '登录已过期，请重新登录', {
      status: 401,
      code: code || 'token_invalid',
      payload: data,
    })
  }

  if (!response.ok) {
    const data = await safeJson(response)
    throw new ApiError(data?.detail ?? `生成报告失败（HTTP ${response.status}）`, {
      status: response.status,
      code: data?.code ?? '',
      payload: data,
    })
  }

  return response
}

/**
 * @param {{
 *   fileId: string,
 *   unitName: string,
 *   preparedBy: string,
 *   reviewedBy: string,
 *   reportDate?: string,
 * }} params
 * @param {{ signal?: AbortSignal }} options
 * @returns {Promise<{ blob: Blob, filename: string, cached: boolean, narrative: string }>}
 */
export async function generateReportPdf(params, { signal } = {}) {
  const unitName = String(params.unitName ?? '').trim()

  const response = await requestPdf(
    {
      file_id: params.fileId,
      unit_name: unitName,
      prepared_by: String(params.preparedBy ?? '').trim(),
      reviewed_by: String(params.reviewedBy ?? '').trim(),
      report_date: params.reportDate || '',
    },
    signal,
    false,
  )

  const blob = await response.blob()
  if (!blob.size) {
    throw new ApiError('生成的报告为空，请重试', { code: 'empty_pdf' })
  }

  return {
    blob,
    filename: parseFilename(response.headers.get('content-disposition')) || `${unitName}体检分析报告.pdf`,
    cached: response.headers.get('x-report-cached') === 'true',
    narrative: response.headers.get('x-report-narrative') || '',
  }
}
